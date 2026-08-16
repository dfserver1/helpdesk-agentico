"""
Authentication endpoints: login, register, refresh, me.
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.rate_limit import limiter
from auth.deps import get_current_user
from auth.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from config.settings import get_settings
from core.exceptions import AuthenticationError, ValidationError
from database.models import User, get_db_session
from api.schemas.auth import LoginRequest, RegisterRequest, RefreshRequest, TokenResponse, UserResponse

router = APIRouter()

# Precomputed bcrypt hash of a fixed dummy password, used to equalize the
# response time when the email address does not exist (prevents timing-based
# account enumeration).
DUMMY_PASSWORD_HASH = "$2b$12$jxpNLyjbMZApMecbxTQKPO42QJX6qkZ/Kc.s5GxNtcpJmBMNUuwJS"


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(
    request: Request,
    body: LoginRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Authenticate with email + password and issue token pair."""
    user = (
        (await session.execute(select(User).where(User.email == body.email.lower())))
        .scalar_one_or_none()
    )
    # Constant-time-ish guard: always run bcrypt so response timing does not
    # reveal whether the email exists (timing-based account enumeration).
    if user is None:
        verify_password(body.password, DUMMY_PASSWORD_HASH)
        raise AuthenticationError("Invalid email or password")
    if not verify_password(body.password, user.hashed_password):
        raise AuthenticationError("Invalid email or password")
    if not user.is_active:
        raise ValidationError("User account is disabled")

    settings = get_settings()
    return TokenResponse(
        access_token=create_access_token(str(user.id), user.role),
        refresh_token=create_refresh_token(str(user.id), user.role),
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/register", response_model=UserResponse)
@limiter.limit("10/minute")
async def register(
    request: Request,
    body: RegisterRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Create a new standard user account."""
    existing = (
        (await session.execute(select(User).where(User.email == body.email.lower())))
        .scalar_one_or_none()
    )
    if existing is not None:
        raise ValidationError("Email already registered")

    user = User(
        email=body.email.lower(),
        username=body.username.strip(),
        full_name=body.full_name.strip(),
        hashed_password=hash_password(body.password),
        role="user",
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("30/minute")
async def refresh(
    request: Request,
    body: RefreshRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Exchange a refresh token for a new token pair."""
    payload = decode_token(body.refresh_token)
    if payload.get("type") != "refresh":
        raise AuthenticationError("Token is not a refresh token")

    raw_sub = payload.get("sub")
    if raw_sub is None:
        raise AuthenticationError("Token subject missing")
    try:
        user_id = int(raw_sub)
    except (ValueError, TypeError):
        raise AuthenticationError("Invalid token subject")

    user = (
        (await session.execute(select(User).where(User.id == user_id)))
        .scalar_one_or_none()
    )
    if user is None or not user.is_active:
        raise AuthenticationError("User not found or inactive")

    settings = get_settings()
    return TokenResponse(
        access_token=create_access_token(str(user.id), user.role),
        refresh_token=create_refresh_token(str(user.id), user.role),
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    """Return the current authenticated user."""
    return user