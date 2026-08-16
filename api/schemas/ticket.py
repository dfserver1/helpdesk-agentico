"""
Ticket-related Pydantic schemas.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class TicketCreate(BaseModel):
    title: str = Field(min_length=3, max_length=500)
    description: str = Field(min_length=5)
    category: str = "Technical Support"
    priority: str = Field(default="P3", pattern="^(P1|P2|P3|P4)$")


class TicketUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=3, max_length=500)
    description: Optional[str] = None
    priority: Optional[str] = Field(default=None, pattern="^(P1|P2|P3|P4)$")
    status: Optional[str] = Field(
        default=None,
        pattern="^(OPEN|IN_PROGRESS|PENDING_APPROVAL|RESOLVED|CLOSED|ESCALATED)$",
    )
    assignee_id: Optional[int] = None


class TicketResponse(BaseModel):
    id: int
    ticket_number: str
    tenant_id: int
    user_id: Optional[int]
    title: str
    description: str
    category: str
    priority: str
    status: str
    assignee_id: Optional[int] = None
    sla_due_at: Optional[datetime]
    sla_escalation_at: Optional[datetime]
    resolved_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TicketEventResponse(BaseModel):
    id: int
    ticket_id: int
    event_type: str
    actor_id: int
    payload: dict
    created_at: datetime

    model_config = {"from_attributes": True}