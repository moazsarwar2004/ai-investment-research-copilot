"""General crypto use cases over CoinGecko data and pure analytics."""

from __future__ import annotations

from collections.abc import Awaitable

from pydantic import BaseModel, ConfigDict

from backend.app.analytics.crypto import (
    CryptoAnomalyAnalysis,
    CryptoRisk,
    CryptoTechnicalAnalysis,
    CryptoTrendAnalysis,
    analyze_crypto_anomalies,
    analyze_crypto_technicals,
    build_crypto_risk,
    build_crypto_trend,
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
from backend.app.providers.coingecko import (
    COINGECKO_PROVIDER,
    CoinGeckoGlobalAdapter,
    CoinGeckoHistoryAdapter,
    CoinGeckoMarketsAdapter,
    CoinGeckoSearchAdapter,
    CoinGeckoTrendingAdapter,
    CoinSearchData,
    CryptoGlobalData,
    CryptoHistoryData,
    CryptoMarket,
    CryptoMarketOrder,
    CryptoMarketsData,
    CryptoTrendingData,
    validate_coin_id,
)
from backend.app.services.binance_spot_service import (
    AggregateProviderMeta,
    AnalyticsResponse,
)


class _ServiceModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


class CryptoResearchData(_ServiceModel):
    coin_id: str
    currency: str = "usd"
    days: int
    overview: CryptoMarket
    history: CryptoHistoryData | None
    technicals: CryptoTechnicalAnalysis | None
    trend: CryptoTrendAnalysis | None
    anomalies: CryptoAnomalyAnalysis | None
    risk: CryptoRisk
    attribution: str = "Powered by CoinGecko"
    disclaimer: str = (
        "Research and education only. This is not personalized financial advice."
    )


def _normalize_search_query(query: str) -> str:
    normalized = " ".join(query.strip().split())
    if not 2 <= len(normalized) <= 80:
        raise ApplicationValidationError("Crypto search must contain 2-80 characters.")
    if any(ord(character) < 32 for character in normalized):
        raise ApplicationValidationError("Crypto search contains control characters.")
    return normalized


def _aggregate_crypto_meta(
    metas: list[ProviderMeta],
    *,
    missing_operations: list[str] | None = None,
) -> AggregateProviderMeta:
    if not metas:
        raise ProviderUnavailableError(cause_code="provider_unavailable")
    missing = missing_operations or []
    statuses = {item.cache_status for item in metas}
    if CacheStatus.STALE in statuses:
        cache_status = CacheStatus.STALE
        freshness = Freshness.STALE
    elif CacheStatus.BYPASS in statuses:
        cache_status = CacheStatus.BYPASS
        freshness = (
            Freshness.DELAYED
            if any(item.freshness is Freshness.DELAYED for item in metas)
            else Freshness.LIVE
        )
    elif CacheStatus.MISS in statuses:
        cache_status = CacheStatus.MISS
        freshness = (
            Freshness.DELAYED
            if any(item.freshness is Freshness.DELAYED for item in metas)
            else Freshness.LIVE
        )
    else:
        cache_status = CacheStatus.HIT
        freshness = Freshness.CACHED
    warnings: list[ProviderWarning] = []
    seen_warning_codes: set[str] = set()
    for meta in metas:
        for warning in meta.warnings:
            if warning.code not in seen_warning_codes:
                warnings.append(warning)
                seen_warning_codes.add(warning.code)
    for operation in missing:
        code = f"{operation}_unavailable".replace(".", "_")
        if code not in seen_warning_codes:
            warnings.append(
                ProviderWarning(
                    code=code,
                    message=f"The {operation} component is temporarily unavailable.",
                )
            )
            seen_warning_codes.add(code)
    sources: list[ProviderProvenance] = []
    seen_sources: set[tuple[str, str]] = set()
    for meta in metas:
        identity = (
            meta.provenance.operation,
            meta.provenance.raw_payload_sha256,
        )
        if identity not in seen_sources:
            sources.append(meta.provenance)
            seen_sources.add(identity)
    source_timestamps = [
        item.source_timestamp for item in metas if item.source_timestamp is not None
    ]
    return AggregateProviderMeta(
        source=COINGECKO_PROVIDER,
        source_timestamp=min(source_timestamps) if source_timestamps else None,
        fetched_at=max(item.fetched_at for item in metas),
        cache_status=cache_status,
        freshness=freshness,
        staleness_seconds=max(item.staleness_seconds for item in metas),
        partial=bool(missing) or any(item.partial for item in metas),
        warnings=warnings,
        sources=sources,
    )


async def _capture[DataT: BaseModel](
    operation: str,
    awaitable: Awaitable[ProviderResponse[DataT]],
) -> tuple[ProviderResponse[DataT] | None, str | None]:
    try:
        return await awaitable, None
    except ProviderUnavailableError:
        return None, operation


class CryptoService:
    """Search IDs, fetch bounded CoinGecko snapshots, and derive research."""

    def __init__(
        self,
        manager: ProviderManager,
        *,
        base_url: str,
        demo_api_key: str | None,
    ) -> None:
        self._manager = manager
        self._search_adapter = CoinGeckoSearchAdapter(
            base_url,
            demo_api_key=demo_api_key,
        )
        self._markets_adapter = CoinGeckoMarketsAdapter(
            base_url,
            demo_api_key=demo_api_key,
        )
        self._history_adapter = CoinGeckoHistoryAdapter(
            base_url,
            demo_api_key=demo_api_key,
        )
        self._global_adapter = CoinGeckoGlobalAdapter(
            base_url,
            demo_api_key=demo_api_key,
        )
        self._trending_adapter = CoinGeckoTrendingAdapter(
            base_url,
            demo_api_key=demo_api_key,
        )

    @staticmethod
    def _asset(coin_id: str) -> CanonicalAsset:
        normalized = validate_coin_id(coin_id)
        return CanonicalAsset(
            asset_type=AssetType.CRYPTO,
            key=normalized,
            provider_id=normalized,
        )

    async def search(self, query: str) -> ProviderResponse[CoinSearchData]:
        normalized = _normalize_search_query(query)
        return await self._manager.fetch(
            self._search_adapter,
            ProviderRequest(
                operation="crypto.search",
                asset=CanonicalAsset(
                    asset_type=AssetType.SYSTEM,
                    key=f"crypto-search-{normalized.casefold()}",
                ),
                parameters={"query": normalized},
                weight=1,
                soft_ttl_seconds=300,
                hard_ttl_seconds=1_800,
            ),
        )

    async def global_market(self) -> ProviderResponse[CryptoGlobalData]:
        return await self._manager.fetch(
            self._global_adapter,
            ProviderRequest(
                operation="crypto.global",
                asset=CanonicalAsset(asset_type=AssetType.SYSTEM, key="crypto-global"),
                weight=1,
                soft_ttl_seconds=1_800,
                hard_ttl_seconds=7_200,
            ),
        )

    async def trending(self) -> ProviderResponse[CryptoTrendingData]:
        return await self._manager.fetch(
            self._trending_adapter,
            ProviderRequest(
                operation="crypto.trending",
                asset=CanonicalAsset(
                    asset_type=AssetType.SYSTEM,
                    key="crypto-trending",
                ),
                weight=1,
                soft_ttl_seconds=1_800,
                hard_ttl_seconds=7_200,
            ),
        )

    async def markets(
        self,
        *,
        page: int,
        per_page: int,
        order: CryptoMarketOrder,
    ) -> ProviderResponse[CryptoMarketsData]:
        return await self._manager.fetch(
            self._markets_adapter,
            ProviderRequest(
                operation="crypto.markets",
                asset=CanonicalAsset(
                    asset_type=AssetType.SYSTEM,
                    key="crypto-markets",
                ),
                parameters={
                    "page": page,
                    "per_page": per_page,
                    "order": order.value,
                },
                weight=1,
                soft_ttl_seconds=900,
                hard_ttl_seconds=3_600,
            ),
        )

    async def _overview(self, coin_id: str) -> ProviderResponse[CryptoMarketsData]:
        normalized = validate_coin_id(coin_id)
        response = await self._manager.fetch(
            self._markets_adapter,
            ProviderRequest(
                operation="crypto.overview",
                asset=self._asset(normalized),
                parameters={
                    "coin_id": normalized,
                    "page": 1,
                    "per_page": 1,
                    "order": CryptoMarketOrder.MARKET_CAP_DESC.value,
                },
                weight=1,
                soft_ttl_seconds=300,
                hard_ttl_seconds=1_800,
            ),
        )
        if not response.data.markets:
            raise ResourceNotFoundError(
                "The requested CoinGecko provider ID was not found."
            )
        if response.data.markets[0].coin_id != normalized:
            raise ResourceNotFoundError(
                "The requested CoinGecko provider ID was not found."
            )
        return response

    async def overview(self, coin_id: str) -> ProviderResponse[CryptoMarket]:
        response = await self._overview(coin_id)
        return ProviderResponse(data=response.data.markets[0], meta=response.meta)

    async def _history(
        self,
        coin_id: str,
        *,
        days: int,
    ) -> ProviderResponse[CryptoHistoryData]:
        normalized = validate_coin_id(coin_id)
        return await self._manager.fetch(
            self._history_adapter,
            ProviderRequest(
                operation="crypto.history",
                asset=self._asset(normalized),
                parameters={"days": days},
                weight=1,
                soft_ttl_seconds=300,
                hard_ttl_seconds=3_600,
            ),
        )

    async def history(
        self,
        coin_id: str,
        *,
        days: int,
    ) -> ProviderResponse[CryptoHistoryData]:
        overview = await self._overview(coin_id)
        return await self._history(overview.data.markets[0].coin_id, days=days)

    async def technicals(
        self,
        coin_id: str,
        *,
        days: int,
    ) -> ProviderResponse[CryptoTechnicalAnalysis]:
        history = await self.history(coin_id, days=days)
        try:
            analytics = analyze_crypto_technicals(history.data)
        except ValueError as error:
            raise ApplicationValidationError(str(error)) from error
        return ProviderResponse(data=analytics, meta=history.meta)

    async def trend(
        self,
        coin_id: str,
        *,
        days: int,
    ) -> ProviderResponse[CryptoTrendAnalysis]:
        technicals = await self.technicals(coin_id, days=days)
        return ProviderResponse(
            data=build_crypto_trend(technicals.data),
            meta=technicals.meta,
        )

    async def anomalies(
        self,
        coin_id: str,
        *,
        days: int,
    ) -> ProviderResponse[CryptoAnomalyAnalysis]:
        history = await self.history(coin_id, days=days)
        try:
            analytics = analyze_crypto_anomalies(history.data)
        except ValueError as error:
            raise ApplicationValidationError(str(error)) from error
        return ProviderResponse(data=analytics, meta=history.meta)

    async def risk(
        self,
        coin_id: str,
        *,
        days: int,
    ) -> AnalyticsResponse[CryptoRisk]:
        overview = await self._overview(coin_id)
        normalized = overview.data.markets[0].coin_id
        history, history_missing = await _capture(
            "history", self._history(normalized, days=days)
        )
        technicals = (
            analyze_crypto_technicals(history.data)
            if history is not None and len(history.data.points) >= 20
            else None
        )
        anomalies = (
            analyze_crypto_anomalies(history.data)
            if history is not None and len(history.data.points) >= 20
            else None
        )
        missing = [history_missing] if history_missing is not None else []
        metas = [overview.meta, *([history.meta] if history is not None else [])]
        meta = _aggregate_crypto_meta(metas, missing_operations=missing)
        freshness_confidence = 0.6 if meta.freshness is Freshness.STALE else 1.0
        return AnalyticsResponse(
            data=build_crypto_risk(
                overview=overview.data.markets[0],
                technicals=technicals,
                anomalies=anomalies,
                freshness_confidence=freshness_confidence,
            ),
            meta=meta,
        )

    async def research(
        self,
        coin_id: str,
        *,
        days: int,
    ) -> AnalyticsResponse[CryptoResearchData]:
        overview = await self._overview(coin_id)
        market = overview.data.markets[0]
        history, history_missing = await _capture(
            "history", self._history(market.coin_id, days=days)
        )
        technicals = (
            analyze_crypto_technicals(history.data)
            if history is not None and len(history.data.points) >= 20
            else None
        )
        trend = build_crypto_trend(technicals) if technicals is not None else None
        anomalies = (
            analyze_crypto_anomalies(history.data)
            if history is not None and len(history.data.points) >= 20
            else None
        )
        missing = [history_missing] if history_missing is not None else []
        if history is not None and technicals is None:
            missing.append("crypto_analytics")
        metas = [overview.meta, *([history.meta] if history is not None else [])]
        meta = _aggregate_crypto_meta(metas, missing_operations=missing)
        risk = build_crypto_risk(
            overview=market,
            technicals=technicals,
            anomalies=anomalies,
            freshness_confidence=(0.6 if meta.freshness is Freshness.STALE else 1.0),
        )
        return AnalyticsResponse(
            data=CryptoResearchData(
                coin_id=market.coin_id,
                days=days,
                overview=market,
                history=history.data if history is not None else None,
                technicals=technicals,
                trend=trend,
                anomalies=anomalies,
                risk=risk,
            ),
            meta=meta,
        )


__all__ = ["CryptoResearchData", "CryptoService"]
