"""Global API abuse budget for the small single-worker production pilot."""

from __future__ import annotations

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from backend.app.core.error_handlers import application_exception_handler
from backend.app.core.exceptions import RateLimitExceededError
from backend.app.core.identity_security import IdentitySecurity
from backend.app.core.rate_limits import ApiRateLimiter


class ApiRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        *,
        limiter: ApiRateLimiter,
        security: IdentitySecurity,
    ) -> None:
        super().__init__(app)
        self._limiter = limiter
        self._security = security

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.url.path.startswith("/api/"):
            client_ip = request.client.host if request.client is not None else None
            client_key = self._security.digest_client_value(client_ip) or "unknown"
            try:
                await self._limiter.check(f"api:{client_key}")
            except RateLimitExceededError as error:
                return await application_exception_handler(request, error)
        return await call_next(request)


__all__ = ["ApiRateLimitMiddleware"]
