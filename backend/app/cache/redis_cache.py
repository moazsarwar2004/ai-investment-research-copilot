"""Versioned JSON caching with soft/hard TTL and Redis-loss fallback."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import cast

from redis.asyncio import Redis
from redis.exceptions import RedisError

from backend.app.core.config import Settings
from backend.app.core.logger import get_logger

logger = get_logger(__name__)

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]

_COMPONENT_PATTERN = re.compile(r"[^a-z0-9._-]+")
_CACHE_SCHEMA_VERSION = 1


class CacheStatus(StrEnum):
    """Stable cache states used by provider response metadata."""

    MISS = "miss"
    HIT = "hit"
    STALE = "stale"
    BYPASS = "bypass"


class CacheLockStatus(StrEnum):
    """Outcome of a best-effort distributed cache-lock attempt."""

    ACQUIRED = "acquired"
    BUSY = "busy"
    BYPASS = "bypass"


@dataclass(frozen=True, slots=True)
class CacheLock:
    """Opaque lock ownership returned by RedisCache."""

    status: CacheLockStatus
    token: str | None = None


@dataclass(frozen=True, slots=True)
class CacheRead:
    """A cache read plus enough timing data to explain freshness."""

    value: JsonValue | None
    status: CacheStatus
    created_at: datetime | None = None
    soft_expires_at: datetime | None = None
    hard_expires_at: datetime | None = None
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class _CacheEnvelope:
    value: JsonValue
    created_at: datetime
    soft_expires_at: datetime
    hard_expires_at: datetime


def _component(value: str, *, field: str) -> str:
    normalized = _COMPONENT_PATTERN.sub("_", value.strip().lower()).strip("_")
    if not normalized:
        raise ValueError(f"{field} must contain a cache-key character")
    return normalized[:80]


def build_cache_key(
    *,
    provider: str,
    operation: str,
    asset: str,
    interval: str | None = None,
    parameters: Mapping[str, JsonScalar] | None = None,
) -> str:
    """Build a stable non-secret key from normalized provider request inputs."""
    components = [
        _component(provider, field="provider"),
        _component(operation, field="operation"),
        _component(asset, field="asset"),
        _component(interval or "none", field="interval"),
    ]
    canonical_parameters = json.dumps(
        dict(parameters or {}),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    parameter_hash = hashlib.sha256(canonical_parameters.encode("utf-8")).hexdigest()[
        :16
    ]
    return ":".join([*components, parameter_hash])


def _is_json_value(value: object) -> bool:
    if value is None or isinstance(value, str | bool | int | float):
        return True
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _is_json_value(item) for key, item in value.items()
        )
    return False


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("cache timestamp must be a string")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("cache timestamp must include a timezone")
    return parsed.astimezone(UTC)


def _decode_envelope(raw: str) -> _CacheEnvelope:
    payload: object = json.loads(raw)
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("unsupported cache envelope")
    value = payload.get("value")
    if not _is_json_value(value):
        raise ValueError("cache value is not JSON-compatible")
    envelope = _CacheEnvelope(
        value=cast(JsonValue, value),
        created_at=_parse_timestamp(payload.get("created_at")),
        soft_expires_at=_parse_timestamp(payload.get("soft_expires_at")),
        hard_expires_at=_parse_timestamp(payload.get("hard_expires_at")),
    )
    if not (
        envelope.created_at <= envelope.soft_expires_at <= envelope.hard_expires_at
    ):
        raise ValueError("cache expiry ordering is invalid")
    return envelope


class RedisCache:
    """Own the async Redis client and convert outages into cache bypasses."""

    def __init__(
        self,
        client: Redis,
        *,
        key_prefix: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._key_prefix = key_prefix
        self._clock = clock or (lambda: datetime.now(UTC))

    @classmethod
    def from_settings(cls, settings: Settings) -> RedisCache:
        """Create a bounded async client without opening a connection eagerly."""
        client = Redis.from_url(
            settings.redis_dsn,
            decode_responses=True,
            socket_connect_timeout=settings.redis_connect_timeout_seconds,
            socket_timeout=settings.redis_socket_timeout_seconds,
            health_check_interval=settings.redis_health_check_interval_seconds,
        )
        return cls(client, key_prefix=settings.redis_key_prefix)

    def _qualified_key(self, key: str) -> str:
        components = key.split(":")
        normalized = ":".join(
            _component(component, field="key") for component in components
        )
        return f"{self._key_prefix}:{normalized}"

    async def ping(self) -> bool:
        """Report Redis availability without exposing connection details."""
        try:
            return bool(await self._client.ping())
        except (RedisError, OSError, TimeoutError) as error:
            logger.warning(
                "redis_probe_failed",
                extra={"exception_type": type(error).__name__},
            )
            return False

    async def read(self, key: str) -> CacheRead:
        """Return fresh/stale state, or bypass cleanly when Redis is unavailable."""
        qualified_key = self._qualified_key(key)
        try:
            raw = await self._client.get(qualified_key)
        except (RedisError, OSError, TimeoutError) as error:
            logger.warning(
                "cache_read_bypassed",
                extra={"exception_type": type(error).__name__},
            )
            return CacheRead(
                value=None,
                status=CacheStatus.BYPASS,
                warning="cache_unavailable",
            )

        if raw is None:
            return CacheRead(value=None, status=CacheStatus.MISS)
        if not isinstance(raw, str):
            return CacheRead(
                value=None,
                status=CacheStatus.MISS,
                warning="cache_entry_invalid",
            )

        try:
            envelope = _decode_envelope(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            await self._best_effort_delete(qualified_key)
            return CacheRead(
                value=None,
                status=CacheStatus.MISS,
                warning="cache_entry_invalid",
            )

        now = self._clock().astimezone(UTC)
        if now >= envelope.hard_expires_at:
            await self._best_effort_delete(qualified_key)
            return CacheRead(
                value=None,
                status=CacheStatus.MISS,
                warning="cache_entry_expired",
            )
        status = (
            CacheStatus.STALE if now >= envelope.soft_expires_at else CacheStatus.HIT
        )
        return CacheRead(
            value=envelope.value,
            status=status,
            created_at=envelope.created_at,
            soft_expires_at=envelope.soft_expires_at,
            hard_expires_at=envelope.hard_expires_at,
            warning="cache_entry_stale" if status is CacheStatus.STALE else None,
        )

    async def write(
        self,
        key: str,
        value: JsonValue,
        *,
        soft_ttl_seconds: int,
        hard_ttl_seconds: int,
    ) -> bool:
        """Write one envelope, using Redis expiry as the hard safety boundary."""
        if soft_ttl_seconds <= 0 or hard_ttl_seconds < soft_ttl_seconds:
            raise ValueError("TTL values must satisfy 0 < soft TTL <= hard TTL")
        if not _is_json_value(value):
            raise TypeError("cache value must be JSON-compatible")

        created_at = self._clock().astimezone(UTC)
        payload = json.dumps(
            {
                "schema_version": _CACHE_SCHEMA_VERSION,
                "value": value,
                "created_at": created_at.isoformat(),
                "soft_expires_at": (
                    created_at + timedelta(seconds=soft_ttl_seconds)
                ).isoformat(),
                "hard_expires_at": (
                    created_at + timedelta(seconds=hard_ttl_seconds)
                ).isoformat(),
            },
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        try:
            result = await self._client.set(
                self._qualified_key(key),
                payload,
                ex=hard_ttl_seconds,
            )
            return bool(result)
        except (RedisError, OSError, TimeoutError) as error:
            logger.warning(
                "cache_write_bypassed",
                extra={"exception_type": type(error).__name__},
            )
            return False

    async def delete(self, key: str) -> bool:
        """Delete a cache value, treating an outage as a harmless no-op."""
        try:
            return bool(await self._client.delete(self._qualified_key(key)))
        except (RedisError, OSError, TimeoutError) as error:
            logger.warning(
                "cache_delete_bypassed",
                extra={"exception_type": type(error).__name__},
            )
            return False

    async def acquire_lock(self, key: str, *, ttl_seconds: int) -> CacheLock:
        """Acquire a token-owned distributed lock without blocking the caller."""
        if ttl_seconds <= 0:
            raise ValueError("lock TTL must be positive")
        token = secrets.token_urlsafe(24)
        try:
            acquired = await self._client.set(
                self._qualified_key(f"lock:{key}"),
                token,
                ex=ttl_seconds,
                nx=True,
            )
        except (RedisError, OSError, TimeoutError) as error:
            logger.warning(
                "cache_lock_bypassed",
                extra={"exception_type": type(error).__name__},
            )
            return CacheLock(status=CacheLockStatus.BYPASS)
        if not acquired:
            return CacheLock(status=CacheLockStatus.BUSY)
        return CacheLock(status=CacheLockStatus.ACQUIRED, token=token)

    async def release_lock(self, key: str, token: str) -> bool:
        """Release a distributed lock only when the ownership token matches."""
        if not token:
            return False
        script = """
        if redis.call('GET', KEYS[1]) == ARGV[1] then
            return redis.call('DEL', KEYS[1])
        end
        return 0
        """
        try:
            released = await self._client.eval(
                script,
                1,
                self._qualified_key(f"lock:{key}"),
                token,
            )
            return bool(released)
        except (RedisError, OSError, TimeoutError, TypeError, ValueError) as error:
            logger.warning(
                "cache_lock_release_bypassed",
                extra={"exception_type": type(error).__name__},
            )
            return False

    async def consume_rate_limit(
        self, key: str, *, limit: int, window_seconds: int
    ) -> tuple[bool, int] | None:
        """Atomically consume a fixed-window budget, or defer to local fallback."""
        script = """
        local count = redis.call('INCR', KEYS[1])
        if count == 1 then
            redis.call('EXPIRE', KEYS[1], ARGV[1])
        end
        local ttl = redis.call('TTL', KEYS[1])
        return {count, ttl}
        """
        try:
            result = await self._client.eval(
                script,
                1,
                self._qualified_key(f"rate:{key}"),
                window_seconds,
            )
            if not isinstance(result, list | tuple) or len(result) != 2:
                return None
            count, ttl = int(result[0]), int(result[1])
            return count <= limit, max(1, ttl)
        except (RedisError, OSError, TimeoutError, TypeError, ValueError) as error:
            logger.warning(
                "rate_limit_redis_bypassed",
                extra={"exception_type": type(error).__name__},
            )
            return None

    async def _best_effort_delete(self, qualified_key: str) -> None:
        try:
            await self._client.delete(qualified_key)
        except (RedisError, OSError, TimeoutError):
            return

    async def close(self) -> None:
        """Close Redis connections during application shutdown."""
        await self._client.aclose()
