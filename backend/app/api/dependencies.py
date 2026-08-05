"""FastAPI identity dependencies and database-backed authorization checks."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import Settings
from backend.app.core.exceptions import AuthenticationError, ServiceUnavailableError
from backend.app.core.identity_security import IdentitySecurity
from backend.app.core.rate_limits import AuthRateLimiter
from backend.app.database import get_database_session
from backend.app.repositories import IdentityRepository
from backend.app.services import (
    BinanceSpotService,
    CryptoService,
    CurrentPrincipal,
    IdentityService,
    RequestContext,
    StockService,
)

bearer_scheme = HTTPBearer(auto_error=False)
DatabaseSessionDependency = Annotated[AsyncSession, Depends(get_database_session)]
BearerDependency = Annotated[
    HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
]


def get_request_settings(request: Request) -> Settings:
    """Return validated process settings from application state."""
    settings = getattr(request.app.state, "settings", None)
    if not isinstance(settings, Settings):
        raise ServiceUnavailableError("Application configuration is unavailable.")
    return settings


async def get_identity_service(
    request: Request,
    session: DatabaseSessionDependency,
    settings: Annotated[Settings, Depends(get_request_settings)],
) -> AsyncIterator[IdentityService]:
    """Build a request-scoped identity service over one database session."""
    security = getattr(request.app.state, "identity_security", None)
    if not isinstance(security, IdentitySecurity):
        raise ServiceUnavailableError("Identity security is unavailable.")
    yield IdentityService(
        IdentityRepository(session),
        settings,
        security=security,
    )


def get_request_context(request: Request) -> RequestContext:
    """Extract bounded request evidence without trusting proxy headers directly."""
    client_ip = request.client.host if request.client is not None else None
    user_agent = request.headers.get("user-agent")
    return RequestContext(
        request_id=getattr(request.state, "request_id", None),
        client_ip=client_ip,
        user_agent=(user_agent or "")[:256] or None,
    )


def get_auth_rate_limiter(request: Request) -> AuthRateLimiter:
    """Return the process-owned Redis-first authentication limiter."""
    limiter = getattr(request.app.state, "auth_rate_limiter", None)
    if not isinstance(limiter, AuthRateLimiter):
        raise ServiceUnavailableError("Authentication rate limiting is unavailable.")
    return limiter


def get_binance_spot_service(request: Request) -> BinanceSpotService:
    """Return the process-owned, read-only Binance Spot research service."""
    service = getattr(request.app.state, "binance_spot_service", None)
    if not isinstance(service, BinanceSpotService):
        raise ServiceUnavailableError("Binance Spot research is unavailable.")
    return service


def get_crypto_service(request: Request) -> CryptoService:
    """Return the process-owned, read-only general crypto research service."""
    service = getattr(request.app.state, "crypto_service", None)
    if not isinstance(service, CryptoService):
        raise ServiceUnavailableError("General cryptocurrency research is unavailable.")
    return service


def get_stock_service(request: Request) -> StockService:
    """Return the process-owned, license-gated stock research service."""
    service = getattr(request.app.state, "stock_service", None)
    if not isinstance(service, StockService):
        raise ServiceUnavailableError("Stock research is unavailable.")
    return service


async def get_current_principal(
    credentials: BearerDependency,
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> CurrentPrincipal:
    """Require a bearer token and validate it against durable session state."""
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise AuthenticationError()
    return await service.authenticate_access(credentials.credentials)


async def get_admin_principal(
    principal: Annotated[CurrentPrincipal, Depends(get_current_principal)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> CurrentPrincipal:
    """Require the administrator role from current database state."""
    service.require_admin(principal)
    return principal
