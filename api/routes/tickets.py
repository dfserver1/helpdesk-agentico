"""
Ticket management endpoints with SLA integration.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas.ticket import TicketCreate, TicketEventResponse, TicketResponse, TicketUpdate
from auth.deps import get_current_user, require_roles
from core.exceptions import NotFoundError
from database.models import Ticket, TicketEvent, User, get_db_session
from sla.engine import get_sla_engine

router = APIRouter()


def _next_ticket_number() -> str:
    # 12 hex chars -> 48 bits of entropy; collisions are then astronomically
    # unlikely, and the create path retries on IntegrityError anyway.
    return "TK-" + uuid.uuid4().hex[:12].upper()


def _ticket_to_dict(ticket: Ticket) -> dict:
    return {
        "id": ticket.id,
        "ticket_number": ticket.ticket_number,
        "tenant_id": ticket.tenant_id,
        "user_id": ticket.user_id,
        "title": ticket.title,
        "description": ticket.description,
        "category": ticket.category,
        "priority": ticket.priority,
        "status": ticket.status,
        "assignee_id": ticket.assignee_id,
        "sla_due_at": ticket.sla_due_at,
        "sla_escalation_at": ticket.sla_escalation_at,
        "resolved_at": ticket.resolved_at,
        "created_at": ticket.created_at,
        "updated_at": ticket.updated_at,
    }


@router.get("", response_model=list[TicketResponse])
async def list_tickets(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    response: Response = None,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """List tickets for the caller's tenant (paginated).

    Regular users only see tickets they submitted; staff (agent, manager, admin, viewer)
    have tenant-wide visibility. The total number of matching tickets is returned in
    the ``X-Total-Count`` header.
    """
    tenant_id = user.organization_id or 1
    is_staff = user.is_superuser or user.role in ("agent", "manager", "admin", "viewer")

    base_filter = [Ticket.tenant_id == tenant_id]
    if not is_staff:
        base_filter.append(Ticket.user_id == user.id)

    total = (
        await session.scalar(
            select(func.count())
            .select_from(Ticket)
            .where(*base_filter)
        )
    ) or 0
    stmt = (
        select(Ticket)
        .where(*base_filter)
        .order_by(Ticket.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    rows = (await session.execute(stmt)).scalars().all()
    if response is not None:
        response.headers["X-Total-Count"] = str(total)
    return [_ticket_to_dict(t) for t in rows]


@router.post("", response_model=TicketResponse, status_code=201)
async def create_ticket(
    body: TicketCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Create a ticket and auto-compute SLA deadlines."""
    engine = get_sla_engine()
    sla = engine.compute_sla(ticket_id="pending", priority=body.priority)

    # Retry on the (astronomically rare) unique ticket_number collision.
    for _ in range(3):
        ticket = Ticket(
            ticket_number=_next_ticket_number(),
            tenant_id=user.organization_id or 1,
            user_id=user.id,
            title=body.title,
            description=body.description,
            category=body.category,
            priority=body.priority,
            status="OPEN",
            created_by=user.id,
            sla_due_at=sla.due_at,
            sla_escalation_at=sla.escalation_at,
        )
        session.add(ticket)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            continue

        session.add(
            TicketEvent(
                ticket_id=ticket.id,
                event_type="CREATED",
                actor_id=user.id,
                payload={"priority": body.priority, "title": body.title},
            )
        )
        await session.commit()
        await session.refresh(ticket)
        return _ticket_to_dict(ticket)

    raise RuntimeError("Could not allocate a unique ticket number")


@router.get("/{ticket_id}", response_model=TicketResponse)
async def get_ticket(
    ticket_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    tenant_id = user.organization_id or 1
    ticket = (
        (await session.execute(
            select(Ticket).where(Ticket.id == ticket_id, Ticket.tenant_id == tenant_id)
        ))
        .scalar_one_or_none()
    )
    if ticket is None:
        raise NotFoundError(f"Ticket {ticket_id} not found")

    is_staff = user.is_superuser or user.role in ("agent", "manager", "admin", "viewer")
    if not is_staff and ticket.user_id != user.id:
        raise NotFoundError(f"Ticket {ticket_id} not found")

    return _ticket_to_dict(ticket)


@router.patch("/{ticket_id}", response_model=TicketResponse)
async def patch_ticket(
    ticket_id: int,
    body: TicketUpdate,
    user: User = Depends(require_roles("agent", "manager", "admin")),
    session: AsyncSession = Depends(get_db_session),
):
    tenant_id = user.organization_id or 1
    ticket = (
        (await session.execute(
            select(Ticket).where(Ticket.id == ticket_id, Ticket.tenant_id == tenant_id)
        ))
        .scalar_one_or_none()
    )
    if ticket is None:
        raise NotFoundError(f"Ticket {ticket_id} not found")

    changed = body.model_dump(exclude_unset=True)
    for field, value in changed.items():
        setattr(ticket, field, value)

    if body.status is not None:
        if body.status == "RESOLVED" and ticket.resolved_at is None:
            ticket.resolved_at = datetime.now(timezone.utc)
        elif body.status != "RESOLVED":
            # Reopening must clear the stale resolution timestamp.
            ticket.resolved_at = None

    ticket.updated_at = datetime.now(timezone.utc)
    await session.flush()

    if changed:
        session.add(
            TicketEvent(
                ticket_id=ticket.id,
                event_type="STATUS_CHANGED" if "status" in changed else "UPDATED",
                actor_id=user.id,
                payload={
                    "fields": sorted(changed.keys()),
                    **({"status": ticket.status} if "status" in changed else {}),
                },
            )
        )

    await session.commit()
    await session.refresh(ticket)
    return _ticket_to_dict(ticket)


@router.get("/{ticket_id}/events", response_model=list[TicketEventResponse])
async def ticket_events(
    ticket_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    tenant_id = user.organization_id or 1
    ticket = (
        (await session.execute(
            select(Ticket).where(Ticket.id == ticket_id, Ticket.tenant_id == tenant_id)
        ))
        .scalar_one_or_none()
    )
    if ticket is None:
        raise NotFoundError(f"Ticket {ticket_id} not found")

    is_staff = user.is_superuser or user.role in ("agent", "manager", "admin", "viewer")
    if not is_staff and ticket.user_id != user.id:
        raise NotFoundError(f"Ticket {ticket_id} not found")

    events = (
        (await session.execute(
            select(TicketEvent)
            .where(TicketEvent.ticket_id == ticket_id)
            .order_by(TicketEvent.created_at.asc())
        ))
        .scalars()
        .all()
    )
    return events