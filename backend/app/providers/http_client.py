"""Bounded async provider HTTP client with safe retries and host controls."""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from email.utils import parsedate_to_datetime
from math import ceil
from urllib.parse import urlsplit

import httpx
from pydantic import AnyHttpUrl

from backend.app.core.config import Settings
from backend.app.core.logger import get_logger
from backend.app.providers.exceptions import (
    ProviderHostNotAllowedError,
    ProviderPayloadTooLargeError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderTransportError,
)
from backend.app.providers.models import OutboundRequest, ProviderHttpResponse

logger = get_logger(__name__)

_RETRYABLE_STATUS_CODES = frozenset({408, 425, 500, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class ProviderHttpPolicy:
    """Validated retry, deadline, and response-size controls."""

    connect_timeout_seconds: float
    read_timeout_seconds: float
    write_timeout_seconds: float
    pool_timeout_seconds: float
    total_deadline_seconds: float
    max_attempts: int
    retry_base_seconds: float
    retry_max_seconds: float
    retry_after_max_seconds: float
    response_max_bytes: int

    @classmethod
    def from_settings(cls, settings: Settings) -> ProviderHttpPolicy:
        return cls(
            connect_timeout_seconds=settings.provider_connect_timeout_seconds,
            read_timeout_seconds=settings.provider_read_timeout_seconds,
            write_timeout_seconds=settings.provider_write_timeout_seconds,
            pool_timeout_seconds=settings.provider_pool_timeout_seconds,
            total_deadline_seconds=settings.provider_total_deadline_seconds,
            max_attempts=settings.provider_max_attempts,
            retry_base_seconds=settings.provider_retry_base_seconds,
            retry_max_seconds=settings.provider_retry_max_seconds,
            retry_after_max_seconds=settings.provider_retry_after_max_seconds,
            response_max_bytes=settings.provider_response_max_bytes,
        )


class ProviderHttpClient:
    """Own one pooled HTTPX client while adapters retain wire-format knowledge."""

    def __init__(
        self,
        policy: ProviderHttpPolicy,
        *,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] | None = None,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        self._policy = policy
        self._client = client or httpx.AsyncClient(
            follow_redirects=False,
            trust_env=False,
        )
        self._owns_client = client is None
        self._sleep = sleep
        self._monotonic = monotonic
        self._wall_clock = wall_clock or (lambda: datetime.now(UTC))
        self._random_value = random_value

    @classmethod
    def from_settings(cls, settings: Settings) -> ProviderHttpClient:
        return cls(ProviderHttpPolicy.from_settings(settings))

    async def request(
        self,
        *,
        provider: str,
        operation: str,
        outbound: OutboundRequest,
        allowed_hosts: Collection[str],
        on_attempt: Callable[[int], None] | None = None,
    ) -> ProviderHttpResponse:
        """Perform an allowlisted request under one total retry deadline."""
        self._validate_destination(outbound, allowed_hosts)
        started_at = self._monotonic()
        deadline = started_at + self._policy.total_deadline_seconds
        last_transport_error: Exception | None = None

        for attempt in range(1, self._policy.max_attempts + 1):
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                raise ProviderTimeoutError(
                    "The provider request exceeded its total deadline."
                )
            if on_attempt is not None:
                on_attempt(attempt)
            timeout = self._attempt_timeout(remaining)
            try:
                async with asyncio.timeout(remaining):
                    response = await self._client.request(
                        outbound.method,
                        str(outbound.url),
                        params=outbound.params,
                        headers=outbound.headers,
                        timeout=timeout,
                    )
            except (TimeoutError, httpx.TimeoutException) as error:
                last_transport_error = error
                if not await self._retry_transport(
                    provider=provider,
                    operation=operation,
                    attempt=attempt,
                    deadline=deadline,
                ):
                    raise ProviderTimeoutError(
                        "The provider request timed out."
                    ) from error
                continue
            except httpx.TransportError as error:
                last_transport_error = error
                if not await self._retry_transport(
                    provider=provider,
                    operation=operation,
                    attempt=attempt,
                    deadline=deadline,
                ):
                    raise ProviderTransportError(
                        "The provider connection failed."
                    ) from error
                continue

            if response.status_code == 429:
                retry_after = self._parse_retry_after(response.headers)
                if await self._retry_after_rate_limit(
                    provider=provider,
                    operation=operation,
                    attempt=attempt,
                    deadline=deadline,
                    retry_after_seconds=retry_after,
                ):
                    continue
                raise ProviderRateLimitError(
                    retry_after_seconds=max(1, ceil(retry_after)),
                )

            if response.status_code in _RETRYABLE_STATUS_CODES:
                if await self._retry_transport(
                    provider=provider,
                    operation=operation,
                    attempt=attempt,
                    deadline=deadline,
                ):
                    continue
                raise ProviderResponseError(
                    status_code=response.status_code,
                    retryable=True,
                )

            if response.is_error:
                raise ProviderResponseError(
                    status_code=response.status_code,
                    retryable=False,
                )

            content = response.content
            if len(content) > self._policy.response_max_bytes:
                raise ProviderPayloadTooLargeError(
                    "The provider response exceeded the configured size limit."
                )
            try:
                payload: object
                if outbound.method == "HEAD" or not content:
                    payload = None
                else:
                    payload = json.loads(content, parse_float=Decimal)
            except (json.JSONDecodeError, UnicodeDecodeError) as error:
                raise ProviderResponseError(
                    status_code=response.status_code,
                    retryable=False,
                ) from error

            headers = {key.lower(): value for key, value in response.headers.items()}
            provider_request_id = (
                headers.get("x-request-id")
                or headers.get("x-correlation-id")
                or headers.get("request-id")
            )
            safe_source_url = str(
                httpx.URL(str(outbound.url)).copy_with(query=None, fragment=None)
            )
            return ProviderHttpResponse(
                payload=payload,
                fetched_at=self._wall_clock().astimezone(UTC),
                source_url=AnyHttpUrl(safe_source_url),
                headers=headers,
                raw_payload_sha256=hashlib.sha256(content).hexdigest(),
                provider_request_id=provider_request_id,
                attempts=attempt,
            )

        if isinstance(last_transport_error, httpx.TimeoutException | TimeoutError):
            raise ProviderTimeoutError("The provider request timed out.")
        raise ProviderTransportError("The provider connection failed.")

    def _validate_destination(
        self,
        outbound: OutboundRequest,
        allowed_hosts: Collection[str],
    ) -> None:
        parsed = urlsplit(str(outbound.url))
        normalized_hosts = {
            candidate.strip().lower().rstrip(".")
            for candidate in allowed_hosts
            if candidate.strip()
        }
        hostname = (parsed.hostname or "").lower().rstrip(".")
        if (
            parsed.scheme != "https"
            or not hostname
            or hostname not in normalized_hosts
            or parsed.port not in {None, 443}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ProviderHostNotAllowedError(
                "The provider destination is not on the adapter allowlist."
            )

    def _attempt_timeout(self, remaining: float) -> httpx.Timeout:
        return httpx.Timeout(
            connect=min(self._policy.connect_timeout_seconds, remaining),
            read=min(self._policy.read_timeout_seconds, remaining),
            write=min(self._policy.write_timeout_seconds, remaining),
            pool=min(self._policy.pool_timeout_seconds, remaining),
        )

    async def _retry_transport(
        self,
        *,
        provider: str,
        operation: str,
        attempt: int,
        deadline: float,
    ) -> bool:
        if attempt >= self._policy.max_attempts:
            return False
        cap = min(
            self._policy.retry_max_seconds,
            self._policy.retry_base_seconds * (2 ** (attempt - 1)),
        )
        delay = cap * (0.5 + 0.5 * self._random_value())
        if self._monotonic() + delay >= deadline:
            return False
        logger.warning(
            "provider_request_retry",
            extra={
                "provider": provider,
                "operation": operation,
                "attempt": attempt,
                "retry_count": attempt,
            },
        )
        await self._sleep(delay)
        return True

    async def _retry_after_rate_limit(
        self,
        *,
        provider: str,
        operation: str,
        attempt: int,
        deadline: float,
        retry_after_seconds: float,
    ) -> bool:
        if (
            attempt >= self._policy.max_attempts
            or retry_after_seconds > self._policy.retry_after_max_seconds
            or self._monotonic() + retry_after_seconds >= deadline
        ):
            return False
        logger.warning(
            "provider_rate_limit_wait",
            extra={
                "provider": provider,
                "operation": operation,
                "attempt": attempt,
                "retry_count": attempt,
                "status_code": 429,
            },
        )
        await self._sleep(retry_after_seconds)
        return True

    def _parse_retry_after(self, headers: httpx.Headers) -> float:
        raw = headers.get("retry-after")
        if raw is None:
            return max(1.0, self._policy.retry_base_seconds)
        try:
            seconds = float(raw)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(raw)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=UTC)
                seconds = (
                    retry_at.astimezone(UTC) - self._wall_clock().astimezone(UTC)
                ).total_seconds()
            except (TypeError, ValueError, OverflowError):
                return max(1.0, self._policy.retry_base_seconds)
        return max(0.0, seconds)

    async def close(self) -> None:
        """Close only a client whose lifecycle this object owns."""
        if self._owns_client:
            await self._client.aclose()
