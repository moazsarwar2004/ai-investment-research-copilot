"""Public, read-only USD-M Futures research routes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict

from backend.app.analytics.binance_futures import FuturesRisk
from backend.app.api.dependencies import (
    get_binance_futures_service,
    get_request_settings,
)
from backend.app.core.config import Settings
from backend.app.core.exceptions import ServiceUnavailableError
from backend.app.providers import ProviderResponse, ProviderUnavailableError
from backend.app.providers.binance_futures import (
    FuturesBasisData,
    FuturesFundingData,
    FuturesMarketData,
    FuturesOpenInterestData,
    FuturesPeriod,
    FuturesPositioningData,
    FuturesSymbolsData,
)
from backend.app.services.binance_futures_service import (
    BinanceFuturesService,
    FuturesResearchData,
)
from backend.app.services.binance_spot_service import AnalyticsResponse

binance_futures_router = APIRouter(prefix="/binance/futures", tags=["binance-futures"])

ServiceDependency = Annotated[
    BinanceFuturesService, Depends(get_binance_futures_service)
]
SymbolPath = Annotated[
    str, Path(min_length=5, max_length=20, pattern=r"^[A-Za-z0-9]+$")
]
PeriodQuery = Annotated[FuturesPeriod, Query()]
LimitQuery = Annotated[int, Query(ge=5, le=100)]
SettingsDependency = Annotated[Settings, Depends(get_request_settings)]


class FuturesProviderStatus(BaseModel):
    """Safe operator/user view of the research-only provider boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool
    reachable: bool | None
    credentials_required: bool = False
    trading_supported: bool = False
    base_url: str
    perpetual_count: int | None = None
    checked_at: datetime
    provider_timestamp: datetime | None = None
    message: str


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@binance_futures_router.get(
    "/symbols", response_model=ProviderResponse[FuturesSymbolsData]
)
async def symbols(
    response: Response, service: ServiceDependency
) -> ProviderResponse[FuturesSymbolsData]:
    _no_store(response)
    return await service.symbols()


@binance_futures_router.get("/status", response_model=FuturesProviderStatus)
async def status(
    request: Request,
    response: Response,
    settings: SettingsDependency,
) -> FuturesProviderStatus:
    """Report feature state and perform one cached public reachability read."""
    _no_store(response)
    checked_at = datetime.now(UTC)
    service = getattr(request.app.state, "binance_futures_service", None)
    if not settings.binance_futures_enabled or not isinstance(
        service, BinanceFuturesService
    ):
        return FuturesProviderStatus(
            enabled=False,
            reachable=None,
            base_url=settings.binance_futures_base_url,
            checked_at=checked_at,
            message="Public Futures research is disabled on this deployment.",
        )
    try:
        available = await service.symbols()
    except ProviderUnavailableError:
        return FuturesProviderStatus(
            enabled=True,
            reachable=False,
            base_url=settings.binance_futures_base_url,
            checked_at=checked_at,
            message="The public Futures host is temporarily unreachable.",
        )
    return FuturesProviderStatus(
        enabled=True,
        reachable=True,
        base_url=settings.binance_futures_base_url,
        perpetual_count=len(available.data.symbols),
        checked_at=checked_at,
        provider_timestamp=available.meta.source_timestamp,
        message="Public read-only Futures research is available.",
    )


@binance_futures_router.get(
    "/{symbol}/market", response_model=ProviderResponse[FuturesMarketData]
)
async def market(
    symbol: SymbolPath, response: Response, service: ServiceDependency
) -> ProviderResponse[FuturesMarketData]:
    _no_store(response)
    return await service.market(symbol)


@binance_futures_router.get(
    "/{symbol}/funding", response_model=ProviderResponse[FuturesFundingData]
)
async def funding(
    symbol: SymbolPath,
    response: Response,
    service: ServiceDependency,
    limit: LimitQuery = 30,
) -> ProviderResponse[FuturesFundingData]:
    _no_store(response)
    return await service.funding(symbol, limit)


@binance_futures_router.get(
    "/{symbol}/open-interest",
    response_model=AnalyticsResponse[FuturesOpenInterestData],
)
async def open_interest(
    symbol: SymbolPath,
    response: Response,
    service: ServiceDependency,
    period: PeriodQuery = FuturesPeriod.ONE_HOUR,
    limit: LimitQuery = 30,
) -> AnalyticsResponse[FuturesOpenInterestData]:
    _no_store(response)
    return await service.open_interest(symbol, period, limit)


@binance_futures_router.get(
    "/{symbol}/positioning",
    response_model=AnalyticsResponse[FuturesPositioningData],
)
async def positioning(
    symbol: SymbolPath,
    response: Response,
    service: ServiceDependency,
    period: PeriodQuery = FuturesPeriod.ONE_HOUR,
    limit: LimitQuery = 30,
) -> AnalyticsResponse[FuturesPositioningData]:
    _no_store(response)
    return await service.positioning(symbol, period, limit)


@binance_futures_router.get(
    "/{symbol}/basis", response_model=ProviderResponse[FuturesBasisData]
)
async def basis(
    symbol: SymbolPath,
    response: Response,
    service: ServiceDependency,
    period: PeriodQuery = FuturesPeriod.ONE_HOUR,
    limit: LimitQuery = 30,
) -> ProviderResponse[FuturesBasisData]:
    _no_store(response)
    return await service.basis(symbol, period, limit)


@binance_futures_router.get(
    "/{symbol}/risk", response_model=AnalyticsResponse[FuturesRisk]
)
async def risk(
    symbol: SymbolPath,
    response: Response,
    service: ServiceDependency,
    period: PeriodQuery = FuturesPeriod.ONE_HOUR,
    limit: LimitQuery = 30,
) -> AnalyticsResponse[FuturesRisk]:
    _no_store(response)
    research = await service.research(symbol, period, limit)
    if research.data.risk is None:
        raise ServiceUnavailableError(
            "Futures risk is unavailable because required public inputs are missing."
        )
    return AnalyticsResponse(data=research.data.risk, meta=research.meta)


@binance_futures_router.get(
    "/{symbol}/research", response_model=AnalyticsResponse[FuturesResearchData]
)
async def research(
    symbol: SymbolPath,
    response: Response,
    service: ServiceDependency,
    period: PeriodQuery = FuturesPeriod.ONE_HOUR,
    limit: LimitQuery = 30,
) -> AnalyticsResponse[FuturesResearchData]:
    _no_store(response)
    return await service.research(symbol, period, limit)
