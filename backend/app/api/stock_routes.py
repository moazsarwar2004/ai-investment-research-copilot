"""Thin, public, read-only stock research routes."""

from __future__ import annotations

from enum import IntEnum
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response

from backend.app.api.dependencies import get_stock_service
from backend.app.providers.stocks import StockExchange, StockInterval
from backend.app.services.binance_spot_service import AnalyticsResponse
from backend.app.services.stock_service import (
    StockCandlesResult,
    StockOverviewData,
    StockResearchData,
    StockRiskResult,
    StockSearchView,
    StockService,
    StockTechnicalsResult,
    StockTrendResult,
)

stock_router = APIRouter(prefix="/stocks", tags=["stocks"])

ServiceDependency = Annotated[StockService, Depends(get_stock_service)]
SymbolPath = Annotated[
    str,
    Path(
        min_length=1,
        max_length=11,
        pattern=r"^[A-Z][A-Z0-9]{0,5}(?:[.-][A-Z0-9]{1,4})?$",
        description=(
            "Canonical uppercase stock symbol, including an optional class suffix."
        ),
    ),
]
SearchQuery = Annotated[str, Query(min_length=1, max_length=80)]
IntervalQuery = Annotated[StockInterval, Query()]
ExchangeQuery = Annotated[StockExchange, Query()]


class StockHistoryDays(IntEnum):
    THIRTY = 30
    NINETY = 90
    HALF_YEAR = 180
    YEAR = 365
    TWO_YEARS = 730
    FIVE_YEARS = 1_825


HistoryDaysQuery = Annotated[StockHistoryDays, Query()]


def _disable_browser_caching(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@stock_router.get("/search", response_model=AnalyticsResponse[StockSearchView])
async def search(
    response: Response,
    service: ServiceDependency,
    q: SearchQuery,
    exchange: ExchangeQuery = StockExchange.PSX,
) -> AnalyticsResponse[StockSearchView]:
    """Search normalized stock identities when a licensed provider is active."""
    _disable_browser_caching(response)
    return await service.search(q, exchange=exchange)


@stock_router.get("/{symbol}", response_model=AnalyticsResponse[StockOverviewData])
async def overview(
    symbol: SymbolPath,
    response: Response,
    service: ServiceDependency,
    exchange: ExchangeQuery = StockExchange.PSX,
) -> AnalyticsResponse[StockOverviewData]:
    """Return company profile and quote, explicitly unavailable when unlicensed."""
    _disable_browser_caching(response)
    return await service.overview(exchange, symbol)


@stock_router.get(
    "/{symbol}/candles",
    response_model=AnalyticsResponse[StockCandlesResult],
)
async def candles(
    symbol: SymbolPath,
    response: Response,
    service: ServiceDependency,
    exchange: ExchangeQuery = StockExchange.PSX,
    interval: IntervalQuery = StockInterval.DAY,
    days: HistoryDaysQuery = StockHistoryDays.YEAR,
) -> AnalyticsResponse[StockCandlesResult]:
    """Return bounded, normalized stock candles when licensed."""
    _disable_browser_caching(response)
    return await service.candles(exchange, symbol, interval=interval, days=int(days))


@stock_router.get(
    "/{symbol}/technicals",
    response_model=AnalyticsResponse[StockTechnicalsResult],
)
async def technicals(
    symbol: SymbolPath,
    response: Response,
    service: ServiceDependency,
    exchange: ExchangeQuery = StockExchange.PSX,
    interval: IntervalQuery = StockInterval.DAY,
    days: HistoryDaysQuery = StockHistoryDays.YEAR,
) -> AnalyticsResponse[StockTechnicalsResult]:
    """Return deterministic indicators calculated from licensed candles."""
    _disable_browser_caching(response)
    return await service.technicals(exchange, symbol, interval=interval, days=int(days))


@stock_router.get(
    "/{symbol}/trend",
    response_model=AnalyticsResponse[StockTrendResult],
)
async def trend(
    symbol: SymbolPath,
    response: Response,
    service: ServiceDependency,
    exchange: ExchangeQuery = StockExchange.PSX,
    interval: IntervalQuery = StockInterval.DAY,
    days: HistoryDaysQuery = StockHistoryDays.YEAR,
) -> AnalyticsResponse[StockTrendResult]:
    """Return the deterministic stock trend and supporting evidence."""
    _disable_browser_caching(response)
    return await service.trend(exchange, symbol, interval=interval, days=int(days))


@stock_router.get(
    "/{symbol}/risk",
    response_model=AnalyticsResponse[StockRiskResult],
)
async def risk(
    symbol: SymbolPath,
    response: Response,
    service: ServiceDependency,
    exchange: ExchangeQuery = StockExchange.PSX,
    interval: IntervalQuery = StockInterval.DAY,
    days: HistoryDaysQuery = StockHistoryDays.YEAR,
) -> AnalyticsResponse[StockRiskResult]:
    """Return price/volume risk with missing-input renormalization."""
    _disable_browser_caching(response)
    return await service.risk(exchange, symbol, interval=interval, days=int(days))


@stock_router.get(
    "/{symbol}/research",
    response_model=AnalyticsResponse[StockResearchData],
)
async def research(
    symbol: SymbolPath,
    response: Response,
    service: ServiceDependency,
    exchange: ExchangeQuery = StockExchange.PSX,
    interval: IntervalQuery = StockInterval.DAY,
    days: HistoryDaysQuery = StockHistoryDays.YEAR,
) -> AnalyticsResponse[StockResearchData]:
    """Return one partial-tolerant payload for the stock research page."""
    _disable_browser_caching(response)
    return await service.research(exchange, symbol, interval=interval, days=int(days))


__all__ = ["StockHistoryDays", "stock_router"]
