"""Thin stock research routes plus authenticated private-upload mutations."""

from __future__ import annotations

from enum import IntEnum
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Response, status

from backend.app.api.dependencies import (
    get_current_principal,
    get_request_context,
    get_stock_service,
    get_stock_upload_service,
)
from backend.app.core.exceptions import ResourceNotFoundError
from backend.app.providers.stocks import StockExchange, StockInterval
from backend.app.services.binance_spot_service import AnalyticsResponse
from backend.app.services.identity_service import CurrentPrincipal, RequestContext
from backend.app.services.stock_service import (
    StockCandlesResult,
    StockFinancialsResult,
    StockOverviewData,
    StockRatiosResult,
    StockReportsResult,
    StockResearchData,
    StockRiskResult,
    StockSearchView,
    StockService,
    StockTechnicalsResult,
    StockTrendResult,
)
from backend.app.services.stock_upload_service import (
    PrivateStockResearch,
    StockPriceUploadRequest,
    StockUploadService,
    StockUploadSummary,
)

stock_router = APIRouter(prefix="/stocks", tags=["stocks"])

ServiceDependency = Annotated[StockService, Depends(get_stock_service)]
UploadServiceDependency = Annotated[
    StockUploadService, Depends(get_stock_upload_service)
]
PrincipalDependency = Annotated[CurrentPrincipal, Depends(get_current_principal)]
ContextDependency = Annotated[RequestContext, Depends(get_request_context)]
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
    "/{symbol}/financials",
    response_model=AnalyticsResponse[StockFinancialsResult],
)
async def financials(
    symbol: SymbolPath,
    response: Response,
    service: ServiceDependency,
    exchange: ExchangeQuery = StockExchange.PSX,
) -> AnalyticsResponse[StockFinancialsResult]:
    """Return normalized SEC or official Pakistani financial periods."""
    _disable_browser_caching(response)
    return await service.financials(exchange, symbol)


@stock_router.get(
    "/{symbol}/ratios",
    response_model=AnalyticsResponse[StockRatiosResult],
)
async def ratios(
    symbol: SymbolPath,
    response: Response,
    service: ServiceDependency,
    exchange: ExchangeQuery = StockExchange.PSX,
) -> AnalyticsResponse[StockRatiosResult]:
    """Return deterministic ratios from official reported facts."""
    _disable_browser_caching(response)
    return await service.ratios(exchange, symbol)


@stock_router.get(
    "/{symbol}/filings",
    response_model=AnalyticsResponse[StockReportsResult],
)
async def filings(
    symbol: SymbolPath,
    response: Response,
    service: ServiceDependency,
    exchange: ExchangeQuery = StockExchange.PSX,
) -> AnalyticsResponse[StockReportsResult]:
    """Return annual, quarterly, announcement, and SEC report links."""
    _disable_browser_caching(response)
    return await service.reports(exchange, symbol)


@stock_router.post(
    "/{symbol}/price-uploads",
    response_model=PrivateStockResearch,
    status_code=status.HTTP_201_CREATED,
)
async def upload_prices(
    symbol: SymbolPath,
    request: StockPriceUploadRequest,
    response: Response,
    service: UploadServiceDependency,
    principal: PrincipalDependency,
    context: ContextDependency,
    exchange: ExchangeQuery = StockExchange.PSX,
) -> PrivateStockResearch:
    """Validate and privately analyze an authenticated user's OHLCV CSV."""
    _disable_browser_caching(response)
    return await service.create(
        principal=principal,
        exchange=exchange,
        symbol=symbol,
        request=request,
        context=context,
    )


@stock_router.get(
    "/{symbol}/price-uploads",
    response_model=list[StockUploadSummary],
)
async def list_price_uploads(
    symbol: SymbolPath,
    response: Response,
    service: UploadServiceDependency,
    principal: PrincipalDependency,
    exchange: ExchangeQuery = StockExchange.PSX,
) -> list[StockUploadSummary]:
    """List only the current owner's uploads for one stock identity."""
    _disable_browser_caching(response)
    return await service.list(principal=principal, exchange=exchange, symbol=symbol)


@stock_router.get(
    "/{symbol}/price-uploads/{upload_id}",
    response_model=PrivateStockResearch,
)
async def private_price_research(
    symbol: SymbolPath,
    upload_id: UUID,
    response: Response,
    service: UploadServiceDependency,
    principal: PrincipalDependency,
    exchange: ExchangeQuery = StockExchange.PSX,
) -> PrivateStockResearch:
    """Return one owner-private upload and its deterministic analytics."""
    _disable_browser_caching(response)
    result = await service.get(principal=principal, upload_id=upload_id)
    if result.upload.symbol != symbol or result.upload.exchange != exchange:
        raise ResourceNotFoundError("The private price upload was not found.")
    return result


@stock_router.delete(
    "/{symbol}/price-uploads/{upload_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_price_upload(
    symbol: SymbolPath,
    upload_id: UUID,
    service: UploadServiceDependency,
    principal: PrincipalDependency,
    context: ContextDependency,
    exchange: ExchangeQuery = StockExchange.PSX,
) -> Response:
    """Delete an owner-private upload without exposing cross-user existence."""
    result = await service.get(principal=principal, upload_id=upload_id)
    if result.upload.symbol != symbol or result.upload.exchange != exchange:
        raise ResourceNotFoundError("The private price upload was not found.")
    await service.delete(principal=principal, upload_id=upload_id, context=context)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
