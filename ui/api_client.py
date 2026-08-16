"""
Async HTTP client for the HelpDesk Copilot REST API.
"""

import os

import httpx


class APIClient:
    """Thin async client wrapping the FastAPI backend."""

    def __init__(self, base_url: str = None, api_prefix: str = "/api/v1"):
        self.base_url = (base_url or os.getenv("API_BASE_URL", "http://localhost:8000")).rstrip("/")
        self.api_prefix = api_prefix

    async def close(self):
        pass

    def url(self, path: str) -> str:
        return f"{self.base_url}{self.api_prefix}{path}"

    async def _request(self, method: str, path: str, token: str = None, **kwargs):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.request(method, self.url(path), headers=headers, **kwargs)
            return resp

    # --- Auth ---------------------------------------------------------------
    async def login(self, email: str, password: str):
        return await self._request("POST", "/auth/login", json={"email": email, "password": password})

    async def register(self, data: dict):
        return await self._request("POST", "/auth/register", json=data)

    async def me(self, token: str):
        return await self._request("GET", "/auth/me", token=token)

    async def oauth_login_url(self, provider: str, redirect_to: str = ""):
        return await self._request(
            "GET",
            f"/auth/oauth/{provider}/login",
            params={"redirect_to": redirect_to} if redirect_to else None,
        )

    # --- Connectors / web search ---------------------------------------------
    async def connector_status(self, token: str):
        return await self._request("GET", "/connectors/status", token=token)

    async def connector_search(self, query: str, token: str, top_k: int = 5, include_web: bool = True):
        return await self._request(
            "POST",
            "/connectors/search",
            token=token,
            params={"query": query, "top_k": top_k, "include_web": include_web},
        )

    # --- Chat ----------------------------------------------------------------
    async def chat(self, message: str, token: str, session_id: int = None):
        body = {"message": message}
        if session_id:
            body["session_id"] = session_id
        return await self._request("POST", "/chat", token=token, json=body)

    async def list_sessions(self, token: str):
        return await self._request("GET", "/chat/sessions", token=token)

    async def get_session_messages(self, session_id: int, token: str):
        return await self._request("GET", f"/chat/sessions/{session_id}/messages", token=token)

    async def decide_ticket(self, session_id: int, decision: str, token: str):
        return await self._request(
            "POST",
            f"/chat/{session_id}/decide",
            token=token,
            params={"decision": decision},
        )

    # --- Tickets -------------------------------------------------------------
    async def list_tickets(self, token: str, page: int = 1, size: int = 20):
        return await self._request(
            "GET", "/tickets", token=token, params={"page": page, "size": size}
        )

    @staticmethod
    def tickets_total(resp) -> int:
        """Total matching tickets exposed via the X-Total-Count header."""
        try:
            return int(resp.headers.get("X-Total-Count", "0") or 0)
        except (AttributeError, ValueError):
            return 0

    async def create_ticket(self, data: dict, token: str):
        return await self._request("POST", "/tickets", token=token, json=data)

    async def get_ticket(self, ticket_id: int, token: str):
        return await self._request("GET", f"/tickets/{ticket_id}", token=token)

    # --- Memory (self-training) ------------------------------------------------
    async def ingest_payload(self, payload: dict, token: str):
        return await self._request("POST", "/memory/ingest", token=token, json={"payload": payload})

    async def create_case_study(self, data: dict, token: str):
        return await self._request("POST", "/memory/case-studies", token=token, json=data)

    async def recall(self, query: str, token: str, top_k: int = 3):
        return await self._request(
            "POST",
            "/memory/recall",
            token=token,
            params={"query": query, "top_k": top_k},
        )

    async def sync_connectors_and_train(self, token: str, query: str = "IT support guide policy", top_k: int = 10):
        return await self._request(
            "POST",
            "/memory/sync-connectors",
            token=token,
            params={"query": query, "top_k": top_k},
        )

    # --- Admin ---------------------------------------------------------------
    async def admin_stats(self, token: str):
        return await self._request("GET", "/admin/stats", token=token)