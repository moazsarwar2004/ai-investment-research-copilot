"""Safe request start/completion logging with monotonic duration."""

from __future__ import annotations

import time

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from backend.app.core.logger import get_logger

logger = get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log request metadata without query strings, headers, cookies, or bodies."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        started_at = time.perf_counter()
        request.state.request_started_at = started_at
        request_id = getattr(request.state, "request_id", "unknown")
        safe_fields = {
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
        }
        logger.info("http_request_started", extra=safe_fields)

        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started_at) * 1000, 3)
        logger.info(
            "http_request_completed",
            extra={
                **safe_fields,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response
