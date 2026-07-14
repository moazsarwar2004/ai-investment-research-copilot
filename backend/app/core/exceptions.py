"""Typed application errors that are safe to translate into API responses."""

from __future__ import annotations

from http import HTTPStatus


class ApplicationError(Exception):
    """Base class for expected, client-safe application failures."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int = HTTPStatus.BAD_REQUEST,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = int(status_code)


class ResourceNotFoundError(ApplicationError):
    """Raised when a requested domain resource does not exist."""

    def __init__(self, message: str = "The requested resource was not found.") -> None:
        super().__init__(
            code="RESOURCE_NOT_FOUND",
            message=message,
            status_code=HTTPStatus.NOT_FOUND,
        )


class ApplicationValidationError(ApplicationError):
    """Raised when valid HTTP input violates a domain rule."""

    def __init__(self, message: str = "The request failed validation.") -> None:
        super().__init__(
            code="VALIDATION_ERROR",
            message=message,
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        )


class ServiceUnavailableError(ApplicationError):
    """Raised when a required application capability is temporarily unavailable."""

    def __init__(
        self, message: str = "The service is temporarily unavailable."
    ) -> None:
        super().__init__(
            code="SERVICE_UNAVAILABLE",
            message=message,
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
        )
