"""
Web search fallback for HelpDesk Enterprise Copilot.

Used when the internal knowledge base and connectors produce no relevant
documentation. Searches the public web through trustworthy sources:

  - DuckDuckGo Instant Answer + HTML results (no API key required)
  - Wikipedia API (reliable, structured encyclopedia content)
  - Optionally Brave Search / Tavily when an API key is configured.

Results are normalized into ``ConnectorResult`` objects with real URLs so the
LLM can cite actual sources.
"""

import re
from typing import List, Optional

import httpx

from config.logging import get_logger
from config.settings import get_settings
from connectors.base import ConnectorResult

logger = get_logger("web_search")

_DDG = "https://html.duckduckgo.com/html/"
_WIKI_API = "https://en.wikipedia.org/w/api.php"
_TG = re.compile(r"<a[^>]+class=\"result__a\"[^>]+href=\"([^\"]+)\"[^>]*>(.*?)</a>", re.S)
_TTG = re.compile(r"<a[^>]+class=\"result__snippet\"[^>]*>(.*?)</a>", re.S)


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


class WebSearchSource:
    """Search the public web through multiple backends."""

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self.timeout = self.settings.WEB_SEARCH_TIMEOUT_SECONDS

    def is_configured(self) -> bool:
        return bool(self.settings.WEB_SEARCH_ENABLED)

    # ------------------------------------------------------------------
    async def _ddg(self, query: str, top: int) -> List[ConnectorResult]:
        headers = {"User-Agent": "Mozilla/5.0 (HelpDeskCopilot/12; +helpdesk)"}
        timeout = httpx.Timeout(self.timeout)
        try:
            async with httpx.AsyncClient(timeout=timeout, headers=headers, verify=False) as client:
                resp = await client.post(_DDG, data={"q": query})
                resp.raise_for_status()
                html = resp.text
        except httpx.HTTPError as e:
            logger.warning(f"DDG search failed: {e}")
            return []

        links = _TG.findall(html)
        snippets = _TTG.findall(html)
        results: List[ConnectorResult] = []
        for i, (href, title) in enumerate(links[:top]):
            snippet = snippets[i] if i < len(snippets) else ""
            results.append(
                ConnectorResult(
                    title=_strip_html(title),
                    content=_strip_html(snippet) or _strip_html(title),
                    source="web",
                    url=href,
                    score=0.7 - i * 0.05,
                    metadata={"engine": "duckduckgo"},
                )
            )
        return results

    # ------------------------------------------------------------------
    async def _wikipedia(self, query: str, top: int) -> List[ConnectorResult]:
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": top,
            "format": "json",
            "prop": "snippet",
        }
        timeout = httpx.Timeout(self.timeout)
        try:
            async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
                resp = await client.get(_WIKI_API, params=params)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            logger.warning(f"Wikipedia search failed: {e}")
            return []

        results: List[ConnectorResult] = []
        for i, hit in enumerate(data.get("query", {}).get("search", [])[:top]):
            title = hit.get("title", "")
            snippet = _strip_html(hit.get("snippet", ""))
            page_url = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"
            results.append(
                ConnectorResult(
                    title=title,
                    content=snippet or title,
                    source="web",
                    url=page_url,
                    score=0.6 - i * 0.03,
                    metadata={"engine": "wikipedia"},
                )
            )
        return results

    # ------------------------------------------------------------------
    async def _brave(self, query: str, top: int) -> List[ConnectorResult]:
        key = self.settings.BRAVE_SEARCH_KEY
        if not key:
            return []
        try:
            async with httpx.AsyncClient(timeout=self.timeout, verify=False) as client:
                resp = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "count": top},
                    headers={"X-Subscription-Token": key, "Accept": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            logger.warning(f"Brave search failed: {e}")
            return []
        out = []
        for i, r in enumerate(data.get("web", {}).get("results", [])[:top]):
            out.append(
                ConnectorResult(
                    title=r.get("title", ""),
                    content=f"{r.get('description', '')} {r.get('title', '')}".strip(),
                    source="web",
                    url=r.get("url"),
                    score=0.8 - i * 0.05,
                    metadata={"engine": "brave"},
                )
            )
        return out

    async def _tavily(self, query: str, top: int) -> List[ConnectorResult]:
        key = self.settings.TAVILY_API_KEY
        if not key:
            return []
        try:
            async with httpx.AsyncClient(timeout=self.timeout, verify=False) as client:
                resp = await client.post(
                    "https://api.tavily.com/search",
                    json={"api_key": key, "query": query, "max_results": top, "search_depth": "basic"},
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            logger.warning(f"Tavily search failed: {e}")
            return []
        out = []
        for i, r in enumerate(data.get("results", [])[:top]):
            out.append(
                ConnectorResult(
                    title=r.get("title", ""),
                    content=r.get("content", ""),
                    source="web",
                    url=r.get("url"),
                    score=0.85 - i * 0.05,
                    metadata={"engine": "tavily"},
                )
            )
        return out

    # ------------------------------------------------------------------
    async def search(self, query: str, top_k: int = 5) -> List[ConnectorResult]:
        """Search the web; prefer configured engines, fall back to DDG+Wiki."""
        awaitables = [self._brave(query, top_k), self._tavily(query, top_k)]
        if not any([self.settings.BRAVE_SEARCH_KEY, self.settings.TAVILY_API_KEY]):
            awaitables = [self._ddg(query, top_k), self._wikipedia(query, top_k)]

        best: List[ConnectorResult] = []
        for per_engine in awaitables:
            try:
                engine_results = await per_engine
            except Exception as e:
                logger.warning(f"Web search engine failed: {e}")
                continue
            for r in engine_results:
                if not r.url or not r.content.strip():
                    continue
                if r.url not in {x.url for x in best}:
                    best.append(r)
        best.sort(key=lambda x: x.score, reverse=True)
        return best[:top_k]


_web_search = WebSearchSource()


def get_web_search() -> WebSearchSource:
    return _web_search