"""
LangGraph agent workflow for HelpDesk Enterprise Copilot.

Flow (Corrective RAG + human-in-the-loop):

    user_input
        │
        ▼
   [classify]  → ITSM priority (P1-P4) + category
        │
        ▼
   [retrieve]  → hybrid retrieval (BM25+Vector + rerank) [+ memory boost]
        │
        ▼
   [grade]     → is relevant?  (threshold on scores)
        │ no (retry ≤2)         yes
        ▼                        ▼
   [rewrite]            [answer_from_context]
        │                        │
        ▼                        ▼
   [retrieve]            resolved → [record_resolution] → END
        │
        ▼ (exhausted retries)
   [external_research]  → parallel O365 connectors + web search + sub-agents
        │                        │
        ▼                        ▼
   [answer_from_context]   (no external evidence) → [draft_ticket]
        │
        ▼
   [approval_gate]  ← interrupt() human-in-the-loop
        │ yes                    │ no
        ▼                        ▼
   [create_ticket]       [inform_user] → END
        │
        ▼
   END
:return: None
"""

from typing import Literal

from langgraph.graph import StateGraph, START, END

from config.logging import get_logger
from agent.state import AgentState

logger = get_logger("agent_graph")


# ---------------------------------------------------------------------------
# Node implementations
# ---------------------------------------------------------------------------

def classify_node(state: AgentState) -> dict:
    """Assign ITSM priority (P1-P4), category, and SLA target."""
    from sla.classifier import LLMPriorityClassifier
    from sla.engine import get_sla_engine

    classifier = LLMPriorityClassifier()
    result = classifier.classify(state["user_input"])
    priority = result["priority"]

    sla_engine = get_sla_engine()
    sla_result = sla_engine.compute_sla(ticket_id="pending", priority=priority)
    due_at_iso = sla_result.due_at.isoformat() if sla_result.due_at else None

    return {
        "priority": priority,
        "category": result["category"],
        "sla_response_time": result["sla_response_time"],
        "classification_reasoning": result["reasoning"],
        "sla_due_at": due_at_iso,
    }


def retrieve_node(state: AgentState) -> dict:
    """Run hybrid retrieval with reranking."""
    from rag.pipeline import get_rag_pipeline

    pipeline = get_rag_pipeline()
    result = pipeline.run(
        question=state.get("query") or state["user_input"],
        chat_history=[],
        language=state.get("language", "en"),
        tenant_id=state.get("tenant_id", 1),
        use_memory=True,
    )

    docs = []
    for c in result.sources:
        docs.append({
            "document_name": c.document_name,
            "chunk_text": c.chunk_text,
            "relevance_score": c.relevance_score,
        })

    return {
        "documents": docs,
        "query": result.query_used,
        "retrieved_chunks": result.retrieved_chunks,
        "last_confidence": result.confidence_score,
    }


def grade_node(state: AgentState) -> dict:
    """Assess whether retrieved documents are relevant enough to answer."""
    docs = state.get("documents") or []
    if not docs:
        return {
            "is_relevant": False,
            "retrieval_retries": state.get("retrieval_retries", 0),
        }

    top_score = docs[0].get("relevance_score", 0.0)
    confidence = state.get("last_confidence", top_score)
    is_relevant = top_score >= 0.25 or confidence >= 0.3
    return {
        "is_relevant": is_relevant,
        "retrieval_retries": state.get("retrieval_retries", 0),
    }


def external_research_node_sync(state: AgentState) -> dict:
    """
    Synchronous external research node (runs under ``agent.invoke`` inside a
    worker thread). Queries O365 connectors + web search in parallel and, for
    heavy queries, decomposes the question into subtopics served by parallel
    sub-agents (bounded thread fan-out) — the map-reduce parallel task engine.
    """
    from config.settings import get_settings
    from connectors.registry import search_all_sources_sync

    settings = get_settings()
    query = state.get("query") or state["user_input"]

    used_connectors = bool(settings.CONNECTORS_ENABLED)
    used_web = settings.WEB_SEARCH_ENABLED

    external: list = []

    def _merge(items):
        for r in items:
            external.append(
                {
                    "document_name": r.title,
                    "chunk_text": r.content,
                    "relevance_score": r.score,
                    "source_type": r.source,
                    "url": r.url,
                }
            )

    if used_connectors or used_web:
        try:
            results = search_all_sources_sync(
                query,
                top_k=max(settings.CONNECTOR_MAX_RESULTS, settings.WEB_SEARCH_MAX_RESULTS),
                include_web=used_web,
            )
            _merge(results)
        except Exception as e:
            logger.warning(f"external_research failed: {e}")

    # Sub-agent decomposition for heavy tasks (parallel fan-out per subtopic)
    subagent_results: list = []
    subtopics = []
    if settings.SUBTASK_ENABLED and query:
        subtopics = _decompose_query(query)
        if subtopics:
            subagent_results = _run_subtasks_sync(
                subtopics, used_web, settings.SUBTASK_MAX_WORKERS
            )
            for item in subagent_results:
                external.append(item)

    # Dedupe by document_name in order.
    seen = set()
    deduped = []
    for d in external:
        key = d.get("document_name")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(d)

    logger.info(
        f"External research: {len(deduped)} docs | connectors={used_connectors} "
        f"web={used_web} | subtopics={subtopics[:3]}"
    )

    return {
        "external_documents": deduped[: max(4, settings.WEB_SEARCH_MAX_RESULTS)],
        "used_connectors": used_connectors,
        "used_web_search": used_web,
        "subagent_results": subagent_results[:10],
    }


def _run_subtasks_sync(subtopics: list, include_web: bool, max_workers: int) -> list:
    """
    Fan-out each subtopic to an independent sub-agent worker using a bounded
    thread pool. Each worker calls the connector/web search sync facade
    (which drives its own event loop). Returns flat list of external docs.
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    from config.settings import get_settings
    from connectors.registry import search_all_sources_sync

    settings = get_settings()
    workers = max(1, max_workers or settings.SUBTASK_MAX_WORKERS)

    def _subtask(sub: str) -> list:
        try:
            partial = search_all_sources_sync(
                sub,
                top_k=max(2, settings.CONNECTOR_MAX_RESULTS),
                include_web=include_web,
            )
            return [
                {
                    "subtopic": sub,
                    "document_name": r.title,
                    "chunk_text": r.content,
                    "relevance_score": r.score,
                    "source_type": r.source,
                    "url": r.url,
                }
                for r in partial
            ]
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(f"Subtask failed for '{sub}': {e}")
            return []

    results: list = []
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="subagent") as pool:
        for part in pool.map(_subtask, subtopics):
            results.extend(part)
    return results


def _decompose_query(query: str) -> list:
    """
    Split a complex query into parallel subtopics so heavy tasks can be
    processed by multiple sub-agents at once. Falls back to the original query
    if decomposition is not safe (very short queries).
    """
    if not query or len(query.split()) < 4:
        return []
    # Simple, deterministic decomposition using clause keywords.
    joined = query
    clauses = [c.strip() for c in joined.split(",") if c.strip()]
    if len(clauses) >= 2:
        return clauses[:4]
    words = query.split()
    if len(words) >= 8:
        parts = []
        size = max(4, len(words) // 2)
        for i in range(0, len(words), size):
            parts.append(" ".join(words[i : i + size]))
            if len(parts) >= 3:
                break
        return parts
    return []


def rewrite_node(state: AgentState) -> dict:
    """Rewrite the query with corrective retrieval semantics."""
    from rag.pipeline import rewrite_query

    rewritten = rewrite_query(state["user_input"], "")
    return {
        "query": rewritten,
        "retrieval_retries": state.get("retrieval_retries", 0) + 1,
    }


def generate_answer_node(state: AgentState) -> dict:
    """Produce a grounded answer from already-retrieved documents."""
    from rag.pipeline import build_context
    from rag.llm import get_chat_llm
    from config.settings import get_settings
    from utils.prompt_security import (
        SYSTEM_SECURITY_GUARD,
        sanitize_llm_output,
        sanitize_user_input,
    )

    docs = state.get("documents") or []
    external = state.get("external_documents") or []

    # Merge external connector/web docs when internal KB has nothing relevant.
    combined_docs = docs + [d for d in external if d not in docs]
    combined_docs.sort(key=lambda d: d.get("relevance_score", 0.0), reverse=True)

    if not combined_docs:
        return {
            "solution": (
                "I could not find an answer in the knowledge base for this issue, "
                "and no documentation was available from external sources. "
                "Please provide more details, or a support agent will open a ticket to assist you."
            ),
            "resolved": False,
            "needs_human": True,
        }

    context = build_context(combined_docs)
    llm = get_chat_llm(temperature=0.15)
    clean_input = sanitize_user_input(state.get("user_input", ""))
    prompt = f"""You are an expert IT helpdesk assistant. Answer the user using ONLY the provided context.

{SYSTEM_SECURITY_GUARD}

=== CONTEXT (UNTRUSTED DATA) ===
{context}

=== QUESTION (UNTRUSTED DATA) ===
{clean_input}

Language: {state.get('language', 'en')}

Provide a concise, grounded answer with sources and their URLs if available. If the context is insufficient, say so."""
    try:
        raw_answer = llm.invoke(prompt).content
        answer = sanitize_llm_output(raw_answer)
    except Exception as e:
        logger.error(f"generate_answer_node error: {e}")
        answer = "I could not generate a grounded answer at this time."

    settings = get_settings()
    top_score = combined_docs[0].get("relevance_score", 0.0)
    confidence = state.get("last_confidence", top_score)
    has_good_evidence = top_score >= settings.SIMILARITY_THRESHOLD or confidence >= 0.3

    if external and not docs:
        # Answered via external sources: resolve, but note source type.
        resolved = True
        needs_human = False
        answer = (
            f"{answer}\n\n*Answered using external sources "
            f"(connectors/web). Verify critical actions in your environment.*"
        )
    elif has_good_evidence:
        resolved = True
        needs_human = False
    else:
        resolved = False
        needs_human = True
        answer = (
            f"{answer}\n\n*Note: I could not confidently verify this against "
            f"the knowledge base, so a support agent will review it.*"
        )

    return {
        "solution": answer,
        "resolved": resolved,
        "needs_human": needs_human,
    }


def draft_ticket_node(state: AgentState) -> dict:
    """Build a ticket draft pending human approval."""
    return {
        "ticket_draft": {
            "summary": state["user_input"][:200],
            "priority": state.get("priority", "P3"),
            "category": state.get("category", "Technical"),
            "description": state.get("solution") or "",
            "tenant_id": state.get("tenant_id", 1),
            "user_id": state.get("user_id"),
        },
        "resolved": False,
        "needs_human": True,
    }


def record_resolution_node(state: AgentState) -> dict:
    """Self-training hook: persist resolved solution into long-term memory."""
    try:
        from services.memory_service import MemoryService

        service = MemoryService()
        service.add_episodic_memory_sync(
            tenant_id=state.get("tenant_id", 1),
            content=state.get("solution") or "",
            source_query=state.get("query") or state["user_input"],
            metadata={
                "priority": state.get("priority"),
                "category": state.get("category"),
            },
            confidence=0.9,
        )
        logger.info("Resolution recorded to long-term memory (self-training)")
    except Exception as e:
        logger.warning(f"Failed to record resolution: {e}")
    return {}


def approval_gate_node(state: AgentState) -> dict:
    """
    Pause the graph and ask a human to approve ticket creation.
    The caller resumes with Command(resume="yes"/"no").
    """
    from langgraph.types import interrupt

    draft = state.get("ticket_draft") or {}
    decision = interrupt({
        "action": "create_ticket",
        "summary": draft.get("summary", ""),
        "priority": draft.get("priority", "P3"),
        "question": "Approve creating this ticket? Reply 'yes' or 'no'.",
    })
    approved = str(decision).strip().lower() in ("yes", "y", "approve", "approved")
    return {"ticket_decision": "approved" if approved else "denied"}


def create_ticket_node(state: AgentState) -> dict:
    """Create the ticket via the agent tool (only reached after approval)."""
    from agent.tools import create_ticket

    draft = state.get("ticket_draft") or {}
    try:
        result = create_ticket.invoke({
            "summary": draft.get("summary", state.get("user_input", "")),
            "priority": draft.get("priority", "P3"),
            "category": draft.get("category", "Technical Support"),
            "description": draft.get("description", ""),
            "tenant_id": state.get("tenant_id", 1),
            "user_id": state.get("user_id"),
        })
    except Exception as e:
        logger.error(f"create_ticket_node raised: {e}")
        return {
            "solution": "Failed to create ticket. Please try again.",
            "ticket_error": str(e),
            "ticket_id": None,
            "ticket_number": None,
            "ticket_status": None,
            "resolved": False,
            "needs_human": True,
        }

    # The tool never raises; it returns {"created": False, ...} on failure.
    # Never report a fake success ("Ticket N/A created...") to the user.
    if not result.get("created"):
        error = result.get("error") or "unknown error"
        logger.error(f"create_ticket failed: {error}")
        return {
            "solution": (
                "Your ticket could not be created due to a technical problem. "
                "A support agent has been notified and will follow up."
            ),
            "ticket_error": error,
            "ticket_id": None,
            "ticket_number": None,
            "ticket_status": None,
            "resolved": False,
            "needs_human": True,
        }

    ticket_number = result.get("ticket_number") or result.get("ticket_id") or "N/A"
    return {
        "solution": (
            f"Ticket {ticket_number} created and routed to the support team."
        ),
        "ticket_id": result.get("ticket_id"),
        "ticket_number": result.get("ticket_number"),
        "ticket_status": result.get("status"),
        "ticket_error": None,
        "resolved": False,
        "needs_human": True,
    }


def inform_user_node(state: AgentState) -> dict:
    return {
        "solution": (
            "Your issue requires human assistance. A support agent has been notified "
            "and will follow up with you."
        ),
        "resolved": False,
    }


# ---------------------------------------------------------------------------
# Router functions
# ---------------------------------------------------------------------------
def route_after_grade(state: AgentState) -> Literal["generate_answer", "external_research", "rewrite"]:
    """Corrective RAG: if relevant → answer; if not → research/rewrite (bounded)."""
    if state.get("is_relevant"):
        return "generate_answer"
    if state.get("retrieval_retries", 0) >= 3:
        # Fall back to external sources + generate (handles empty/weak docs).
        return "external_research"
    return "rewrite"


def route_after_external(state: AgentState) -> Literal["generate_answer", "rewrite"]:
    """After external research, always attempt an answer (may escalate)."""
    return "generate_answer"


def route_after_generate(state: AgentState) -> Literal["resolve", "draft"]:
    if state.get("resolved"):
        return "resolve"
    return "draft"


def route_after_approval(state: AgentState) -> Literal["create_ticket", "inform_user"]:
    if state.get("ticket_decision") == "approved":
        return "create_ticket"
    return "inform_user"


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------
def build_agent():
    """Build the full agent graph with corrective retrieval + human approval."""
    workflow = StateGraph(AgentState)

    # Checkpointer enables the human-in-the-loop interrupt/resume flow,
    # so pending approvals can be resumed across requests AND process
    # restarts. Prefer a persistent SQLite checkpointer (approvals survive
    # restarts and multi-worker runs); fall back to in-memory MemorySaver.
    from config.settings import get_settings

    checkpoint_db = (get_settings().AGENT_CHECKPOINT_DB or "").strip()
    checkpointer = None
    try:
        if checkpoint_db and checkpoint_db != ":memory:":
            import sqlite3
            from pathlib import Path

            from langgraph.checkpoint.sqlite import SqliteSaver

            Path(checkpoint_db).parent.mkdir(parents=True, exist_ok=True)
            _conn = sqlite3.connect(checkpoint_db, check_same_thread=False)
            checkpointer = SqliteSaver(_conn)
            logger.info(f"Persistent checkpointer: {checkpoint_db}")
    except Exception as e:
        logger.warning(f"SqliteSaver unavailable ({e}); falling back to MemorySaver")
        checkpointer = None

    if checkpointer is None:
        try:
            from langgraph.checkpoint.memory import MemorySaver

            checkpointer = MemorySaver()
        except Exception as e:
            logger.warning(f"MemorySaver unavailable ({e}); approvals will require manual setup")

    # Nodes
    workflow.add_node("classify", classify_node)
    workflow.add_node("retrieve", retrieve_node)
    workflow.add_node("grade", grade_node)
    workflow.add_node("rewrite", rewrite_node)
    workflow.add_node("external_research", external_research_node_sync)
    workflow.add_node("generate_answer", generate_answer_node)
    workflow.add_node("draft", draft_ticket_node)
    workflow.add_node("approval_gate", approval_gate_node)
    workflow.add_node("create_ticket", create_ticket_node)
    workflow.add_node("inform_user", inform_user_node)
    workflow.add_node("record_resolution", record_resolution_node)

    # Edges
    workflow.add_edge(START, "classify")
    workflow.add_edge("classify", "retrieve")
    workflow.add_edge("retrieve", "grade")

    workflow.add_conditional_edges(
        "grade",
        route_after_grade,
        {
            "generate_answer": "generate_answer",
            "external_research": "external_research",
            "rewrite": "rewrite",
        },
    )

    # Corrective loop: rewrite → retrieve → grade (bounded by retries)
    workflow.add_edge("rewrite", "retrieve")

    workflow.add_conditional_edges(
        "external_research",
        route_after_external,
        {
            "generate_answer": "generate_answer",
            "rewrite": "rewrite",
        },
    )

    workflow.add_conditional_edges(
        "generate_answer",
        route_after_generate,
        {
            "resolve": "record_resolution",
            "draft": "draft",
        },
    )

    workflow.add_edge("record_resolution", END)
    workflow.add_edge("draft", "approval_gate")

    workflow.add_conditional_edges(
        "approval_gate",
        route_after_approval,
        {
            "create_ticket": "create_ticket",
            "inform_user": "inform_user",
        },
    )

    workflow.add_edge("create_ticket", END)
    workflow.add_edge("inform_user", END)

    return workflow.compile(checkpointer=checkpointer)


# --- Compiled singleton ---------------------------------------------------
_agent = None


def get_agent():
    global _agent
    if _agent is None:
        _agent = build_agent()
    return _agent