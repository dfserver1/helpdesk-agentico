"""
Google Workspace Client for HelpDesk Enterprise Copilot.

Interacts with Google Drive API v3 and Gmail API v1 using Google Service Account
(with Domain-Wide Delegation) or OAuth2 Access Tokens to retrieve files, documents,
knowledge bases, and support email threads.
"""

import json
import os
import time
import urllib.parse
from typing import Any, Dict, List, Optional

import httpx

from config.logging import get_logger
from config.settings import get_settings
from core.exceptions import ExternalServiceError
from utils.prompt_security import sanitize_context_chunk

logger = get_logger("google_client")

DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1"
OAUTH2_TOKEN_URL = "https://oauth2.googleapis.com/token"

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
]


class GoogleWorkspaceClient:
    """Async client wrapper for Google Drive and Gmail APIs."""

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self._cached_token: Optional[str] = None
        self._token_expires_at: float = 0.0

    def is_configured(self) -> bool:
        """Check whether Google Service Account or API credentials are provided."""
        if not self.settings.GOOGLE_CONNECTORS_ENABLED:
            return False
        if self.settings.GOOGLE_SERVICE_ACCOUNT_JSON or self.settings.GOOGLE_SERVICE_ACCOUNT_FILE:
            return True
        if self.settings.GOOGLE_OAUTH_CLIENT_ID and self.settings.GOOGLE_OAUTH_CLIENT_SECRET:
            return True
        return False

    def _get_service_account_info(self) -> Optional[Dict[str, Any]]:
        if self.settings.GOOGLE_SERVICE_ACCOUNT_JSON:
            try:
                return json.loads(self.settings.GOOGLE_SERVICE_ACCOUNT_JSON)
            except Exception as e:
                logger.error(f"Failed to parse GOOGLE_SERVICE_ACCOUNT_JSON: {e}")
                return None
        if self.settings.GOOGLE_SERVICE_ACCOUNT_FILE and os.path.exists(self.settings.GOOGLE_SERVICE_ACCOUNT_FILE):
            try:
                with open(self.settings.GOOGLE_SERVICE_ACCOUNT_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load GOOGLE_SERVICE_ACCOUNT_FILE: {e}")
                return None
        return None

    async def get_access_token(self) -> Optional[str]:
        """Generate/cache OAuth2 Bearer token for Google APIs."""
        if self._cached_token and time.time() < self._token_expires_at - 60:
            return self._cached_token

        sa_info = self._get_service_account_info()
        if not sa_info:
            return None

        try:
            from jose import jwt

            now = int(time.time())
            payload = {
                "iss": sa_info["client_email"],
                "scope": " ".join(SCOPES),
                "aud": OAUTH2_TOKEN_URL,
                "exp": now + 3600,
                "iat": now,
            }
            if self.settings.GOOGLE_ADMIN_DELEGATE_EMAIL:
                payload["sub"] = self.settings.GOOGLE_ADMIN_DELEGATE_EMAIL

            assertion = jwt.encode(
                payload,
                sa_info["private_key"],
                algorithm="RS256",
            )

            async with httpx.AsyncClient(timeout=15.0, verify=self.settings.verify_tls) as client:
                resp = await client.post(
                    OAUTH2_TOKEN_URL,
                    data={
                        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                        "assertion": assertion,
                    },
                )
                if resp.status_code != 200:
                    logger.error(f"Google OAuth token request failed ({resp.status_code}): {resp.text}")
                    return None

                data = resp.json()
                self._cached_token = data.get("access_token")
                self._token_expires_at = time.time() + data.get("expires_in", 3600)
                return self._cached_token
        except Exception as e:
            logger.error(f"Failed to acquire Google access token: {e}")
            return None

    # ------------------------------------------------------------------
    # Google Drive & Docs Search
    # ------------------------------------------------------------------
    async def search_drive(self, query: str, top: int = 5) -> List[Dict[str, Any]]:
        """Search Google Drive for documents, guides, PDFs, or files matching query."""
        token = await self.get_access_token()
        if not token:
            logger.debug("Google Drive search skipped (no access token configured)")
            return []

        # Sanitize query and prepare Drive v3 q parameter
        clean_q = query.replace("'", "\\'")
        q_filter = f"name contains '{clean_q}' or fullText contains '{clean_q}' and trashed = false"

        url = f"{DRIVE_API_BASE}/files"
        params = {
            "q": q_filter,
            "pageSize": min(top, 20),
            "fields": "files(id, name, mimeType, webViewLink, description, modifiedTime)",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }

        try:
            async with httpx.AsyncClient(timeout=15.0, verify=self.settings.verify_tls) as client:
                headers = {"Authorization": f"Bearer {token}"}
                resp = await client.get(url, params=params, headers=headers)
                if resp.status_code != 200:
                    logger.warning(f"Drive search returned {resp.status_code}: {resp.text[:200]}")
                    return []

                files = resp.json().get("files", [])
                results = []
                for f in files:
                    file_id = f.get("id")
                    name = f.get("name", "Untitled")
                    mime = f.get("mimeType", "")
                    link = f.get("webViewLink", f"https://drive.google.com/file/d/{file_id}/view")
                    desc = f.get("description") or f"Google Drive file ({mime})"
                    
                    # Fetch plain text snippet for Docs if available
                    snippet = desc
                    if "document" in mime:
                        export_url = f"{DRIVE_API_BASE}/files/{file_id}/export"
                        try:
                            exp_resp = await client.get(
                                export_url,
                                params={"mimeType": "text/plain"},
                                headers=headers,
                                timeout=10.0,
                            )
                            if exp_resp.status_code == 200:
                                snippet = exp_resp.text[:1200]
                        except Exception:
                            pass

                    results.append({
                        "title": f"Drive: {name}",
                        "content": sanitize_context_chunk(snippet),
                        "url": link,
                        "mimeType": mime,
                    })
                return results
        except Exception as e:
            logger.error(f"Google Drive search error: {e}")
            return []

    # ------------------------------------------------------------------
    # Gmail Search (IT Support Inboxes, alerts, threads)
    # ------------------------------------------------------------------
    async def search_gmail(self, query: str, top: int = 5) -> List[Dict[str, Any]]:
        """Search Gmail for support emails, incident logs, or resolved solutions."""
        token = await self.get_access_token()
        if not token:
            logger.debug("Gmail search skipped (no access token configured)")
            return []

        user_id = self.settings.GOOGLE_ADMIN_DELEGATE_EMAIL or "me"
        url = f"{GMAIL_API_BASE}/users/{urllib.parse.quote(user_id, safe='')}/messages"
        params = {
            "q": query,
            "maxResults": min(top, 10),
        }

        try:
            async with httpx.AsyncClient(timeout=15.0, verify=self.settings.verify_tls) as client:
                headers = {"Authorization": f"Bearer {token}"}
                resp = await client.get(url, params=params, headers=headers)
                if resp.status_code != 200:
                    logger.warning(f"Gmail search returned {resp.status_code}: {resp.text[:200]}")
                    return []

                messages = resp.json().get("messages", [])
                results = []
                for msg in messages[:top]:
                    msg_id = msg.get("id")
                    msg_url = f"{GMAIL_API_BASE}/users/{urllib.parse.quote(user_id, safe='')}/messages/{msg_id}"
                    m_resp = await client.get(msg_url, params={"format": "snippet"}, headers=headers)
                    if m_resp.status_code == 200:
                        m_data = m_resp.json()
                        snippet = m_data.get("snippet", "")
                        headers_list = m_data.get("payload", {}).get("headers", [])
                        subject = next((h["value"] for h in headers_list if h["name"].lower() == "subject"), "Email thread")
                        results.append({
                            "title": f"Gmail: {subject}",
                            "content": sanitize_context_chunk(snippet),
                            "url": f"https://mail.google.com/mail/u/0/#inbox/{msg_id}",
                        })
                return results
        except Exception as e:
            logger.error(f"Gmail search error: {e}")
            return []


_google_client: Optional[GoogleWorkspaceClient] = None


def get_google_client() -> GoogleWorkspaceClient:
    global _google_client
    if _google_client is None:
        _google_client = GoogleWorkspaceClient()
    return _google_client
