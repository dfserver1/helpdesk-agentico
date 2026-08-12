"""
Connectors package for HelpDesk Enterprise Copilot.

Extends the agent's retrieval with external sources so it can answer from
O365 (SharePoint / Teams / Outlook via Microsoft Graph) and — when there is no
internal documentation — from the public web using trustworthy sources.
"""

from connectors.base import BaseConnector, ConnectorResult
from connectors.registry import ConnectorRegistry, get_registry, search_all_sources

__all__ = [
    "BaseConnector",
    "ConnectorResult",
    "ConnectorRegistry",
    "get_registry",
    "search_all_sources",
]