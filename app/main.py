"""
FastAPI application entrypoint for HelpDesk Enterprise Copilot.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api.routes import api_router
from app.rate_limit import limiter
from config.logging import get_logger
from config.settings import get_settings
from core.exceptions import HelpDeskException
from database.models import close_db, init_db

logger = get_logger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    try:
        await init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.warning(f"DB init skipped: {e}")

    yield
    await close_db()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="Enterprise HelpDesk AI Copilot with self-training memory.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.exception_handler(HelpDeskException)
    async def helpdesk_error_handler(request: Request, exc: HelpDeskException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.code,
                "message": exc.message,
                "details": exc.details,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        logger.exception(f"Unhandled error on {request.method} {request.url.path}: {exc}")
        return JSONResponse(
            status_code=500,
            content={"error": "INTERNAL_ERROR", "message": "An unexpected error occurred"},
        )

    app.include_router(api_router, prefix="/api/v1")

    @app.get("/")
    async def root():
        return {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "docs": "/docs",
            "openapi": "/openapi.json",
        }

    return app


app = create_app()