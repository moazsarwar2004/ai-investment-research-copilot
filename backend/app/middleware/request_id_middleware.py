"""Request-ID validation, generation, propagation, and context binding."""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from backend.app.core.logger import bind_request_id, reset_request_id

REQUEST_ID_HEADER = "X-Request-ID"


def normalize_request_id(candidate: str | None) -> str:
    """Return a canonical UUID request ID, generating one for invalid input."""
    if candidate is not None and len(candidate) <= 64:
        try:
            return str(UUID(candidate))
        except (ValueError, AttributeError):
            pass
    return str(uuid4())


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Bind one correlation ID to request state, logs, errors, and responses."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = normalize_request_id(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id
        token = bind_request_id(request_id)
        try:
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            reset_request_id(token)
