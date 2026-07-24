"""Provider normalization, schema-change, cache, and single-flight tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, ClassVar, cast

import pytest
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, ValidationError

from backend.app.cache import (
    CacheLock,
    CacheLockStatus,
    CacheRead,
    CacheStatus,
    JsonValue,
)
from backend.app.providers import (
    AssetType,
    CanonicalAsset,
    CircuitBreakerRegistry,
    DelayClass,
    NormalizedPayload,
    OutboundRequest,
    ProviderAdapter,
    ProviderHttpClient,
    ProviderHttpResponse,
    ProviderManager,
    ProviderQuotaManager,
    ProviderRequest,
    ProviderSchemaError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)


class QuoteData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    price: Decimal


class QuoteWire(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price: Decimal
    source_timestamp: datetime


class FixtureAdapter(ProviderAdapter[QuoteData]):
    provider: ClassVar[str] = "fixture"
    schema_version: ClassVar[str] = "quote-v1"
    terms_review_version: ClassVar[str] = "fixture-2026-07-23"
    attribution: ClassVar[str] = "Fixture data for automated tests"
    allowed_hosts: ClassVar[frozenset[str]] = frozenset({"fixture.example"})
    data_model: ClassVar[type[BaseModel]] = QuoteData

    def build_request(self, request: ProviderRequest) -> OutboundRequest:
        return OutboundRequest(url=AnyHttpUrl("https://fixture.example/quote"))

    def normalize(
        self,
        response: ProviderHttpResponse,
        request: ProviderRequest,
    ) -> NormalizedPayload[QuoteData]:
        try:
            wire = QuoteWire.model_validate(response.payload)
        except ValidationError as error:
            raise ProviderSchemaError("Fixture schema changed.") from error
        return NormalizedPayload[QuoteData](
            data=QuoteData(price=wire.price),
            source_timestamp=wire.source_timestamp,
            delay_class=DelayClass.LIVE,
        )


class FixtureAdapterV2(FixtureAdapter):
    schema_version: ClassVar[str] = "quote-v2"


class MemoryProviderCache:
    """Provider cache double with controllable freshness and lock state."""

    def __init__(self) -> None:
        self.value: JsonValue | None = None
        self.status = CacheStatus.MISS
        self.writes = 0
        self.lock_status = CacheLockStatus.ACQUIRED

    async def read(self, key: str) -> CacheRead:
        return CacheRead(value=self.value, status=self.status)

    async def write(
        self,
        key: str,
        value: JsonValue,
        *,
        soft_ttl_seconds: int,
        hard_ttl_seconds: int,
    ) -> bool:
        self.value = value
        self.status = CacheStatus.HIT
        self.writes += 1
        return True

    async def delete(self, key: str) -> bool:
        existed = self.value is not None
        self.value = None
        self.status = CacheStatus.MISS
        return existed

    async def acquire_lock(self, key: str, *, ttl_seconds: int) -> CacheLock:
        return CacheLock(
            status=self.lock_status,
            token=(
                "fixture-lock" if self.lock_status is CacheLockStatus.ACQUIRED else None
            ),
        )

    async def release_lock(self, key: str, token: str) -> bool:
        return token == "fixture-lock"


class StubHttpClient:
    """Queue-backed HTTP client that never touches the network."""

    def __init__(self, outcomes: list[ProviderHttpResponse | ProviderTimeoutError]):
        self.outcomes = outcomes
        self.calls = 0

    async def request(self, **_: Any) -> ProviderHttpResponse:
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, ProviderTimeoutError):
            raise outcome
        return outcome


class BlockingHttpClient:
    def __init__(self, response: ProviderHttpResponse) -> None:
        self.response = response
        self.calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def request(self, **_: Any) -> ProviderHttpResponse:
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return self.response


def _request() -> ProviderRequest:
    return ProviderRequest(
        operation="quote",
        asset=CanonicalAsset(asset_type=AssetType.CRYPTO, key="fixture-coin"),
        soft_ttl_seconds=10,
        hard_ttl_seconds=30,
    )


def _http_response(
    payload: object,
    *,
    fetched_at: datetime | None = None,
) -> ProviderHttpResponse:
    return ProviderHttpResponse(
        payload=payload,
        fetched_at=fetched_at or datetime(2026, 7, 23, 12, 0, tzinfo=UTC),
        source_url=AnyHttpUrl("https://fixture.example/quote"),
        headers={},
        raw_payload_sha256="a" * 64,
        provider_request_id="fixture-request",
        attempts=1,
    )


def _manager(
    http_client: StubHttpClient | BlockingHttpClient,
    cache: MemoryProviderCache,
    *,
    now: datetime | None = None,
    failure_threshold: int = 2,
) -> ProviderManager:
    return ProviderManager(
        http_client=cast(ProviderHttpClient, http_client),
        cache=cache,
        quota_manager=ProviderQuotaManager(),
        circuits=CircuitBreakerRegistry(
            failure_threshold=failure_threshold,
            recovery_timeout_seconds=60,
        ),
        cache_lock_ttl_seconds=5,
        cache_lock_wait_seconds=0,
        cache_lock_poll_seconds=0.01,
        clock=lambda: now or datetime(2026, 7, 23, 12, 0, tzinfo=UTC),
    )


async def test_normalized_result_has_decimal_safe_provenance_and_cache_hit() -> None:
    fetched_at = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    source_at = fetched_at - timedelta(seconds=2)
    http = StubHttpClient(
        [_http_response({"price": "10.2500", "source_timestamp": source_at})]
    )
    cache = MemoryProviderCache()
    manager = _manager(http, cache, now=fetched_at)

    miss = await manager.fetch(FixtureAdapter(), _request())
    hit = await manager.fetch(FixtureAdapter(), _request())

    assert miss.data.price == Decimal("10.2500")
    assert miss.meta.cache_status is CacheStatus.MISS
    assert miss.meta.staleness_seconds == 2
    assert miss.meta.provenance.raw_payload_sha256 == "a" * 64
    assert miss.meta.provenance.schema_version == "quote-v1"
    assert hit.meta.cache_status is CacheStatus.HIT
    assert hit.meta.freshness.value == "cached"
    assert http.calls == 1


async def test_schema_change_is_typed_and_opens_circuit_without_live_io() -> None:
    http = StubHttpClient(
        [
            _http_response({"renamed_price": "10"}),
            _http_response({"renamed_price": "11"}),
        ]
    )
    cache = MemoryProviderCache()
    manager = _manager(http, cache, failure_threshold=2)

    for expected_code in (
        "provider_schema_changed",
        "provider_schema_changed",
        "provider_circuit_open",
    ):
        with pytest.raises(ProviderUnavailableError) as error:
            await manager.fetch(FixtureAdapter(), _request())
        assert error.value.cause_code == expected_code

    assert http.calls == 2


async def test_timeout_returns_original_stale_value_with_explicit_warnings() -> None:
    source_at = datetime(2026, 7, 23, 11, 55, tzinfo=UTC)
    cache = MemoryProviderCache()
    warm_http = StubHttpClient(
        [_http_response({"price": "9.5", "source_timestamp": source_at})]
    )
    warm_manager = _manager(warm_http, cache)
    warm = await warm_manager.fetch(FixtureAdapter(), _request())
    original_fetch_time = warm.meta.fetched_at
    cache.status = CacheStatus.STALE

    failing_http = StubHttpClient([ProviderTimeoutError("fixture timeout")])
    stale_manager = _manager(
        failing_http,
        cache,
        now=datetime(2026, 7, 23, 12, 5, tzinfo=UTC),
    )
    stale = await stale_manager.fetch(FixtureAdapter(), _request())

    warning_codes = {warning.code for warning in stale.meta.warnings}
    assert stale.data.price == Decimal("9.5")
    assert stale.meta.fetched_at == original_fetch_time
    assert stale.meta.cache_status is CacheStatus.STALE
    assert stale.meta.freshness.value == "stale"
    assert "stale_cache_fallback" in warning_codes
    assert "provider_timeout" in warning_codes


async def test_normalization_schema_version_change_evicts_cached_value() -> None:
    source_at = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    cache = MemoryProviderCache()
    first_http = StubHttpClient(
        [_http_response({"price": "9.5", "source_timestamp": source_at})]
    )
    await _manager(first_http, cache).fetch(FixtureAdapter(), _request())

    second_http = StubHttpClient(
        [_http_response({"price": "10.5", "source_timestamp": source_at})]
    )
    refreshed = await _manager(second_http, cache).fetch(
        FixtureAdapterV2(),
        _request(),
    )

    assert refreshed.data.price == Decimal("10.5")
    assert refreshed.meta.provenance.schema_version == "quote-v2"
    assert refreshed.meta.cache_status is CacheStatus.MISS
    assert second_http.calls == 1


async def test_concurrent_cache_misses_use_one_in_process_refresh() -> None:
    response = _http_response(
        {
            "price": "12.0",
            "source_timestamp": datetime(2026, 7, 23, 12, 0, tzinfo=UTC),
        }
    )
    http = BlockingHttpClient(response)
    cache = MemoryProviderCache()
    manager = _manager(http, cache)

    first = asyncio.create_task(manager.fetch(FixtureAdapter(), _request()))
    await http.started.wait()
    second = asyncio.create_task(manager.fetch(FixtureAdapter(), _request()))
    await asyncio.sleep(0)
    http.release.set()
    first_result, second_result = await asyncio.gather(first, second)

    assert first_result.data == second_result.data
    assert http.calls == 1
    assert cache.writes == 1
    assert {
        first_result.meta.cache_status,
        second_result.meta.cache_status,
    } == {CacheStatus.MISS, CacheStatus.HIT}
