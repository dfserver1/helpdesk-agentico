"""
SLA package for HelpDesk Enterprise Copilot v12.
Priority classification (P1-P4), SLA computation, and escalation rules.
"""

from sla.classifier import (
    LLMPriorityClassifier,
    PriorityClassification,
    SLA_DEFINITIONS,
    classify_ticket,
)
from sla.engine import SLAEngine, SLAStatus, get_sla_engine
from sla.escalation import (
    EscalationPolicy,
    EscalationResult,
    EscalationEngine,
    get_escalation_engine,
)

__all__ = [
    "LLMPriorityClassifier",
    "PriorityClassification",
    "SLA_DEFINITIONS",
    "classify_ticket",
    "SLAEngine",
    "SLAStatus",
    "get_sla_engine",
    "EscalationPolicy",
    "EscalationResult",
    "EscalationEngine",
    "get_escalation_engine",
]