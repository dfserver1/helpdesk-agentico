"""
Agent tools for HelpDesk Enterprise Copilot.

Tools:
  - search_knowledge_base : RAG-powered KB lookup (read-only)
  - get_ticket_status     : Lookup ticket status (read-only)
  - create_ticket         : Escalate with human-approval gate (irreversible)
  - record_resolution     : Self-training memory write (learn from past cases)
  - get_sla_policy        : Query SLA targets for a priority (read-only)
"""

import json
from typing import Any, Dict, Optional

from langchain_core.tools import tool

from config.logging import get_logger
from rag.pipeline import get_rag_pipeline
from sla.classifier import SLA_DEFINITIONS
from core.exceptions import AgentError

logger = get_logger("agent_tools")


# --- Mock ticket store (replace with DB/ITSM connector in production) -----
_ticket_store: Dict[str, Dict[str, Any]] = {}
_next_ticket_id = 5000


def _new_ticket_id() -> str:
    global _next_ticket_id
    tid = f"INC-{_next_ticket_id}"
    _next_ticket_id += 1
    return tid


@tool
def search_knowledge_base(query: str, tenant_id: int = 1) -> dict:
    """
    Search the IT helpdesk knowledge base for a solution to a technical problem.
    Uses hybrid retrieval (keyword + semantic) with reranking. Returns a grounded
    answer plus citations, or found=False if no relevant content exists.
    Call this FIRST for every issue.
    """
    try:
        pipeline = get_rag_pipeline()
        result = pipeline.run(question=query, tenant_id=tenant_id)
        return {
            "answer": result.answer,
            "found": result.retrieved_chunks > 0,
            "sources": [c.document_name for c in result.sources],
            "confidence": round(result.confidence_score, 3) if hasattr(result, "confidence_score") else 0.0,
        }
    except Exception as e:
        logger.error(f"search_knowledge_base failed: {e}")
        return {"answer": "", "found": False, "sources": [], "confidence": 0.0}


@tool
def get_ticket_status(ticket_id: str) -> dict:
    """Look up an existing helpdesk ticket by ID (e.g. INC-5001). Read-only."""
    return _ticket_store.get(
        ticket_id,
        {"error": f"No ticket found with id {ticket_id}"},
    )


@tool
def create_ticket(summary: str, priority: str = "P3", description: str = "") -> dict:
    """
    Open a new helpdesk ticket to escalate an issue the knowledge base cannot solve.
    This is IRREVERSIBLE and therefore requires human approval before it writes.
    Pass a clear one-line summary and a sensible priority (P1-P4).
    """
    # NOTE: actual human-approval gating is handled in the agent graph via
    # interrupt(); this tool only records the ticket after approval.
    from sla.classifier import PRIORITY_LEVELS

    pri = priority.strip().upper()
    if pri not in PRIORITY_LEVELS:
        pri = "P3"

    ticket_id = _new_ticket_id()
    _ticket_store[ticket_id] = {
        "id": ticket_id,
        "summary": summary,
        "description": description,
        "priority": pri,
        "status": "OPEN",
        "assignee": "Unassigned",
        "created_at": None,  # set by service layer
    }
    logger.info(f"Ticket created: {ticket_id} [{pri}] {summary[:80]}")
    return {"created": True, "ticket_id": ticket_id, "priority": pri}



@tool
def get_sla_policy(priority: str = "P3") -> dict:
    """
    Return the SLA definition for a priority level (P1-P4):
    response target, resolution hours, escalation window, and label.
    """
    p = priority.strip().upper()
    definition = SLA_DEFINITIONS.get(p, SLA_DEFINITIONS["P3"])
    return {
        "priority": p,
        "label": definition["label"],
        "response": definition["response"],
        "resolve_hours": definition["resolve_hours"],
        "escalation_minutes": definition.get("escalation_minutes", 60),
    }


@tool
def record_resolution(
    query: str,
    solution: str,
    tenant_id: int = 1,
    payload: Optional[dict] = None,
) -> dict:
    """
    Self-training hook: store a resolved issue into the agent's long-term memory
    so it can answer future similar queries without human help.
    """
    try:
        from services.memory_service import MemoryService

        service = MemoryService()
        entry = service.add_episodic_memory_sync(
            tenant_id=tenant_id,
            content=solution,
            source_query=query,
            metadata=payload or {},
            confidence=0.9,
        )
        return {"recorded": True, "memory_id": entry.id}
    except Exception as e:
        logger.error(f"record_resolution failed: {e}")
        return {"recorded": False, "error": str(e)}


# --- Register all tools ----------------------------------------------------
AGENT_TOOLS = [
    search_knowledge_base,
    get_ticket_status,
    create_ticket,
    get_sla_policy,
    record_resolution,
]


def get_tools() -> list:
    return AGENT_TOOLS


ALL_TOOL_NAMES = [t.name for t in AGENT_TOOLS]