"""Thin, public, read-only Binance Spot research routes."""

from __future__ import annotations

from decimal import Decimal
from enum import IntEnum
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response

from backend.app.analytics import (
    OrderBookAnalysis,
    SpotRisk,
    TechnicalAnalysis,
    TradeAnalysis,
)
from backend.app.api.dependencies import get_binance_spot_service
from backend.app.providers import ProviderResponse
from backend.app.providers.binance_spot import (
    BinanceSpotInterval,
    SpotCandlesData,
    SpotSymbolsData,
    SpotTickerData,
)
from backend.app.services import (
    AnalyticsResponse,
    BinanceSpotService,
    SpotResearchData,
)

binance_spot_router = APIRouter(
    prefix="/binance/spot",
    tags=["binance-spot"],
)

ServiceDependency = Annotated[
    BinanceSpotService,
    Depends(get_binance_spot_service),
]
SymbolPath = Annotated[
    str,
    Path(min_length=5, max_length=20, pattern=r"^[A-Za-z0-9]+$"),
]
IntervalQuery = Annotated[BinanceSpotInterval, Query()]
CandleLimitQuery = Annotated[int, Query(ge=50, le=500)]
TradeLimitQuery = Annotated[int, Query(ge=1, le=200)]


class BookDepth(IntEnum):
    TWENTY = 20
    FIFTY = 50
    ONE_HUNDRED = 100


BookLimitQuery = Annotated[BookDepth, Query()]
SlippageNotionalQuery = Annotated[
    Decimal,
    Query(gt=0, le=1_000_000, decimal_places=8),
]


def _disable_browser_caching(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@binance_spot_router.get(
    "/symbols",
    response_model=ProviderResponse[SpotSymbolsData],
)
async def symbols(
    response: Response,
    service: ServiceDependency,
) -> ProviderResponse[SpotSymbolsData]:
    """List only currently tradable public Spot pairs."""
    _disable_browser_caching(response)
    return await service.symbols()


@binance_spot_router.get(
    "/{symbol}/ticker",
    response_model=ProviderResponse[SpotTickerData],
)
async def ticker(
    symbol: SymbolPath,
    response: Response,
    service: ServiceDependency,
) -> ProviderResponse[SpotTickerData]:
    """Return normalized 24-hour public ticker statistics."""
    _disable_browser_caching(response)
    return await service.ticker(symbol)


@binance_spot_router.get(
    "/{symbol}/candles",
    response_model=ProviderResponse[SpotCandlesData],
)
async def candles(
    symbol: SymbolPath,
    response: Response,
    service: ServiceDependency,
    interval: IntervalQuery = BinanceSpotInterval.ONE_HOUR,
    limit: CandleLimitQuery = 200,
) -> ProviderResponse[SpotCandlesData]:
    """Return UTC candles at one of the product-approved intervals."""
    _disable_browser_caching(response)
    return await service.candles(symbol, interval=interval, limit=limit)


@binance_spot_router.get(
    "/{symbol}/order-book",
    response_model=ProviderResponse[OrderBookAnalysis],
)
async def order_book(
    symbol: SymbolPath,
    response: Response,
    service: ServiceDependency,
    limit: BookLimitQuery = BookDepth.ONE_HUNDRED,
    slippage_notional_quote: SlippageNotionalQuery = Decimal("1000"),
) -> ProviderResponse[OrderBookAnalysis]:
    """Return bounded depth plus spread, imbalance, pressure, and slippage."""
    _disable_browser_caching(response)
    return await service.order_book(
        symbol,
        limit=int(limit),
        slippage_notional_quote=slippage_notional_quote,
    )


@binance_spot_router.get(
    "/{symbol}/trades",
    response_model=ProviderResponse[TradeAnalysis],
)
async def trades(
    symbol: SymbolPath,
    response: Response,
    service: ServiceDependency,
    limit: TradeLimitQuery = 100,
) -> ProviderResponse[TradeAnalysis]:
    """Return bounded recent trades with pressure and large-trade anomalies."""
    _disable_browser_caching(response)
    return await service.trades(symbol, limit=limit)


@binance_spot_router.get(
    "/{symbol}/technicals",
    response_model=ProviderResponse[TechnicalAnalysis],
)
async def technicals(
    symbol: SymbolPath,
    response: Response,
    service: ServiceDependency,
    interval: IntervalQuery = BinanceSpotInterval.ONE_HOUR,
    limit: CandleLimitQuery = 200,
) -> ProviderResponse[TechnicalAnalysis]:
    """Return deterministic indicators and a rule-based trend state."""
    _disable_browser_caching(response)
    return await service.technicals(symbol, interval=interval, limit=limit)


@binance_spot_router.get(
    "/{symbol}/risk",
    response_model=AnalyticsResponse[SpotRisk],
)
async def risk(
    symbol: SymbolPath,
    response: Response,
    service: ServiceDependency,
    interval: IntervalQuery = BinanceSpotInterval.ONE_HOUR,
    candle_limit: CandleLimitQuery = 200,
    book_limit: BookLimitQuery = BookDepth.ONE_HUNDRED,
    trade_limit: TradeLimitQuery = 100,
    slippage_notional_quote: SlippageNotionalQuery = Decimal("1000"),
) -> AnalyticsResponse[SpotRisk]:
    """Return explainable volatility, liquidity, anomaly, and trend risk."""
    _disable_browser_caching(response)
    return await service.risk(
        symbol,
        interval=interval,
        candle_limit=candle_limit,
        book_limit=int(book_limit),
        trade_limit=trade_limit,
        slippage_notional_quote=slippage_notional_quote,
    )


@binance_spot_router.get(
    "/{symbol}/research",
    response_model=AnalyticsResponse[SpotResearchData],
)
async def research(
    symbol: SymbolPath,
    response: Response,
    service: ServiceDependency,
    interval: IntervalQuery = BinanceSpotInterval.ONE_HOUR,
    candle_limit: CandleLimitQuery = 200,
    book_limit: BookLimitQuery = BookDepth.ONE_HUNDRED,
    trade_limit: TradeLimitQuery = 100,
    slippage_notional_quote: SlippageNotionalQuery = Decimal("1000"),
) -> AnalyticsResponse[SpotResearchData]:
    """Return one partial-tolerant payload for the first research page."""
    _disable_browser_caching(response)
    return await service.research(
        symbol,
        interval=interval,
        candle_limit=candle_limit,
        book_limit=int(book_limit),
        trade_limit=trade_limit,
        slippage_notional_quote=slippage_notional_quote,
    )
