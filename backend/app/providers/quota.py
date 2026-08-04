"""Provider weight budgets with reserved interactive capacity."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
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
    window_seconds: int


@dataclass(slots=True)
class _QuotaWindow:
    started_at: float
    used: int = 0


class ProviderQuotaManager:
    """Reject calls against one or more atomic provider budget windows.

    A provider can have a short request-rate window and a longer call-credit
    window.  All applicable windows are checked before any is incremented, so
    a rejected monthly-budget reservation cannot consume minute capacity.
    """

    def __init__(
        self,
        policies: Mapping[str, QuotaPolicy | Sequence[QuotaPolicy]] | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._policies: dict[str, tuple[QuotaPolicy, ...]] = {}
        for provider, configured in (policies or {}).items():
            normalized = provider.strip().lower()
            provider_policies = (
                (configured,)
                if isinstance(configured, QuotaPolicy)
                else tuple(configured)
            )
            if not provider_policies:
                raise ValueError("at least one quota policy is required per provider")
            windows = [policy.window_seconds for policy in provider_policies]
            if len(windows) != len(set(windows)):
                raise ValueError("provider quota windows must be unique")
            self._policies[normalized] = tuple(
                sorted(provider_policies, key=lambda policy: policy.window_seconds)
            )
        self._clock = clock
        self._windows: dict[tuple[str, int], _QuotaWindow] = {}

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
        policies = self._policies.get(normalized)
        if policies is None:
            return None

        now = self._clock()
        active: list[tuple[QuotaPolicy, _QuotaWindow]] = []
        for policy in policies:
            key = (normalized, policy.window_seconds)
            window = self._windows.get(key)
            if window is None or now - window.started_at >= policy.window_seconds:
                window = _QuotaWindow(started_at=now)
            active.append((policy, window))

        failures: list[int] = []
        for policy, window in active:
            effective_limit = policy.limit
            if kind is RequestKind.SCHEDULED:
                effective_limit -= policy.interactive_reserve
            if window.used + weight > effective_limit:
                failures.append(
                    ceil(
                        max(
                            0.001,
                            policy.window_seconds - (now - window.started_at),
                        )
                    )
                )
        if failures:
            raise ProviderQuotaExceededError(retry_after_seconds=max(failures))

        for policy, window in active:
            window.used += weight
            self._windows[(normalized, policy.window_seconds)] = window
        return self.snapshot(normalized)

    def reconcile_used_weight(self, provider: str, used: int) -> None:
        """Raise local usage to an authoritative provider-header value."""
        if used < 0:
            raise ValueError("reported provider usage cannot be negative")
        normalized = provider.strip().lower()
        if normalized not in self._policies:
            return
        now = self._clock()
        policy = self._policies[normalized][0]
        key = (normalized, policy.window_seconds)
        window = self._windows.get(key)
        if window is None or now - window.started_at >= policy.window_seconds:
            window = _QuotaWindow(started_at=now)
            self._windows[key] = window
        window.used = max(window.used, used)

    def snapshot(self, provider: str) -> QuotaSnapshot | None:
        normalized = provider.strip().lower()
        policies = self._policies.get(normalized)
        if policies is None:
            return None
        policy = policies[0]
        now = self._clock()
        window = self._windows.get((normalized, policy.window_seconds))
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
            window_seconds=policy.window_seconds,
        )

    def snapshots(self, provider: str) -> list[QuotaSnapshot]:
        """Return all configured windows for monitoring and budget tests."""
        normalized = provider.strip().lower()
        policies = self._policies.get(normalized)
        if policies is None:
            return []
        now = self._clock()
        snapshots: list[QuotaSnapshot] = []
        for policy in policies:
            window = self._windows.get((normalized, policy.window_seconds))
            if window is None or now - window.started_at >= policy.window_seconds:
                used = 0
                reset_after = policy.window_seconds
            else:
                used = window.used
                reset_after = ceil(
                    max(0.001, policy.window_seconds - (now - window.started_at))
                )
            snapshots.append(
                QuotaSnapshot(
                    provider=normalized,
                    used=used,
                    limit=policy.limit,
                    remaining=max(0, policy.limit - used),
                    reset_after_seconds=reset_after,
                    window_seconds=policy.window_seconds,
                )
            )
        return snapshots
