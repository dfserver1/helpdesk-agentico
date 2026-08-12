"""
Self-training memory endpoints: ingest payloads, case studies, recall.
"""

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas.memory import (
    CaseStudyCreate,
    MemoryEntryResponse,
    PayloadIngestRequest,
    TrainingRunResponse,
)
from auth.deps import require_roles
from core.exceptions import MemoryError, NotFoundError
from database.models import TrainingRun, User, get_db_session
from services.memory_service import MemoryService

router = APIRouter()

_manager = None


def _service() -> MemoryService:
    global _manager
    if _manager is None:
        _manager = MemoryService()
    return _manager


@router.post("/ingest", response_model=TrainingRunResponse, status_code=201)
async def ingest_payload(
    body: PayloadIngestRequest,
    user: User = Depends(require_roles("agent", "manager", "admin")),
):
    """Teach the agent a new issue/resolution pair (self-training)."""
    run = await _service().ingest_payload(
        tenant_id=user.organization_id or 1,
        payload=body.payload,
    )
    return run


@router.post("/case-studies", response_model=dict, status_code=201)
async def create_case_study(
    body: CaseStudyCreate,
    user: User = Depends(require_roles("agent", "manager", "admin")),
):
    """Store a labeled case study for supervised self-training."""
    study = await _service().add_case_study(
        tenant_id=user.organization_id or 1,
        title=body.title,
        description=body.description,
        resolution=body.resolution,
        priority=body.priority,
        category=body.category,
        tags=body.tags,
        payload=body.payload,
    )
    return {"id": study.id, "title": study.title}


@router.post("/recall", response_model=List[MemoryEntryResponse])
async def recall(
    query: str,
    top_k: int = 3,
    user: User = Depends(require_roles("agent", "manager", "admin")),
):
    """Retrieve relevant learned memory entries for a query."""
    entries = await _service().recall(
        tenant_id=user.organization_id or 1,
        query=query,
        top_k=max(1, min(top_k, 10)),
    )
    return entries


@router.get("/runs", response_model=list[TrainingRunResponse])
async def list_runs(
    user: User = Depends(require_roles("agent", "manager", "admin")),
    db: AsyncSession = Depends(get_db_session),
):
    """List recent self-training runs for the tenant."""
    runs = (
        (await db.execute(
            select(TrainingRun)
            .where(TrainingRun.tenant_id == (user.organization_id or 1))
            .order_by(TrainingRun.created_at.desc())
            .limit(50)
        ))
        .scalars()
        .all()
    )
    return runs