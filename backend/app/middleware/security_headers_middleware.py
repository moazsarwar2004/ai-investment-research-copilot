"""Initial defense-in-depth response headers."""

from __future__ import annotations

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from backend.app.core.config import Settings
from backend.app.core.security import build_security_headers


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach browser security headers without enabling local-development HSTS."""

    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        super().__init__(app)
        self.headers = build_security_headers(settings)

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        for header_name, header_value in self.headers.items():
            response.headers.setdefault(header_name, header_value)
        return response
