"""Cache freshness, key stability, and Redis-loss fallback tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from backend.app.cache import CacheStatus, RedisCache, build_cache_key


class FakeRedis:
    """Small async Redis double that preserves serialized values in memory."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.unavailable = False
        self.closed = False

    def _require_available(self) -> None:
        if self.unavailable:
            raise RedisConnectionError("test Redis unavailable")

    async def ping(self) -> bool:
        self._require_available()
        return True

    async def get(self, key: str) -> str | None:
        self._require_available()
        return self.values.get(key)

    async def set(self, key: str, value: str, **_: Any) -> bool:
        self._require_available()
        if _.get("nx") and key in self.values:
            return False
        self.values[key] = value
        return True

    async def delete(self, key: str) -> int:
        self._require_available()
        return int(self.values.pop(key, None) is not None)

    async def eval(
        self,
        script: str,
        number_of_keys: int,
        key: str,
        *arguments: object,
    ) -> int:
        self._require_available()
        if "GET" in script and arguments and self.values.get(key) == arguments[0]:
            return await self.delete(key)
        return 0

    async def aclose(self) -> None:
        self.closed = True


def _cache(backend: FakeRedis, clock: list[datetime]) -> RedisCache:
    return RedisCache(
        cast(Redis, backend),
        key_prefix="copilot:v1",
        clock=lambda: clock[0],
    )


def test_cache_key_is_canonical_and_parameter_order_independent() -> None:
    first = build_cache_key(
        provider=" Binance ",
        operation="Ticker",
        asset="BTC/USDT",
        interval="1m",
        parameters={"limit": 100, "market": "spot"},
    )
    second = build_cache_key(
        provider="binance",
        operation="ticker",
        asset="btc/usdt",
        interval="1m",
        parameters={"market": "spot", "limit": 100},
    )

    assert first == second
    assert first.startswith("binance:ticker:btc_usdt:1m:")


async def test_cache_transitions_from_hit_to_stale_to_hard_miss() -> None:
    backend = FakeRedis()
    clock = [datetime(2026, 7, 15, 12, 0, tzinfo=UTC)]
    cache = _cache(backend, clock)

    written = await cache.write(
        "binance:ticker:btcusdt:1m:abc",
        {"price": "65000.00"},
        soft_ttl_seconds=10,
        hard_ttl_seconds=20,
    )
    fresh = await cache.read("binance:ticker:btcusdt:1m:abc")

    clock[0] += timedelta(seconds=10)
    stale = await cache.read("binance:ticker:btcusdt:1m:abc")

    clock[0] += timedelta(seconds=10)
    expired = await cache.read("binance:ticker:btcusdt:1m:abc")

    assert written is True
    assert fresh.status is CacheStatus.HIT
    assert fresh.value == {"price": "65000.00"}
    assert stale.status is CacheStatus.STALE
    assert stale.warning == "cache_entry_stale"
    assert expired.status is CacheStatus.MISS
    assert expired.value is None
    assert expired.warning == "cache_entry_expired"


async def test_redis_loss_returns_bypass_and_never_breaks_primary_flow() -> None:
    backend = FakeRedis()
    backend.unavailable = True
    clock = [datetime(2026, 7, 15, 12, 0, tzinfo=UTC)]
    cache = _cache(backend, clock)

    read = await cache.read("provider:operation:asset:none:abc")
    written = await cache.write(
        "provider:operation:asset:none:abc",
        {"available_from_source": True},
        soft_ttl_seconds=5,
        hard_ttl_seconds=10,
    )
    deleted = await cache.delete("provider:operation:asset:none:abc")
    lock = await cache.acquire_lock(
        "provider:operation:asset:none:abc",
        ttl_seconds=5,
    )

    assert read.status is CacheStatus.BYPASS
    assert read.warning == "cache_unavailable"
    assert written is False
    assert deleted is False
    assert lock.status.value == "bypass"
    assert await cache.ping() is False


async def test_invalid_cache_entry_is_evicted_as_a_miss() -> None:
    backend = FakeRedis()
    clock = [datetime(2026, 7, 15, 12, 0, tzinfo=UTC)]
    cache = _cache(backend, clock)
    backend.values["copilot:v1:invalid:entry"] = "not-json"

    result = await cache.read("invalid:entry")

    assert result.status is CacheStatus.MISS
    assert result.warning == "cache_entry_invalid"
    assert backend.values == {}


async def test_cache_rejects_inverted_ttl_values() -> None:
    backend = FakeRedis()
    clock = [datetime(2026, 7, 15, 12, 0, tzinfo=UTC)]
    cache = _cache(backend, clock)

    with pytest.raises(ValueError, match="soft TTL"):
        await cache.write(
            "provider:operation:asset:none:abc",
            {},
            soft_ttl_seconds=20,
            hard_ttl_seconds=10,
        )


async def test_cache_lock_is_token_owned_and_reports_contention() -> None:
    backend = FakeRedis()
    clock = [datetime(2026, 7, 15, 12, 0, tzinfo=UTC)]
    cache = _cache(backend, clock)

    acquired = await cache.acquire_lock("provider:quote:btc", ttl_seconds=5)
    busy = await cache.acquire_lock("provider:quote:btc", ttl_seconds=5)

    assert acquired.status.value == "acquired"
    assert acquired.token is not None
    assert busy.status.value == "busy"
    assert await cache.release_lock("provider:quote:btc", "wrong-token") is False
    assert await cache.release_lock("provider:quote:btc", acquired.token) is True
