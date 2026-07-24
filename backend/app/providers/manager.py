"""Cache-first provider orchestration with quotas, locks, and stale fallback."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from backend.app.cache import (
    CacheLock,
    CacheLockStatus,
    CacheRead,
    CacheStatus,
    JsonValue,
    build_cache_key,
)
from backend.app.core.config import Settings
from backend.app.core.logger import get_logger
from backend.app.providers.adapters import ProviderAdapter
from backend.app.providers.circuit_breaker import CircuitBreakerRegistry
from backend.app.providers.exceptions import (
    ProviderCircuitOpenError,
    ProviderConfigurationError,
    ProviderError,
    ProviderQuotaExceededError,
    ProviderRefreshInProgressError,
    ProviderSchemaError,
    ProviderUnavailableError,
)
from backend.app.providers.http_client import ProviderHttpClient
from backend.app.providers.models import (
    DelayClass,
    Freshness,
    ProviderMeta,
    ProviderProvenance,
    ProviderRequest,
    ProviderResponse,
    ProviderWarning,
)
from backend.app.providers.quota import ProviderQuotaManager

logger = get_logger(__name__)

DataT = TypeVar("DataT", bound=BaseModel)


class ProviderCache(Protocol):
    """Cache behavior required by the provider manager."""

    async def read(self, key: str) -> CacheRead: ...

    async def write(
        self,
        key: str,
        value: JsonValue,
        *,
        soft_ttl_seconds: int,
        hard_ttl_seconds: int,
    ) -> bool: ...

    async def delete(self, key: str) -> bool: ...

    async def acquire_lock(self, key: str, *, ttl_seconds: int) -> CacheLock: ...

    async def release_lock(self, key: str, token: str) -> bool: ...


class ProviderManager:
    """Execute normalized provider reads without exposing vendor payloads."""

    def __init__(
        self,
        *,
        http_client: ProviderHttpClient,
        cache: ProviderCache,
        quota_manager: ProviderQuotaManager,
        circuits: CircuitBreakerRegistry,
        cache_lock_ttl_seconds: int,
        cache_lock_wait_seconds: float,
        cache_lock_poll_seconds: float,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._http_client = http_client
        self._cache = cache
        self._quota_manager = quota_manager
        self._circuits = circuits
        self._cache_lock_ttl_seconds = cache_lock_ttl_seconds
        self._cache_lock_wait_seconds = cache_lock_wait_seconds
        self._cache_lock_poll_seconds = cache_lock_poll_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sleep = sleep
        self._local_locks: dict[str, asyncio.Lock] = {}

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        http_client: ProviderHttpClient,
        cache: ProviderCache,
        quota_manager: ProviderQuotaManager | None = None,
    ) -> ProviderManager:
        return cls(
            http_client=http_client,
            cache=cache,
            quota_manager=quota_manager or ProviderQuotaManager(),
            circuits=CircuitBreakerRegistry(
                failure_threshold=settings.provider_circuit_failure_threshold,
                recovery_timeout_seconds=settings.provider_circuit_recovery_seconds,
            ),
            cache_lock_ttl_seconds=settings.provider_cache_lock_ttl_seconds,
            cache_lock_wait_seconds=settings.provider_cache_lock_wait_seconds,
            cache_lock_poll_seconds=settings.provider_cache_lock_poll_seconds,
        )

    async def fetch(
        self,
        adapter: ProviderAdapter[DataT],
        request: ProviderRequest,
    ) -> ProviderResponse[DataT]:
        """Return fresh normalized data or a clearly labelled stale fallback."""
        cache_key = build_cache_key(
            provider=adapter.provider,
            operation=request.operation,
            asset=request.asset.cache_identity,
            interval=request.interval,
            parameters=request.parameters,
        )
        initial = await self._read_cached(cache_key, adapter)
        if initial is not None and initial[1] is CacheStatus.HIT:
            return self._with_cache_state(initial[0], CacheStatus.HIT)
        stale = initial[0] if initial is not None else None
        initial_cache_status = (
            CacheStatus.BYPASS
            if initial is None
            and (await self._cache_status_without_value(cache_key))
            is CacheStatus.BYPASS
            else CacheStatus.MISS
        )

        local_lock = self._local_locks.setdefault(cache_key, asyncio.Lock())
        async with local_lock:
            second = await self._read_cached(cache_key, adapter)
            if second is not None and second[1] is CacheStatus.HIT:
                return self._with_cache_state(second[0], CacheStatus.HIT)
            if second is not None:
                stale = second[0]

            distributed_lock = await self._cache.acquire_lock(
                cache_key,
                ttl_seconds=self._cache_lock_ttl_seconds,
            )
            if distributed_lock.status is CacheLockStatus.BUSY:
                waited = await self._wait_for_refresh(cache_key, adapter)
                if waited is not None:
                    if waited[1] is CacheStatus.HIT:
                        return self._with_cache_state(waited[0], CacheStatus.HIT)
                    stale = waited[0]
                error = ProviderRefreshInProgressError(
                    "Another process is refreshing this provider value."
                )
                if stale is not None:
                    return self._stale_fallback(stale, error)
                raise ProviderUnavailableError(cause_code=error.code) from error

            try:
                return await self._refresh(
                    adapter=adapter,
                    request=request,
                    cache_key=cache_key,
                    cache_status=(
                        CacheStatus.BYPASS
                        if distributed_lock.status is CacheLockStatus.BYPASS
                        else initial_cache_status
                    ),
                )
            except ProviderError as error:
                if stale is not None:
                    return self._stale_fallback(stale, error)
                if isinstance(error, ProviderUnavailableError):
                    raise
                raise ProviderUnavailableError(cause_code=error.code) from error
            finally:
                if (
                    distributed_lock.status is CacheLockStatus.ACQUIRED
                    and distributed_lock.token is not None
                ):
                    await self._cache.release_lock(
                        cache_key,
                        distributed_lock.token,
                    )

    async def _refresh(
        self,
        *,
        adapter: ProviderAdapter[DataT],
        request: ProviderRequest,
        cache_key: str,
        cache_status: CacheStatus,
    ) -> ProviderResponse[DataT]:
        breaker = self._circuits.for_provider(adapter.provider)
        try:
            breaker.allow_request()
            self._quota_manager.reserve(
                adapter.provider,
                weight=request.weight,
                kind=request.kind,
            )
            try:
                outbound = adapter.build_request(request)
            except (ValidationError, TypeError, ValueError, KeyError) as error:
                raise ProviderConfigurationError(
                    "The adapter could not build a valid outbound request."
                ) from error

            def reserve_retry(attempt: int) -> None:
                if attempt > 1:
                    self._quota_manager.reserve(
                        adapter.provider,
                        weight=request.weight,
                        kind=request.kind,
                    )

            http_response = await self._http_client.request(
                provider=adapter.provider,
                operation=request.operation,
                outbound=outbound,
                allowed_hosts=adapter.allowed_hosts,
                on_attempt=reserve_retry,
            )
            try:
                reported_weight = adapter.reported_used_weight(http_response)
            except (TypeError, ValueError, KeyError) as error:
                raise ProviderSchemaError(
                    "The provider usage headers are invalid."
                ) from error
            if reported_weight is not None:
                self._quota_manager.reconcile_used_weight(
                    adapter.provider,
                    reported_weight,
                )
            try:
                normalized = adapter.normalize(http_response, request)
            except (ValidationError, TypeError, ValueError, KeyError) as error:
                raise ProviderSchemaError(
                    "The provider payload no longer matches the adapter schema."
                ) from error
        except ProviderCircuitOpenError:
            raise
        except (ProviderConfigurationError, ProviderQuotaExceededError):
            breaker.cancel_request()
            raise
        except ProviderError:
            breaker.record_failure()
            snapshot = breaker.snapshot()
            logger.warning(
                "provider_request_failed",
                extra={
                    "provider": adapter.provider,
                    "operation": request.operation,
                    "circuit_state": snapshot.state.value,
                },
            )
            raise

        breaker.record_success()
        now = self._clock().astimezone(UTC)
        freshness = (
            Freshness.LIVE
            if normalized.delay_class is DelayClass.LIVE
            else Freshness.DELAYED
        )
        response = ProviderResponse[DataT](
            data=normalized.data,
            meta=ProviderMeta(
                source=adapter.provider,
                source_timestamp=normalized.source_timestamp,
                fetched_at=http_response.fetched_at,
                cache_status=cache_status,
                freshness=freshness,
                staleness_seconds=self._staleness_seconds(
                    now,
                    normalized.source_timestamp or http_response.fetched_at,
                ),
                partial=normalized.partial,
                warnings=normalized.warnings,
                delay_class=normalized.delay_class,
                provenance=ProviderProvenance(
                    provider=adapter.provider,
                    operation=request.operation,
                    source_url=http_response.source_url,
                    provider_request_id=http_response.provider_request_id,
                    raw_payload_sha256=http_response.raw_payload_sha256,
                    schema_version=adapter.schema_version,
                    terms_review_version=adapter.terms_review_version,
                    attribution=adapter.attribution,
                ),
            ),
        )
        cache_written = await self._cache.write(
            cache_key,
            response.as_cache_value(),
            soft_ttl_seconds=request.soft_ttl_seconds,
            hard_ttl_seconds=request.hard_ttl_seconds,
        )
        if not cache_written:
            warning = ProviderWarning(
                code="cache_write_bypassed",
                message="The normalized result could not be cached.",
            )
            response = response.model_copy(
                update={
                    "meta": response.meta.model_copy(
                        update={
                            "cache_status": CacheStatus.BYPASS,
                            "warnings": [*response.meta.warnings, warning],
                        }
                    )
                }
            )
        logger.info(
            "provider_request_succeeded",
            extra={
                "provider": adapter.provider,
                "operation": request.operation,
                "attempt": http_response.attempts,
                "retry_count": http_response.attempts - 1,
                "cache_status": response.meta.cache_status.value,
                "circuit_state": breaker.snapshot().state.value,
            },
        )
        return response

    async def _read_cached(
        self,
        key: str,
        adapter: ProviderAdapter[DataT],
    ) -> tuple[ProviderResponse[DataT], CacheStatus] | None:
        cached = await self._cache.read(key)
        if cached.value is None or cached.status not in {
            CacheStatus.HIT,
            CacheStatus.STALE,
        }:
            return None
        if not isinstance(cached.value, dict):
            await self._cache.delete(key)
            return None
        try:
            data = adapter.validate_cached_data(cached.value.get("data"))
            meta = ProviderMeta.model_validate(cached.value.get("meta"))
        except (ProviderSchemaError, ValidationError, TypeError):
            await self._cache.delete(key)
            return None
        if (
            meta.source != adapter.provider
            or meta.provenance.provider != adapter.provider
            or meta.provenance.schema_version != adapter.schema_version
        ):
            await self._cache.delete(key)
            return None
        return ProviderResponse[DataT](data=data, meta=meta), cached.status

    async def _cache_status_without_value(self, key: str) -> CacheStatus:
        """Preserve cache outage metadata without coupling it to typed cache reads."""
        read = await self._cache.read(key)
        return read.status

    async def _wait_for_refresh(
        self,
        key: str,
        adapter: ProviderAdapter[DataT],
    ) -> tuple[ProviderResponse[DataT], CacheStatus] | None:
        waited = 0.0
        while waited < self._cache_lock_wait_seconds:
            delay = min(
                self._cache_lock_poll_seconds,
                self._cache_lock_wait_seconds - waited,
            )
            if delay <= 0:
                break
            await self._sleep(delay)
            waited += delay
            cached = await self._read_cached(key, adapter)
            if cached is not None and cached[1] is CacheStatus.HIT:
                return cached
        return await self._read_cached(key, adapter)

    def _with_cache_state(
        self,
        response: ProviderResponse[DataT],
        status: CacheStatus,
    ) -> ProviderResponse[DataT]:
        now = self._clock().astimezone(UTC)
        meta = response.meta.model_copy(
            update={
                "cache_status": status,
                "freshness": (
                    Freshness.CACHED if status is CacheStatus.HIT else Freshness.STALE
                ),
                "staleness_seconds": self._staleness_seconds(
                    now,
                    response.meta.source_timestamp or response.meta.fetched_at,
                ),
            }
        )
        return response.model_copy(update={"meta": meta})

    def _stale_fallback(
        self,
        response: ProviderResponse[DataT],
        cause: ProviderError,
    ) -> ProviderResponse[DataT]:
        stale = self._with_cache_state(response, CacheStatus.STALE)
        existing_codes = {warning.code for warning in stale.meta.warnings}
        warnings = list(stale.meta.warnings)
        if "stale_cache_fallback" not in existing_codes:
            warnings.append(
                ProviderWarning(
                    code="stale_cache_fallback",
                    message=(
                        "A stale cached value is shown because the provider "
                        "refresh failed."
                    ),
                )
            )
        if cause.code not in existing_codes:
            warnings.append(
                ProviderWarning(
                    code=cause.code,
                    message="The provider refresh could not be completed.",
                )
            )
        meta = stale.meta.model_copy(update={"warnings": warnings})
        logger.warning(
            "provider_stale_fallback",
            extra={
                "provider": stale.meta.source,
                "operation": stale.meta.provenance.operation,
                "cache_status": CacheStatus.STALE.value,
            },
        )
        return stale.model_copy(update={"meta": meta})

    @staticmethod
    def _staleness_seconds(now: datetime, source_time: datetime) -> int:
        return max(0, int((now - source_time.astimezone(UTC)).total_seconds()))
