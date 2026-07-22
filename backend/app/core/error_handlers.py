"""Global exception handlers with one safe JSON error contract."""

from __future__ import annotations

import time
from http import HTTPStatus
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse, Response

from backend.app.core.config import Settings
from backend.app.core.exceptions import (
    ApplicationError,
    AuthenticationError,
    RateLimitExceededError,
)
from backend.app.core.logger import get_logger
from backend.app.core.security import build_security_headers

logger = get_logger(__name__)


def _request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and request_id:
        return request_id
    generated = str(uuid4())
    request.state.request_id = generated
    return generated


def _settings(request: Request) -> Settings:
    settings: object = request.app.state.settings
    if not isinstance(settings, Settings):
        raise RuntimeError("Application settings are unavailable")
    return settings


def _response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    extra_headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = _request_id(request)
    content: dict[str, Any] = {
        "success": False,
        "data": None,
        "errors": [{"code": code, "message": message}],
        "meta": {"request_id": request_id},
    }
    headers = build_security_headers(_settings(request))
    headers["X-Request-ID"] = request_id
    headers.update(extra_headers or {})
    return JSONResponse(status_code=status_code, content=content, headers=headers)


async def application_exception_handler(request: Request, exc: Exception) -> Response:
    """Translate an expected application failure without leaking internals."""
    if not isinstance(exc, ApplicationError):
        return await unexpected_exception_handler(request, exc)
    extra_headers: dict[str, str] = {}
    if isinstance(exc, AuthenticationError):
        extra_headers["WWW-Authenticate"] = "Bearer"
    if isinstance(exc, RateLimitExceededError):
        extra_headers["Retry-After"] = str(exc.retry_after_seconds)
    return _response(
        request,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        extra_headers=extra_headers,
    )


async def request_validation_exception_handler(
    request: Request, exc: Exception
) -> Response:
    """Return a stable error for malformed HTTP input."""
    if not isinstance(exc, RequestValidationError):
        return await unexpected_exception_handler(request, exc)
    return _response(
        request,
        status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        code="REQUEST_VALIDATION_ERROR",
        message="The request contains invalid or missing values.",
    )


async def http_exception_handler(request: Request, exc: Exception) -> Response:
    """Normalize framework HTTP failures, including unknown routes."""
    if not isinstance(exc, StarletteHTTPException):
        return await unexpected_exception_handler(request, exc)

    status_code = int(exc.status_code)
    if status_code == HTTPStatus.NOT_FOUND:
        message = "The requested resource was not found."
    elif status_code == HTTPStatus.METHOD_NOT_ALLOWED:
        message = "The HTTP method is not allowed for this resource."
    else:
        message = "The request could not be completed."
    return _response(
        request,
        status_code=status_code,
        code="RESOURCE_NOT_FOUND" if status_code == 404 else f"HTTP_{status_code}",
        message=message,
    )


async def unexpected_exception_handler(request: Request, exc: Exception) -> Response:
    """Log an unexpected failure and return a generic response."""
    request_id = _request_id(request)
    started_at = getattr(request.state, "request_started_at", None)
    duration_ms = None
    if isinstance(started_at, float):
        duration_ms = round((time.perf_counter() - started_at) * 1000, 3)

    logger.error(
        "unhandled_exception",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": HTTPStatus.INTERNAL_SERVER_ERROR,
            "duration_ms": duration_ms,
        },
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return _response(
        request,
        status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        code="INTERNAL_SERVER_ERROR",
        message="An unexpected error occurred.",
    )


def register_exception_handlers(application: FastAPI) -> None:
    """Register all application and framework exception translators."""
    application.add_exception_handler(ApplicationError, application_exception_handler)
    application.add_exception_handler(
        RequestValidationError, request_validation_exception_handler
    )
    application.add_exception_handler(StarletteHTTPException, http_exception_handler)
    application.add_exception_handler(Exception, unexpected_exception_handler)
