"""
Health check endpoints.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import get_db_session

router = APIRouter()


@router.get("")
async def health_check(session: AsyncSession = Depends(get_db_session)) -> dict:
    """Basic liveness probe."""
    return {"status": "ok", "version": "12.0.0"}


@router.get("/ready")
async def readiness(session: AsyncSession = Depends(get_db_session)) -> dict:
    """Readiness probe verifying DB connectivity."""
    try:
        await session.execute(text("SELECT 1"))
        db = "ok"
    except Exception:
        db = "unavailable"
    return {"status": "ready" if db == "ok" else "degraded", "database": db}