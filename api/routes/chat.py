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
    )


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

    state = await run_agent_blocking(
        agent.invoke,
        Command(resume=decision),
        config,
    )
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
    )