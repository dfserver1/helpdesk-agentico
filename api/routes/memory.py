"""
Self-training memory endpoints: ingest payloads, case studies, recall.
"""

from typing import List

from fastapi import APIRouter, Depends, Query
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
    query: str = Query(..., min_length=1, max_length=1000),
    top_k: int = Query(default=3, ge=1, le=20),
    user: User = Depends(require_roles("agent", "manager", "admin")),
):
    """Retrieve relevant learned memory entries for a query."""
    clean_query = query.strip()
    entries = await _service().recall(
        tenant_id=user.organization_id or 1,
        query=clean_query,
        top_k=top_k,
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


@router.post("/sync-connectors", response_model=dict, status_code=200)
async def sync_connectors_and_train(
    query: str = Query(default="IT support troubleshooting guide policy procedure manual", max_length=500),
    top_k: int = Query(default=10, ge=1, le=50),
    user: User = Depends(require_roles("agent", "manager", "admin")),
):
    """
    Harvest documents and case resolutions from connected enterprise sources
    (Google Drive, Gmail, SharePoint, Teams, Outlook) and auto-train the memory model.
    """
    from connectors.registry import search_all_sources
    from rag.pipeline import get_rag_pipeline

    tenant_id = user.organization_id or 1
    results = await search_all_sources(query=query, top_k=top_k, include_web=False)

    learned_count = 0
    service = _service()

    for r in results:
        if r.content and len(r.content.strip()) > 30:
            await service.ingest_payload(
                tenant_id=tenant_id,
                payload={
                    "issue": r.title,
                    "resolution": r.content,
                    "source": r.source,
                    "url": r.url or "",
                },
            )
            learned_count += 1

    return {
        "status": "success",
        "synced_sources": len(results),
        "learned_entries": learned_count,
        "message": f"Successfully ingested and trained {learned_count} entries from enterprise repositories.",
    }