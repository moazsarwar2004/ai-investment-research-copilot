"""Provider weight budgets with reserved interactive capacity."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from math import ceil

from backend.app.providers.exceptions import ProviderQuotaExceededError
from backend.app.providers.models import RequestKind


@dataclass(frozen=True, slots=True)
class QuotaPolicy:
    """One rolling fixed-window weight budget."""

    limit: int
    window_seconds: int
    interactive_reserve: int = 0

    def __post_init__(self) -> None:
        if self.limit <= 0 or self.window_seconds <= 0:
            raise ValueError("quota limit and window must be positive")
        if not 0 <= self.interactive_reserve <= self.limit:
            raise ValueError("interactive reserve must be within the quota limit")


@dataclass(frozen=True, slots=True)
class QuotaSnapshot:
    """Current local budget state for later metrics/admin surfaces."""

    provider: str
    used: int
    limit: int
    remaining: int
    reset_after_seconds: int


@dataclass(slots=True)
class _QuotaWindow:
    started_at: float
    used: int = 0


class ProviderQuotaManager:
    """Reject budget-amplifying calls before an outbound request is made."""

    def __init__(
        self,
        policies: Mapping[str, QuotaPolicy] | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._policies = {
            provider.strip().lower(): policy
            for provider, policy in (policies or {}).items()
        }
        self._clock = clock
        self._windows: dict[str, _QuotaWindow] = {}

    def reserve(
        self,
        provider: str,
        *,
        weight: int,
        kind: RequestKind,
    ) -> QuotaSnapshot | None:
        """Atomically reserve local weight or fail with the reset duration."""
        if weight <= 0:
            raise ValueError("provider request weight must be positive")
        normalized = provider.strip().lower()
        policy = self._policies.get(normalized)
        if policy is None:
            return None

        now = self._clock()
        window = self._windows.get(normalized)
        if window is None or now - window.started_at >= policy.window_seconds:
            window = _QuotaWindow(started_at=now)
            self._windows[normalized] = window

        effective_limit = policy.limit
        if kind is RequestKind.SCHEDULED:
            effective_limit -= policy.interactive_reserve
        if window.used + weight > effective_limit:
            retry_after = ceil(
                max(0.001, policy.window_seconds - (now - window.started_at))
            )
            raise ProviderQuotaExceededError(
                retry_after_seconds=retry_after,
            )

        window.used += weight
        return self.snapshot(normalized)

    def reconcile_used_weight(self, provider: str, used: int) -> None:
        """Raise local usage to an authoritative provider-header value."""
        if used < 0:
            raise ValueError("reported provider usage cannot be negative")
        normalized = provider.strip().lower()
        if normalized not in self._policies:
            return
        now = self._clock()
        policy = self._policies[normalized]
        window = self._windows.get(normalized)
        if window is None or now - window.started_at >= policy.window_seconds:
            window = _QuotaWindow(started_at=now)
            self._windows[normalized] = window
        window.used = max(window.used, used)

    def snapshot(self, provider: str) -> QuotaSnapshot | None:
        normalized = provider.strip().lower()
        policy = self._policies.get(normalized)
        if policy is None:
            return None
        now = self._clock()
        window = self._windows.get(normalized)
        if window is None or now - window.started_at >= policy.window_seconds:
            used = 0
            reset_after = policy.window_seconds
        else:
            used = window.used
            reset_after = ceil(
                max(0.001, policy.window_seconds - (now - window.started_at))
            )
        return QuotaSnapshot(
            provider=normalized,
            used=used,
            limit=policy.limit,
            remaining=max(0, policy.limit - used),
            reset_after_seconds=reset_after,
        )
