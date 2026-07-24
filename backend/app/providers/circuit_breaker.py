"""Per-provider circuit breakers with one guarded half-open probe."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from backend.app.providers.exceptions import ProviderCircuitOpenError


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True, slots=True)
class CircuitSnapshot:
    """Sanitized operational state for logs and later admin diagnostics."""

    state: CircuitState
    consecutive_failures: int
    retry_after_seconds: int


class CircuitBreaker:
    """Fail fast after repeated upstream failures and test recovery safely."""

    def __init__(
        self,
        *,
        failure_threshold: int,
        recovery_timeout_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold <= 0 or recovery_timeout_seconds <= 0:
            raise ValueError("circuit thresholds must be positive")
        self._failure_threshold = failure_threshold
        self._recovery_timeout_seconds = recovery_timeout_seconds
        self._clock = clock
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._half_open_probe_active = False

    def allow_request(self) -> None:
        """Allow a request or raise while the circuit cannot safely probe."""
        now = self._clock()
        if self._state is CircuitState.OPEN:
            opened_at = self._opened_at
            if (
                opened_at is not None
                and now - opened_at >= self._recovery_timeout_seconds
            ):
                self._state = CircuitState.HALF_OPEN
                self._half_open_probe_active = False
            else:
                raise ProviderCircuitOpenError(
                    "The provider circuit is temporarily open."
                )

        if self._state is CircuitState.HALF_OPEN:
            if self._half_open_probe_active:
                raise ProviderCircuitOpenError(
                    "The provider recovery probe is already running."
                )
            self._half_open_probe_active = True

    def record_success(self) -> None:
        """Close the circuit after any successful call or recovery probe."""
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at = None
        self._half_open_probe_active = False

    def record_failure(self) -> None:
        """Count a failed call and open immediately when a probe fails."""
        self._half_open_probe_active = False
        if self._state is CircuitState.HALF_OPEN:
            self._open()
            return

        self._consecutive_failures += 1
        if self._consecutive_failures >= self._failure_threshold:
            self._open()

    def cancel_request(self) -> None:
        """Release a half-open permit when no upstream call was attempted."""
        if self._state is CircuitState.HALF_OPEN:
            self._half_open_probe_active = False

    def _open(self) -> None:
        self._state = CircuitState.OPEN
        self._opened_at = self._clock()
        self._half_open_probe_active = False

    def snapshot(self) -> CircuitSnapshot:
        """Return current state without exposing provider request details."""
        retry_after = 0
        if self._state is CircuitState.OPEN and self._opened_at is not None:
            elapsed = self._clock() - self._opened_at
            retry_after = max(
                0,
                int(self._recovery_timeout_seconds - elapsed + 0.999),
            )
        return CircuitSnapshot(
            state=self._state,
            consecutive_failures=self._consecutive_failures,
            retry_after_seconds=retry_after,
        )


class CircuitBreakerRegistry:
    """Lazily allocate an independent breaker for each configured provider."""

    def __init__(
        self,
        *,
        failure_threshold: int,
        recovery_timeout_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_timeout_seconds = recovery_timeout_seconds
        self._clock = clock
        self._breakers: dict[str, CircuitBreaker] = {}

    def for_provider(self, provider: str) -> CircuitBreaker:
        normalized = provider.strip().lower()
        if not normalized:
            raise ValueError("provider must not be blank")
        breaker = self._breakers.get(normalized)
        if breaker is None:
            breaker = CircuitBreaker(
                failure_threshold=self._failure_threshold,
                recovery_timeout_seconds=self._recovery_timeout_seconds,
                clock=self._clock,
            )
            self._breakers[normalized] = breaker
        return breaker
