"""
API integration tests using FastAPI TestClient (sync SQLite-backed run).
Uses a dedicated temp database to avoid polluting real data.
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure project root importable regardless of CWD
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///" + str(
    Path(tempfile.gettempdir()) / "hdtest_api.db"
)
os.environ["JWT_SECRET_KEY"] = "test-secret-key-please-change-32chars-plus"
os.environ["LOG_FORMAT"] = "json"
os.environ["LOG_LEVEL"] = "ERROR"

_db_path = Path(tempfile.gettempdir()) / "hdtest_api.db"
if _db_path.exists():
    _db_path.unlink()

from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def auth_headers(client):
    from sqlalchemy import select, update
    from database.models import SessionLocal as _SL, User as _U

    email = "api.test@helpdesk.ai"
    password = "Str0ng!Pass123"
    client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "username": "apitest",
            "full_name": "API Test User",
        },
    )

    # Promote the test user to agent directly in the DB: registration always
    # creates a plain "user" (privilege-escalation fix), so privileged
    # endpoints (tickets patch, memory ingest/recall) need a real agent.
    def _promote_to_agent():
        async def _run():
            async with _SL() as session:
                user_id = (
                    await session.execute(select(_U.id).where(_U.email == email))
                ).scalar_one_or_none()
                if user_id is not None:
                    await session.execute(
                        update(_U).where(_U.id == user_id).values(role="agent")
                    )
                    await session.commit()

        asyncio.run(_run())

    _promote_to_agent()

    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, f"login failed: {login.text}"
    token = login.json()["access_token"]
    assert token, "no access token returned"
    return {"Authorization": f"Bearer {token}"}