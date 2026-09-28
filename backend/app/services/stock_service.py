"""License-gated stock identity, market-data, and analytics use cases."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable
from datetime import UTC, date, datetime

from pydantic import BaseModel, ConfigDict, Field

from backend.app.analytics.stock_fundamentals import (
    FinancialRatios,
    FundamentalRisk,
    build_fundamental_risk,
    calculate_financial_ratios,
)
from backend.app.analytics.stocks import (
    StockRisk,
    StockTechnicalAnalysis,
    StockTrendAnalysis,
    analyze_stock_technicals,
    build_stock_risk,
    build_stock_trend,
)
from backend.app.cache import CacheStatus
from backend.app.core.exceptions import (
    ApplicationValidationError,
    ResourceNotFoundError,
)
from backend.app.providers import (
    Freshness,
    ProviderConfigurationError,
    ProviderMeta,
    ProviderProvenance,
    ProviderResponse,
    ProviderSchemaError,
    ProviderUnavailableError,
    ProviderWarning,
)
from backend.app.providers.stock_fundamentals import (
    CompanyReport,
    FinancialPeriod,
    FundamentalModel,
    StockDataMode,
    StockFundamentalsProvider,
    StockFundamentalsSnapshot,
)
from backend.app.providers.stocks import (
    StockCandlesData,
    StockExchange,
    StockInterval,
    StockLicenseDisclosure,
    StockMarketDataProvider,
    StockMarketDataStatus,
    StockProfile,
    StockProviderLicense,
    StockQuote,
    StockSearchResult,
)
from backend.app.services.binance_spot_service import (
    AggregateProviderMeta,
    AnalyticsResponse,
)

STOCK_DISCLAIMER = (
    "Research and education only. This is not personalized financial advice."
)
_UNAVAILABLE_MESSAGE = (
    "Stock quotes and candles are unavailable because no provider with reviewed "
    "multi-user display rights is configured. Official-report fundamentals and "
    "private user-supplied price analysis remain independent."
)
_SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{0,5}(?:[.-][A-Z0-9]{1,4})?$")


class _StockServiceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class StockSearchView(_StockServiceModel):
    query: str
    exchange: StockExchange
    results: list[StockSearchResult]
    market_data_status: StockMarketDataStatus
    license: StockLicenseDisclosure


class StockOverviewData(_StockServiceModel):
    symbol: str
    exchange: StockExchange
    profile: StockProfile | None
    quote: StockQuote | None
    market_data_status: StockMarketDataStatus
    license: StockLicenseDisclosure


class StockCandlesResult(_StockServiceModel):
    symbol: str
    exchange: StockExchange
    interval: StockInterval
    days: int
    candles: StockCandlesData | None
    market_data_status: StockMarketDataStatus
    license: StockLicenseDisclosure


class StockTechnicalsResult(_StockServiceModel):
    symbol: str
    exchange: StockExchange
    interval: StockInterval
    days: int
    technicals: StockTechnicalAnalysis | None
    market_data_status: StockMarketDataStatus
    license: StockLicenseDisclosure


class StockTrendResult(_StockServiceModel):
    symbol: str
    exchange: StockExchange
    interval: StockInterval
    days: int
    trend: StockTrendAnalysis | None
    market_data_status: StockMarketDataStatus
    license: StockLicenseDisclosure


class StockRiskResult(_StockServiceModel):
    symbol: str
    exchange: StockExchange
    interval: StockInterval
    days: int
    risk: StockRisk | None
    market_data_status: StockMarketDataStatus
    license: StockLicenseDisclosure


class StockFundamentalsView(_StockServiceModel):
    symbol: str
    exchange: StockExchange
    profile: StockProfile
    fundamental_model: FundamentalModel
    periods: list[FinancialPeriod]
    ratios: list[FinancialRatios]
    reports: list[CompanyReport]
    risk: FundamentalRisk | None
    source_warnings: list[str]
    data_mode: str = StockDataMode.OFFICIAL_REPORTS


class StockFinancialsResult(_StockServiceModel):
    symbol: str
    exchange: StockExchange
    periods: list[FinancialPeriod]


class StockRatiosResult(_StockServiceModel):
    symbol: str
    exchange: StockExchange
    ratios: list[FinancialRatios]


class StockReportsResult(_StockServiceModel):
    symbol: str
    exchange: StockExchange
    reports: list[CompanyReport]


class StockResearchData(_StockServiceModel):
    symbol: str
    exchange: StockExchange
    interval: StockInterval
    days: int
    profile: StockProfile | None
    quote: StockQuote | None
    candles: StockCandlesData | None
    technicals: StockTechnicalAnalysis | None
    trend: StockTrendAnalysis | None
    risk: StockRisk | None
    fundamentals: StockFundamentalsView | None = None
    data_modes: list[str] = Field(default_factory=list)
    market_data_status: StockMarketDataStatus
    license: StockLicenseDisclosure
    disclaimer: str = STOCK_DISCLAIMER


def validate_stock_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if not _SYMBOL_PATTERN.fullmatch(normalized):
        raise ApplicationValidationError(
            "Stock symbols must use 1-11 uppercase letters/digits with at most "
            "one dot or hyphen class suffix."
        )
    return normalized


def _normalize_query(query: str) -> str:
    normalized = " ".join(query.strip().split())
    if not 1 <= len(normalized) <= 80:
        raise ApplicationValidationError("Stock search must contain 1-80 characters.")
    return normalized


def _require_identity(
    data: StockProfile | StockQuote | StockCandlesData,
    *,
    exchange: StockExchange,
    symbol: str,
) -> None:
    if data.exchange is not exchange or data.symbol != symbol:
        raise ProviderSchemaError(
            "The stock provider returned data for a different canonical identity."
        )


def _unavailable_license() -> StockLicenseDisclosure:
    return StockLicenseDisclosure(
        status=StockMarketDataStatus.UNAVAILABLE,
        display_authorized=False,
        message=_UNAVAILABLE_MESSAGE,
    )


def _license_disclosure(value: StockProviderLicense) -> StockLicenseDisclosure:
    return StockLicenseDisclosure(
        status=StockMarketDataStatus.AVAILABLE,
        display_authorized=True,
        provider=value.provider,
        plan=value.plan,
        terms_url=value.terms_url,
        terms_reviewed_on=value.terms_reviewed_on,
        quote_delay_minutes=value.quote_delay_minutes,
        quote_data_kind=value.quote_data_kind,
        history_data_kind=value.history_data_kind,
        authorization_reference=value.authorization_reference,
        authorization_scope=value.authorization_scope,
        authorization_expires_on=value.authorization_expires_on,
        attribution=value.attribution,
        message=(
            f"{value.provider} {value.plan} display rights were reviewed on "
            f"{value.terms_reviewed_on.isoformat()}; quote class is "
            f"{value.quote_data_kind.value} and history class is "
            f"{value.history_data_kind.value}."
        ),
    )


def _unavailable_meta() -> AggregateProviderMeta:
    return AggregateProviderMeta(
        source="unavailable",
        source_timestamp=None,
        fetched_at=datetime.now(UTC),
        cache_status=CacheStatus.BYPASS,
        freshness=Freshness.UNAVAILABLE,
        staleness_seconds=0,
        partial=True,
        warnings=[
            ProviderWarning(
                code="stock_market_data_unavailable",
                message=_UNAVAILABLE_MESSAGE,
            )
        ],
        sources=[],
    )


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
    warning_codes: set[str] = set()
    for meta in metas:
        for warning in meta.warnings:
            if warning.code not in warning_codes:
                warnings.append(warning)
                warning_codes.add(warning.code)
    for operation in missing:
        code = f"stock_{operation}_unavailable"
        if code not in warning_codes:
            warnings.append(
                ProviderWarning(
                    code=code,
                    message=f"The stock {operation} component is unavailable.",
                )
            )
            warning_codes.add(code)
    sources: list[ProviderProvenance] = []
    source_keys: set[tuple[str, str]] = set()
    for meta in metas:
        key = (meta.provenance.operation, meta.provenance.raw_payload_sha256)
        if key not in source_keys:
            sources.append(meta.provenance)
            source_keys.add(key)
    source_times = [item.source_timestamp for item in metas if item.source_timestamp]
    return AggregateProviderMeta(
        source=metas[0].source,
        source_timestamp=min(source_times) if source_times else None,
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
    except (ProviderUnavailableError, ResourceNotFoundError):
        return None, operation


class StockService:
    """Combine license-gated prices with independent official fundamentals."""

    def __init__(
        self,
        provider: StockMarketDataProvider | None = None,
        fundamentals_provider: StockFundamentalsProvider | None = None,
    ) -> None:
        if provider is not None and not provider.license.display_authorized:
            raise ProviderConfigurationError(
                "A stock provider cannot be activated without reviewed display rights."
            )
        self._provider = provider
        self._fundamentals_provider = fundamentals_provider

    @staticmethod
    def _fundamental_view(
        snapshot: StockFundamentalsSnapshot,
    ) -> StockFundamentalsView:
        ratios = calculate_financial_ratios(
            snapshot.periods,
            fundamental_model=snapshot.fundamental_model,
        )
        risk = build_fundamental_risk(
            snapshot.periods,
            ratios,
            report_warning_count=len(snapshot.source_warnings),
            fundamental_model=snapshot.fundamental_model,
        )
        return StockFundamentalsView(
            symbol=snapshot.symbol,
            exchange=snapshot.exchange,
            profile=snapshot.profile,
            fundamental_model=snapshot.fundamental_model,
            periods=snapshot.periods,
            ratios=ratios,
            reports=sorted(
                snapshot.reports,
                key=lambda item: (
                    item.published_at or item.approved_at or item.period_end or date.min
                ),
                reverse=True,
            ),
            risk=risk,
            source_warnings=snapshot.source_warnings,
        )

    async def _get_fundamentals(
        self, exchange: StockExchange, symbol: str
    ) -> ProviderResponse[StockFundamentalsSnapshot]:
        if self._fundamentals_provider is None:
            raise ResourceNotFoundError(
                "Official fundamentals are not configured for this company."
            )
        response = await self._fundamentals_provider.fundamentals(exchange, symbol)
        if response.data.exchange is not exchange or response.data.symbol != symbol:
            raise ProviderSchemaError(
                "The fundamentals provider returned a different canonical identity."
            )
        return response

    @property
    def _status(self) -> StockMarketDataStatus:
        return (
            StockMarketDataStatus.AVAILABLE
            if self._provider is not None
            else StockMarketDataStatus.UNAVAILABLE
        )

    @property
    def _license(self) -> StockLicenseDisclosure:
        if self._provider is None:
            return _unavailable_license()
        return _license_disclosure(self._provider.license)

    async def search(
        self,
        query: str,
        *,
        exchange: StockExchange,
    ) -> AnalyticsResponse[StockSearchView]:
        normalized = _normalize_query(query)
        if self._provider is None:
            return AnalyticsResponse(
                data=StockSearchView(
                    query=normalized,
                    exchange=exchange,
                    results=[],
                    market_data_status=self._status,
                    license=self._license,
                ),
                meta=_unavailable_meta(),
            )
        response = await self._provider.search(normalized, exchange=exchange)
        if any(item.exchange is not exchange for item in response.data.results):
            raise ProviderSchemaError(
                "The stock search provider returned a cross-exchange identity."
            )
        return AnalyticsResponse(
            data=StockSearchView(
                query=response.data.query,
                exchange=exchange,
                results=response.data.results,
                market_data_status=self._status,
                license=self._license,
            ),
            meta=_aggregate_meta([response.meta]),
        )

    async def overview(
        self,
        exchange: StockExchange,
        symbol: str,
    ) -> AnalyticsResponse[StockOverviewData]:
        normalized = validate_stock_symbol(symbol)
        if self._provider is None:
            return AnalyticsResponse(
                data=StockOverviewData(
                    symbol=normalized,
                    exchange=exchange,
                    profile=None,
                    quote=None,
                    market_data_status=self._status,
                    license=self._license,
                ),
                meta=_unavailable_meta(),
            )
        profile_result, quote_result = await asyncio.gather(
            _capture("profile", self._provider.profile(exchange, normalized)),
            _capture("quote", self._provider.quote(exchange, normalized)),
        )
        profile, profile_missing = profile_result
        quote, quote_missing = quote_result
        if profile is not None:
            _require_identity(profile.data, exchange=exchange, symbol=normalized)
        if quote is not None:
            _require_identity(quote.data, exchange=exchange, symbol=normalized)
        metas = [item.meta for item in (profile, quote) if item is not None]
        missing = [item for item in (profile_missing, quote_missing) if item]
        return AnalyticsResponse(
            data=StockOverviewData(
                symbol=normalized,
                exchange=exchange,
                profile=profile.data if profile else None,
                quote=quote.data if quote else None,
                market_data_status=self._status,
                license=self._license,
            ),
            meta=_aggregate_meta(metas, missing_operations=missing),
        )

    async def candles(
        self,
        exchange: StockExchange,
        symbol: str,
        *,
        interval: StockInterval,
        days: int,
    ) -> AnalyticsResponse[StockCandlesResult]:
        normalized = validate_stock_symbol(symbol)
        if self._provider is None:
            return AnalyticsResponse(
                data=StockCandlesResult(
                    symbol=normalized,
                    exchange=exchange,
                    interval=interval,
                    days=days,
                    candles=None,
                    market_data_status=self._status,
                    license=self._license,
                ),
                meta=_unavailable_meta(),
            )
        response = await self._provider.candles(
            exchange, normalized, interval=interval, days=days
        )
        _require_identity(response.data, exchange=exchange, symbol=normalized)
        return AnalyticsResponse(
            data=StockCandlesResult(
                symbol=normalized,
                exchange=exchange,
                interval=interval,
                days=days,
                candles=response.data,
                market_data_status=self._status,
                license=self._license,
            ),
            meta=_aggregate_meta([response.meta]),
        )

    async def technicals(
        self,
        exchange: StockExchange,
        symbol: str,
        *,
        interval: StockInterval,
        days: int,
    ) -> AnalyticsResponse[StockTechnicalsResult]:
        candles = await self.candles(exchange, symbol, interval=interval, days=days)
        analysis: StockTechnicalAnalysis | None = None
        if candles.data.candles is not None:
            try:
                analysis = analyze_stock_technicals(candles.data.candles)
            except ValueError as error:
                raise ApplicationValidationError(str(error)) from error
        return AnalyticsResponse(
            data=StockTechnicalsResult(
                symbol=candles.data.symbol,
                exchange=exchange,
                interval=interval,
                days=days,
                technicals=analysis,
                market_data_status=self._status,
                license=self._license,
            ),
            meta=candles.meta,
        )

    async def trend(
        self,
        exchange: StockExchange,
        symbol: str,
        *,
        interval: StockInterval,
        days: int,
    ) -> AnalyticsResponse[StockTrendResult]:
        technicals = await self.technicals(
            exchange, symbol, interval=interval, days=days
        )
        trend = (
            build_stock_trend(technicals.data.technicals)
            if technicals.data.technicals is not None
            else None
        )
        return AnalyticsResponse(
            data=StockTrendResult(
                symbol=technicals.data.symbol,
                exchange=exchange,
                interval=interval,
                days=days,
                trend=trend,
                market_data_status=self._status,
                license=self._license,
            ),
            meta=technicals.meta,
        )

    async def risk(
        self,
        exchange: StockExchange,
        symbol: str,
        *,
        interval: StockInterval,
        days: int,
    ) -> AnalyticsResponse[StockRiskResult]:
        research = await self.research(exchange, symbol, interval=interval, days=days)
        return AnalyticsResponse(
            data=StockRiskResult(
                symbol=research.data.symbol,
                exchange=exchange,
                interval=interval,
                days=days,
                risk=research.data.risk,
                market_data_status=self._status,
                license=self._license,
            ),
            meta=research.meta,
        )

    async def financials(
        self, exchange: StockExchange, symbol: str
    ) -> AnalyticsResponse[StockFinancialsResult]:
        normalized = validate_stock_symbol(symbol)
        response = await self._get_fundamentals(exchange, normalized)
        return AnalyticsResponse(
            data=StockFinancialsResult(
                symbol=normalized,
                exchange=exchange,
                periods=response.data.periods,
            ),
            meta=_aggregate_meta([response.meta]),
        )

    async def ratios(
        self, exchange: StockExchange, symbol: str
    ) -> AnalyticsResponse[StockRatiosResult]:
        normalized = validate_stock_symbol(symbol)
        response = await self._get_fundamentals(exchange, normalized)
        return AnalyticsResponse(
            data=StockRatiosResult(
                symbol=normalized,
                exchange=exchange,
                ratios=calculate_financial_ratios(
                    response.data.periods,
                    fundamental_model=response.data.fundamental_model,
                ),
            ),
            meta=_aggregate_meta([response.meta]),
        )

    async def reports(
        self, exchange: StockExchange, symbol: str
    ) -> AnalyticsResponse[StockReportsResult]:
        normalized = validate_stock_symbol(symbol)
        response = await self._get_fundamentals(exchange, normalized)
        return AnalyticsResponse(
            data=StockReportsResult(
                symbol=normalized,
                exchange=exchange,
                reports=sorted(
                    response.data.reports,
                    key=lambda item: (
                        item.published_at
                        or item.approved_at
                        or item.period_end
                        or date.min
                    ),
                    reverse=True,
                ),
            ),
            meta=_aggregate_meta([response.meta]),
        )

    async def research(
        self,
        exchange: StockExchange,
        symbol: str,
        *,
        interval: StockInterval,
        days: int,
    ) -> AnalyticsResponse[StockResearchData]:
        normalized = validate_stock_symbol(symbol)
        if self._provider is None and self._fundamentals_provider is None:
            return AnalyticsResponse(
                data=StockResearchData(
                    symbol=normalized,
                    exchange=exchange,
                    interval=interval,
                    days=days,
                    profile=None,
                    quote=None,
                    candles=None,
                    technicals=None,
                    trend=None,
                    risk=None,
                    fundamentals=None,
                    data_modes=[],
                    market_data_status=self._status,
                    license=self._license,
                ),
                meta=_unavailable_meta(),
            )
        profile_result: tuple[ProviderResponse[StockProfile] | None, str | None]
        quote_result: tuple[ProviderResponse[StockQuote] | None, str | None]
        candles_result: tuple[ProviderResponse[StockCandlesData] | None, str | None]
        if self._provider is None:
            profile_result = (None, "profile")
            quote_result = (None, "quote")
            candles_result = (None, "candles")
        else:
            profile_result, quote_result, candles_result = await asyncio.gather(
                _capture("profile", self._provider.profile(exchange, normalized)),
                _capture("quote", self._provider.quote(exchange, normalized)),
                _capture(
                    "candles",
                    self._provider.candles(
                        exchange, normalized, interval=interval, days=days
                    ),
                ),
            )
        fundamentals, fundamentals_missing = await _capture(
            "fundamentals", self._get_fundamentals(exchange, normalized)
        )
        profile, profile_missing = profile_result
        quote, quote_missing = quote_result
        candles, candles_missing = candles_result
        for response in (profile, quote, candles):
            if response is not None:
                _require_identity(
                    response.data,
                    exchange=exchange,
                    symbol=normalized,
                )
        technicals: StockTechnicalAnalysis | None = None
        if candles is not None and len(candles.data.candles) >= 20:
            technicals = analyze_stock_technicals(candles.data)
        trend = build_stock_trend(technicals) if technicals is not None else None
        risk = (
            build_stock_risk(
                quote=quote.data if quote else None,
                technicals=technicals,
                freshness_confidence=(
                    0.6
                    if any(
                        item is not None and item.meta.freshness is Freshness.STALE
                        for item in (profile, quote, candles)
                    )
                    else 1.0
                ),
            )
            if quote is not None or technicals is not None
            else None
        )
        missing = [
            item
            for item in (profile_missing, quote_missing, candles_missing)
            if item is not None
        ]
        if candles is not None and technicals is None:
            missing.append("technicals")
        metas = [item.meta for item in (profile, quote, candles) if item is not None]
        if fundamentals is not None:
            metas.append(fundamentals.meta)
        if fundamentals_missing is not None:
            missing.append(fundamentals_missing)
        if not metas:
            return AnalyticsResponse(
                data=StockResearchData(
                    symbol=normalized,
                    exchange=exchange,
                    interval=interval,
                    days=days,
                    profile=None,
                    quote=None,
                    candles=None,
                    technicals=None,
                    trend=None,
                    risk=None,
                    fundamentals=None,
                    data_modes=[],
                    market_data_status=self._status,
                    license=self._license,
                ),
                meta=_unavailable_meta(),
            )
        fundamental_view = (
            self._fundamental_view(fundamentals.data)
            if fundamentals is not None
            else None
        )
        modes: list[str] = []
        if fundamentals is not None:
            modes.append(StockDataMode.OFFICIAL_REPORTS)
        if any(item is not None for item in (quote, candles)):
            if any(
                item is not None and item.meta.delay_class.value == "offline"
                for item in (quote, candles)
            ):
                modes.append(StockDataMode.OFFLINE_DEMO)
            else:
                modes.append(StockDataMode.LICENSED_PROVIDER)
        return AnalyticsResponse(
            data=StockResearchData(
                symbol=normalized,
                exchange=exchange,
                interval=interval,
                days=days,
                profile=(
                    profile.data
                    if profile
                    else fundamental_view.profile if fundamental_view else None
                ),
                quote=quote.data if quote else None,
                candles=candles.data if candles else None,
                technicals=technicals,
                trend=trend,
                risk=risk,
                fundamentals=fundamental_view,
                data_modes=modes,
                market_data_status=self._status,
                license=self._license,
            ),
            meta=_aggregate_meta(metas, missing_operations=missing),
        )


__all__ = [
    "STOCK_DISCLAIMER",
    "StockCandlesResult",
    "StockFinancialsResult",
    "StockFundamentalsView",
    "StockOverviewData",
    "StockRatiosResult",
    "StockReportsResult",
    "StockResearchData",
    "StockRiskResult",
    "StockSearchView",
    "StockService",
    "StockTechnicalsResult",
    "StockTrendResult",
    "validate_stock_symbol",
]
