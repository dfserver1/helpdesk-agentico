"""
Tests for the OAuth helpers: PKCE code-challenge generation, the authorize
URL wiring, the code_verifier sent on exchange, and the TLS policy (M5/B5).
"""

import asyncio
import base64
import hashlib

import pytest


def _challenge_for(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def test_pkce_produces_matching_challenge():
    """The S256 challenge must be recomputable from the returned verifier."""
    from auth.oauth import _pkce

    verifier, challenge = _pkce()
    assert verifier and challenge
    assert challenge == _challenge_for(verifier)
    # Unique per call.
    verifier2, challenge2 = _pkce()
    assert verifier != verifier2
    assert challenge != challenge2


class _FakeOAuthProvider:
    client_id = "cid"
    client_secret = "csec"
    redirect_uri = "http://localhost:8000/api/v1/auth/oauth/callback"
    authorize_url = "https://accounts.google.com/o/oauth2/v2/auth"
    scope = "openid%20email%20profile"

    def __init__(self, name):
        self.name = name

    def is_configured(self):
        return True

    def build_authorize_url(self, state, code_challenge=None):
        import urllib.parse

        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": self.scope.replace("%20", " "),
            "state": state,
        }
        if code_challenge:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"
        return f"{self.authorize_url}?{urllib.parse.urlencode(params)}"


def test_begin_oauth_includes_pkce_for_google(monkeypatch):
    """Google/Microsoft authorize URLs must carry code_challenge (M5)."""
    from auth import oauth as oauth_helpers

    monkeypatch.setattr(oauth_helpers, "OAuthProvider", _FakeOAuthProvider)

    url, state, verifier = oauth_helpers.begin_oauth("google")
    assert "code_challenge=" in url
    assert "code_challenge_method=S256" in url
    assert verifier is not None
    assert "state=" in url

    # GitHub does not support PKCE: no challenge, no verifier.
    url_g, _, verifier_g = oauth_helpers.begin_oauth("github")
    assert "code_challenge=" not in url_g
    assert verifier_g is None


class _FakeAsyncClient:
    """Minimal httpx.AsyncClient stand-in that records the request."""

    last_post: dict = None

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **kwargs):
        _FakeAsyncClient.last_post = kwargs.get("data") or {}
        from httpx import Response

        return Response(200, json={"access_token": "tok"})


def test_exchange_sends_code_verifier(monkeypatch):
    """The token exchange must include code_verifier when one is supplied."""
    import httpx

    from auth.oauth import OAuthProvider

    provider = OAuthProvider.__new__(OAuthProvider)
    provider.client_id = "cid"
    provider.client_secret = "csec"
    provider.redirect_uri = "http://localhost:8000/cb"
    provider.token_url = "https://oauth2.googleapis.com/token"

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    asyncio.run(provider.exchange("CODE", code_verifier="THE_VERIFIER"))
    assert _FakeAsyncClient.last_post["code_verifier"] == "THE_VERIFIER"
    assert _FakeAsyncClient.last_post["grant_type"] == "authorization_code"

    asyncio.run(provider.exchange("CODE2"))
    assert "code_verifier" not in _FakeAsyncClient.last_post


def test_verify_tls_defaults_true():
    """TLS verification must be on unless explicitly disabled (B5)."""
    from config.settings import get_settings

    assert get_settings().verify_tls is True