"""
Common interface and result models for connectors.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ConnectorResult:
    """A single retrieved piece of content from an external source."""

    title: str
    content: str
    source: str = "external"          # e.g. sharepoint / teams / outlook / web
    url: Optional[str] = None
    score: float = 0.5
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "content": self.content,
            "source": self.source,
            "url": self.url,
            "score": self.score,
            "metadata": self.metadata,
        }


class BaseConnector:
    """Interface every connector must implement."""

    name: str = "base"
    label: str = "Base connector"

    def __init__(self, enabled: bool = True, max_results: int = 8):
        self.enabled = enabled
        self.max_results = max_results

    def is_configured(self) -> bool:
        """Return True if required credentials/configuration are present."""
        return True

    def is_enabled(self) -> bool:
        return self.enabled and self.is_configured()

    async def search(self, query: str, top_k: int = 5) -> List[ConnectorResult]:
        """Search this source for the query. Must be implemented by subclasses."""
        raise NotImplementedError

    def status(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "enabled": self.is_enabled(),
            "configured": self.is_configured(),
        }