"""
Admin endpoints: tenant-wide visibility and user management.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import and_, false, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas.auth import UserResponse
from auth.deps import get_current_admin
from core.exceptions import ValidationError
from database.models import User, Ticket, get_db_session

router = APIRouter()


@router.get("/stats")
async def platform_stats(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Aggregate platform statistics."""
    tenant = admin.organization_id or 1

    ticket_total = (
        await db.execute(
            select(func.count(Ticket.id)).where(Ticket.tenant_id == tenant)
        )
    ).scalar() or 0
    ticket_open = (
        await db.execute(
            select(func.count(Ticket.id)).where(
                Ticket.tenant_id == tenant,
                Ticket.status.in_(["OPEN", "IN_PROGRESS"]),
            )
        )
    ).scalar() or 0
    user_count = (
        await db.execute(
            select(func.count(User.id)).where(
                or_(
                    User.organization_id == tenant,
                    and_(true() if tenant == 1 else false(), User.organization_id.is_(None)),
                )
            )
        )
    ).scalar() or 0

    return {
        "tenant_id": tenant,
        "tickets_total": ticket_total,
        "tickets_open": ticket_open,
        "users": user_count,
    }


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """List users in the current tenant (admin-only)."""
    tenant = admin.organization_id or 1
    users = (
        await db.execute(
            select(User)
            .where(
                or_(
                    User.organization_id == tenant,
                    and_(true() if tenant == 1 else false(), User.organization_id.is_(None)),
                )
            )
            .order_by(User.created_at.desc())
        )
    ).scalars().all()
    return users


@router.patch("/users/{user_id}/role")
async def set_user_role(
    user_id: int,
    role: str,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Change a user's role (admin-only)."""
    allowed = {"user", "agent", "manager", "viewer", "admin"}
    if role not in allowed:
        raise ValidationError(f"Invalid role '{role}'")

    user = (
        (await db.execute(
            select(User).where(User.id == user_id)
        )).scalar_one_or_none()
    )
    if user is None:
        raise ValidationError(f"User {user_id} not found")

    tenant = admin.organization_id or 1
    if (user.organization_id or 1) != tenant and not admin.is_superuser:
        raise ValidationError("Cannot modify a user from another tenant")
    if user.id == admin.id:
        raise ValidationError("An admin cannot change their own role")
    if user.is_superuser and not admin.is_superuser:
        raise ValidationError("Cannot modify a superuser account")

    user.role = role
    await db.commit()
    return {"id": user.id, "role": user.role}