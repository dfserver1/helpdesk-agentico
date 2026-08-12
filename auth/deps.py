"""
FastAPI security dependencies: current user resolution and RBAC guards.
"""

from typing import Callable, List, Union

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.security import decode_token
from config.settings import get_settings
from core.exceptions import AuthenticationError, AuthorizationError
from database.models import User, get_db_session

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Union[HTTPAuthorizationCredentials, None] = Depends(_bearer),
    session: AsyncSession = Depends(get_db_session),
) -> User:
    """Resolve the authenticated user from the Bearer token."""
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Missing bearer token")

    payload = decode_token(credentials.credentials)
    if payload.get("type") != "access":
        raise AuthenticationError("Token is not an access token")

    user_id = payload.get("sub")
    if user_id is None:
        raise AuthenticationError("Token subject missing")

    user = (
        (await session.execute(select(User).where(User.id == int(user_id))))
        .scalar_one_or_none()
    )
    if user is None or not user.is_active:
        raise AuthenticationError("User not found or inactive")
    return user


def require_roles(*roles: str):
    """Factory returning a dependency that enforces role membership."""

    async def _guard(user: User = Depends(get_current_user)) -> User:
        allowed = set(roles)
        if "admin" in allowed and user.is_superuser:
            return user
        if user.role not in allowed and not user.is_superuser:
            raise AuthorizationError(f"Requires role(s): {', '.join(roles)}")
        return user

    return _guard


async def get_current_active_user(user: User = Depends(get_current_user)) -> User:
    """Require an active authenticated user."""
    if not user.is_active:
        raise AuthorizationError("User account is inactive")
    return user


async def get_current_admin(user: User = Depends(get_current_user)) -> User:
    """Require superuser/admin access."""
    if not user.is_superuser and user.role != "admin":
        raise AuthorizationError("Admin privileges required")
    return user