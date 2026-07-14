"""FastAPI application factory and process entry point."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.health_routes import health_router, probe_router, root_router
from backend.app.core.config import Settings, get_settings
from backend.app.core.error_handlers import register_exception_handlers
from backend.app.core.logger import configure_logging, get_logger
from backend.app.middleware.logging_middleware import RequestLoggingMiddleware
from backend.app.middleware.request_id_middleware import RequestIDMiddleware
from backend.app.middleware.security_headers_middleware import (
    SecurityHeadersMiddleware,
)

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Record startup readiness and graceful process shutdown."""
    settings: object = application.state.settings
    if not isinstance(settings, Settings):
        raise RuntimeError("Application settings were not initialized")

    application.state.started = True
    logger.info(
        "application_started",
        extra={"version": settings.app_version},
    )
    try:
        yield
    finally:
        application.state.started = False
        logger.info(
            "application_stopped",
            extra={"version": settings.app_version},
        )


def create_application(settings: Settings | None = None) -> FastAPI:
    """Create a fully configured, independently testable FastAPI instance."""
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings)

    application = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        description=(
            "Source-backed investment research API. Research and education only; "
            "not personalized financial advice."
        ),
        debug=False,
        docs_url="/docs" if resolved_settings.docs_enabled else None,
        redoc_url="/redoc" if resolved_settings.docs_enabled else None,
        openapi_url="/openapi.json" if resolved_settings.docs_enabled else None,
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.state.started = False

    register_exception_handlers(application)

    # Starlette executes the last-added middleware first. Request ID is therefore
    # outermost, so all inner logs and handled errors share the same correlation ID.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "X-Request-ID",
        ],
        expose_headers=["X-Request-ID"],
    )
    application.add_middleware(
        SecurityHeadersMiddleware,
        settings=resolved_settings,
    )
    application.add_middleware(RequestLoggingMiddleware)
    application.add_middleware(RequestIDMiddleware)

    application.include_router(root_router)
    application.include_router(probe_router)
    application.include_router(
        health_router,
        prefix=resolved_settings.api_v1_prefix,
    )
    return application


app = create_application()
