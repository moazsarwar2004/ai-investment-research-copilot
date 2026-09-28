"""Request metric collection using route templates rather than raw asset paths."""

from __future__ import annotations

import time

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from backend.app.core.metrics import RequestMetrics


class MetricsMiddleware(BaseHTTPMiddleware):
    def __init__(
        self, app: ASGIApp, *, registry: RequestMetrics, api_prefix: str
    ) -> None:
        super().__init__(app)
        self._registry = registry
        self._api_prefix = api_prefix

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            if request.url.path != "/metrics":
                route_object = request.scope.get("route")
                route = getattr(route_object, "path", "unmatched")
                if request.url.path.startswith(self._api_prefix) and not str(
                    route
                ).startswith(self._api_prefix):
                    route = f"{self._api_prefix}{route}"
                self._registry.observe(
                    method=request.method,
                    route=str(route),
                    status_code=status_code,
                    duration_seconds=time.perf_counter() - started,
                )


__all__ = ["MetricsMiddleware"]
