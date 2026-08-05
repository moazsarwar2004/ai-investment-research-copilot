"""Stock service tests for licensing, exchange identity, and aggregation."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import AnyHttpUrl

from backend.app.cache import CacheStatus
from backend.app.providers import (
    DelayClass,
    Freshness,
    ProviderConfigurationError,
    ProviderMeta,
    ProviderProvenance,
    ProviderResponse,
    ProviderSchemaError,
)
from backend.app.providers.stocks import (
    StockCandlesData,
    StockExchange,
    StockInterval,
    StockMarketDataProvider,
    StockProfile,
    StockProviderLicense,
    StockQuote,
    StockSearchData,
    StockSearchResult,
)
from backend.app.services.stock_service import StockService
from backend.app.tests.test_stock_analytics import stock_candles, stock_quote


def _meta(operation: str) -> ProviderMeta:
    timestamp = datetime(2025, 8, 8, 10, 0, tzinfo=UTC)
    return ProviderMeta(
        source="licensed-fixture",
        source_timestamp=timestamp,
        fetched_at=timestamp,
        cache_status=CacheStatus.MISS,
        freshness=Freshness.DELAYED,
        staleness_seconds=900,
        partial=False,
        warnings=[],
        delay_class=DelayClass.OFFLINE,
        provenance=ProviderProvenance(
            provider="licensed-fixture",
            operation=operation,
            source_url=AnyHttpUrl("https://example.invalid/offline-stock-fixture"),
            raw_payload_sha256="a" * 64,
            schema_version="stock-fixture-v1",
            terms_review_version="test-license-2025-08-08",
            attribution="Dated offline demonstration data",
        ),
    )


class FixtureStockProvider(StockMarketDataProvider):
    def __init__(self, *, authorized: bool = True) -> None:
        self.license = StockProviderLicense(
            provider="Fixture Stock Data",
            plan="Offline test fixture",
            terms_url=AnyHttpUrl("https://example.invalid/fixture-terms"),
            terms_reviewed_on=date(2025, 8, 8),
            display_authorized=authorized,
            quote_delay_minutes=15,
            attribution="Dated offline demonstration data",
        )
        self.calls: list[tuple[str, StockExchange, str]] = []

    async def search(
        self,
        query: str,
        *,
        exchange: StockExchange,
    ) -> ProviderResponse[StockSearchData]:
        self.calls.append(("search", exchange, query))
        return ProviderResponse(
            data=StockSearchData(
                query=query,
                results=[
                    StockSearchResult(
                        symbol="OGDC",
                        company_name="Oil & Gas Development Company Limited",
                        exchange=exchange,
                        country="Pakistan",
                        provider_id=f"{exchange.value}:OGDC",
                    )
                ],
            ),
            meta=_meta("stocks.search"),
        )

    async def profile(
        self,
        exchange: StockExchange,
        symbol: str,
    ) -> ProviderResponse[StockProfile]:
        self.calls.append(("profile", exchange, symbol))
        return ProviderResponse(
            data=StockProfile(
                symbol=symbol,
                company_name="Oil & Gas Development Company Limited",
                exchange=exchange,
                currency="PKR",
                country="Pakistan",
                sector="Oil and gas",
                industry="Exploration and production",
                provider_id=f"{exchange.value}:{symbol}",
            ),
            meta=_meta("stocks.profile"),
        )

    async def quote(
        self,
        exchange: StockExchange,
        symbol: str,
    ) -> ProviderResponse[StockQuote]:
        self.calls.append(("quote", exchange, symbol))
        value = stock_quote().model_copy(
            update={"exchange": exchange, "symbol": symbol}
        )
        return ProviderResponse(data=value, meta=_meta("stocks.quote"))

    async def candles(
        self,
        exchange: StockExchange,
        symbol: str,
        *,
        interval: StockInterval,
        days: int,
    ) -> ProviderResponse[StockCandlesData]:
        self.calls.append(("candles", exchange, symbol))
        value = stock_candles().model_copy(
            update={
                "exchange": exchange,
                "symbol": symbol,
                "interval": interval,
                "days": days,
            }
        )
        return ProviderResponse(data=value, meta=_meta("stocks.candles"))


async def test_unavailable_service_is_safe_and_exchange_neutral() -> None:
    service = StockService()

    psx = await service.research(
        StockExchange.PSX,
        "OGDC",
        interval=StockInterval.DAY,
        days=365,
    )
    nasdaq = await service.research(
        StockExchange.NASDAQ,
        "AAPL",
        interval=StockInterval.DAY,
        days=365,
    )

    assert psx.data.exchange is StockExchange.PSX
    assert psx.data.symbol == "OGDC"
    assert psx.data.quote is None
    assert psx.meta.freshness is Freshness.UNAVAILABLE
    assert psx.meta.partial is True
    assert psx.data.license.display_authorized is False
    assert nasdaq.data.exchange is StockExchange.NASDAQ
    assert nasdaq.data.symbol == "AAPL"


def test_provider_activation_requires_recorded_display_rights() -> None:
    with pytest.raises(ProviderConfigurationError, match="display rights"):
        StockService(FixtureStockProvider(authorized=False))


async def test_licensed_fixture_builds_stock_research_without_live_calls() -> None:
    provider = FixtureStockProvider()
    service = StockService(provider)

    result = await service.research(
        StockExchange.PSX,
        "OGDC",
        interval=StockInterval.DAY,
        days=365,
    )

    assert result.data.profile is not None
    assert result.data.quote is not None
    assert result.data.candles is not None
    assert result.data.technicals is not None
    assert result.data.technicals.sma_200 is not None
    assert result.data.trend is not None
    assert result.data.risk is not None
    assert result.data.license.display_authorized is True
    assert result.meta.source == "licensed-fixture"
    assert result.meta.freshness is Freshness.DELAYED
    assert {call[0] for call in provider.calls} == {"profile", "quote", "candles"}


async def test_search_preserves_explicit_exchange_identity() -> None:
    provider = FixtureStockProvider()
    service = StockService(provider)

    result = await service.search("oil gas", exchange=StockExchange.PSX)

    assert result.data.exchange is StockExchange.PSX
    assert result.data.results[0].provider_id == "PSX:OGDC"
    assert provider.calls == [("search", StockExchange.PSX, "oil gas")]


async def test_provider_cannot_cross_exchange_identity_boundaries() -> None:
    class WrongExchangeProvider(FixtureStockProvider):
        async def quote(
            self,
            exchange: StockExchange,
            symbol: str,
        ) -> ProviderResponse[StockQuote]:
            response = await super().quote(exchange, symbol)
            return response.model_copy(
                update={
                    "data": response.data.model_copy(
                        update={"exchange": StockExchange.NYSE}
                    )
                }
            )

    service = StockService(WrongExchangeProvider())

    with pytest.raises(ProviderSchemaError, match="different canonical identity"):
        await service.research(
            StockExchange.PSX,
            "OGDC",
            interval=StockInterval.DAY,
            days=365,
        )
