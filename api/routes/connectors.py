"""
Connector endpoints: inspect status and search external sources.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request

from app.rate_limit import limiter
from auth.deps import get_current_active_user
from connectors.base import ConnectorResult
from connectors.registry import get_registry, search_all_sources
from database.models import User

router = APIRouter(tags=["connectors"])


@router.get("/status")
async def connector_status(user: User = Depends(get_current_active_user)):
    """Return the configuration status of every connector."""
    return {"connectors": get_registry().status()}


@router.post("/search")
@limiter.limit("30/minute")
async def connector_search(
    request: Request,
    query: str = Query(..., min_length=1, max_length=1000),
    top_k: int = Query(default=5, ge=1, le=20),
    include_web: bool = Query(default=True),
    user: User = Depends(get_current_active_user),
):
    """Search enabled external connectors (and optionally the web)."""
    results = await search_all_sources(query, top_k=top_k, include_web=include_web)
    return {
        "query": query,
        "count": len(results),
        "results": [r.to_dict() for r in results],
    }