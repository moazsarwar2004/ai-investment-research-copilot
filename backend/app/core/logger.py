"""Minimal structured logging with request correlation and safe fields."""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any

from backend.app.core.config import LogFormat, Settings

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_SAFE_EXTRA_FIELDS = (
    "request_id",
    "method",
    "path",
    "status_code",
    "duration_ms",
    "version",
    "dependency",
    "exception_type",
)


def bind_request_id(request_id: str) -> Token[str | None]:
    """Bind a request ID to the current asynchronous context."""
    return _request_id.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    """Restore the request-ID context after a request completes."""
    _request_id.reset(token)


def current_request_id() -> str | None:
    """Return the request ID bound to the current context, if any."""
    return _request_id.get()


class JsonFormatter(logging.Formatter):
    """Render a stable, allowlisted JSON log record."""

    def __init__(self, *, service: str, environment: str) -> None:
        super().__init__()
        self.service = service
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        """Serialize an application event without arbitrary record attributes."""
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "service": self.service,
            "environment": self.environment,
            "event": record.getMessage(),
        }

        context_request_id = current_request_id()
        if context_request_id is not None:
            payload["request_id"] = context_request_id

        for field_name in _SAFE_EXTRA_FIELDS:
            field_value = getattr(record, field_name, None)
            if field_value is not None:
                payload[field_name] = field_value

        if record.exc_info and record.exc_info[0] is not None:
            payload["exception_type"] = record.exc_info[0].__name__

        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class ConsoleFormatter(logging.Formatter):
    """Render concise human-readable local logs with the same safe fields."""

    def format(self, record: logging.LogRecord) -> str:
        """Format a safe console event."""
        request_id = getattr(record, "request_id", None) or current_request_id() or "-"
        extras = []
        for field_name in ("method", "path", "status_code", "duration_ms"):
            field_value = getattr(record, field_name, None)
            if field_value is not None:
                extras.append(f"{field_name}={field_value}")
        suffix = f" {' '.join(extras)}" if extras else ""
        return (
            f"{record.levelname} request_id={request_id} {record.getMessage()}{suffix}"
        )


def configure_logging(settings: Settings) -> None:
    """Configure one stdout handler and disable duplicate Uvicorn access logs."""
    handler = logging.StreamHandler(sys.stdout)
    if settings.log_format is LogFormat.JSON:
        handler.setFormatter(
            JsonFormatter(
                service=settings.app_name,
                environment=settings.environment.value,
            )
        )
    else:
        handler.setFormatter(ConsoleFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.log_level)

    logging.getLogger("uvicorn.access").disabled = True


def get_logger(name: str) -> logging.Logger:
    """Return a standard logger configured by the application factory."""
    return logging.getLogger(name)
