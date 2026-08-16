"""
Tests for the pluggable ticket backend (Database / Freshservice / Jira)
and for the agent tools now backed by real persistence (no more in-memory mock).
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Use a clean temp DB for backend tests (env vars must be set before the
# settings cache is first built by the conftest app bootstrap).
_db = Path(tempfile.gettempdir()) / "hdtest_tickets.db"
_db.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///" + str(_db)
os.environ["JWT_SECRET_KEY"] = "test-secret-key-please-change-32chars-plus"
os.environ["LOG_LEVEL"] = "ERROR"

from database.models import init_db  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _db_init():
    asyncio.run(init_db())
    yield
    _db.unlink(missing_ok=True)


def _noop_resp(status_code: int = 200, payload: dict = None):
    """Minimal httpx.Response stand-in for external-backend tests."""
    _code = status_code

    class _Resp:
        status_code = _code

        def raise_for_status(self):
            if self.status_code >= 400:
                from httpx import HTTPStatusError

                raise HTTPStatusError("boom", request=None, response=self)

        def json(self):
            return payload or {}

    return _Resp()


# ---------------------------------------------------------------------------
# Database backend
# ---------------------------------------------------------------------------

def test_db_backend_creates_real_ticket():
    """Tickets must persist with a real number, timestamps, SLA and audit event."""
    from services.ticket_backend import DatabaseTicketBackend

    backend = DatabaseTicketBackend()
    rec = backend.create_ticket(
        summary="VPN not connecting after update",
        description="GlobalProtect error 800",
        priority="P2",
        category="Network",
        tenant_id=7,
        user_id=42,
    )

    assert rec.ticket_id.startswith("TK-")
    assert rec.ticket_number == rec.ticket_id
    assert rec.priority == "P2"
    assert rec.status == "OPEN"
    assert rec.tenant_id == 7
    assert rec.user_id == 42
    assert rec.created_at is not None
    assert rec.sla_due_at is not None
    assert rec.metadata.get("source") == "database"

    # The row must be queryable and carry the audit event.
    from sqlalchemy import select

    from database.models import SessionLocal, Ticket, TicketEvent

    async def _check():
        async with SessionLocal() as session:
            ticket = (
                (await session.execute(
                    select(Ticket).where(Ticket.ticket_number == rec.ticket_number)
                ))
                .scalar_one_or_none()
            )
            assert ticket is not None
            assert ticket.title == "VPN not connecting after update"
            assert ticket.status == "OPEN"
            events = (
                await session.execute(
                    select(TicketEvent).where(TicketEvent.ticket_id == ticket.id)
                )
            ).scalars().all()
            assert any(e.event_type == "CREATED" for e in events)

    asyncio.run(_check())


def test_db_backend_get_ticket():
    from services.ticket_backend import DatabaseTicketBackend

    backend = DatabaseTicketBackend()
    rec = backend.create_ticket(summary="Printer jam", priority="P3", tenant_id=1)

    found = backend.get_ticket(rec.ticket_id)
    assert found is not None
    assert found.title == "Printer jam"
    assert found.ticket_id == rec.ticket_id

    missing = backend.get_ticket("TK-NOPE999")
    assert missing is None


def test_db_backend_validates_priority():
    from services.ticket_backend import DatabaseTicketBackend

    rec = DatabaseTicketBackend().create_ticket(
        summary="weird priority",
        priority="P9",
        tenant_id=1,
    )
    assert rec.priority == "P3"


# ---------------------------------------------------------------------------
# Freshservice backend (HTTP, mocked)
# ---------------------------------------------------------------------------

def test_freshservice_requires_config():
    from services.ticket_backend import FreshserviceTicketBackend

    backend = FreshserviceTicketBackend()
    assert backend.is_configured() is False
    assert backend.health() is False


def test_freshservice_create_ticket(monkeypatch):
    import httpx

    from services.ticket_backend import FreshserviceTicketBackend

    backend = FreshserviceTicketBackend()
    backend.base_url = "https://demo.freshservice.com"
    backend.api_key = "abc123"

    def fake_post(url, json=None, headers=None, timeout=None):
        assert url == "https://demo.freshservice.com/api/v2/tickets"
        assert headers and "Authorization" in headers and headers["Authorization"].startswith("Basic")
        assert json["subject"] == "Laptop won't boot"
        assert json["priority"] == 2
        return _noop_resp(
            201,
            {"ticket": {"id": 9001, "display_id": 288, "subject": "Laptop won't boot",
                        "priority": 2, "status": 2, "created_at": "2026-01-01T10:00:00Z"}},
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    rec = backend.create_ticket(
        summary="Laptop won't boot",
        description="Blue screen on startup",
        priority="P2",
        tenant_id=3,
    )
    assert rec.ticket_id == "9001"
    assert rec.ticket_number == "9001"
    assert rec.priority == "P2"
    assert rec.metadata["source"] == "freshservice"
    assert rec.created_at is not None


def test_freshservice_get_ticket_missing(monkeypatch):
    import httpx

    from services.ticket_backend import FreshserviceTicketBackend

    backend = FreshserviceTicketBackend()
    backend.base_url = "https://demo.freshservice.com"
    backend.api_key = "abc123"

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _noop_resp(404, {}))
    assert backend.get_ticket("999") is None


# ---------------------------------------------------------------------------
# Jira backend (HTTP, mocked)
# ---------------------------------------------------------------------------

def test_jira_requires_config():
    from services.ticket_backend import JiraTicketBackend

    assert JiraTicketBackend().is_configured() is False


def test_jira_create_ticket(monkeypatch):
    import httpx

    from services.ticket_backend import JiraTicketBackend

    backend = JiraTicketBackend()
    backend.base_url = "https://demo.atlassian.net"
    backend.email = "bot@example.com"
    backend.api_token = "tok"
    backend.project_key = "HELPDESK"

    def fake_post(url, json=None, headers=None, timeout=None):
        assert url == "https://demo.atlassian.net/rest/api/2/issue"
        fields = json["fields"]
        assert fields["project"]["key"] == "HELPDESK"
        assert fields["issuetype"]["name"] == "Task"
        assert fields["priority"]["name"] == "High"
        return _noop_resp(201, {"key": "HELPDESK-77", "self": "https://demo.atlassian.net/rest/api/2/issue/77"})

    monkeypatch.setattr(httpx, "post", fake_post)
    rec = backend.create_ticket(
        summary="Email broken",
        priority="P2",
        tenant_id=1,
    )
    assert rec.ticket_id == "HELPDESK-77"
    assert rec.priority == "P2"
    assert rec.metadata["source"] == "jira"


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def test_factory_defaults_to_database(monkeypatch):
    from services import ticket_backend as tb

    class FakeSettings:
        TICKET_BACKEND = "database"
        FRESHSERVICE_BASE_URL = ""
        FRESHSERVICE_API_KEY = ""
        FRESHSERVICE_API_KEY_ID = ""
        JIRA_BASE_URL = ""
        JIRA_EMAIL = ""
        JIRA_API_TOKEN = ""
        JIRA_PROJECT_KEY = "HELPDESK"

    monkeypatch.setattr(tb, "get_settings", lambda: FakeSettings())
    backend = tb.get_ticket_backend()
    assert backend.name == "database"


def test_factory_falls_back_when_itsm_unconfigured(monkeypatch):
    from services import ticket_backend as tb

    class FakeSettings:
        TICKET_BACKEND = "freshservice"
        FRESHSERVICE_BASE_URL = ""
        FRESHSERVICE_API_KEY = ""
        FRESHSERVICE_API_KEY_ID = ""
        JIRA_BASE_URL = ""
        JIRA_EMAIL = ""
        JIRA_API_TOKEN = ""
        JIRA_PROJECT_KEY = "HELPDESK"

    monkeypatch.setattr(tb, "get_settings", lambda: FakeSettings())
    backend = tb.get_ticket_backend()
    assert backend.name == "database"


def test_factory_returns_freshservice_when_configured(monkeypatch):
    from services import ticket_backend as tb

    class FakeSettings:
        TICKET_BACKEND = "freshservice"
        FRESHSERVICE_BASE_URL = "https://demo.freshservice.com"
        FRESHSERVICE_API_KEY = "abc"
        FRESHSERVICE_API_KEY_ID = ""
        JIRA_BASE_URL = ""
        JIRA_EMAIL = ""
        JIRA_API_TOKEN = ""
        JIRA_PROJECT_KEY = "HELPDESK"

    monkeypatch.setattr(tb, "get_settings", lambda: FakeSettings())
    backend = tb.get_ticket_backend()
    assert backend.name == "freshservice"


# ---------------------------------------------------------------------------
# Agent tools (no more mock store)
# ---------------------------------------------------------------------------

def test_agent_create_ticket_tool_persists():
    """The agent's create_ticket tool must persist to a real backend."""
    from agent.tools import create_ticket, get_ticket_status

    result = create_ticket.invoke({
        "summary": "WiFi dropping every hour",
        "priority": "P3",
        "tenant_id": 5,
        "user_id": 11,
    })
    assert result["created"] is True
    assert result["ticket_id"].startswith("TK-")
    assert result["backend"] in ("database", "freshservice", "jira")

    status = get_ticket_status.invoke({
        "ticket_id": result["ticket_id"],
        "tenant_id": 5,
    })
    assert "error" not in status
    assert status["ticket_number"] == result["ticket_id"]
    assert status["status"] == "OPEN"
    assert status["tenant_id"] == 5


def test_agent_get_ticket_status_missing():
    from agent.tools import get_ticket_status

    status = get_ticket_status.invoke({"ticket_id": "TK-NOTEXIST", "tenant_id": 1})
    assert "error" in status


def test_db_backend_get_ticket_is_tenant_scoped():
    """A ticket from tenant A must be invisible to a tenant-B lookup."""
    from services.ticket_backend import DatabaseTicketBackend

    backend = DatabaseTicketBackend()
    rec = backend.create_ticket(
        summary="Tenant-scoped issue",
        priority="P3",
        tenant_id=9,
    )

    found_same_tenant = backend.get_ticket(rec.ticket_id, tenant_id=9)
    assert found_same_tenant is not None
    assert found_same_tenant.tenant_id == 9

    cross_tenant = backend.get_ticket(rec.ticket_id, tenant_id=2)
    assert cross_tenant is None

    # Unscoped lookup still works (backward compatible).
    unscoped = backend.get_ticket(rec.ticket_id)
    assert unscoped is not None


def test_agent_get_ticket_status_cross_tenant_blocked():
    """The agent tool must not leak tickets across tenants."""
    from services.ticket_backend import DatabaseTicketBackend
    from agent.tools import get_ticket_status

    backend = DatabaseTicketBackend()
    rec = backend.create_ticket(
        summary="Secret tenant issue",
        priority="P3",
        tenant_id=10,
    )

    # Wrong tenant → not found.
    blocked = get_ticket_status.invoke({"ticket_id": rec.ticket_id, "tenant_id": 3})
    assert "error" in blocked

    # Correct tenant → found.
    ok = get_ticket_status.invoke({"ticket_id": rec.ticket_id, "tenant_id": 10})
    assert "error" not in ok
    assert ok["ticket_number"] == rec.ticket_id


def test_create_ticket_falls_back_to_database_on_itsm_runtime_failure(monkeypatch):
    """If the configured ITSM raises at runtime, the ticket must still persist
    locally (never silently lost) instead of reporting failure."""
    from agent import tools as agent_tools

    class _ExplodingBackend:
        name = "freshservice"

        def create_ticket(self, **kwargs):
            raise ConnectionError("ITSMs are down")

    # Force the factory (as seen by the tool) to return an ITSM that raises.
    monkeypatch.setattr(agent_tools, "get_ticket_backend", lambda: _ExplodingBackend())

    result = agent_tools.create_ticket.invoke({
        "summary": "Outage resilience",
        "priority": "P2",
        "tenant_id": 11,
        "user_id": 1,
    })

    assert result["created"] is True
    assert result["backend"] == "database"
    assert result["ticket_id"].startswith("TK-")


def test_create_ticket_reports_failure_when_database_fails(monkeypatch):
    """If even the local database backend fails, the tool must report
    created=False (no fake success)."""
    from agent import tools as agent_tools

    class _BrokenDb:
        name = "database"

        def create_ticket(self, **kwargs):
            raise RuntimeError("disk full")

    monkeypatch.setattr(agent_tools, "get_ticket_backend", lambda: _BrokenDb())

    result = agent_tools.create_ticket.invoke({
        "summary": "Failing scenario",
        "priority": "P3",
        "tenant_id": 1,
    })
    assert result["created"] is False
    assert "error" in result
