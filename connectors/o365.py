"""
Concrete O365 connectors (SharePoint, Teams, Outlook) built on Microsoft Graph.
"""

from typing import List

from config.settings import get_settings
from connectors.base import BaseConnector, ConnectorResult


class SharePointConnector(BaseConnector):
    name = "sharepoint"
    label = "SharePoint"

    def __init__(self):
        s = get_settings()
        super().__init__(enabled=s.SHAREPOINT_ENABLED, max_results=s.CONNECTOR_MAX_RESULTS)

    def is_configured(self) -> bool:
        from connectors.graph_client import get_graph_client

        return get_graph_client().is_configured()

    async def search(self, query: str, top_k: int = 5) -> List[ConnectorResult]:
        from connectors.graph_client import get_graph_client

        items = await get_graph_client().search_sharepoint(query, top=min(top_k, self.max_results))
        return [
            ConnectorResult(
                title=i["title"],
                content=i["content"],
                source="sharepoint",
                url=i.get("url"),
            )
            for i in items
        ]


class TeamsConnector(BaseConnector):
    name = "teams"
    label = "Teams"

    def __init__(self):
        s = get_settings()
        super().__init__(enabled=s.TEAMS_ENABLED, max_results=s.CONNECTOR_MAX_RESULTS)

    def is_configured(self) -> bool:
        from connectors.graph_client import get_graph_client

        return get_graph_client().is_configured()

    async def search(self, query: str, top_k: int = 5) -> List[ConnectorResult]:
        from connectors.graph_client import get_graph_client

        items = await get_graph_client().search_teams(query, top=min(top_k, self.max_results))
        return [
            ConnectorResult(
                title=i["title"],
                content=i["content"],
                source="teams",
                url=i.get("url"),
            )
            for i in items
        ]


class OutlookConnector(BaseConnector):
    name = "outlook"
    label = "Outlook"

    def __init__(self):
        s = get_settings()
        super().__init__(enabled=s.OUTLOOK_ENABLED, max_results=s.CONNECTOR_MAX_RESULTS)

    def is_configured(self) -> bool:
        from connectors.graph_client import get_graph_client

        return get_graph_client().is_configured()

    async def search(self, query: str, top_k: int = 5) -> List[ConnectorResult]:
        from connectors.graph_client import get_graph_client

        items = await get_graph_client().search_outlook(query, top=min(top_k, self.max_results))
        return [
            ConnectorResult(
                title=i["title"],
                content=i["content"],
                source="outlook",
                url=i.get("url"),
            )
            for i in items
        ]