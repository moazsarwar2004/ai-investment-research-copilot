"""FastAPI application factory and process entry point."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.binance_spot_routes import binance_spot_router
from backend.app.api.crypto_routes import crypto_router
from backend.app.api.health_routes import health_router, probe_router, root_router
from backend.app.api.identity_routes import identity_router
from backend.app.api.stock_routes import stock_router
from backend.app.cache import RedisCache
from backend.app.core.config import Settings, get_settings
from backend.app.core.error_handlers import register_exception_handlers
from backend.app.core.identity_security import IdentitySecurity
from backend.app.core.logger import configure_logging, get_logger
from backend.app.core.rate_limits import AuthRateLimiter
from backend.app.core.resources import ApplicationResources, create_resources
from backend.app.database import DatabaseManager
from backend.app.middleware.logging_middleware import RequestLoggingMiddleware
from backend.app.middleware.request_id_middleware import RequestIDMiddleware
from backend.app.middleware.security_headers_middleware import (
    SecurityHeadersMiddleware,
)
from backend.app.providers import (
    ProviderHttpClient,
    ProviderManager,
    ProviderQuotaManager,
    QuotaPolicy,
)
from backend.app.services import BinanceSpotService, CryptoService, StockService

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Record startup readiness and graceful process shutdown."""
    settings: object = application.state.settings
    if not isinstance(settings, Settings):
        raise RuntimeError("Application settings were not initialized")

    resources: object = application.state.resources
    if not isinstance(resources, ApplicationResources):
        raise RuntimeError("Application resources were not initialized")

    application.state.started = True
    logger.info(
        "application_started",
        extra={"version": settings.app_version},
    )
    try:
        yield
    finally:
        application.state.started = False
        await resources.close()
        logger.info(
            "application_stopped",
            extra={"version": settings.app_version},
        )


def create_application(
    settings: Settings | None = None,
    resources: ApplicationResources | None = None,
) -> FastAPI:
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
    resolved_resources = resources or create_resources(resolved_settings)
    application.state.resources = resolved_resources
    application.state.database_manager = (
        resolved_resources.database
        if isinstance(resolved_resources.database, DatabaseManager)
        else None
    )
    redis_cache = (
        resolved_resources.cache
        if isinstance(resolved_resources.cache, RedisCache)
        else None
    )
    application.state.identity_security = IdentitySecurity(resolved_settings)
    application.state.auth_rate_limiter = AuthRateLimiter(
        resolved_settings, redis_cache
    )
    application.state.provider_http_client = (
        resolved_resources.provider_http
        if isinstance(resolved_resources.provider_http, ProviderHttpClient)
        else None
    )
    application.state.binance_spot_service = None
    application.state.crypto_service = None
    # The service is intentionally present without a provider. It returns a
    # structured unavailable state until reviewed display rights are configured.
    application.state.stock_service = StockService()
    if (
        resolved_settings.binance_spot_enabled
        and isinstance(resolved_resources.provider_http, ProviderHttpClient)
        and isinstance(resolved_resources.cache, RedisCache)
    ):
        provider_manager = ProviderManager.from_settings(
            resolved_settings,
            http_client=resolved_resources.provider_http,
            cache=resolved_resources.cache,
            quota_manager=ProviderQuotaManager(
                {
                    "binance_spot": QuotaPolicy(
                        limit=(resolved_settings.binance_spot_weight_limit_per_minute),
                        window_seconds=60,
                        interactive_reserve=(
                            resolved_settings.binance_spot_interactive_reserve
                        ),
                    )
                }
            ),
        )
        application.state.binance_spot_service = BinanceSpotService(
            provider_manager,
            base_url=resolved_settings.binance_spot_base_url,
        )
    if (
        resolved_settings.coingecko_enabled
        and isinstance(resolved_resources.provider_http, ProviderHttpClient)
        and isinstance(resolved_resources.cache, RedisCache)
    ):
        crypto_provider_manager = ProviderManager.from_settings(
            resolved_settings,
            http_client=resolved_resources.provider_http,
            cache=resolved_resources.cache,
            quota_manager=ProviderQuotaManager(
                {
                    "coingecko": (
                        QuotaPolicy(
                            limit=resolved_settings.coingecko_limit_per_minute,
                            window_seconds=60,
                            interactive_reserve=(
                                resolved_settings.coingecko_interactive_reserve_per_minute
                            ),
                        ),
                        QuotaPolicy(
                            limit=resolved_settings.coingecko_monthly_call_budget,
                            window_seconds=30 * 24 * 60 * 60,
                            interactive_reserve=(
                                resolved_settings.coingecko_interactive_reserve_per_month
                            ),
                        ),
                    )
                }
            ),
        )
        application.state.crypto_service = CryptoService(
            crypto_provider_manager,
            base_url=resolved_settings.coingecko_base_url,
            demo_api_key=resolved_settings.coingecko_api_key,
        )
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
    application.include_router(
        identity_router,
        prefix=resolved_settings.api_v1_prefix,
    )
    application.include_router(
        binance_spot_router,
        prefix=resolved_settings.api_v1_prefix,
    )
    application.include_router(
        crypto_router,
        prefix=resolved_settings.api_v1_prefix,
    )
    application.include_router(
        stock_router,
        prefix=resolved_settings.api_v1_prefix,
    )
    return application


app = create_application()
