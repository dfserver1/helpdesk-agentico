"""
Chat endpoints backed by the LangGraph agent.
Supports interrupt/resume for human-in-the-loop ticket approval.
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent import get_agent, initial_state
from api.schemas.chat import ChatRequest, ChatResponse
from app.rate_limit import limiter
from auth.deps import get_current_user
from core.exceptions import NotFoundError, ValidationError
from database.models import ChatSession, User, get_db_session

router = APIRouter()

_THREAD_PREFIX = "thread-"


async def _get_or_create_session(
    session: AsyncSession,
    user_id: int,
    session_id: int | None = None,
) -> ChatSession:
    if session_id is not None:
        chat = (
            (await session.execute(
                select(ChatSession).where(ChatSession.id == session_id)
            ))
            .scalar_one_or_none()
        )
        if chat is not None:
            if chat.user_id != user_id:
                # Do not confirm the session exists when it belongs to someone
                # else (prevents cross-tenant resource enumeration).
                raise NotFoundError("Chat session not found")
            return chat

    chat = ChatSession(user_id=user_id, title="New chat")
    session.add(chat)
    await session.commit()
    await session.refresh(chat)
    return chat


@router.post("", response_model=ChatResponse)
@limiter.limit("60/minute")
async def chat(
    request: Request,
    body: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Run the agent on a user message (supports resume via decision)."""
    chat_session = await _get_or_create_session(db, user.id, body.session_id)

    state = initial_state(
        user_input=body.message,
        user_id=user.id,
        tenant_id=user.organization_id or 1,
        thread_id=f"{_THREAD_PREFIX}{chat_session.id}",
    )

    agent = get_agent()
    config = {"configurable": {"thread_id": f"{_THREAD_PREFIX}{chat_session.id}"}}

    # Multithreaded execution: the agent runs expected blocking LLM/retrieval
    # work in a worker thread under a global concurrency cap, so different
    # user sessions execute in parallel without saturating the runtime.
    from app.concurrency import run_agent_blocking

    state = await run_agent_blocking(agent.invoke, state, config)

    # If the workflow paused for ticket approval, surface it to the caller.
    pending_approval = (
        state.get("ticket_decision") is None
        and state.get("ticket_draft") is not None
        and state.get("needs_human")
    )
    # Save messages to SQL database for persistence and cross-session retrieval
    from database.models import Message
    user_msg = Message(
        session_id=chat_session.id,
        role="user",
        content=body.message,
    )
    assistant_msg = Message(
        session_id=chat_session.id,
        role="assistant",
        content=state.get("solution") or "No answer generated.",
        payload_json={
            "priority": state.get("priority"),
            "category": state.get("category"),
            "sla_due_at": state.get("sla_due_at"),
            "used_connectors": state.get("used_connectors", False),
            "used_web_search": state.get("used_web_search", False),
            "ticket_number": state.get("ticket_number"),
            "sources": state.get("documents", []) or [],
        },
    )
    db.add_all([user_msg, assistant_msg])
    if chat_session.title == "New chat" and body.message:
        chat_session.title = body.message[:60].strip()
    await db.commit()

    return ChatResponse(
        answer=state.get("solution") or "No answer generated.",
        session_id=chat_session.id,
        priority=state.get("priority"),
        category=state.get("category"),
        sla_due_at=state.get("sla_due_at"),
        needs_approval=pending_approval,
        decision_prompt=(
            "Approve creating this ticket? Reply 'yes' or 'no'."
            if pending_approval
            else None
        ),
        sources=state.get("documents", []) or [],
        used_connectors=state.get("used_connectors", False),
        used_web_search=state.get("used_web_search", False),
        subagent_results=state.get("subagent_results", []) or [],
        ticket_id=state.get("ticket_id"),
        ticket_number=state.get("ticket_number"),
        ticket_status=state.get("ticket_status"),
        ticket_error=state.get("ticket_error"),
    )


@router.get("/sessions", response_model=list[dict])
async def list_user_sessions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Retrieve all past chat sessions belonging to the authenticated user."""
    sessions = (
        (await db.execute(
            select(ChatSession)
            .where(ChatSession.user_id == user.id)
            .order_by(ChatSession.updated_at.desc())
        ))
        .scalars()
        .all()
    )
    return [
        {
            "id": s.id,
            "title": s.title,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        }
        for s in sessions
    ]


@router.get("/sessions/{session_id}/messages", response_model=list[dict])
async def get_session_messages(
    session_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Retrieve full message history for a specific chat session."""
    chat = (
        (await db.execute(
            select(ChatSession).where(ChatSession.id == session_id)
        ))
        .scalar_one_or_none()
    )
    if chat is None or chat.user_id != user.id:
        raise NotFoundError("Chat session not found")

    from database.models import Message
    messages = (
        (await db.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.asc())
        ))
        .scalars()
        .all()
    )
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "payload": m.payload_json or {},
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in messages
    ]


@router.post("/{session_id}/decide", response_model=ChatResponse)
@limiter.limit("30/minute")
async def decide_on_ticket(
    request: Request,
    session_id: int,
    decision: str = "yes",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Resume an interrupted agent run with an approval decision."""
    from langgraph.types import Command

    decision = decision.strip().lower()
    allowed = {"yes", "y", "no", "n", "approve", "deny", "approved", "denied"}
    if decision not in allowed:
        raise ValidationError(
            "Invalid decision. Use 'yes' or 'no'."
        )

    # Verify the session belongs to the calling user before resuming.
    chat = (
        (await db.execute(
            select(ChatSession).where(ChatSession.id == session_id)
        ))
        .scalar_one_or_none()
    )
    if chat is None:
        raise NotFoundError(f"Chat session {session_id} not found")
    if chat.user_id != user.id:
        # Same non-enumerable response for foreign sessions in the decide flow.
        raise NotFoundError("Chat session not found")

    agent = get_agent()
    config = {"configurable": {"thread_id": f"{_THREAD_PREFIX}{session_id}"}}
    from app.concurrency import run_agent_blocking

    # Only resume an interrupted run that is actually waiting for approval.
    # A finished thread, a double approve, or a lost checkpoint must produce a
    # clear error instead of silently returning "No answer generated."
    snapshot = await run_agent_blocking(agent.get_state, config)
    if not getattr(snapshot, "next", None) or "approval_gate" not in set(snapshot.next):
        raise ValidationError("No pending ticket approval for this session")

    state = await run_agent_blocking(
        agent.invoke,
        Command(resume=decision),
        config,
    )

    # Save decision and resolution messages to SQL database for chat persistence
    from database.models import Message
    decision_user_msg = Message(
        session_id=session_id,
        role="user",
        content=f"Ticket Decision: {decision.capitalize()}",
    )
    decision_assistant_msg = Message(
        session_id=session_id,
        role="assistant",
        content=state.get("solution") or "No answer generated.",
        payload_json={
            "priority": state.get("priority"),
            "category": state.get("category"),
            "sla_due_at": state.get("sla_due_at"),
            "used_connectors": state.get("used_connectors", False),
            "used_web_search": state.get("used_web_search", False),
            "ticket_number": state.get("ticket_number"),
            "ticket_status": state.get("ticket_status"),
            "ticket_error": state.get("ticket_error"),
            "sources": state.get("documents", []) or [],
        },
    )
    db.add_all([decision_user_msg, decision_assistant_msg])
    await db.commit()

    return ChatResponse(
        answer=state.get("solution") or "No answer generated.",
        session_id=session_id,
        priority=state.get("priority"),
        category=state.get("category"),
        sla_due_at=state.get("sla_due_at"),
        needs_approval=False,
        decision_prompt=None,
        sources=state.get("documents", []) or [],
        used_connectors=state.get("used_connectors", False),
        used_web_search=state.get("used_web_search", False),
        subagent_results=state.get("subagent_results", []) or [],
        ticket_id=state.get("ticket_id"),
        ticket_number=state.get("ticket_number"),
        ticket_status=state.get("ticket_status"),
        ticket_error=state.get("ticket_error"),
    )