"""
Database and ORM models for HelpDesk Enterprise Copilot v12.
Uses SQLAlchemy 2.0 with typed mappings.
"""

from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Enum,
    JSON,
    Index,
    Table,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    Session,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config.settings import get_settings


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    def to_dict(self) -> dict:
        return {
            column.name: getattr(self, column.name)
            for column in self.__table__.columns
        }


# --- Enum Values ---
PRIORITY_LEVELS = ("P1", "P2", "P3", "P4")
TICKET_STATUS = ("OPEN", "IN_PROGRESS", "PENDING_APPROVAL", "RESOLVED", "CLOSED", "ESCALATED")
ROLE_TYPES = ("admin", "user", "agent", "manager", "viewer")
MEMORY_TYPE = ("EPISODIC", "SEMANTIC", "PROCEDURAL", "WORKFLOW")
DOCUMENT_STATUS = ("PENDING", "PROCESSING", "INDEXED", "FAILED")
TRAINING_STATUS = ("PENDING", "PROCESSING", "COMPLETED", "FAILED")
ANALYTICS_EVENT = ("CHAT", "TICKET", "SLA", "RETRIEVAL", "MEMORY", "TRAINING")


# --- Database Engine ---
def create_db_engine():
    """Create the appropriate database engine based on URL."""
    settings = get_settings()
    return create_async_engine(
        settings.DATABASE_URL,
        echo=settings.DEBUG,
        pool_pre_ping=True,
    )


engine = create_db_engine()
SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def get_db_session() -> AsyncSession:
    """Async generator for FastAPI dependency injection."""
    async with SessionLocal() as session:
        yield session


# ---------------------------------------------------------------------------
# User & Organization (Multi-tenant)
# ---------------------------------------------------------------------------

class Organization(Base):
    """Enterprise tenant for multi-tenancy."""

    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    branding: Mapped[dict] = mapped_column(JSON, default=dict)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    users: Mapped[list["User"]] = relationship(back_populates="organization")


class User(Base):
    """User account for authentication and RBAC."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(100), index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(Enum(*ROLE_TYPES, name="role_type"), default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)

    organization_id: Mapped[Optional[int]] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    organization: Mapped[Optional[Organization]] = relationship(back_populates="users")

    # Entra ID (Azure AD) integration
    entra_id: Mapped[Optional[str]] = mapped_column(String(255), index=True, nullable=True)
    # OAuth (Google / Microsoft / GitHub) identity
    oauth_provider: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    oauth_subject: Mapped[Optional[str]] = mapped_column(String(255), index=True, nullable=True)
    preferred_language: Mapped[str] = mapped_column(String(10), default="en")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    sessions: Mapped[list["ChatSession"]] = relationship(back_populates="user")
    tickets: Mapped[list["Ticket"]] = relationship(
        back_populates="user",
        foreign_keys="Ticket.user_id",
    )


# ---------------------------------------------------------------------------
# Knowledge & Documents
# ---------------------------------------------------------------------------

class KnowledgeDocument(Base):
    """Document indexed in the vector store for RAG."""

    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, index=True)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000))
    file_type: Mapped[str] = mapped_column(String(50))
    hash: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(Enum(*DOCUMENT_STATUS, name="doc_status"), default="PENDING")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    chunked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    indexed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (Index("ix_docs_tenant_status", "tenant_id", "status"),)


# ---------------------------------------------------------------------------
# Chat & Tickets
# ---------------------------------------------------------------------------

class ChatSession(Base):
    """User chat conversation session."""

    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(500), default="New chat")
    language: Mapped[str] = mapped_column(String(10), default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user: Mapped[Optional[User]] = relationship(back_populates="sessions")
    messages: Mapped[list["Message"]] = relationship(back_populates="session")


class Message(Base):
    """Individual chat message."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # user / assistant / system
    content: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)  # optional metadata payload
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    session: Mapped[Optional[ChatSession]] = relationship(back_populates="messages")


class Ticket(Base):
    """Helpdesk incident ticket with SLA tracking."""

    __tablename__ = "tickets"
    __table_args__ = (
        Index("ix_tickets_tenant_priority", "tenant_id", "priority"),
        Index("ix_tickets_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_number: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    tenant_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(100), default="Technical Support")
    priority: Mapped[str] = mapped_column(Enum(*PRIORITY_LEVELS, name="priority_level"), default="P3")
    status: Mapped[str] = mapped_column(Enum(*TICKET_STATUS, name="ticket_status"), default="OPEN")
    assignee_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    sla_due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    sla_escalation_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user: Mapped[Optional[User]] = relationship(back_populates="tickets", foreign_keys=[user_id])


class TicketEvent(Base):
    """Audit trail of ticket lifecycle events."""

    __tablename__ = "ticket_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(50))  # CREATED, ASSIGNED, COMMENTED, ESCALATED
    actor_id: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Self-Training Memory (the core differentiator)
# ---------------------------------------------------------------------------

class MemoryEntry(Base):
    """Persistent self-training memory entry (episodic/semantic/procedural)."""

    __tablename__ = "memory_entries"
    __table_args__ = (Index("ix_memory_tenant_type", "tenant_id", "memory_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, index=True)
    memory_type: Mapped[str] = mapped_column(Enum(*MEMORY_TYPE, name="memory_type"), default="EPISODIC")
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(255), default="user_feedback")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    times_used: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    embedding: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)  # JSON array of floats
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class CaseStudy(Base):
    """Labeled case study for supervised self-training."""

    __tablename__ = "case_studies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text)
    resolution: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(Enum(*PRIORITY_LEVELS, name="case_priority"), default="P3")
    category: Mapped[str] = mapped_column(String(100))
    tags: Mapped[dict] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)  # accepts arbitrary payloads
    embedding: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    times_retrieved: Mapped[int] = mapped_column(Integer, default=0)
    resolution_rate: Mapped[float] = mapped_column(Float, default=0.0)
    created_by: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class TrainingRun(Base):
    """Log of a self-training pipeline execution."""

    __tablename__ = "training_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, index=True)
    trigger_type: Mapped[str] = mapped_column(String(50))  # MANUAL, SCHEDULED, AUTO_FEEDBACK
    status: Mapped[str] = mapped_column(Enum(*TRAINING_STATUS, name="training_status"), default="PENDING")
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    indexed_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

class AnalyticsEvent(Base):
    """Event log for analytics and observability."""

    __tablename__ = "analytics_events"
    __table_args__ = (Index("ix_analytics_event_range", "event_type", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(Enum(*ANALYTICS_EVENT, name="analytics_event"), default="CHAT")
    session_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Initialize
# ---------------------------------------------------------------------------

async def init_db():
    """Create all tables on startup."""
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Verify connection
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def close_db():
    """Dispose engine on shutdown."""
    await engine.dispose()


# Re-export for convenience
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