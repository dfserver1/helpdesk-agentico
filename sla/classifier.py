"""
ITSM Priority Classifier for HelpDesk Enterprise Copilot.
Classifies tickets into P1-P4 based on impact and urgency, mapped to the
company's 11-SLA/PriorityMatrix.md:
    P1 Critico | P2 Alto | P3 Medio | P4 Bajo
"""

from typing import Dict, Optional, TypedDict

from config.settings import get_settings
from config.logging import get_logger

logger = get_logger("priority_classifier")


class PriorityClassification(TypedDict):
    priority: str           # P1-P4
    sla_response_time: str  # Human-readable SLA target
    category: str           # Incident category
    reasoning: str          # Why this priority was assigned


# SLA definitions (aligned with 11-SLA/PriorityMatrix.md)
SLA_DEFINITIONS = {
    "P1": {
        "label": "Critico",
        "impact": "Total service outage / critical business system down",
        "response": "Immediate (0-15 min)",
        "resolve_hours": 4,
        "escalation_minutes": 15,
    },
    "P2": {
        "label": "Alto",
        "impact": "Major feature failure / many users affected",
        "response": "Within 4 hours",
        "resolve_hours": 8,
        "escalation_minutes": 60,
    },
    "P3": {
        "label": "Medio",
        "impact": "Partial failure / few users affected",
        "response": "Within 24 hours",
        "resolve_hours": 48,
        "escalation_minutes": 240,
    },
    "P4": {
        "label": "Bajo",
        "impact": "Simple question / improvement request",
        "response": "Within 72 hours",
        "resolve_hours": 168,
        "escalation_minutes": 1440,
    },
}

PRIORITY_LEVELS = {"P1", "P2", "P3", "P4"}

CLASSIFIER_PROMPT = """You are an expert ITSM (IT Service Management) classifier.
Analyze the incident described below and assign a priority level using these rules:

P1 CRITICO - total service outage, critical business system down, security breach,
             data loss, production down, complete outage affecting many
P2 ALTO - major feature broken, many users affected, workaround limited/none
P3 MEDIO - partial feature failure, few users affected, workaround available
P4 BAJO - simple question, minor issue, improvement request, no interruption

Also classify the category. Use one of:
[Technical, Billing, Account, Network, Hardware, Software, Security, Printers,
 VPN_Remote, Email, Applications, Other]

Incident description:
{incident}

Respond EXACTLY in this format:
PRIORITY: [P1|P2|P3|P4]
CATEGORY: [category]
REASON: [1 sentence why]
"""


class LLMPriorityClassifier:
    """Priority classifier using an LLM with ITSM guidelines."""

    def __init__(self, llm=None, require_llm: bool = True):
        self.llm = llm
        self.settings = get_settings()
        self.require_llm = require_llm

    def _ensure_llm(self):
        if self.llm is None:
            from rag.llm import get_chat_llm
            self.llm = get_chat_llm(temperature=0)
        return self.llm

    def classify(self, text: str, metadata: Optional[Dict] = None) -> PriorityClassification:
        """Classify an incident/ticket description into priority and category."""
        if self.require_llm:
            try:
                return self._classify_with_llm(text)
            except Exception as e:
                logger.warning(f"LLM classification failed, falling back to heuristics: {e}")

        return self._classify_heuristic(text, metadata or {})

    def _classify_with_llm(self, text: str) -> PriorityClassification:
        llm = self._ensure_llm()
        response = llm.invoke(CLASSIFIER_PROMPT.format(incident=text)).content

        priority = "P3"
        category = "Other"
        reasoning = ""

        for line in response.splitlines():
            line = line.strip()
            upper = line.upper()
            if upper.startswith("PRIORITY:"):
                p = line.split(":", 1)[1].strip().upper()
                if p in PRIORITY_LEVELS:
                    priority = p
            elif upper.startswith("CATEGORY:"):
                category = line.split(":", 1)[1].strip()
            elif upper.startswith("REASON:"):
                reasoning = line.split(":", 1)[1].strip()

        return self._build_result(priority, category, reasoning)

    def _classify_heuristic(self, text: str, metadata: Dict) -> PriorityClassification:
        """Deterministic keyword-based classification (offline fallback)."""
        t = text.lower()
        priority = "P4"
        category = "Other"

        category_map = {
            "vpn": "VPN_Remote",
            "remote": "VPN_Remote",
            "email": "Email",
            "outlook": "Email",
            "mail": "Email",
            "printer": "Printers",
            "print": "Printers",
            "network": "Network",
            "internet": "Network",
            "wifi": "Network",
            "hardware": "Hardware",
            "monitor": "Hardware",
            "laptop": "Hardware",
            "security": "Security",
            "virus": "Security",
            "password": "Account",
            "login": "Account",
            "account": "Account",
            "billing": "Billing",
            "invoice": "Billing",
            "software": "Software",
            "application": "Software",
            "license": "Software",
        }
        for keyword, cat in category_map.items():
            if keyword in t:
                category = cat
                break

        p1_keywords = [
            "down", "outage", "critical", "entire office", "all users",
            "security breach", "data loss", "production down",
        ]
        p2_keywords = [
            "major", "widespread", "multiple users", "cannot work",
            "error", "unable to access", "failed", "broken",
        ]
        p3_keywords = [
            "some users", "workaround", "intermittent", "slow", "partially",
        ]

        if any(k in t for k in p1_keywords):
            priority = "P1"
        elif any(k in t for k in p2_keywords):
            priority = "P2"
        elif any(k in t for k in p3_keywords):
            priority = "P3"

        # Metadata boost based on reported affected users
        affected = metadata.get("affected_users")
        if affected:
            try:
                n = int(affected)
                if n >= 500 and priority in ("P3", "P2"):
                    priority = "P1"
                elif n >= 100 and priority == "P3":
                    priority = "P2"
            except (TypeError, ValueError):
                pass

        reasoning = "Heuristic classification based on keywords and reported impact."
        return self._build_result(priority, category, reasoning)

    def _build_result(self, priority: str, category: str, reasoning: str) -> PriorityClassification:
        sla = SLA_DEFINITIONS[priority]
        return {
            "priority": priority,
            "category": category,
            "sla_response_time": sla["response"],
            "reasoning": reasoning,
        }


# Convenience facade
_default_classifier = None


def classify_ticket(text: str, metadata: Optional[Dict] = None) -> PriorityClassification:
    """Convenience facade for priority classification."""
    global _default_classifier
    if _default_classifier is None:
        _default_classifier = LLMPriorityClassifier()
    return _default_classifier.classify(text, metadata)