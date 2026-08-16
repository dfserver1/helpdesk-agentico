"""
Concrete Google Workspace connectors (Google Drive, Gmail, Docs) for HelpDesk Copilot.
"""

from typing import List

from config.settings import get_settings
from connectors.base import BaseConnector, ConnectorResult


class GoogleDriveConnector(BaseConnector):
    name = "google_drive"
    label = "Google Drive"

    def __init__(self):
        s = get_settings()
        super().__init__(enabled=s.GOOGLE_DRIVE_ENABLED, max_results=s.CONNECTOR_MAX_RESULTS)

    def is_configured(self) -> bool:
        from connectors.google_client import get_google_client

        return get_google_client().is_configured()

    async def search(self, query: str, top_k: int = 5) -> List[ConnectorResult]:
        from connectors.google_client import get_google_client

        items = await get_google_client().search_drive(query, top=min(top_k, self.max_results))
        return [
            ConnectorResult(
                title=i["title"],
                content=i["content"],
                source="google_drive",
                url=i.get("url"),
                score=0.75,
                metadata={"mimeType": i.get("mimeType", "")},
            )
            for i in items
        ]


class GmailConnector(BaseConnector):
    name = "gmail"
    label = "Gmail"

    def __init__(self):
        s = get_settings()
        super().__init__(enabled=s.GOOGLE_GMAIL_ENABLED, max_results=s.CONNECTOR_MAX_RESULTS)

    def is_configured(self) -> bool:
        from connectors.google_client import get_google_client

        return get_google_client().is_configured()

    async def search(self, query: str, top_k: int = 5) -> List[ConnectorResult]:
        from connectors.google_client import get_google_client

        items = await get_google_client().search_gmail(query, top=min(top_k, self.max_results))
        return [
            ConnectorResult(
                title=i["title"],
                content=i["content"],
                source="gmail",
                url=i.get("url"),
                score=0.70,
            )
            for i in items
        ]
