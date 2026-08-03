"""Binance Spot use cases over normalized provider data and pure analytics."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.analytics import (
    OrderBookAnalysis,
    SpotRisk,
    TechnicalAnalysis,
    TradeAnalysis,
    analyze_order_book,
    analyze_technicals,
    analyze_trades,
    build_spot_risk,
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
from backend.app.providers.binance_spot import (
    BINANCE_SPOT_PROVIDER,
    BinanceSpotCandlesAdapter,
    BinanceSpotInterval,
    BinanceSpotOrderBookAdapter,
    BinanceSpotSymbolsAdapter,
    BinanceSpotTickerAdapter,
    BinanceSpotTradesAdapter,
    SpotCandlesData,
    SpotOrderBookData,
    SpotSymbolsData,
    SpotTickerData,
    SpotTradesData,
)


class _ServiceModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


class AggregateProviderMeta(_ServiceModel):
    """Freshness contract for analytics derived from one or more provider reads."""

    source: str = BINANCE_SPOT_PROVIDER
    source_timestamp: datetime | None
    fetched_at: datetime
    cache_status: CacheStatus
    freshness: Freshness
    staleness_seconds: int = Field(ge=0)
    partial: bool
    warnings: list[ProviderWarning]
    sources: list[ProviderProvenance]


class AnalyticsResponse[DataT: BaseModel](_ServiceModel):
    data: DataT
    meta: AggregateProviderMeta


class SpotResearchData(_ServiceModel):
    symbol: str
    interval: BinanceSpotInterval
    ticker: SpotTickerData | None
    candles: SpotCandlesData | None
    order_book: OrderBookAnalysis | None
    trades: TradeAnalysis | None
    technicals: TechnicalAnalysis | None
    risk: SpotRisk | None
    disclaimer: str = (
        "Research and education only. This is not personalized financial advice."
    )


def _normalized_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if not 3 <= len(normalized) <= 20 or not normalized.isalnum():
        raise ApplicationValidationError(
            "Binance Spot symbols must contain 3-20 letters or digits."
        )
    return normalized


def _aggregate_meta(
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
        freshness = Freshness.LIVE
    elif CacheStatus.MISS in statuses:
        cache_status = CacheStatus.MISS
        freshness = Freshness.LIVE
    else:
        cache_status = CacheStatus.HIT
        freshness = Freshness.CACHED
    timestamps = [
        item.source_timestamp for item in metas if item.source_timestamp is not None
    ]
    warnings: list[ProviderWarning] = []
    seen_warnings: set[str] = set()
    for meta in metas:
        for warning in meta.warnings:
            if warning.code not in seen_warnings:
                warnings.append(warning)
                seen_warnings.add(warning.code)
    for operation in missing:
        code = f"{operation}_unavailable".replace(".", "_")
        if code not in seen_warnings:
            warnings.append(
                ProviderWarning(
                    code=code,
                    message=f"The {operation} component is temporarily unavailable.",
                )
            )
            seen_warnings.add(code)
    provenances: list[ProviderProvenance] = []
    seen_sources: set[tuple[str, str]] = set()
    for meta in metas:
        identity = (
            meta.provenance.operation,
            meta.provenance.raw_payload_sha256,
        )
        if identity not in seen_sources:
            provenances.append(meta.provenance)
            seen_sources.add(identity)
    return AggregateProviderMeta(
        source=BINANCE_SPOT_PROVIDER,
        source_timestamp=min(timestamps) if timestamps else None,
        fetched_at=max(item.fetched_at for item in metas),
        cache_status=cache_status,
        freshness=freshness,
        staleness_seconds=max(item.staleness_seconds for item in metas),
        partial=bool(missing) or any(item.partial for item in metas),
        warnings=warnings,
        sources=provenances,
    )


async def _capture[DataT: BaseModel](
    operation: str,
    awaitable: Awaitable[ProviderResponse[DataT]],
) -> tuple[ProviderResponse[DataT] | None, str | None]:
    try:
        return await awaitable, None
    except ProviderUnavailableError:
        return None, operation


class BinanceSpotService:
    """Validate public pairs, fetch bounded snapshots, and derive research data."""

    def __init__(self, manager: ProviderManager, *, base_url: str) -> None:
        self._manager = manager
        self._symbols_adapter = BinanceSpotSymbolsAdapter(base_url)
        self._ticker_adapter = BinanceSpotTickerAdapter(base_url)
        self._candles_adapter = BinanceSpotCandlesAdapter(base_url)
        self._order_book_adapter = BinanceSpotOrderBookAdapter(base_url)
        self._trades_adapter = BinanceSpotTradesAdapter(base_url)

    @staticmethod
    def _asset(symbol: str) -> CanonicalAsset:
        return CanonicalAsset(asset_type=AssetType.BINANCE_SPOT, key=symbol)

    async def symbols(self) -> ProviderResponse[SpotSymbolsData]:
        return await self._manager.fetch(
            self._symbols_adapter,
            ProviderRequest(
                operation="spot.symbols",
                asset=CanonicalAsset(asset_type=AssetType.SYSTEM, key="spot-symbols"),
                weight=20,
                soft_ttl_seconds=300,
                hard_ttl_seconds=3_600,
            ),
        )

    async def _require_symbol(self, symbol: str) -> str:
        normalized = _normalized_symbol(symbol)
        available = await self.symbols()
        if not any(item.symbol == normalized for item in available.data.symbols):
            raise ResourceNotFoundError(
                "The requested Binance Spot pair is not currently tradable."
            )
        return normalized

    async def _ticker(self, symbol: str) -> ProviderResponse[SpotTickerData]:
        return await self._manager.fetch(
            self._ticker_adapter,
            ProviderRequest(
                operation="spot.ticker",
                asset=self._asset(symbol),
                weight=2,
                soft_ttl_seconds=15,
                hard_ttl_seconds=30,
            ),
        )

    async def ticker(self, symbol: str) -> ProviderResponse[SpotTickerData]:
        return await self._ticker(await self._require_symbol(symbol))

    async def _candles(
        self,
        symbol: str,
        *,
        interval: BinanceSpotInterval,
        limit: int,
    ) -> ProviderResponse[SpotCandlesData]:
        return await self._manager.fetch(
            self._candles_adapter,
            ProviderRequest(
                operation="spot.candles",
                asset=self._asset(symbol),
                interval=interval.value,
                parameters={"limit": limit},
                weight=2,
                soft_ttl_seconds=60,
                hard_ttl_seconds=300,
            ),
        )

    async def candles(
        self,
        symbol: str,
        *,
        interval: BinanceSpotInterval,
        limit: int,
    ) -> ProviderResponse[SpotCandlesData]:
        normalized = await self._require_symbol(symbol)
        return await self._candles(normalized, interval=interval, limit=limit)

    async def _raw_order_book(
        self,
        symbol: str,
        *,
        limit: int,
    ) -> ProviderResponse[SpotOrderBookData]:
        return await self._manager.fetch(
            self._order_book_adapter,
            ProviderRequest(
                operation="spot.order_book",
                asset=self._asset(symbol),
                parameters={"limit": limit},
                weight=5,
                soft_ttl_seconds=5,
                hard_ttl_seconds=10,
            ),
        )

    async def order_book(
        self,
        symbol: str,
        *,
        limit: int,
        slippage_notional_quote: Decimal,
    ) -> ProviderResponse[OrderBookAnalysis]:
        normalized = await self._require_symbol(symbol)
        response = await self._raw_order_book(normalized, limit=limit)
        return ProviderResponse[OrderBookAnalysis](
            data=analyze_order_book(
                response.data,
                slippage_notional_quote=slippage_notional_quote,
            ),
            meta=response.meta,
        )

    async def _raw_trades(
        self,
        symbol: str,
        *,
        limit: int,
    ) -> ProviderResponse[SpotTradesData]:
        return await self._manager.fetch(
            self._trades_adapter,
            ProviderRequest(
                operation="spot.trades",
                asset=self._asset(symbol),
                parameters={"limit": limit},
                weight=25,
                soft_ttl_seconds=10,
                hard_ttl_seconds=30,
            ),
        )

    async def trades(
        self,
        symbol: str,
        *,
        limit: int,
    ) -> ProviderResponse[TradeAnalysis]:
        normalized = await self._require_symbol(symbol)
        response = await self._raw_trades(normalized, limit=limit)
        return ProviderResponse[TradeAnalysis](
            data=analyze_trades(response.data),
            meta=response.meta,
        )

    async def technicals(
        self,
        symbol: str,
        *,
        interval: BinanceSpotInterval,
        limit: int,
    ) -> ProviderResponse[TechnicalAnalysis]:
        normalized = await self._require_symbol(symbol)
        response = await self._candles(normalized, interval=interval, limit=limit)
        return ProviderResponse[TechnicalAnalysis](
            data=analyze_technicals(response.data),
            meta=response.meta,
        )

    async def risk(
        self,
        symbol: str,
        *,
        interval: BinanceSpotInterval,
        candle_limit: int,
        book_limit: int,
        trade_limit: int,
        slippage_notional_quote: Decimal,
    ) -> AnalyticsResponse[SpotRisk]:
        normalized = await self._require_symbol(symbol)
        candle_result, book_result, trade_result = await asyncio.gather(
            _capture(
                "candles",
                self._candles(
                    normalized,
                    interval=interval,
                    limit=candle_limit,
                ),
            ),
            _capture(
                "order_book",
                self._raw_order_book(normalized, limit=book_limit),
            ),
            _capture(
                "trades",
                self._raw_trades(normalized, limit=trade_limit),
            ),
        )
        candles, candle_missing = candle_result
        book, book_missing = book_result
        trades, trade_missing = trade_result
        technicals = analyze_technicals(candles.data) if candles else None
        book_analysis = (
            analyze_order_book(
                book.data,
                slippage_notional_quote=slippage_notional_quote,
            )
            if book
            else None
        )
        trade_analysis = analyze_trades(trades.data) if trades else None
        metas = [
            response.meta
            for response in (candles, book, trades)
            if response is not None
        ]
        missing = [
            operation
            for operation in (candle_missing, book_missing, trade_missing)
            if operation is not None
        ]
        meta = _aggregate_meta(metas, missing_operations=missing)
        freshness_confidence = 0.6 if meta.freshness is Freshness.STALE else 1.0
        return AnalyticsResponse[SpotRisk](
            data=build_spot_risk(
                technicals=technicals,
                order_book=book_analysis,
                trades=trade_analysis,
                freshness_confidence=freshness_confidence,
            ),
            meta=meta,
        )

    async def research(
        self,
        symbol: str,
        *,
        interval: BinanceSpotInterval,
        candle_limit: int,
        book_limit: int,
        trade_limit: int,
        slippage_notional_quote: Decimal,
    ) -> AnalyticsResponse[SpotResearchData]:
        normalized = await self._require_symbol(symbol)
        ticker_result, candle_result, book_result, trade_result = await asyncio.gather(
            _capture("ticker", self._ticker(normalized)),
            _capture(
                "candles",
                self._candles(
                    normalized,
                    interval=interval,
                    limit=candle_limit,
                ),
            ),
            _capture(
                "order_book",
                self._raw_order_book(normalized, limit=book_limit),
            ),
            _capture(
                "trades",
                self._raw_trades(normalized, limit=trade_limit),
            ),
        )
        ticker, ticker_missing = ticker_result
        candles, candle_missing = candle_result
        book, book_missing = book_result
        trades, trade_missing = trade_result
        technicals = analyze_technicals(candles.data) if candles else None
        book_analysis = (
            analyze_order_book(
                book.data,
                slippage_notional_quote=slippage_notional_quote,
            )
            if book
            else None
        )
        trade_analysis = analyze_trades(trades.data) if trades else None
        risk = (
            build_spot_risk(
                technicals=technicals,
                order_book=book_analysis,
                trades=trade_analysis,
            )
            if any((technicals, book_analysis, trade_analysis))
            else None
        )
        responses = [ticker, candles, book, trades]
        metas = [response.meta for response in responses if response is not None]
        missing = [
            operation
            for operation in (
                ticker_missing,
                candle_missing,
                book_missing,
                trade_missing,
            )
            if operation is not None
        ]
        meta = _aggregate_meta(metas, missing_operations=missing)
        if risk is not None and meta.freshness is Freshness.STALE:
            risk = risk.model_copy(
                update={"data_confidence": round(risk.data_confidence * 0.6, 6)}
            )
        return AnalyticsResponse[SpotResearchData](
            data=SpotResearchData(
                symbol=normalized,
                interval=interval,
                ticker=ticker.data if ticker else None,
                candles=candles.data if candles else None,
                order_book=book_analysis,
                trades=trade_analysis,
                technicals=technicals,
                risk=risk,
            ),
            meta=meta,
        )


__all__ = [
    "AggregateProviderMeta",
    "AnalyticsResponse",
    "BinanceSpotService",
    "SpotResearchData",
]
