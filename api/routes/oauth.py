"""
OAuth login routes (Google / Microsoft / GitHub).

  GET  /oauth/{provider}/login      -> { authorize_url }
  GET  /oauth/{provider}/callback   -> exchanges code, issues token pair,
                                       and (for browser flows) redirects to the
                                       UI with ?token=<access_token>
"""

import secrets
import time
import urllib.parse
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas.auth import TokenResponse, UserResponse
from app.rate_limit import limiter
from auth import oauth as oauth_helpers
from auth.security import create_access_token, create_refresh_token
from config.logging import get_logger
from config.settings import get_settings
from core.exceptions import AuthenticationError
from database.models import User, get_db_session

logger = get_logger("oauth_routes")

router = APIRouter(prefix="/oauth", tags=["oauth"])

VALID = {"google", "microsoft", "github"}
_STATE_TTL_SECONDS = 600  # 10 minutes TTL for OAuth authorization states
_state_cache: dict = {}


def _clean_expired_states() -> None:
    """Prune expired OAuth states to prevent memory exhaustion."""
    now = time.time()
    expired = [
        k for k, v in _state_cache.items()
        if now - v.get("created_at", 0) > _STATE_TTL_SECONDS
    ]
    for k in expired:
        _state_cache.pop(k, None)


def _is_safe_redirect_url(url: str, allowed_origins: list[str]) -> bool:
    """Validate that a redirect URL points to a trusted origin or relative path."""
    if not url:
        return False
    parsed = urllib.parse.urlparse(url)
    # Reject protocol-relative or non-http(s) schemes
    if url.startswith("//") or url.startswith("/\\"):
        return False
    # Allow safe relative paths
    if not parsed.scheme and not parsed.netloc:
        return url.startswith("/")
    # Validate absolute URL against configured origins
    if parsed.scheme in ("http", "https"):
        origin = f"{parsed.scheme}://{parsed.netloc}".lower()
        normalized_allowed = {o.rstrip("/").lower() for o in allowed_origins}
        return origin in normalized_allowed
    return False


@router.get("/{provider}/login")
@limiter.limit("30/minute")
async def oauth_login(
    request: Request,
    provider: str,
    redirect_to: str = Query(default="", description="Optional UI URL to return to"),
):
    """Start the OAuth authorization flow. Returns the authorize URL."""
    if provider not in VALID:
        raise AuthenticationError(f"Unsupported OAuth provider: {provider}")
    authorize_url, state, verifier = oauth_helpers.begin_oauth(provider)

    settings = get_settings()
    # Validate redirect_to to prevent open redirect vulnerabilities
    safe_redirect = (
        redirect_to
        if _is_safe_redirect_url(redirect_to, settings.CORS_ORIGINS)
        else ""
    )

    _clean_expired_states()
    state_store = {
        "state": state,
        "verifier": verifier,
        "redirect_to": safe_redirect,
        "created_at": time.time(),
    }
    _state_cache[state] = state_store

    return JSONResponse(
        {"authorize_url": authorize_url, "state": state, "provider": provider},
        status_code=200,
    )


@router.get("/{provider}/callback")
async def oauth_callback(
    provider: str,
    code: str = Query(...),
    state: str = Query(...),
    session: AsyncSession = Depends(get_db_session),
):
    """Exchange the code for identity, then return tokens (JSON or redirect)."""
    if provider not in VALID:
        raise AuthenticationError(f"Unsupported OAuth provider: {provider}")

    _clean_expired_states()
    state_store = _state_cache.pop(state, None)
    if state_store is None:
        # Unknown/replayed/expired state: refuse the exchange (CSRF protection).
        raise AuthenticationError("OAuth state mismatch or expired")

    # Check TTL explicitly
    if time.time() - state_store.get("created_at", 0) > _STATE_TTL_SECONDS:
        raise AuthenticationError("OAuth state has expired")

    identity = await oauth_helpers.complete_oauth(
        provider, code, state, code_verifier=state_store.get("verifier")
    )

    user = await _get_or_create_user(session, identity)

    settings = get_settings()
    access = create_access_token(str(user.id), user.role)
    refresh = create_refresh_token(str(user.id), user.role)

    payload = {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "user": UserResponse.model_validate(user).model_dump(),
    }

    raw_redirect = (state_store or {}).get("redirect_to")
    redirect_to = (
        raw_redirect
        if _is_safe_redirect_url(raw_redirect, settings.CORS_ORIGINS)
        else _default_ui_url(access)
    )

    if redirect_to:
        sep = "&" if "?" in redirect_to else "?"
        return RedirectResponse(url=f"{redirect_to}{sep}token={access}&refresh={refresh}")

    return JSONResponse(payload, status_code=200)


async def _get_or_create_user(session: AsyncSession, identity: dict) -> User:
    """Find or create a local user for the given OAuth identity (by email)."""
    email = identity.get("email", "").lower()
    sub = identity.get("sub") or ""
    provider = identity.get("provider", "")

    if not email:
        raise AuthenticationError("OAuth profile has no email address")

    # 1) Match by unique OAuth subject
    if sub:
        user = (
            (await session.execute(
                select(User).where(User.oauth_subject == sub, User.oauth_provider == provider)
            ))
            .scalar_one_or_none()
        )
        if user is not None:
            if not user.is_active:
                raise AuthenticationError("User account is disabled")
            return user

    # 2) Match by email
    user = (
        (await session.execute(select(User).where(User.email == email)))
        .scalar_one_or_none()
    )

    if user is None:
        from auth.security import hash_password

        user = User(
            email=email,
            username=identity.get("username") or email.split("@")[0],
            full_name=identity.get("display_name") or "OAuth User",
            hashed_password=hash_password(secrets.token_urlsafe(24)),
            role="user",
            oauth_provider=provider,
            oauth_subject=sub,
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user

    if not user.is_active:
        raise AuthenticationError("User account is disabled")

    # Link provider to existing account
    user.oauth_provider = provider
    if sub:
        user.oauth_subject = sub
    await session.commit()
    await session.refresh(user)
    return user


def _default_ui_url(access: str = "") -> str:
    # Streamlit frontend default; real deployments should override redirect_to.
    return "http://localhost:8501"