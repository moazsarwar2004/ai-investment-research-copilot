"""HTTP contract tests for the public, read-only Binance Spot surface."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from httpx import AsyncClient

from backend.app.api.dependencies import get_binance_spot_service
from backend.app.cache import CacheStatus
from backend.app.providers import Freshness
from backend.app.providers.binance_spot import BinanceSpotInterval
from backend.app.services import (
    AggregateProviderMeta,
    AnalyticsResponse,
    SpotResearchData,
)


class StubResearchService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def research(self, symbol: str, **kwargs: Any) -> Any:
        self.calls.append({"symbol": symbol, **kwargs})
        return AnalyticsResponse[SpotResearchData](
            data=SpotResearchData(
                symbol=symbol.upper(),
                interval=kwargs["interval"],
                ticker=None,
                candles=None,
                order_book=None,
                trades=None,
                technicals=None,
                risk=None,
            ),
            meta=AggregateProviderMeta(
                source_timestamp=datetime(2026, 7, 24, 12, 0, tzinfo=UTC),
                fetched_at=datetime(2026, 7, 24, 12, 0, tzinfo=UTC),
                cache_status=CacheStatus.STALE,
                freshness=Freshness.STALE,
                staleness_seconds=30,
                partial=True,
                warnings=[],
                sources=[],
            ),
        )


async def test_research_route_preserves_partial_and_stale_ui_contract(
    application: FastAPI,
    client: AsyncClient,
) -> None:
    service = StubResearchService()
    application.dependency_overrides[get_binance_spot_service] = lambda: service

    response = await client.get(
        "/api/v1/binance/spot/btcusdt/research",
        params={
            "interval": "4h",
            "candle_limit": 200,
            "book_limit": 50,
            "trade_limit": 75,
            "slippage_notional_quote": "2500",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["symbol"] == "BTCUSDT"
    assert payload["data"]["interval"] == "4h"
    assert payload["meta"]["partial"] is True
    assert payload["meta"]["freshness"] == "stale"
    assert payload["meta"]["cache_status"] == "stale"
    assert response.headers["cache-control"] == "no-store"
    assert service.calls[0]["interval"] is BinanceSpotInterval.FOUR_HOURS
    assert service.calls[0]["book_limit"] == 50


async def test_binance_query_bounds_fail_before_provider_work(
    application: FastAPI,
    client: AsyncClient,
) -> None:
    service = StubResearchService()
    application.dependency_overrides[get_binance_spot_service] = lambda: service

    invalid_interval = await client.get(
        "/api/v1/binance/spot/BTCUSDT/research?interval=30m"
    )
    amplified_depth = await client.get(
        "/api/v1/binance/spot/BTCUSDT/research?book_limit=500"
    )
    invalid_symbol = await client.get("/api/v1/binance/spot/BTC-USDT/research")

    assert invalid_interval.status_code == 422
    assert amplified_depth.status_code == 422
    assert invalid_symbol.status_code == 422
    assert service.calls == []


async def test_binance_routes_are_documented_and_service_can_be_disabled(
    application: FastAPI,
    client: AsyncClient,
) -> None:
    response = await client.get("/api/v1/binance/spot/symbols")
    openapi = (await client.get("/openapi.json")).json()

    assert response.status_code == 503
    assert response.json()["errors"][0]["code"] == "SERVICE_UNAVAILABLE"
    expected_paths = {
        "/api/v1/binance/spot/symbols",
        "/api/v1/binance/spot/{symbol}/ticker",
        "/api/v1/binance/spot/{symbol}/candles",
        "/api/v1/binance/spot/{symbol}/order-book",
        "/api/v1/binance/spot/{symbol}/trades",
        "/api/v1/binance/spot/{symbol}/technicals",
        "/api/v1/binance/spot/{symbol}/risk",
        "/api/v1/binance/spot/{symbol}/research",
    }
    assert expected_paths <= set(openapi["paths"])
    assert not any(
        term in path
        for path in openapi["paths"]
        for term in ("order", "account", "balance", "withdraw", "position")
        if "/order-book" not in path
    )
