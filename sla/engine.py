"""
SLA Engine for HelpDesk Enterprise Copilot.
Calculates SLA due times (business-hours aware), tracks breach state,
and drives automatic escalation based on the PriorityMatrix:
    P1 Critico | P2 Alto | P3 Medio | P4 Bajo
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config.settings import get_settings
from config.logging import get_logger
from sla.classifier import SLA_DEFINITIONS

logger = get_logger("sla_engine")


@dataclass
class SLAStatus:
    ticket_id: str
    priority: str
    created_at: datetime
    due_at: Optional[datetime]             # SLA deadline
    escalation_at: Optional[datetime]      # when to escalate
    status: str = "ON_TRACK"               # ON_TRACK | AT_RISK | BREACHED | ESCALATED
    remaining_seconds: float = 0.0
    threshold_seconds: float = 0.0
    response_seconds: float = 0.0          # first-response SLA target
    breaches: List[dict] = field(default_factory=list)


class SLAEngine:
    """Calculate and track SLA compliance."""

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        try:
            self.tz = ZoneInfo(self.settings.SLA_TIMEZONE)
        except (ZoneInfoNotFoundError, ValueError):
            self.tz = timezone.utc
        self.business_hours = (
            self.settings.SLA_BUSINESS_HOURS_START,
            self.settings.SLA_BUSINESS_HOURS_END,
        )

    # --- Time helpers ------------------------------------------------------
    def _now(self) -> datetime:
        return datetime.now(self.tz)

    def _is_business_hour(self, dt: datetime) -> bool:
        start, end = self.business_hours
        return start <= dt.hour < end

    def _next_business_start(self, dt: datetime) -> datetime:
        """Next business-day start at 09:00 local."""
        candidate = dt + timedelta(days=1)
        while candidate.weekday() >= 5:  # skip Sat/Sun
            candidate += timedelta(days=1)
        return candidate.replace(
            hour=self.business_hours[0], minute=0, second=0, microsecond=0
        )

    # --- SLA target helpers ------------------------------------------------
    def _definition(self, priority: str) -> dict:
        return SLA_DEFINITIONS.get(priority, SLA_DEFINITIONS["P3"])

    def _resolve_hours(self, priority: str) -> float:
        """Resolution SLA hours for a priority, from settings when set."""
        key = f"SLA_P{priority[-1]}_RESOLVE_HOURS"
        value = getattr(self.settings, key, None)
        if value:
            return float(value)
        return float(self._definition(priority)["resolve_hours"])

    def _escalation_minutes(self, priority: str) -> float:
        """Escalation delay (calendar minutes) for a priority, from settings."""
        key = f"SLA_P{priority[-1]}_ESCALATION_MINUTES"
        value = getattr(self.settings, key, None)
        if value:
            return float(value)
        return float(self._definition(priority).get("escalation_minutes", 60))

    def response_target_seconds(self, priority: str) -> float:
        """First-response SLA target in seconds, from settings."""
        key = f"SLA_P{priority[-1]}_RESPONSE_"
        if priority == "P1":
            value = getattr(self.settings, f"{key}MINUTES", None)
            seconds = float(value or 0) * 60
        else:
            value = getattr(self.settings, f"{key}HOURS", None)
            seconds = float(value or 0) * 3600
        return seconds

    def sla_target_seconds(self, priority: str) -> float:
        """Total response SLA seconds for a priority level."""
        return self._resolve_hours(priority) * 3600

    def sla_threshold_seconds(self, priority: str) -> float:
        """Resolve-threshold used for the AT_RISK window."""
        return self.sla_target_seconds(priority)

    # --- Business-hours-aware deadline math ---------------------------------
    def _add_business_hours(self, start: datetime, hours: float) -> datetime:
        """Add N business hours, skipping nights, weekends."""
        remaining = hours * 3600.0
        current = start

        while remaining > 0:
            if not self._is_business_hour(current):
                current = self._next_business_start(current)
                continue

            end_of_day = current.replace(
                hour=self.business_hours[1], minute=0, second=0, microsecond=0
            )
            available = (end_of_day - current).total_seconds()
            if available <= 0:
                current = self._next_business_start(current)
                continue

            if remaining <= available:
                return current + timedelta(seconds=remaining)

            remaining -= available
            current = self._next_business_start(current)

        return start

    def _add_business_minutes(self, start: datetime, minutes: float) -> datetime:
        return self._add_business_hours(start, minutes / 60)

    # --- Core SLA computation ------------------------------------------------
    def compute_sla(self, ticket_id: str = "pending", priority: str = "P3", created_at: datetime = None) -> SLAStatus:
        """
        Compute SLA due and escalation deadlines for a ticket.
        Business-hours-aware scheduling.
        """
        created_at = created_at or self._now()
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=self.tz)

        resolve_hours = self._resolve_hours(priority)
        escalation_minutes = self._escalation_minutes(priority)

        due = self._add_business_hours(created_at, resolve_hours)
        escalation = self._add_business_minutes(created_at, escalation_minutes)

        return SLAStatus(
            ticket_id=ticket_id,
            priority=priority,
            created_at=created_at,
            due_at=due,
            escalation_at=escalation,
            threshold_seconds=self.sla_threshold_seconds(priority),
            response_seconds=self.response_target_seconds(priority),
        )

    # --- Status evaluation -----------------------------------------------------
    def evaluate(self, sla: SLAStatus, now: datetime = None) -> str:
        """
        Determine current SLA status:
          ON_TRACK  - comfortably inside SLA
          AT_RISK   - within 20% of the deadline
          BREACHED  - past deadline
        """
        now = now or self._now()
        if sla.due_at is None:
            sla.status = "ON_TRACK"
            return sla.status

        remaining = (sla.due_at - now).total_seconds()
        total = sla.threshold_seconds or self.sla_threshold_seconds(sla.priority)
        risk_window = total * 0.2

        if remaining <= 0:
            sla.status = "BREACHED"
        elif remaining <= risk_window:
            sla.status = "AT_RISK"
        else:
            sla.status = "ON_TRACK"

        sla.remaining_seconds = max(0.0, remaining)
        return sla.status

    def is_escalation_due(self, sla: SLAStatus, now: datetime = None) -> bool:
        """True if the escalation_at deadline has passed."""
        now = now or self._now()
        if sla.escalation_at is None:
            return False
        if now >= sla.escalation_at:
            sla.status = "ESCALATED"
            return True
        return False

    # --- Snapshots ------------------------------------------------------------
    def sla_summary(self, sla: SLAStatus) -> dict:
        """Return a JSON-friendly SLA status snapshot."""
        remaining = 0.0
        if sla.due_at:
            remaining = max(0.0, (sla.due_at - self._now()).total_seconds())
        return {
            "ticket_id": sla.ticket_id,
            "priority": sla.priority,
            "status": sla.status,
            "created_at": sla.created_at.isoformat(),
            "due_at": sla.due_at.isoformat() if sla.due_at else None,
            "escalation_at": sla.escalation_at.isoformat() if sla.escalation_at else None,
            "remaining_seconds": round(remaining, 2),
            "threshold_seconds": sla.threshold_seconds,
            "response_seconds": sla.response_seconds,
            "breaches": sla.breaches,
        }


_engine = None


def get_sla_engine() -> SLAEngine:
    global _engine
    if _engine is None:
        _engine = SLAEngine()
    return _engine