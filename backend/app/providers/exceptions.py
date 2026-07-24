"""Typed provider failures used for fallback and safe API translation."""

from __future__ import annotations

from http import HTTPStatus

from backend.app.core.exceptions import ApplicationError


class ProviderError(ApplicationError):
    """Base error with a stable, non-secret operational code."""

    code = "provider_error"
    retryable = False

    def __init__(self, message: str) -> None:
        super().__init__(
            code=self.code,
            message=message,
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
        )
        self.message = message


class ProviderConfigurationError(ProviderError):
    code = "provider_configuration_error"


class ProviderHostNotAllowedError(ProviderConfigurationError):
    code = "provider_host_not_allowed"


class ProviderTransportError(ProviderError):
    code = "provider_transport_error"
    retryable = True


class ProviderTimeoutError(ProviderTransportError):
    code = "provider_timeout"


class ProviderResponseError(ProviderError):
    code = "provider_response_error"

    def __init__(self, *, status_code: int, retryable: bool) -> None:
        super().__init__("The provider returned an unsuccessful response.")
        self.status_code = status_code
        self.retryable = retryable


class ProviderRateLimitError(ProviderResponseError):
    code = "provider_rate_limited"
    retryable = True

    def __init__(self, *, retry_after_seconds: int) -> None:
        super().__init__(status_code=429, retryable=True)
        self.retry_after_seconds = max(1, retry_after_seconds)


class ProviderPayloadTooLargeError(ProviderError):
    code = "provider_payload_too_large"


class ProviderSchemaError(ProviderError):
    code = "provider_schema_changed"


class ProviderCircuitOpenError(ProviderError):
    code = "provider_circuit_open"
    retryable = True


class ProviderQuotaExceededError(ProviderError):
    code = "provider_quota_exceeded"
    retryable = True

    def __init__(self, *, retry_after_seconds: int) -> None:
        super().__init__("The configured provider request budget is exhausted.")
        self.retry_after_seconds = max(1, retry_after_seconds)


class ProviderRefreshInProgressError(ProviderError):
    code = "provider_refresh_in_progress"
    retryable = True


class ProviderUnavailableError(ProviderError):
    code = "provider_unavailable"
    retryable = True

    def __init__(self, *, cause_code: str) -> None:
        super().__init__("Provider data is temporarily unavailable.")
        self.cause_code = cause_code
