"""Read-only Binance USD-M Futures research use cases."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable

from pydantic import BaseModel, ConfigDict, Field

from backend.app.analytics.binance_futures import (
    FuturesAnalytics,
    FuturesRisk,
    analyze_futures,
    build_futures_risk,
)
from backend.app.cache import CacheStatus
from backend.app.core.exceptions import (
    ApplicationValidationError,
    ResourceNotFoundError,
)
from backend.app.providers import (
    AssetType,
    CanonicalAsset,
    Freshness,
    ProviderManager,
    ProviderMeta,
    ProviderProvenance,
    ProviderRequest,
    ProviderResponse,
    ProviderUnavailableError,
    ProviderWarning,
)
from backend.app.providers.adapters import ProviderAdapter
from backend.app.providers.binance_futures import (
    BINANCE_FUTURES_PROVIDER,
    AccountRatioData,
    BinanceFuturesAccountRatioAdapter,
    BinanceFuturesBasisAdapter,
    BinanceFuturesCurrentOpenInterestAdapter,
    BinanceFuturesFundingAdapter,
    BinanceFuturesMarketAdapter,
    BinanceFuturesOpenInterestHistoryAdapter,
    BinanceFuturesSymbolsAdapter,
    BinanceFuturesTakerFlowAdapter,
    FuturesBasisData,
    FuturesFundingData,
    FuturesMarketData,
    FuturesOpenInterestData,
    FuturesPeriod,
    FuturesPositioningData,
    FuturesSymbolsData,
    OpenInterestCurrentData,
    OpenInterestHistoryData,
    TakerFlowData,
)
from backend.app.services.binance_spot_service import (
    AggregateProviderMeta,
    AnalyticsResponse,
)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class FuturesResearchData(_Model):
    symbol: str
    period: FuturesPeriod
    market: FuturesMarketData | None
    funding: FuturesFundingData | None
    open_interest: FuturesOpenInterestData | None
    basis: FuturesBasisData | None
    positioning: FuturesPositioningData | None
    analytics: FuturesAnalytics | None
    risk: FuturesRisk | None
    components: dict[str, ProviderMeta] = Field(default_factory=dict)
    leverage_warning: str = (
        "Leveraged futures can cause rapid liquidation and loss of all margin."
    )
    disclaimer: str = (
        "Public market research and education only; not personalized financial advice."
    )


def _symbol(value: str) -> str:
    normalized = value.strip().upper()
    if not 5 <= len(normalized) <= 20 or not normalized.isalnum():
        raise ApplicationValidationError(
            "Binance Futures symbols must contain 5-20 letters or digits."
        )
    return normalized


def _aggregate(
    metas: list[ProviderMeta], missing: list[str] | None = None
) -> AggregateProviderMeta:
    if not metas:
        raise ProviderUnavailableError(cause_code="provider_unavailable")
    missing = missing or []
    statuses = {item.cache_status for item in metas}
    if CacheStatus.STALE in statuses or any(
        item.freshness is Freshness.STALE for item in metas
    ):
        cache_status, freshness = CacheStatus.STALE, Freshness.STALE
    elif CacheStatus.BYPASS in statuses:
        cache_status, freshness = CacheStatus.BYPASS, Freshness.LIVE
    elif CacheStatus.MISS in statuses:
        cache_status, freshness = CacheStatus.MISS, Freshness.LIVE
    else:
        cache_status, freshness = CacheStatus.HIT, Freshness.CACHED
    timestamps = [item.source_timestamp for item in metas if item.source_timestamp]
    warnings: list[ProviderWarning] = []
    seen: set[str] = set()
    for meta in metas:
        for warning in meta.warnings:
            if warning.code not in seen:
                warnings.append(warning)
                seen.add(warning.code)
    for operation in missing:
        code = f"{operation}_unavailable".replace(".", "_")
        if code not in seen:
            warnings.append(
                ProviderWarning(
                    code=code,
                    message=f"The {operation} component is temporarily unavailable.",
                )
            )
            seen.add(code)
    sources: list[ProviderProvenance] = []
    source_ids: set[tuple[str, str]] = set()
    for meta in metas:
        identity = (meta.provenance.operation, meta.provenance.raw_payload_sha256)
        if identity not in source_ids:
            sources.append(meta.provenance)
            source_ids.add(identity)
    return AggregateProviderMeta(
        source=BINANCE_FUTURES_PROVIDER,
        source_timestamp=min(timestamps) if timestamps else None,
        fetched_at=max(item.fetched_at for item in metas),
        cache_status=cache_status,
        freshness=freshness,
        staleness_seconds=max(item.staleness_seconds for item in metas),
        partial=bool(missing) or any(item.partial for item in metas),
        warnings=warnings,
        sources=sources,
    )


async def _capture[DataT: BaseModel](
    operation: str, awaitable: Awaitable[ProviderResponse[DataT]]
) -> tuple[ProviderResponse[DataT] | None, str | None]:
    try:
        return await awaitable, None
    except ProviderUnavailableError:
        return None, operation


class BinanceFuturesService:
    """Fetch bounded public snapshots and derive evidence-linked risk."""

    def __init__(self, manager: ProviderManager, *, base_url: str) -> None:
        self._manager = manager
        self._symbols_adapter = BinanceFuturesSymbolsAdapter(base_url)
        self._market_adapter = BinanceFuturesMarketAdapter(base_url)
        self._funding_adapter = BinanceFuturesFundingAdapter(base_url)
        self._oi_current_adapter = BinanceFuturesCurrentOpenInterestAdapter(base_url)
        self._oi_history_adapter = BinanceFuturesOpenInterestHistoryAdapter(base_url)
        self._basis_adapter = BinanceFuturesBasisAdapter(base_url)
        self._accounts_adapter = BinanceFuturesAccountRatioAdapter(base_url)
        self._taker_adapter = BinanceFuturesTakerFlowAdapter(base_url)

    async def _fetch[DataT: BaseModel](
        self, adapter: ProviderAdapter[DataT], request: ProviderRequest
    ) -> ProviderResponse[DataT]:
        response = await self._manager.fetch(adapter, request)
        # Cached arrival time is not evidence that the upstream observation is new.
        if request.operation == "futures.symbols":
            return response
        period = request.interval or "1h"
        period_seconds = int(period[:-1]) * {"m": 60, "h": 3600, "d": 86400}[period[-1]]
        maximum_age = (
            86400
            if request.operation == "futures.funding"
            else (
                120
                if request.operation
                in {"futures.market", "futures.open_interest.current"}
                else 2 * period_seconds + 300
            )
        )
        if response.meta.staleness_seconds > maximum_age:
            response = response.model_copy(
                update={
                    "meta": response.meta.model_copy(
                        update={
                            "freshness": Freshness.STALE,
                            "warnings": [
                                *response.meta.warnings,
                                ProviderWarning(
                                    code="upstream_observation_old",
                                    message=(
                                        "The provider observation is older than its "
                                        "update window."
                                    ),
                                ),
                            ],
                        }
                    )
                }
            )
        return response

    @staticmethod
    def _asset(symbol: str) -> CanonicalAsset:
        return CanonicalAsset(asset_type=AssetType.BINANCE_FUTURES, key=symbol)

    async def symbols(self) -> ProviderResponse[FuturesSymbolsData]:
        return await self._fetch(
            self._symbols_adapter,
            ProviderRequest(
                operation="futures.symbols",
                asset=CanonicalAsset(
                    asset_type=AssetType.SYSTEM, key="futures-symbols"
                ),
                weight=1,
                soft_ttl_seconds=300,
                hard_ttl_seconds=3_600,
            ),
        )

    async def _require_symbol(self, symbol: str) -> str:
        normalized = _symbol(symbol)
        available = await self.symbols()
        if not any(item.symbol == normalized for item in available.data.symbols):
            raise ResourceNotFoundError(
                "The requested USD-M perpetual is not currently tradable."
            )
        return normalized

    async def _market(self, symbol: str) -> ProviderResponse[FuturesMarketData]:
        return await self._fetch(
            self._market_adapter,
            ProviderRequest(
                operation="futures.market",
                asset=self._asset(symbol),
                weight=1,
                soft_ttl_seconds=10,
                hard_ttl_seconds=30,
            ),
        )

    async def market(self, symbol: str) -> ProviderResponse[FuturesMarketData]:
        return await self._market(await self._require_symbol(symbol))

    async def _funding(
        self, symbol: str, limit: int
    ) -> ProviderResponse[FuturesFundingData]:
        return await self._fetch(
            self._funding_adapter,
            ProviderRequest(
                operation="futures.funding",
                asset=self._asset(symbol),
                parameters={"limit": limit},
                weight=1,
                soft_ttl_seconds=60,
                hard_ttl_seconds=300,
            ),
        )

    async def funding(
        self, symbol: str, limit: int
    ) -> ProviderResponse[FuturesFundingData]:
        return await self._funding(await self._require_symbol(symbol), limit)

    async def _oi_current(
        self, symbol: str
    ) -> ProviderResponse[OpenInterestCurrentData]:
        return await self._fetch(
            self._oi_current_adapter,
            ProviderRequest(
                operation="futures.open_interest.current",
                asset=self._asset(symbol),
                weight=1,
                soft_ttl_seconds=10,
                hard_ttl_seconds=30,
            ),
        )

    async def _oi_history(
        self, symbol: str, period: FuturesPeriod, limit: int
    ) -> ProviderResponse[OpenInterestHistoryData]:
        return await self._fetch(
            self._oi_history_adapter,
            ProviderRequest(
                operation="futures.open_interest.history",
                asset=self._asset(symbol),
                interval=period.value,
                parameters={"limit": limit},
                weight=1,
                soft_ttl_seconds=60,
                hard_ttl_seconds=300,
            ),
        )

    @staticmethod
    def _combine_oi(
        current: ProviderResponse[OpenInterestCurrentData] | None,
        history: ProviderResponse[OpenInterestHistoryData] | None,
        symbol: str,
        period: FuturesPeriod,
    ) -> FuturesOpenInterestData:
        return FuturesOpenInterestData(
            symbol=symbol,
            current_open_interest=current.data.open_interest if current else None,
            current_timestamp=current.data.timestamp if current else None,
            period=period,
            history=history.data.points if history else [],
        )

    async def open_interest(
        self, symbol: str, period: FuturesPeriod, limit: int
    ) -> AnalyticsResponse[FuturesOpenInterestData]:
        normalized = await self._require_symbol(symbol)
        current, history = await asyncio.gather(
            self._oi_current(normalized), self._oi_history(normalized, period, limit)
        )
        return AnalyticsResponse(
            data=self._combine_oi(current, history, normalized, period),
            meta=_aggregate([current.meta, history.meta]),
        )

    async def _basis(
        self, symbol: str, period: FuturesPeriod, limit: int
    ) -> ProviderResponse[FuturesBasisData]:
        return await self._fetch(
            self._basis_adapter,
            ProviderRequest(
                operation="futures.basis",
                asset=self._asset(symbol),
                interval=period.value,
                parameters={"limit": limit},
                weight=1,
                soft_ttl_seconds=60,
                hard_ttl_seconds=300,
            ),
        )

    async def basis(
        self, symbol: str, period: FuturesPeriod, limit: int
    ) -> ProviderResponse[FuturesBasisData]:
        return await self._basis(await self._require_symbol(symbol), period, limit)

    async def _accounts(
        self, symbol: str, period: FuturesPeriod, limit: int
    ) -> ProviderResponse[AccountRatioData]:
        return await self._fetch(
            self._accounts_adapter,
            ProviderRequest(
                operation="futures.positioning.accounts",
                asset=self._asset(symbol),
                interval=period.value,
                parameters={"limit": limit},
                weight=1,
                soft_ttl_seconds=60,
                hard_ttl_seconds=300,
            ),
        )

    async def _taker(
        self, symbol: str, period: FuturesPeriod, limit: int
    ) -> ProviderResponse[TakerFlowData]:
        return await self._fetch(
            self._taker_adapter,
            ProviderRequest(
                operation="futures.positioning.taker",
                asset=self._asset(symbol),
                interval=period.value,
                parameters={"limit": limit},
                weight=1,
                soft_ttl_seconds=60,
                hard_ttl_seconds=300,
            ),
        )

    @staticmethod
    def _combine_positioning(
        accounts: ProviderResponse[AccountRatioData] | None,
        taker: ProviderResponse[TakerFlowData] | None,
        symbol: str,
        period: FuturesPeriod,
    ) -> FuturesPositioningData:
        return FuturesPositioningData(
            symbol=symbol,
            period=period,
            account_ratio=accounts.data.points if accounts else [],
            taker_flow=taker.data.points if taker else [],
        )

    async def positioning(
        self, symbol: str, period: FuturesPeriod, limit: int
    ) -> AnalyticsResponse[FuturesPositioningData]:
        normalized = await self._require_symbol(symbol)
        accounts, taker = await asyncio.gather(
            self._accounts(normalized, period, limit),
            self._taker(normalized, period, limit),
        )
        return AnalyticsResponse(
            data=self._combine_positioning(accounts, taker, normalized, period),
            meta=_aggregate([accounts.meta, taker.meta]),
        )

    async def research(
        self, symbol: str, period: FuturesPeriod, limit: int
    ) -> AnalyticsResponse[FuturesResearchData]:
        normalized = await self._require_symbol(symbol)
        results = await asyncio.gather(
            _capture("market", self._market(normalized)),
            _capture("funding", self._funding(normalized, limit)),
            _capture("open_interest_current", self._oi_current(normalized)),
            _capture(
                "open_interest_history", self._oi_history(normalized, period, limit)
            ),
            asyncio.gather(
                _capture("basis", self._basis(normalized, period, limit)),
                _capture(
                    "positioning_accounts", self._accounts(normalized, period, limit)
                ),
                _capture("positioning_taker", self._taker(normalized, period, limit)),
            ),
        )
        all_results = (*results[:4], *results[4])
        responses = [result[0] for result in all_results]
        missing = [result[1] for result in all_results if result[1] is not None]
        market, _ = results[0]
        funding, _ = results[1]
        current, _ = results[2]
        history, _ = results[3]
        basis, _ = results[4][0]
        accounts, _ = results[4][1]
        taker, _ = results[4][2]
        open_interest = (
            self._combine_oi(current, history, normalized, period)
            if current or history
            else None
        )
        positioning = (
            self._combine_positioning(accounts, taker, normalized, period)
            if accounts or taker
            else None
        )
        analytics = analyze_futures(
            funding=funding.data if funding else None,
            open_interest=open_interest,
            basis=basis.data if basis else None,
            positioning=positioning,
            market=market.data if market else None,
        )
        metas = [response.meta for response in responses if response is not None]
        meta = _aggregate(metas, missing)
        risk = (
            build_futures_risk(
                analytics=analytics,
                freshness_confidence=0.6 if meta.freshness is Freshness.STALE else 1.0,
            )
            if analytics is not None
            else None
        )
        return AnalyticsResponse(
            data=FuturesResearchData(
                symbol=normalized,
                period=period,
                market=market.data if market else None,
                funding=funding.data if funding else None,
                open_interest=open_interest,
                basis=basis.data if basis else None,
                positioning=positioning,
                analytics=analytics,
                risk=risk,
                components={
                    response.meta.provenance.operation: response.meta
                    for response in responses
                    if response is not None
                },
            ),
            meta=meta,
        )
