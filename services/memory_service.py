"""
Self-Training Memory Service for HelpDesk Enterprise Copilot.

Core differentiator: the agent learns continuously from real usage.

Memory types:
  - EPISODIC   : past resolved conversations (query->solution)
  - SEMANTIC   : generalized facts learned from payloads/schemas
  - PROCEDURAL : learned workflows/steps (how to resolve repeated issues)
  - WORKFLOW   : runbook/playbook entries

Ingestion API (arbitrary metadata/payloads):
  PostCaseStudy(payload={...})      -> supervised teaching example
  Feedback(query, resolution, rating) -> auto-learned memory
  LearnFromResolution(query, solution, metadata) -> episodic memory

Retrieval integration is wired into the RAG pipeline (BM25 corpus + vector
recall), so the agent answers future similar queries using its memory first.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_settings
from config.logging import get_logger
from core.exceptions import MemoryError
from database.models import (
    MemoryEntry,
    CaseStudy,
    TrainingRun,
    SessionLocal,
)

logger = get_logger("memory_service")


# --------------------------------------------------------------------------
# Sync bridge for LangChain/langgraph (which run synchronously)
# --------------------------------------------------------------------------
def _run_sync(factory):
    """
    Run an async worker (built by ``factory``) to completion from a
    synchronous caller.

    ``factory`` must be a zero-arg callable returning an awaitable; the
    engine/connections it creates all live inside a single event loop so
    aiosqlite never crosses thread/loop boundaries.

    Works whether or not a loop is already running in this thread:
      - no running loop -> asyncio.run() directly
      - running loop    -> execute in a fresh worker thread with its own loop
    """
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

    box: Dict[str, Any] = {}
    exc_box: Dict[str, Any] = {}

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
    return box.get("result")


def _new_session_maker():
    """Build an isolated async engine + sessionmaker for sync-bridge calls.

    Returns ``(engine, maker)``. Must be constructed and used within a single
    event loop (the sync facades build it inside the loop that runs them).
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from database.models import create_db_engine

    engine = create_db_engine()
    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    return engine, maker


class MemoryService:
    """Persistent self-training memory store + recall."""

    def __init__(self, settings=None):
        self.settings = settings or get_settings()

    # ------------------------------------------------------------------
    # Write: register learned knowledge
    # ------------------------------------------------------------------
    async def add_episodic_memory(
        self,
        tenant_id: int,
        content: str,
        source_query: str = "",
        metadata: Optional[Dict] = None,
        confidence: float = 0.9,
        _sessionmaker=None,
    ) -> MemoryEntry:
        """Store a resolved query->solution pair."""
        maker = _sessionmaker or SessionLocal
        async with maker() as session:
            entry = MemoryEntry(
                tenant_id=tenant_id,
                memory_type="EPISODIC",
                content=content,
                source=self._source_from(metadata),
                confidence=confidence,
                metadata_json=self._safe_metadata(metadata, {"source_query": source_query}),
            )
            session.add(entry)
            await session.commit()
            await session.refresh(entry)
            logger.info(f"Stored episodic memory #{entry.id} for tenant {tenant_id}")
            return entry

    async def add_case_study(
        self,
        tenant_id: int,
        title: str,
        description: str,
        resolution: str,
        priority: str = "P3",
        category: str = "Technical",
        tags: Optional[List[str]] = None,
        payload: Optional[Dict] = None,
    ) -> "CaseStudy":
        """Ingest a labeled case study (supervised self-training example)."""
        from database.models import CaseStudy

        async with SessionLocal() as session:
            study = CaseStudy(
                tenant_id=tenant_id,
                title=title,
                description=description,
                resolution=resolution,
                priority=priority,
                category=category,
                tags=tags or [],
                metadata_json=payload or {},
            )
            session.add(study)
            await session.commit()
            await session.refresh(study)
            logger.info(f"Stored case study #{study.id}: {title}")
            return study

    async def ingest_payload(
        self,
        tenant_id: int,
        payload: Dict[str, Any],
    ) -> TrainingRun:
        """
        Ingest an arbitrary metadata/payload object to teach the agent.
        Payloads may include: issue, resolution, environment, symptoms,
        affected_app, patch_levels, steps, results.

        Returns the TrainingRun created.
        """
        issue = payload.get("issue") or payload.get("query") or payload.get("title")
        resolution = payload.get("resolution") or payload.get("solution") or payload.get("answer")

        if not issue or not resolution:
            raise MemoryError(
                "Payload must include 'issue'/'query' and 'resolution'/'solution' fields.",
                details={"required": ["issue", "resolution"]},
            )

        async with SessionLocal() as session:
            run = TrainingRun(
                tenant_id=tenant_id,
                trigger_type="AUTO_PAYLOAD",
                status="PROCESSING",
            )
            session.add(run)
            await session.commit()
            await session.refresh(run)

        try:
            await self.add_episodic_memory(
                tenant_id=tenant_id,
                content=resolution,
                source_query=issue,
                metadata=self._payload_to_meta(payload),
                confidence=float(payload.get("confidence", 0.9)),
            )
            # Mark run complete
            async with SessionLocal() as session:
                await session.execute(
                    update(TrainingRun)
                    .where(TrainingRun.id == run.id)
                    .values(status="COMPLETED", completed_at=datetime.now(timezone.utc))
                )
                await session.commit()
                refreshed = (
                    (await session.execute(select(TrainingRun).where(TrainingRun.id == run.id)))
                    .scalar_one()
                )
                logger.info(f"Payload ingest run #{run.id} COMPLETED for tenant {tenant_id}")
            return refreshed
        except Exception as e:
            async with SessionLocal() as session:
                await session.execute(
                    update(TrainingRun)
                    .where(TrainingRun.id == run.id)
                    .values(status="FAILED", error_message=str(e))
                )
                await session.commit()
            raise

    # ------------------------------------------------------------------
    # Query: recall learned knowledge
    # ------------------------------------------------------------------
    async def recall(
        self,
        tenant_id: int,
        query: str,
        top_k: int = 3,
        min_confidence: float = 0.5,
        _sessionmaker=None,
    ) -> List[MemoryEntry]:
        """
        Retrieve relevant memory entries for a query using keyword overlap;
        may be upgraded to vector recall when embeddings are configured.
        """
        maker = _sessionmaker or SessionLocal
        async with maker() as session:
            rows = (
                (await session.execute(
                    select(MemoryEntry)
                    .where(
                        MemoryEntry.tenant_id == tenant_id,
                        MemoryEntry.confidence >= min_confidence,
                    )
                    .order_by(MemoryEntry.times_used.desc())
                    .limit(200)
                ))
                .scalars()
                .all()
            )

        query_tokens = set(w.lower() for w in query.split())
        scored = []
        for entry in rows:
            meta = entry.metadata_json or {}
            text = f"{entry.source} {entry.content} {meta.get('source_query', '')}"
            text_tokens = set(w.lower() for w in text.split())
            overlap = len(query_tokens & text_tokens)
            if overlap > 0:
                scored.append((overlap, entry.times_used, entry))

        scored.sort(key=lambda x: (-x[0], -x[1]))
        return [e for _, _, e in scored[:top_k]]

    async def get_retrieval_documents(
        self,
        tenant_id: int,
        limit: int = 500,
        _sessionmaker=None,
    ) -> list:
        """Return memory entries as LangChain Documents for BM25 corpus seeding."""
        from langchain_core.documents import Document

        maker = _sessionmaker or SessionLocal
        async with maker() as session:
            rows = (
                await session.execute(
                    select(MemoryEntry)
                    .where(MemoryEntry.tenant_id == tenant_id)
                    .order_by(MemoryEntry.confidence.desc())
                    .limit(limit)
                )
            ).scalars().all()

        docs = []
        for entry in rows:
            meta = entry.metadata_json or {}
            source_query = meta.get("source_query", "")
            content = source_query + "\n" + entry.content
            docs.append(Document(
                page_content=content,
                metadata={
                    "source": f"memory_{entry.id}",
                    "tenant_id": str(tenant_id),
                    "memory_type": entry.memory_type,
                    "confidence": entry.confidence,
                    "times_used": entry.times_used,
                },
            ))
        return docs

    # --- Sync facades (for LangChain/langgraph sync execution) -------------
    def get_retrieval_documents_sync(self, tenant_id: int, limit: int = 500) -> list:
        """Synchronous counterpart used by the RAG pipeline BM25 seeding."""
        async def _worker():
            engine, maker = _new_session_maker()
            try:
                return await self.get_retrieval_documents(tenant_id, limit, _sessionmaker=maker)
            finally:
                await engine.dispose()

        return _run_sync(_worker)

    def add_episodic_memory_sync(
        self,
        tenant_id: int,
        content: str,
        source_query: str = "",
        metadata: Optional[Dict] = None,
        confidence: float = 0.9,
    ) -> MemoryEntry:
        """Synchronous counterpart of add_episodic_memory."""
        async def _worker():
            engine, maker = _new_session_maker()
            try:
                return await self.add_episodic_memory(
                    tenant_id,
                    content,
                    source_query=source_query,
                    metadata=metadata,
                    confidence=confidence,
                    _sessionmaker=maker,
                )
            finally:
                await engine.dispose()

        return _run_sync(_worker)

    def get_relevant_context_sync(
        self,
        tenant_id: int,
        query: str,
        top_k: int = 3,
        confidence_threshold: float = 0.7,
    ) -> tuple:
        """Synchronous counterpart of get_relevant_context for the RAG pipeline."""
        async def _worker():
            engine, maker = _new_session_maker()
            try:
                matches = await self.recall(
                    tenant_id,
                    query,
                    top_k=top_k,
                    min_confidence=confidence_threshold,
                    _sessionmaker=maker,
                )
                if not matches:
                    return False, None

                parts = [
                    f"[Past case: {(m.metadata_json or {}).get('source_query', 'N/A')} "
                    f"(confidence {m.confidence:.2f}, used {m.times_used}x)]\n{m.content}"
                    for m in matches[:3]
                ]
                return True, "\n\n---\n\n".join(parts)
            finally:
                await engine.dispose()

        return _run_sync(_worker)

    async def get_relevant_context(
        self,
        tenant_id: int,
        query: str,
        top_k: int = 3,
        confidence_threshold: float = 0.7,
    ) -> tuple:
        """
        Return (used: bool, context_text: str) if high-confidence memory exists.
        Called by the RAG pipeline as a memory-boost before KB-only generation.
        """
        matches = await self.recall(
            tenant_id,
            query,
            top_k=top_k,
            min_confidence=confidence_threshold,
        )
        if not matches:
            return False, None

        context_parts = []
        for m in matches[:3]:
            context_parts.append(
                f"[Past case: {(m.metadata_json or {}).get('source_query', 'N/A')} "
                f"(confidence {m.confidence:.2f}, used {m.times_used}x)]\n{m.content}"
            )
            # Increment usage stats
            await self._bump_usage(m.id)
        return True, "\n\n---\n\n".join(context_parts)

    async def _bump_usage(self, memory_id: int):
        async with SessionLocal() as session:
            await session.execute(
                update(MemoryEntry)
                .where(MemoryEntry.id == memory_id)
                .values(
                    times_used=MemoryEntry.times_used + 1,
                    last_used_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()

    # ------------------------------------------------------------------
    # Feedback / reinforcement
    # ------------------------------------------------------------------
    async def record_feedback(
        self,
        tenant_id: int,
        query: str,
        solution: str,
        rating: int = 5,
        metadata: Optional[Dict] = None,
    ) -> MemoryEntry:
        """
        Reinforce a solution into memory based on user feedback.
        rating (1-5) adjusts confidence: >=4 high, else moderate.
        """
        confidence = min(0.95, 0.5 + rating * 0.09)
        return await self.add_episodic_memory(
            tenant_id=tenant_id,
            content=solution,
            source_query=query,
            metadata={"source": (metadata or {}).get("source", "user_feedback"), "rating": rating},
            confidence=confidence,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _safe_metadata(metadata: Optional[Dict], defaults: Optional[Dict] = None) -> Dict:
        safe = dict(metadata or {})
        if defaults:
            for k, v in defaults.items():
                safe.setdefault(k, v)
        return safe

    @staticmethod
    def _payload_to_meta(payload: Dict) -> Dict:
        """Normalize a payload into memory metadata (keep provenance)."""
        keys = [
            "environment", "priority", "category", "symptoms", "steps",
            "applies_to", "owner", "created_by", "schema_version",
        ]
        meta = {k: payload[k] for k in keys if k in payload}
        meta["payload_provenance"] = payload.get("provenance", "api")
        return meta

    @staticmethod
    def _source_from(metadata: Optional[Dict]) -> str:
        if not metadata:
            return "user_input"
        return metadata.get("source", metadata.get("provenance", "user_input"))


def merge_defaults(target: Dict, defaults: Dict) -> Dict:
    """Merge defaults into target (non-destructive)."""
    result = dict(defaults)
    result.update(target)
    return result