"""Thin, public, read-only general cryptocurrency research routes."""

from __future__ import annotations

from enum import IntEnum
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response

from backend.app.analytics.crypto import (
    CryptoAnomalyAnalysis,
    CryptoRisk,
    CryptoTechnicalAnalysis,
    CryptoTrendAnalysis,
)
from backend.app.api.dependencies import get_crypto_service
from backend.app.providers import ProviderResponse
from backend.app.providers.coingecko import (
    CoinSearchData,
    CryptoGlobalData,
    CryptoHistoryData,
    CryptoMarket,
    CryptoMarketOrder,
    CryptoMarketsData,
    CryptoTrendingData,
)
from backend.app.services.binance_spot_service import AnalyticsResponse
from backend.app.services.crypto_service import CryptoResearchData, CryptoService

crypto_router = APIRouter(prefix="/crypto", tags=["crypto"])

ServiceDependency = Annotated[CryptoService, Depends(get_crypto_service)]
CoinIdPath = Annotated[
    str,
    Path(
        min_length=1,
        max_length=160,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        description="Canonical CoinGecko provider ID, not a ticker symbol.",
    ),
]
SearchQuery = Annotated[str, Query(min_length=2, max_length=80)]


class HistoryDays(IntEnum):
    ONE = 1
    SEVEN = 7
    THIRTY = 30
    NINETY = 90
    YEAR = 365


HistoryDaysQuery = Annotated[HistoryDays, Query()]
MarketPageQuery = Annotated[int, Query(ge=1, le=10)]
MarketPageSizeQuery = Annotated[int, Query(ge=1, le=100)]
MarketOrderQuery = Annotated[CryptoMarketOrder, Query()]


def _disable_browser_caching(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@crypto_router.get("/search", response_model=ProviderResponse[CoinSearchData])
async def search(
    response: Response,
    service: ServiceDependency,
    q: SearchQuery,
) -> ProviderResponse[CoinSearchData]:
    """Search names, symbols, and provider IDs with explicit ambiguity."""
    _disable_browser_caching(response)
    return await service.search(q)


@crypto_router.get("/global", response_model=ProviderResponse[CryptoGlobalData])
async def global_market(
    response: Response,
    service: ServiceDependency,
) -> ProviderResponse[CryptoGlobalData]:
    """Return the cached global market cap, volume, and dominance snapshot."""
    _disable_browser_caching(response)
    return await service.global_market()


@crypto_router.get("/trending", response_model=ProviderResponse[CryptoTrendingData])
async def trending(
    response: Response,
    service: ServiceDependency,
) -> ProviderResponse[CryptoTrendingData]:
    """Return CoinGecko's provider-supported trending search assets."""
    _disable_browser_caching(response)
    return await service.trending()


@crypto_router.get("/markets", response_model=ProviderResponse[CryptoMarketsData])
async def markets(
    response: Response,
    service: ServiceDependency,
    page: MarketPageQuery = 1,
    per_page: MarketPageSizeQuery = 50,
    order: MarketOrderQuery = CryptoMarketOrder.MARKET_CAP_DESC,
) -> ProviderResponse[CryptoMarketsData]:
    """Return one bounded page of global crypto markets."""
    _disable_browser_caching(response)
    return await service.markets(page=page, per_page=per_page, order=order)


@crypto_router.get("/{coin_id}", response_model=ProviderResponse[CryptoMarket])
async def overview(
    coin_id: CoinIdPath,
    response: Response,
    service: ServiceDependency,
) -> ProviderResponse[CryptoMarket]:
    """Return overview, supply, range, rank, ATH, and ATL metadata by ID."""
    _disable_browser_caching(response)
    return await service.overview(coin_id)


@crypto_router.get(
    "/{coin_id}/history",
    response_model=ProviderResponse[CryptoHistoryData],
)
async def history(
    coin_id: CoinIdPath,
    response: Response,
    service: ServiceDependency,
    days: HistoryDaysQuery = HistoryDays.NINETY,
) -> ProviderResponse[CryptoHistoryData]:
    """Return bounded USD price, market-cap, and volume history."""
    _disable_browser_caching(response)
    return await service.history(coin_id, days=int(days))


@crypto_router.get(
    "/{coin_id}/technicals",
    response_model=ProviderResponse[CryptoTechnicalAnalysis],
)
async def technicals(
    coin_id: CoinIdPath,
    response: Response,
    service: ServiceDependency,
    days: HistoryDaysQuery = HistoryDays.NINETY,
) -> ProviderResponse[CryptoTechnicalAnalysis]:
    """Return deterministic indicators, volatility, and drawdown."""
    _disable_browser_caching(response)
    return await service.technicals(coin_id, days=int(days))


@crypto_router.get(
    "/{coin_id}/trend",
    response_model=ProviderResponse[CryptoTrendAnalysis],
)
async def trend(
    coin_id: CoinIdPath,
    response: Response,
    service: ServiceDependency,
    days: HistoryDaysQuery = HistoryDays.NINETY,
) -> ProviderResponse[CryptoTrendAnalysis]:
    """Return a rule-based trend and its supporting evidence."""
    _disable_browser_caching(response)
    return await service.trend(coin_id, days=int(days))


@crypto_router.get(
    "/{coin_id}/anomalies",
    response_model=ProviderResponse[CryptoAnomalyAnalysis],
)
async def anomalies(
    coin_id: CoinIdPath,
    response: Response,
    service: ServiceDependency,
    days: HistoryDaysQuery = HistoryDays.NINETY,
) -> ProviderResponse[CryptoAnomalyAnalysis]:
    """Return rolling return and volume anomaly flags."""
    _disable_browser_caching(response)
    return await service.anomalies(coin_id, days=int(days))


@crypto_router.get("/{coin_id}/risk", response_model=AnalyticsResponse[CryptoRisk])
async def risk(
    coin_id: CoinIdPath,
    response: Response,
    service: ServiceDependency,
    days: HistoryDaysQuery = HistoryDays.NINETY,
) -> AnalyticsResponse[CryptoRisk]:
    """Return explainable six-component crypto risk with renormalization."""
    _disable_browser_caching(response)
    return await service.risk(coin_id, days=int(days))


@crypto_router.get(
    "/{coin_id}/research",
    response_model=AnalyticsResponse[CryptoResearchData],
)
async def research(
    coin_id: CoinIdPath,
    response: Response,
    service: ServiceDependency,
    days: HistoryDaysQuery = HistoryDays.NINETY,
) -> AnalyticsResponse[CryptoResearchData]:
    """Return one partial-tolerant payload for the crypto research page."""
    _disable_browser_caching(response)
    return await service.research(coin_id, days=int(days))


__all__ = ["HistoryDays", "crypto_router"]
