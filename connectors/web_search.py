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


import urllib.parse

def _is_safe_external_url(url: Optional[str]) -> bool:
    """Validate external URLs to prevent SSRF and unsafe schemes."""
    if not url:
        return False
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = (parsed.hostname or "").lower()
        if not hostname:
            return False
        # Block loopback, metadata endpoints, and link-local addresses
        blocked_hosts = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "169.254.169.254", "metadata.google.internal"}
        if hostname in blocked_hosts or hostname.endswith(".localhost"):
            return False
        return True
    except Exception:
        return False


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
            async with httpx.AsyncClient(
                timeout=timeout, headers=headers, verify=self.settings.verify_tls
            ) as client:
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
            clean_href = href.strip()
            # If DDG returned a relative uddg redirect, decode the actual target
            if "uddg=" in clean_href:
                try:
                    query_params = urllib.parse.parse_qs(urllib.parse.urlparse(clean_href).query)
                    if "uddg" in query_params:
                        clean_href = query_params["uddg"][0]
                except Exception:
                    pass

            if not _is_safe_external_url(clean_href):
                continue

            results.append(
                ConnectorResult(
                    title=_strip_html(title),
                    content=_strip_html(snippet) or _strip_html(title),
                    source="web",
                    url=clean_href,
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
            async with httpx.AsyncClient(
                timeout=timeout, verify=self.settings.verify_tls
            ) as client:
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
            safe_title = urllib.parse.quote(title.replace(" ", "_"), safe=":/~")
            page_url = f"https://en.wikipedia.org/wiki/{safe_title}"
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
            async with httpx.AsyncClient(
                timeout=self.timeout, verify=self.settings.verify_tls
            ) as client:
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
            raw_url = r.get("url")
            if not _is_safe_external_url(raw_url):
                continue
            out.append(
                ConnectorResult(
                    title=r.get("title", ""),
                    content=f"{r.get('description', '')} {r.get('title', '')}".strip(),
                    source="web",
                    url=raw_url,
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
            async with httpx.AsyncClient(
                timeout=self.timeout, verify=self.settings.verify_tls
            ) as client:
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
            raw_url = r.get("url")
            if not _is_safe_external_url(raw_url):
                continue
            out.append(
                ConnectorResult(
                    title=r.get("title", ""),
                    content=r.get("content", ""),
                    source="web",
                    url=raw_url,
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
                if not r.url or not r.content.strip() or not _is_safe_external_url(r.url):
                    continue
                if r.url not in {x.url for x in best}:
                    best.append(r)
        best.sort(key=lambda x: x.score, reverse=True)
        return best[:top_k]


_web_search = WebSearchSource()


def get_web_search() -> WebSearchSource:
    return _web_search