"""
API schemas package for HelpDesk Enterprise Copilot v12.
"""

from api.schemas.auth import (
    LoginRequest,
    TokenResponse,
    RefreshRequest,
    RegisterRequest,
    UserResponse,
)
from api.schemas.ticket import (
    TicketCreate,
    TicketUpdate,
    TicketResponse,
    TicketEventResponse,
)
from api.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ChatMessage,
    ChatSessionResponse,
)
from api.schemas.memory import (
    PayloadIngestRequest,
    CaseStudyCreate,
    TrainingRunResponse,
    MemoryEntryResponse,
)

__all__ = [
    "LoginRequest",
    "TokenResponse",
    "RefreshRequest",
    "RegisterRequest",
    "UserResponse",
    "TicketCreate",
    "TicketUpdate",
    "TicketResponse",
    "TicketEventResponse",
    "ChatRequest",
    "ChatResponse",
    "ChatMessage",
    "ChatSessionResponse",
    "PayloadIngestRequest",
    "CaseStudyCreate",
    "TrainingRunResponse",
    "MemoryEntryResponse",
]