"""
Database package for HelpDesk Enterprise Copilot.
"""

from database.models import (
    Base,
    engine,
    SessionLocal,
    get_db_session,
    init_db,
    close_db,
    Organization,
    User,
    KnowledgeDocument,
    ChatSession,
    Message,
    Ticket,
    TicketEvent,
    MemoryEntry,
    CaseStudy,
    TrainingRun,
    AnalyticsEvent,
)

__all__ = [
    "Base",
    "engine",
    "SessionLocal",
    "get_db_session",
    "init_db",
    "close_db",
    "Organization",
    "User",
    "KnowledgeDocument",
    "ChatSession",
    "Message",
    "Ticket",
    "TicketEvent",
    "MemoryEntry",
    "CaseStudy",
    "TrainingRun",
    "AnalyticsEvent",
]