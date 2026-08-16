"""
Chat-related Pydantic schemas.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str
    content: str
    timestamp: Optional[datetime] = None


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10000)
    session_id: Optional[int] = None
    use_memory: bool = True


class ChatResponse(BaseModel):
    answer: str
    session_id: int
    priority: Optional[str] = None
    category: Optional[str] = None
    sla_due_at: Optional[str] = None
    needs_approval: bool = False
    decision_prompt: Optional[str] = None
    ticket_id: Optional[str] = None
    ticket_number: Optional[str] = None
    ticket_status: Optional[str] = None
    ticket_error: Optional[str] = None
    sources: List[dict] = []
    used_connectors: bool = False
    used_web_search: bool = False
    subagent_results: List[dict] = []


class ChatSessionResponse(BaseModel):
    id: int
    user_id: int
    title: str
    language: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}