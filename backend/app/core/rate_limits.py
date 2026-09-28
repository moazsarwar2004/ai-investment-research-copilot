"""Redis-first authentication throttling with a safe process-local fallback."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from backend.app.cache import RedisCache
from backend.app.core.config import Settings
from backend.app.core.exceptions import RateLimitExceededError


class FixedWindowRateLimiter:
    """Redis-first fixed-window limiter with a bounded local fallback."""

    def __init__(
        self,
        *,
        limit: int,
        window_seconds: int,
        redis_cache: RedisCache | None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if limit <= 0 or window_seconds <= 0:
            raise ValueError("rate limit and window must be positive")
        self._limit = limit
        self._window_seconds = window_seconds
        self._redis_cache = redis_cache
        self._clock = clock or (lambda: datetime.now(UTC))
        self._local: dict[str, tuple[int, datetime]] = {}
        self._lock = asyncio.Lock()

    async def check(self, key: str) -> None:
        """Consume one attempt and raise a typed 429 with safe retry timing."""
        if self._redis_cache is not None:
            remote = await self._redis_cache.consume_rate_limit(
                key,
                limit=self._limit,
                window_seconds=self._window_seconds,
            )
            if remote is not None:
                allowed, retry_after = remote
                if not allowed:
                    raise RateLimitExceededError(retry_after)
                return

        now = self._clock().astimezone(UTC)
        async with self._lock:
            if key not in self._local and len(self._local) >= 10_000:
                self._local = {
                    item_key: value
                    for item_key, value in self._local.items()
                    if value[1] > now
                }
                if len(self._local) >= 10_000:
                    raise RateLimitExceededError(self._window_seconds)
            count, expires_at = self._local.get(
                key, (0, now + timedelta(seconds=self._window_seconds))
            )
            if now >= expires_at:
                count = 0
                expires_at = now + timedelta(seconds=self._window_seconds)
            count += 1
            self._local[key] = (count, expires_at)
        if count > self._limit:
            retry_after = math.ceil((expires_at - now).total_seconds())
            raise RateLimitExceededError(retry_after)


class AuthRateLimiter(FixedWindowRateLimiter):
    """Enforce the strict Phase 3 IP+identity authentication budget."""

    def __init__(
        self,
        settings: Settings,
        redis_cache: RedisCache | None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(
            limit=settings.auth_rate_limit_attempts,
            window_seconds=settings.auth_rate_limit_window_seconds,
            redis_cache=redis_cache,
            clock=clock,
        )


class ApiRateLimiter(FixedWindowRateLimiter):
    """Bound total API work per trusted client address for the pilot."""

    def __init__(self, settings: Settings, redis_cache: RedisCache | None) -> None:
        super().__init__(
            limit=settings.api_rate_limit_requests,
            window_seconds=settings.api_rate_limit_window_seconds,
            redis_cache=redis_cache,
        )


__all__ = ["ApiRateLimiter", "AuthRateLimiter", "FixedWindowRateLimiter"]
