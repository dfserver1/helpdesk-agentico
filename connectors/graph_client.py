"""
Microsoft Graph client for HelpDesk Enterprise Copilot.

Interacts with SharePoint (drives/sites), Teams (channels/messages) and
Outlook (messages via Graph search endpoint) using a client-credentials
token obtained through MSAL (Entra ID app registration).
"""

from typing import List, Optional

import httpx

from config.logging import get_logger
from config.settings import get_settings
from core.exceptions import ExternalServiceError

logger = get_logger("graph_client")

GRAPH_AUTHORITY = "https://login.microsoftonline.com"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class MicrosoftGraphClient:
    """Thin async wrapper around the Microsoft Graph API."""

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self._app = None
        self._token = None

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------
    def _build_app(self):
        if self._app is None:
            from msal import ConfidentialClientApplication

            if not (self.settings.GRAPH_CLIENT_ID and self.settings.GRAPH_CLIENT_SECRET):
                return None
            self._app = ConfidentialClientApplication(
                client_id=self.settings.GRAPH_CLIENT_ID,
                client_credential=self.settings.GRAPH_CLIENT_SECRET,
                authority=f"{GRAPH_AUTHORITY}/{self.settings.GRAPH_TENANT_ID or 'common'}",
                validate_authority=False,
            )
        return self._app

    def is_configured(self) -> bool:
        return bool(
            self.settings.GRAPH_CLIENT_ID
            and self.settings.GRAPH_CLIENT_SECRET
            and self.settings.GRAPH_TENANT_ID
        )

    def get_access_token(self) -> Optional[str]:
        """Obtain (and cache) an app-only access token via MSAL."""
        app = self._build_app()
        if app is None:
            return None
        if self._token:
            return self._token
        try:
            result = app.acquire_token_for_client(scopes=[GRAPH_SCOPE])
        except Exception as e:  # pragma: no cover - depends on MSAL internals
            logger.error(f"MSAL token acquisition failed: {e}")
            return None
        if "access_token" not in result:
            logger.error(
                f"MSAL failed: {result.get('error')} {result.get('error_description', '')[:200]}"
            )
            return None
        self._token = result["access_token"]
        return self._token

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------
    async def _get(self, url: str, params: Optional[dict] = None) -> dict:
        token = self.get_access_token()
        if not token:
            raise ExternalServiceError(
                "Graph token not available", service="microsoft_graph"
            )
        headers = {
            "Authorization": f"Bearer {token}",
            "ConsistencyLevel": "eventual",  # required for $search / case-insensitive filters
        }
        timeout = httpx.Timeout(20.0, connect=10.0)
        try:
            async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
                resp = await client.get(url, headers=headers, params=params)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as e:
            # 404 on a search deletes anyway to an empty result
            if e.response.status_code == 404:
                return {}
            logger.warning(f"Graph GET {url} -> {e.response.status_code}")
            return {}
        except httpx.HTTPError as e:
            logger.warning(f"Graph request error {url}: {e}")
            return {}

    # ------------------------------------------------------------------
    # SharePoint
    # ------------------------------------------------------------------
    async def search_sharepoint(self, query: str, top: int = 8) -> List[dict]:
        """Search SharePoint sites/files via the Graph $search capability."""
        params = {"$search": f'"{query}"', "$top": top, "$count": "true"}
        data = await self._get(f"{GRAPH_BASE}/sites", params=params)
        sites = []
        for site in data.get("value", [])[:top]:
            name = site.get("displayName") or site.get("name") or site.get("id", "")
            web_url = site.get("webUrl", "")
            # Attempt to fetch the default drive to grab a sample file
            drive_sample = ""
            try:
                drive = await self._get(
                    f"{GRAPH_BASE}/sites/{site.get('id', '')}/drive/root/children",
                    params={"$top": 3},
                )
                names = [item.get("name", "") for item in drive.get("value", [])]
                drive_sample = ", ".join(names[:3]) if names else ""
            except Exception:
                pass
            sites.append(
                {
                    "title": name,
                    "content": f"SharePoint site '{name}'. Sample files: {drive_sample or 'n/a'}",
                    "source": "sharepoint",
                    "url": web_url,
                }
            )
        return sites

    # ------------------------------------------------------------------
    # Teams
    # ------------------------------------------------------------------
    async def search_teams(self, query: str, top: int = 8) -> List[dict]:
        """Search Teams channels/messages via Graph."""
        data = await self._get(f"{GRAPH_BASE}/me/chats", params={"$top": top})
        results = []
        for chat in data.get("value", [])[:top]:
            chat_id = chat.get("id", "")
            msgs = await self._get(
                f"{GRAPH_BASE}/me/chats/{chat_id}/messages",
                params={"$top": 5},
            )
            for msg in msgs.get("value", [])[:5]:
                body = (msg.get("body") or {}).get("content", "")
                if not body:
                    continue
                results.append(
                    {
                        "title": f"Teams chat message ({chat.get('topic', chat_id[:8])})",
                        "content": body[:1000],
                        "source": "teams",
                        "url": None,
                    }
                )
        # Fallback: grouped message search
        search = await self._get(
            f"{GRAPH_BASE}/me/messages",
            params={"$search": f'"{query}"', "$top": top},
        )
        return results[:top]

    # ------------------------------------------------------------------
    # Outlook
    # ------------------------------------------------------------------
    async def search_outlook(self, query: str, top: int = 8) -> List[dict]:
        """Search the user's mailbox via Graph (classic search extension)."""
        params = {"$search": f'"{query}"', "$top": top, "$select": "subject,bodyPreview,webLink,from"}
        data = await self._get(f"{GRAPH_BASE}/me/messages", params=params)
        results = []
        for msg in data.get("value", [])[:top]:
            results.append(
                {
                    "title": f"Email: {msg.get('subject', '')}",
                    "content": (msg.get("bodyPreview", "") or "")[:1000],
                    "source": "outlook",
                    "url": msg.get("webLink"),
                }
            )
        return results


client = MicrosoftGraphClient()


def get_graph_client() -> MicrosoftGraphClient:
    return client