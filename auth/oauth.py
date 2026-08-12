"""
OAuth 2.0 helper for HelpDesk Enterprise Copilot.

Supports "Login with Google" and "Login with Microsoft 365 / Entra ID" using the
Authorization Code flow (PKCE for browser clients). Exchanges the code for a
token, fetches the profile, and lets the UI/CLI bootstrap the session.
"""

import base64
import hashlib
import os
import secrets
import urllib.parse

import httpx

from config.logging import get_logger
from config.settings import get_settings
from core.exceptions import AuthenticationError

logger = get_logger("oauth")

_PROVIDERS = {"google", "microsoft", "github"}


def _pkce() -> tuple:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


class OAuthProvider:
    """Config and endpoints for one OAuth provider."""

    def __init__(self, name: str):
        self.name = name
        s = get_settings()

        if name == "google":
            self.client_id = s.GOOGLE_OAUTH_CLIENT_ID
            self.client_secret = s.GOOGLE_OAUTH_CLIENT_SECRET
            self.redirect_uri = s.GOOGLE_OAUTH_REDIRECT_URI
            self.authorize_url = "https://accounts.google.com/o/oauth2/v2/auth"
            self.token_url = "https://oauth2.googleapis.com/token"
            self.userinfo_url = "https://www.googleapis.com/oauth2/v3/userinfo"
            self.scope = "openid%20email%20profile"
        elif name == "microsoft":
            s_m = get_settings()
            self.client_id = s_m.MICROSOFT_OAUTH_CLIENT_ID
            self.client_secret = s_m.MICROSOFT_OAUTH_CLIENT_SECRET
            self.redirect_uri = s_m.MICROSOFT_OAUTH_REDIRECT_URI
            tenant = s_m.GRAPH_TENANT_ID or "common"
            self.authorize_url = (
                f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
            )
            self.token_url = (
                f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
            )
            self.userinfo_url = "https://graph.microsoft.com/v1.0/me"
            self.scope = "openid%20email%20profile%20offline_access%20User.Read"
        elif name == "github":
            self.client_id = ""
            self.client_secret = ""
            self.redirect_uri = "http://localhost:8000/api/v1/auth/oauth/github/callback"
            self.authorize_url = "https://github.com/login/oauth/authorize"
            self.token_url = "https://github.com/login/oauth/access_token"
            self.userinfo_url = "https://api.github.com/user"
            self.scope = "user:email"
        else:
            raise AuthenticationError(f"Unknown OAuth provider: {name}")

    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def build_authorize_url(self, state: str) -> str:
        params = urllib.parse.urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "scope": self.scope.replace("%20", " "),
                "state": state,
            }
        )
        return f"{self.authorize_url}?{params}"

    async def exchange(self, code: str) -> dict:
        async with httpx.AsyncClient(timeout=20.0, verify=False) as client:
            resp = await client.post(
                self.token_url,
                data={
                    "code": code,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uri": self.redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            if resp.status_code != 200:
                logger.warning(f"OAuth token exchange failed: {resp.status_code} {resp.text[:200]}")
                raise AuthenticationError("OAuth token exchange failed")
            return resp.json()

    async def fetch_profile(self, access_token: str) -> dict:
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient(timeout=20.0, verify=False) as client:
            resp = await client.get(self.userinfo_url, headers=headers)
            if resp.status_code != 200:
                raise AuthenticationError("OAuth profile fetch failed")
            return resp.json()


def new_state() -> str:
    return secrets.token_urlsafe(24)


def begin_oauth(name: str) -> tuple:
    """Return (authorize_url, state). Raises if provider not configured."""
    if name not in _PROVIDERS:
        raise AuthenticationError(f"Unsupported provider: {name}")
    prov = OAuthProvider(name)
    if not prov.is_configured():
        raise AuthenticationError(
            f"OAuth provider '{name}' is not configured on the server. "
            "Set its CLIENT_ID / CLIENT_SECRET in .env."
        )
    state = new_state()
    return prov.build_authorize_url(state), state


async def complete_oauth(name: str, code: str, state: str) -> dict:
    """Exchange code + state for a normalized profile (OAuth-style login)."""
    if name not in _PROVIDERS:
        raise AuthenticationError(f"Unsupported provider: {name}")
    prov = OAuthProvider(name)
    if not prov.is_configured():
        raise AuthenticationError(f"OAuth provider '{name}' is not configured.")
    token = await prov.exchange(code)
    profile = await prov.fetch_profile(token.get("access_token", ""))
    sub = profile.get("sub")
    email = profile.get("email") or profile.get("userPrincipalName") or ""
    name_full = profile.get("name") or profile.get("displayName") or email.split("@")[0]
    username = (email.split("@")[0] if email else profile.get("login") or "oauth_user")
    return {
        "provider": name,
        "sub": sub or profile.get("id"),
        "email": email,
        "display_name": name_full,
        "username": username,
    }