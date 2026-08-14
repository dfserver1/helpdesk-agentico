"""
Ticket backend abstraction for HelpDesk Enterprise Copilot.

Replaces the old in-memory mock ticket store with real, pluggable backends:

  - ``DatabaseTicketBackend``  (default)  persists tickets into the app DB
    (``Ticket`` + ``TicketEvent``) with real ``created_at``, SLA deadlines,
    ticket numbers and an audit trail.
  - ``FreshserviceTicketBackend``         creates/reads tickets in Freshservice
    through its REST API v2 (opt-in via ``TICKET_BACKEND=freshservice``).
  - ``JiraTicketBackend``                 creates/reads tickets in Jira through
    its REST API v2 (opt-in via ``TICKET_BACKEND=jira``).

Contract-first: the ``TicketBackend`` ABC is the only surface the agent tools
depend on, so switching an org to an external ITSM never changes agent code.
"""

import base64
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from config.settings import get_settings
from config.logging import get_logger

logger = get_logger("ticket_backend")


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------

@dataclass
class TicketRecord:
    """Normalized ticket view returned by every backend."""

    ticket_id: str                     # external id (ticket number / ITSM key)
    ticket_number: str                 # human-facing reference
    title: str
    description: str
    category: str
    priority: str                      # P1-P4
    status: str                        # OPEN, IN_PROGRESS, RESOLVED, ...
    tenant_id: int
    user_id: Optional[int] = None
    assignee: Optional[str] = None
    created_at: Optional[datetime] = None
    sla_due_at: Optional[datetime] = None
    sla_escalation_at: Optional[datetime] = None
    metadata: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "ticket_id": self.ticket_id,
            "ticket_number": self.ticket_number,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "priority": self.priority,
            "status": self.status,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "assignee": self.assignee,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "sla_due_at": self.sla_due_at.isoformat() if self.sla_due_at else None,
            "sla_escalation_at": self.sla_escalation_at.isoformat() if self.sla_escalation_at else None,
            "metadata": self.metadata,
        }


class TicketBackend(ABC):
    """Interface implemented by all ticket backends."""

    name: str = "base"

    @abstractmethod
    def create_ticket(
        self,
        *,
        summary: str,
        description: str = "",
        priority: str = "P3",
        category: str = "Technical Support",
        tenant_id: int = 1,
        user_id: Optional[int] = None,
    ) -> TicketRecord:
        """Open a new ticket and return its normalized record."""

    @abstractmethod
    def get_ticket(self, ticket_id: str) -> Optional[TicketRecord]:
        """Fetch a ticket by its external id; None if not found."""

    def health(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# Sync bridge (SQLAlchemy async from synchronous LangChain tools)
# ---------------------------------------------------------------------------

def _run_sync(factory):
    """Run an async worker (built by ``factory``) to completion from a
    synchronous caller. Mirrors the bridge used by ``services.memory_service``:
    all engine/session work lives inside a single event loop so aiosqlite never
    crosses thread/loop boundaries."""
    import asyncio
    import threading

    def _run():
        return asyncio.run(factory())

    try:
        asyncio.get_running_loop()
        in_loop = True
    except RuntimeError:
        in_loop = False

    if not in_loop:
        return _run()

    box: Dict[str, object] = {}
    exc_box: Dict[str, object] = {}

    def target():
        try:
            box["result"] = _run()
        except BaseException as e:  # capture for the caller thread
            exc_box["error"] = e

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()

    if "error" in exc_box:
        raise exc_box["error"]
    return box["result"]


def _new_session_maker():
    """Build an isolated async engine + sessionmaker for sync-bridge calls."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

    from database.models import create_db_engine

    engine = create_db_engine()
    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    return engine, maker


# ---------------------------------------------------------------------------
# Database backend (default)
# ---------------------------------------------------------------------------

class DatabaseTicketBackend(TicketBackend):
    """Persist tickets into the application database with real SLA + audit."""

    name = "database"

    def _new_ticket_number(self) -> str:
        return "TK-" + uuid.uuid4().hex[:10].upper()

    def create_ticket(
        self,
        *,
        summary: str,
        description: str = "",
        priority: str = "P3",
        category: str = "Technical Support",
        tenant_id: int = 1,
        user_id: Optional[int] = None,
    ) -> TicketRecord:
        from database.models import Ticket, TicketEvent
        from sla.engine import get_sla_engine

        pri = str(priority).strip().upper()
        if pri not in {"P1", "P2", "P3", "P4"}:
            pri = "P3"

        engine = get_sla_engine()
        sla = engine.compute_sla(ticket_id="pending", priority=pri)
        ticket_number = self._new_ticket_number()

        async def _worker():
            e, maker = _new_session_maker()
            try:
                async with maker() as session:
                    ticket = Ticket(
                        ticket_number=ticket_number,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        title=(summary or "")[:500],
                        description=description or summary or "",
                        category=category,
                        priority=pri,
                        status="OPEN",
                        created_by=user_id or 0,
                        sla_due_at=sla.due_at,
                        sla_escalation_at=sla.escalation_at,
                    )
                    session.add(ticket)
                    await session.flush()
                    session.add(
                        TicketEvent(
                            ticket_id=ticket.id,
                            event_type="CREATED",
                            actor_id=user_id or 0,
                            payload={"priority": pri, "title": (summary or "")[:100]},
                        )
                    )
                    await session.commit()
                    await session.refresh(ticket)
                    return ticket
            finally:
                await e.dispose()

        try:
            ticket = _run_sync(_worker)
        except Exception as exc:
            logger.error(f"DatabaseTicketBackend.create_ticket failed: {exc}")
            raise

        record = TicketRecord(
            ticket_id=ticket.ticket_number,
            ticket_number=ticket.ticket_number,
            title=ticket.title,
            description=ticket.description,
            category=ticket.category,
            priority=ticket.priority,
            status=ticket.status,
            tenant_id=ticket.tenant_id,
            user_id=ticket.user_id,
            assignee=None,
            created_at=ticket.created_at,
            sla_due_at=ticket.sla_due_at,
            sla_escalation_at=ticket.sla_escalation_at,
            metadata={"source": "database", "db_id": str(ticket.id)},
        )
        logger.info(f"Ticket {ticket_number} [{pri}] created via database backend")
        return record

    def get_ticket(self, ticket_id: str) -> Optional[TicketRecord]:
        from sqlalchemy import select

        from database.models import Ticket

        ticket_id = (ticket_id or "").strip()

        async def _worker():
            e, maker = _new_session_maker()
            try:
                async with maker() as session:
                    stmt = select(Ticket).where(Ticket.ticket_number == ticket_id)
                    if ticket_id.isdigit():
                        stmt = select(Ticket).where(Ticket.id == int(ticket_id))
                    return (await session.execute(stmt)).scalar_one_or_none()
            finally:
                await e.dispose()

        try:
            ticket = _run_sync(_worker)
        except Exception as exc:
            logger.error(f"DatabaseTicketBackend.get_ticket failed: {exc}")
            return None
        if ticket is None:
            return None

        return TicketRecord(
            ticket_id=ticket.ticket_number,
            ticket_number=ticket.ticket_number,
            title=ticket.title,
            description=ticket.description,
            category=ticket.category,
            priority=ticket.priority,
            status=ticket.status,
            tenant_id=ticket.tenant_id,
            user_id=ticket.user_id,
            assignee=None,
            created_at=ticket.created_at,
            sla_due_at=ticket.sla_due_at,
            sla_escalation_at=ticket.sla_escalation_at,
            metadata={"source": "database", "db_id": str(ticket.id)},
        )


# ---------------------------------------------------------------------------
# Freshservice backend (REST API v2)
# ---------------------------------------------------------------------------

class FreshserviceTicketBackend(TicketBackend):
    """Create/read tickets in Freshservice via its REST API v2."""

    name = "freshservice"

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self.base_url = (self.settings.FRESHSERVICE_BASE_URL or "").rstrip("/")
        self.api_key = self.settings.FRESHSERVICE_API_KEY or ""
        self.api_key_id = self.settings.FRESHSERVICE_API_KEY_ID or ""

    def _auth_header(self) -> dict:
        # Freshservice v2 uses HTTP Basic auth: the API key acts as the
        # username and 'X' is the password. Newer API key pairs may carry an
        # api_key_id as the username.
        user = self.api_key_id or self.api_key
        token = base64.b64encode(f"{user}:X".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    def _priority_map(self) -> dict:
        return {"P1": 1, "P2": 2, "P3": 3, "P4": 4}

    def _reverse_priority(self, value) -> str:
        for k, v in self._priority_map().items():
            if str(value) == str(v):
                return k
        return "P3"

    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    def health(self) -> bool:
        return self.is_configured()

    def create_ticket(
        self,
        *,
        summary: str,
        description: str = "",
        priority: str = "P3",
        category: str = "Technical Support",
        tenant_id: int = 1,
        user_id: Optional[int] = None,
    ) -> TicketRecord:
        import httpx

        if not self.is_configured():
            raise RuntimeError("Freshservice is not configured (FRESHSERVICE_BASE_URL/API_KEY)")

        pri = str(priority).strip().upper()
        payload = {
            "subject": (summary or "")[:500],
            "description": description or summary or "",
            "priority": self._priority_map().get(pri, 3),
            "status": 2,  # Open
            "category": category,
        }
        headers = {"Content-Type": "application/json", **self._auth_header()}
        try:
            resp = httpx.post(
                f"{self.base_url}/api/v2/tickets",
                json=payload,
                headers=headers,
                timeout=15.0,
            )
            resp.raise_for_status()
            data = resp.json().get("ticket", {})
        except Exception as exc:
            logger.error(f"Freshservice create_ticket failed: {exc}")
            raise

        fresh_id = str(data.get("id", ""))
        record = TicketRecord(
            ticket_id=fresh_id,
            ticket_number=fresh_id,
            title=data.get("subject", summary),
            description=data.get("description", description),
            category=data.get("category", category),
            priority=self._reverse_priority(data.get("priority", pri)),
            status=data.get("status", "OPEN"),
            tenant_id=tenant_id,
            user_id=user_id,
            created_at=self._parse_date(data.get("created_at")),
            sla_due_at=self._parse_date(data.get("due_by")),
            metadata={"source": "freshservice", "display_id": str(data.get("display_id", ""))},
        )
        logger.info(f"Freshservice ticket {fresh_id} created [{pri}]")
        return record

    def get_ticket(self, ticket_id: str) -> Optional[TicketRecord]:
        import httpx

        ticket_id = (ticket_id or "").strip()
        if not self.is_configured():
            return None
        headers = self._auth_header()
        try:
            resp = httpx.get(
                f"{self.base_url}/api/v2/tickets/{ticket_id}",
                headers=headers,
                timeout=15.0,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json().get("ticket", {})
        except Exception as exc:
            logger.error(f"Freshservice get_ticket failed: {exc}")
            return None

        return TicketRecord(
            ticket_id=str(data.get("id", ticket_id)),
            ticket_number=str(data.get("display_id", data.get("id", ticket_id))),
            title=data.get("subject", ""),
            description=data.get("description", ""),
            category=data.get("category", "Technical Support"),
            priority=self._reverse_priority(data.get("priority", "P3")),
            status=str(data.get("status", "OPEN")),
            tenant_id=1,
            assignee=None,
            created_at=self._parse_date(data.get("created_at")),
            sla_due_at=self._parse_date(data.get("due_by")),
            metadata={"source": "freshservice"},
        )

    @staticmethod
    def _parse_date(value) -> Optional[datetime]:
        if not value:
            return None
        from dateutil import parser as _dp

        try:
            parsed = _dp.parse(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except (ValueError, TypeError, OverflowError):
            return None


# ---------------------------------------------------------------------------
# Jira backend (REST API v2)
# ---------------------------------------------------------------------------

class JiraTicketBackend(TicketBackend):
    """Create/read issues in Jira (Cloud) via its REST API v2."""

    name = "jira"

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self.base_url = (self.settings.JIRA_BASE_URL or "").rstrip("/")
        self.email = self.settings.JIRA_EMAIL or ""
        self.api_token = self.settings.JIRA_API_TOKEN or ""
        self.project_key = (self.settings.JIRA_PROJECT_KEY or "HELPDESK").strip().upper()

    def _auth_header(self) -> dict:
        token = base64.b64encode(f"{self.email}:{self.api_token}".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    def _priority_map(self) -> dict:
        return {"P1": "Highest", "P2": "High", "P3": "Medium", "P4": "Low"}

    def _reverse_priority(self, name: str) -> str:
        for k, v in self._priority_map().items():
            if str(name).lower() == str(v).lower():
                return k
        return "P3"

    def is_configured(self) -> bool:
        return bool(self.base_url and self.email and self.api_token)

    def health(self) -> bool:
        return self.is_configured()

    def create_ticket(
        self,
        *,
        summary: str,
        description: str = "",
        priority: str = "P3",
        category: str = "Technical Support",
        tenant_id: int = 1,
        user_id: Optional[int] = None,
    ) -> TicketRecord:
        import httpx

        if not self.is_configured():
            raise RuntimeError("Jira is not configured (JIRA_BASE_URL/EMAIL/API_TOKEN)")

        pri = str(priority).strip().upper()
        fields = {
            "project": {"key": self.project_key},
            "summary": (summary or "")[:255],
            "description": description or summary or "",
            "issuetype": {"name": "Task"},
            "priority": {"name": self._priority_map().get(pri, "Medium")},
        }
        headers = {"Content-Type": "application/json", **self._auth_header()}
        try:
            resp = httpx.post(
                f"{self.base_url}/rest/api/2/issue",
                json={"fields": fields},
                headers=headers,
                timeout=15.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.error(f"Jira create_issue failed: {exc}")
            raise

        key = str(data.get("key", "UNKNOWN"))
        record = TicketRecord(
            ticket_id=key,
            ticket_number=key,
            title=summary or "",
            description=description or summary or "",
            category=category,
            priority=pri,
            status="OPEN",
            tenant_id=tenant_id,
            user_id=user_id,
            created_at=datetime.now(timezone.utc),
            sla_due_at=None,
            sla_escalation_at=None,
            metadata={"source": "jira", "self": str(data.get("self", ""))},
        )
        logger.info(f"Jira issue {key} created [{pri}]")
        return record

    def get_ticket(self, ticket_id: str) -> Optional[TicketRecord]:
        import httpx

        ticket_id = (ticket_id or "").strip()
        if not self.is_configured():
            return None
        headers = self._auth_header()
        try:
            resp = httpx.get(
                f"{self.base_url}/rest/api/2/issue/{ticket_id}",
                headers=headers,
                timeout=15.0,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            fields = data.get("fields", {})
        except Exception as exc:
            logger.error(f"Jira get_issue failed: {exc}")
            return None

        status = fields.get("status", {}).get("name", "OPEN")
        return TicketRecord(
            ticket_id=str(data.get("key", ticket_id)),
            ticket_number=str(data.get("key", ticket_id)),
            title=fields.get("summary", ""),
            description=fields.get("description", ""),
            category=fields.get("labels", ["Technical"])[0] if fields.get("labels") else "Technical",
            priority=self._reverse_priority(fields.get("priority", {}).get("name", "Medium")),
            status=status.upper(),
            tenant_id=1,
            created_at=self._parse_date(fields.get("created")),
            sla_due_at=self._parse_date(fields.get("duedate")),
            metadata={"source": "jira", "self": str(data.get("self", ""))},
        )

    @staticmethod
    def _parse_date(value) -> Optional[datetime]:
        if not value:
            return None
        from dateutil import parser as _dp

        try:
            parsed = _dp.parse(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except (ValueError, TypeError, OverflowError):
            return None


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_ticket_backend() -> TicketBackend:
    """Return the configured ticket backend, defaulting to the database."""
    settings = get_settings()
    provider = (settings.TICKET_BACKEND or "database").strip().lower()

    if provider == "freshservice":
        backend = FreshserviceTicketBackend(settings)
        if backend.is_configured():
            logger.info("Ticket backend: freshservice")
            return backend
        logger.warning("TICKET_BACKEND=freshservice but Freshservice is not configured; using database")
    elif provider == "jira":
        backend = JiraTicketBackend(settings)
        if backend.is_configured():
            logger.info("Ticket backend: jira")
            return backend
        logger.warning("TICKET_BACKEND=jira but Jira is not configured; using database")

    logger.info("Ticket backend: database")
    return DatabaseTicketBackend()