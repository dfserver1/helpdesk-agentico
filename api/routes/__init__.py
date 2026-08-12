"""
API routes package for HelpDesk Enterprise Copilot v12.
"""

from fastapi import APIRouter

from api.routes.auth import router as auth_router
from api.routes.tickets import router as tickets_router
from api.routes.chat import router as chat_router
from api.routes.memory import router as memory_router
from api.routes.admin import router as admin_router
from api.routes.health import router as health_router
from api.routes.oauth import router as oauth_router
from api.routes.connectors import router as connectors_router

api_router = APIRouter()
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(oauth_router, prefix="/auth", tags=["auth"])
api_router.include_router(tickets_router, prefix="/tickets", tags=["tickets"])
api_router.include_router(chat_router, prefix="/chat", tags=["chat"])
api_router.include_router(memory_router, prefix="/memory", tags=["memory"])
api_router.include_router(connectors_router, prefix="/connectors", tags=["connectors"])
api_router.include_router(admin_router, prefix="/admin", tags=["admin"])

__all__ = ["api_router"]