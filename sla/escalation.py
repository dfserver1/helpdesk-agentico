"""
Escalation rules for HelpDesk Enterprise Copilot v12.
Defines when and to whom tickets escalate based on SLA breaches,
priority, and organizational tier structure (L1/L2/L3 support).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime, timezone

from config.settings import get_settings
from config.logging import get_logger

logger = get_logger("escalation")


@dataclass
class EscalationPolicy:
    """Policy per priority level."""
    priority: str
    first_level: str           # role/team to escalate to first
    second_level: str
    third_level: str
    hours_since_created: float  # hours of inactivity before auto-escalation


# Default tiered escalation policy (ITIL-aligned)
DEFAULT_ESCALATION_POLICY = {
    "P1": EscalationPolicy("P1", "L1_Support", "Shift_Lead", "IT_Manager", hours_since_created=0.5),
    "P2": EscalationPolicy("P2", "L1_Support", "L2_Support", "IT_Supervisor", hours_since_created=2),
    "P3": EscalationPolicy("P3", "L1_Support", "L2_Support", "L3_Support", hours_since_created=8),
    "P4": EscalationPolicy("P4", "L1_Support", "L2_Support", "Service_Owner", hours_since_created=48),
}


@dataclass
class EscalationResult:
    escalated: bool
    target: Optional[str]
    reason: str
    level: int            # 1, 2, 3
    policy: Optional[Dict] = None


class EscalationEngine:
    """Drives hierarchical escalation based on SLA state."""

    def __init__(self, settings=None, policy: Dict[str, EscalationPolicy] = None):
        self.settings = settings or get_settings()
        self.policy = policy or DEFAULT_ESCALATION_POLICY

    def evaluate(
        self,
        priority: str,
        sla_status: str,
        elapsed_hours: float,
        current_assignee: Optional[str] = None,
    ) -> EscalationResult:
        """
        Decide whether to escalate and to whom.

        Args:
            priority:        P1-P4.
            sla_status:      ON_TRACK / AT_RISK / BREACHED / ESCALATED
            elapsed_hours:   Hours since ticket creation / last update.
            current_assignee:Who currently owns the ticket.

        Returns:
            EscalationResult.
        """
        policy = self.policy.get(priority, self.policy["P3"])
        reasonable = f"elapsed {elapsed_hours:.1f}h against {policy.hours_since_created}h policy; SLA={sla_status}"

        # P1: escalate immediately if breached or at risk
        if priority == "P1" and sla_status in ("BREACHED", "AT_RISK"):
            return EscalationResult(
                escalated=True,
                target=policy.first_level,
                reason=reasonable,
                level=1,
            )

        # Past policy inactivity threshold => level 1 escalation
        if elapsed_hours >= policy.hours_since_created:
            return EscalationResult(
                escalated=True,
                target=policy.first_level,
                reason=f"SLA inactivity policy triggered: {reason}",
                level=1,
            )

        # Breached SLA but below inactivity threshold => risk
        if sla_status == "BREACHED":
            return EscalationResult(
                escalated=False,
                target=current_assignee or "Unassigned",
                reason=f"SLA breached but policy window not reached: {reasonable}",
                level=0,
            )

        return EscalationResult(
            escalated=False,
            target=current_assignee or "Unassigned",
            reason=f"Within SLA: {reasonable}",
            level=0,
        )


_escalation_engine = None


def get_escalation_engine() -> EscalationEngine:
    global _escalation_engine
    if _escalation_engine is None:
        _escalation_engine = EscalationEngine()
    return _escalation_engine