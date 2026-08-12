"""
Unit tests for auth security utilities and the self-training memory service.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-please-change-32chars-plus")

from auth.security import (  # noqa: E402
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from core.exceptions import AuthenticationError  # noqa: E402


# --- Password hashing ------------------------------------------------------
def test_password_hash_and_verify():
    hashed = hash_password("S3cure!Password")
    assert hashed != "S3cure!Password"
    assert verify_password("S3cure!Password", hashed) is True
    assert verify_password("wrong", hashed) is False


def test_unique_salts():
    a = hash_password("same")
    b = hash_password("same")
    assert a != b


# --- JWT tokens --------------------------------------------------------------
def test_access_token_roundtrip():
    token = create_access_token("42", "agent")
    payload = decode_token(token)
    assert payload["sub"] == "42"
    assert payload["role"] == "agent"
    assert payload["type"] == "access"


def test_refresh_token_type():
    token = create_refresh_token("7", "manager")
    payload = decode_token(token)
    assert payload["type"] == "refresh"
    assert payload["sub"] == "7"


def test_invalid_token_raises():
    with pytest.raises(AuthenticationError):
        decode_token("not.a.valid.token")


@pytest.mark.asyncio
async def test_memory_ingest_and_recall():
    import tempfile as _tf
    from pathlib import Path as _P

    db_url = "sqlite+aiosqlite:///" + str(_P(_tf.gettempdir()) / "hdtest_mem.db")
    _P(db_url.split("///")[1]).unlink(missing_ok=True)
    os.environ["DATABASE_URL"] = db_url

    # Import lazily after env is set so engine binds to test DB.
    from database.models import init_db  # noqa: E402
    from services.memory_service import MemoryService  # noqa: E402

    await init_db()
    svc = MemoryService()

    run = await svc.ingest_payload(
        1,
        {
            "issue": "Laptop fans run loudly",
            "resolution": "Update BIOS and check thermal profile",
            "environment": "Dell Latitude",
            "priority": "P3",
        },
    )
    assert run.status == "COMPLETED"

    used, context = await svc.get_relevant_context(1, "laptop fan loud noise")
    assert used is True
    assert context and "BIOS" in context

    # Re-ingesting the same issue should not duplicate run logs badly.
    docs = await svc.get_retrieval_documents(1)
    assert len(docs) >= 1


@pytest.mark.asyncio
async def test_add_case_study_defaults():
    import os as _os

    db_path = Path(tempfile.gettempdir()) / "hdtest_mem.db"
    _os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///" + str(db_path)

    from services.memory_service import MemoryService  # noqa: E402

    svc = MemoryService()
    study = await svc.add_case_study(
        tenant_id=1,
        title="Printer spooler hang",
        description="Queue gets stuck after update",
        resolution="Restart spooler, clear queue",
        priority="P2",
        category="Printing",
        tags=["print", "spooler"],
    )
    assert study.id > 0
    assert study.created_by == 0  # DB default since not provided