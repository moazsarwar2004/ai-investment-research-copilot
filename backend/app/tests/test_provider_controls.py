"""Circuit-breaker and quota behavior tests."""

from __future__ import annotations

import pytest

from backend.app.providers import (
    CircuitBreaker,
    CircuitState,
    ProviderCircuitOpenError,
    ProviderQuotaExceededError,
    ProviderQuotaManager,
    QuotaPolicy,
    RequestKind,
)


def test_circuit_opens_then_allows_one_half_open_recovery_probe() -> None:
    clock = [100.0]
    circuit = CircuitBreaker(
        failure_threshold=2,
        recovery_timeout_seconds=30,
        clock=lambda: clock[0],
    )

    circuit.allow_request()
    circuit.record_failure()
    circuit.allow_request()
    circuit.record_failure()

    assert circuit.snapshot().state is CircuitState.OPEN
    with pytest.raises(ProviderCircuitOpenError):
        circuit.allow_request()

    clock[0] += 30
    circuit.allow_request()
    assert circuit.snapshot().state is CircuitState.HALF_OPEN
    with pytest.raises(ProviderCircuitOpenError):
        circuit.allow_request()

    circuit.record_success()
    assert circuit.snapshot().state is CircuitState.CLOSED
    assert circuit.snapshot().consecutive_failures == 0


def test_failed_half_open_probe_reopens_the_circuit() -> None:
    clock = [0.0]
    circuit = CircuitBreaker(
        failure_threshold=1,
        recovery_timeout_seconds=5,
        clock=lambda: clock[0],
    )
    circuit.allow_request()
    circuit.record_failure()
    clock[0] = 5
    circuit.allow_request()
    circuit.record_failure()

    assert circuit.snapshot().state is CircuitState.OPEN
    assert circuit.snapshot().retry_after_seconds == 5


def test_scheduled_quota_preserves_interactive_capacity_and_resets() -> None:
    clock = [0.0]
    quotas = ProviderQuotaManager(
        {
            "fixture": QuotaPolicy(
                limit=10,
                window_seconds=60,
                interactive_reserve=3,
            )
        },
        clock=lambda: clock[0],
    )

    quotas.reserve("fixture", weight=7, kind=RequestKind.SCHEDULED)
    with pytest.raises(ProviderQuotaExceededError) as scheduled_error:
        quotas.reserve("fixture", weight=1, kind=RequestKind.SCHEDULED)

    interactive = quotas.reserve(
        "fixture",
        weight=3,
        kind=RequestKind.INTERACTIVE,
    )
    assert scheduled_error.value.retry_after_seconds == 60
    assert interactive is not None
    assert interactive.remaining == 0

    clock[0] = 60
    reset = quotas.reserve("fixture", weight=1, kind=RequestKind.SCHEDULED)
    assert reset is not None
    assert reset.used == 1


def test_provider_usage_header_reconciliation_never_reduces_local_usage() -> None:
    quotas = ProviderQuotaManager(
        {"fixture": QuotaPolicy(limit=100, window_seconds=60)}
    )
    quotas.reserve("fixture", weight=10, kind=RequestKind.INTERACTIVE)
    quotas.reconcile_used_weight("fixture", 5)
    first = quotas.snapshot("fixture")
    quotas.reconcile_used_weight("fixture", 25)
    second = quotas.snapshot("fixture")

    assert first is not None and first.used == 10
    assert second is not None and second.used == 25
