"""
Self-training memory API schemas.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PayloadIngestRequest(BaseModel):
    payload: Dict[str, Any] = Field(
        ...,
        description="Arbitrary metadata object with at least 'issue' and 'resolution'.",
    )


class CaseStudyCreate(BaseModel):
    title: str = Field(min_length=3, max_length=500)
    description: str = Field(min_length=3)
    resolution: str = Field(min_length=5)
    priority: str = Field(default="P3", pattern="^(P1|P2|P3|P4)$")
    category: str = "Technical"
    tags: List[str] = []
    payload: Dict[str, Any] = {}


class MemoryEntryResponse(BaseModel):
    id: int
    memory_type: str
    content: str
    source: str
    confidence: float
    times_used: int
    metadata_json: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class TrainingRunResponse(BaseModel):
    id: int
    tenant_id: int
    trigger_type: str
    status: str
    source_count: int
    indexed_count: int
    metrics: dict
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}