"""
Rate limiter for HelpDesk Enterprise Copilot.

The limiter is defined here (instead of in app.main) so API routes can import
it without creating an import cycle (routes -> main -> routes).
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from config.settings import get_settings

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[f"{get_settings().RATE_LIMIT_PER_MINUTE}/minute"],
    storage_uri="memory://",
)