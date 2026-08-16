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
from app.concurrency import shutdown_executor
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
        # In production a broken DB must prevent startup (fail fast), not
        # silently degrade to 500s at runtime.
        if settings.is_production:
            logger.error(f"DB init failed in production: {e}")
            raise
        logger.warning(f"DB init skipped (dev): {e}")

    yield
    await close_db()
    shutdown_executor(wait=False)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="Enterprise HelpDesk AI Copilot with self-training memory.",
        lifespan=lifespan,
    )

    # Security Headers Middleware
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    # Safe CORS configuration
    cors_origins = settings.CORS_ORIGINS
    allow_credentials = True
    if "*" in cors_origins:
        # Wildcard cannot be used with credentials
        allow_credentials = False

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=allow_credentials,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
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