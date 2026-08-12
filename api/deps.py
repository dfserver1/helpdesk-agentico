"""
Shared API dependencies.
"""

from typing import Optional

import fastapi
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import get_current_user
from database.models import User, get_db_session


async def get_current_tenant_id(user: User = Depends(get_current_user)) -> int:
    """Resolve the caller's tenant id (falls back to 1)."""
    return user.organization_id or 1