"""
Connector registry: aggregates results across all configured sources in
parallel (map phase) and deduplicates them.
"""

from typing import List

from config.logging import get_logger
from config.settings import get_settings
from connectors.base import BaseConnector, ConnectorResult
from app.concurrency import run_subtasks

logger = get_logger("connectors")


class ConnectorRegistry:
    """Builds and runs the set of enabled connectors + web search."""

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self.persistent = self._build_persistent()

    # ------------------------------------------------------------------
    def _build_persistent(self) -> List[BaseConnector]:
        out = []
        if self.settings.CONNECTORS_ENABLED:
            try:
                from connectors.o365 import OutlookConnector, SharePointConnector, TeamsConnector

                out.extend([
                    SharePointConnector(),
                    TeamsConnector(),
                    OutlookConnector(),
                ])
            except Exception as e:  # pragma: no cover - import safety
                logger.warning(f"O365 connectors unavailable: {e}")

        if getattr(self.settings, "GOOGLE_CONNECTORS_ENABLED", False):
            try:
                from connectors.google import GmailConnector, GoogleDriveConnector

                out.extend([
                    GoogleDriveConnector(),
                    GmailConnector(),
                ])
            except Exception as e:
                logger.warning(f"Google connectors unavailable: {e}")

        return out

    # ------------------------------------------------------------------
    def status(self) -> List[dict]:
        web = get_web_search_source()
        items = [c.status() for c in self.persistent]
        items.append(
            {
                "name": "web",
                "label": "Web search (fallback)",
                "enabled": web.is_configured() if web else False,
                "configured": web.is_configured() if web else False,
            }
        )
        return items

    # ------------------------------------------------------------------
    async def search_source(
        self,
        connector: BaseConnector,
        query: str,
        top_k: int,
    ) -> List[ConnectorResult]:
        try:
            return await connector.search(query, top_k=top_k)
        except Exception as e:
            logger.warning(f"Connector {connector.name} failed: {e}")
            return []

    async def search_all(
        self,
        query: str,
        top_k: int = 5,
        include_web: bool = True,
    ) -> List[ConnectorResult]:
        """Query every source in parallel and merge the results."""
        tasks = []
        for c in self.persistent:
            if c.is_enabled():
                tasks.append(self.search_source(c, query, top_k))

        if include_web and self.settings.WEB_SEARCH_ENABLED:
            web = get_web_search_source()
            if web is not None:
                tasks.append(web.search(query, top_k=top_k))

        if not tasks:
            return []

        results_lists = await run_subtasks(tasks, max_workers=self.settings.SUBTASK_MAX_WORKERS)

        merged: List[ConnectorResult] = []
        seen = set()
        for rl in results_lists:
            if isinstance(rl, Exception):
                continue
            for r in rl:
                key = (r.source, r.url or r.title)
                if key in seen:
                    continue
                seen.add(key)
                merged.append(r)
        merged.sort(key=lambda r: r.score, reverse=True)
        return merged[: max(top_k * 3, top_k)]


_registry: ConnectorRegistry | None = None


def get_registry() -> ConnectorRegistry:
    global _registry
    if _registry is None:
        _registry = ConnectorRegistry()
        logger.debug(f"Connector registry ready: {[c.name for c in _registry.persistent]}")
    return _registry


def get_web_search_source():
    try:
        from connectors.web_search import get_web_search

        return get_web_search()
    except Exception:  # pragma: no cover
        return None


async def search_all_sources(
    query: str,
    top_k: int = 5,
    include_web: bool = True,
) -> List[ConnectorResult]:
    """Public async facade used by routes and the agent graph."""
    return await get_registry().search_all(query, top_k=top_k, include_web=include_web)


def search_all_sources_sync(
    query: str,
    top_k: int = 5,
    include_web: bool = True,
) -> List[ConnectorResult]:
    """
    Synchronous facade for the sync LangGraph nodes.

    The agent runs in a worker thread with no running event loop, so we can
    drive the async connector fan-out with ``asyncio.run`` here (mirrors the
    memory_service sync-bridge pattern).
    """
    return _run_sync_bridge(lambda: search_all_sources(query, top_k=top_k, include_web=include_web))


def _run_sync_bridge(factory):
    """Run ``factory()`` (returns an awaitable) to completion safely across thread/loop boundaries."""
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

    box: dict = {}
    exc_box: dict = {}

    def target():
        try:
            box["result"] = _run()
        except BaseException as e:
            exc_box["error"] = e

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()

    if "error" in exc_box:
        raise exc_box["error"]
    return box.get("result", [])