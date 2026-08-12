"""
Agent state schema for HelpDesk Enterprise Copilot v12.
TypedDict-based LangGraph state with typed message flow.
"""

from typing import Annotated, Any, Dict, List, Optional, TypedDict
from langgraph.graph import add_messages


class AgentMessage(TypedDict, total=False):
    role: str                 # user / assistant / system / tool
    content: str
    tool_calls: List[Dict[str, Any]]
    metadata: Optional[Dict[str, Any]]


class AgentState(TypedDict, total=False):
    """LangGraph shared state for the helpdesk agent."""

    # Core conversation
    messages: Annotated[list, add_messages]
    user_id: Optional[int]
    tenant_id: int
    thread_id: Optional[str]
    language: str

    # Input / classification
    user_input: str
    priority: str
    category: str
    sla_response_time: str
    classification_reasoning: str

    # RAG
    query: str                              # rewritten query
    documents: Optional[List[Dict[str, Any]]]   # retrieved chunks w/ metadata
    is_relevant: Optional[bool]
    retrieval_retries: int

    # Connectors / web / sub-agents
    external_documents: Optional[List[Dict[str, Any]]]  # docs from O365/web
    used_connectors: bool                   # True if connectors were consulted
    used_web_search: bool                   # True if web fallback was consulted
    subagent_results: Optional[List[Dict[str, Any]]]    # parallel subtask outputs

    # Resolution
    solution: Optional[str]
    resolved: bool                          # True = answered from KB
    needs_human: bool                       # True = escalate to ticket

    # Ticket escalation
    ticket_decision: Optional[str]          # approval result: yes/no
    ticket_draft: Optional[Dict[str, Any]]

    # Self-training
    learning_payload: Optional[Dict[str, Any]]  # metadata to store in memory
    feedback: Optional[Dict[str, Any]]

    # SLA
    sla_status: Optional[Dict[str, Any]]


def initial_state(
    user_input: str,
    user_id: Optional[int] = None,
    tenant_id: int = 1,
    language: str = "en",
    thread_id: Optional[str] = None,
) -> AgentState:
    """Build the initial agent state."""
    return {
        "messages": [],
        "user_id": user_id,
        "tenant_id": tenant_id,
        "language": language,
        "thread_id": thread_id,
        "user_input": user_input,
        "query": user_input,
        "priority": "",
        "category": "",
        "sla_response_time": "",
        "classification_reasoning": "",
        "documents": None,
        "is_relevant": None,
        "retrieval_retries": 0,
        "external_documents": None,
        "used_connectors": False,
        "used_web_search": False,
        "subagent_results": None,
        "solution": None,
        "resolved": False,
        "needs_human": False,
        "ticket_decision": None,
        "ticket_draft": None,
        "learning_payload": None,
        "feedback": None,
        "sla_status": None,
    }