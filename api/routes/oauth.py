"""
OAuth login routes (Google / Microsoft / GitHub).

  GET  /oauth/{provider}/login      -> { authorize_url }
  GET  /oauth/{provider}/callback   -> exchanges code, issues token pair,
                                       and (for browser flows) redirects to the
                                       UI with ?token=<access_token>
"""

import secrets

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas.auth import TokenResponse, UserResponse
from app.rate_limit import limiter
from auth import oauth as oauth_helpers
from auth.security import create_access_token, create_refresh_token
from config.settings import get_settings
from core.exceptions import AuthenticationError
from database.models import User, get_db_session

router = APIRouter(prefix="/oauth", tags=["oauth"])

VALID = {"google", "microsoft", "github"}


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
    authorize_url, state = oauth_helpers.begin_oauth(provider)

    state_store = {
        "state": state,
        "redirect_to": redirect_to or "",
    }
    # Persist state in-memory (single instance). Production multi-worker
    # deployments should move this to Redis - see config/settings.py.
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

    state_store = _state_cache.pop(state, None)

    identity = await oauth_helpers.complete_oauth(provider, code, state)

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

    redirect_to = (state_store or {}).get("redirect_to") or _default_ui_url(access)
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

    # Link provider to existing account
    user.oauth_provider = provider
    if sub:
        user.oauth_subject = sub
    await session.commit()
    await session.refresh(user)
    return user


def _default_ui_url(access: str) -> str:
    s = get_settings()
    # Streamlit frontend default; real deployments should override redirect_to.
    return f"http://localhost:8501?token={access}"


_state_cache: dict = {}