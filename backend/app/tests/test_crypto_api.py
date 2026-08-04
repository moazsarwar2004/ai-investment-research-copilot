"""HTTP contract tests for the public general-crypto surface."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import FastAPI
from httpx import AsyncClient

from backend.app.analytics.crypto import CryptoRisk
from backend.app.api.dependencies import get_crypto_service
from backend.app.cache import CacheStatus
from backend.app.providers import Freshness
from backend.app.providers.coingecko import CryptoMarket
from backend.app.services import (
    AggregateProviderMeta,
    AnalyticsResponse,
    CryptoResearchData,
)


class StubCryptoService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def research(self, coin_id: str, **kwargs: Any) -> Any:
        self.calls.append({"coin_id": coin_id, **kwargs})
        return AnalyticsResponse[CryptoResearchData](
            data=CryptoResearchData(
                coin_id=coin_id,
                days=kwargs["days"],
                overview=CryptoMarket(
                    coin_id=coin_id,
                    symbol="BTC",
                    name="Bitcoin",
                    current_price=Decimal("119000"),
                    market_cap=Decimal("2360000000000"),
                    market_cap_rank=1,
                    total_volume_24h=Decimal("45000000000"),
                    high_24h=Decimal("121000"),
                    low_24h=Decimal("116500"),
                    all_time_high=Decimal("126000"),
                    distance_from_ath_percent=Decimal("5.55"),
                    all_time_low=Decimal("67.81"),
                    last_updated=datetime(2026, 8, 4, 8, 0, tzinfo=UTC),
                ),
                history=None,
                technicals=None,
                trend=None,
                anomalies=None,
                risk=CryptoRisk(
                    overall_score=20,
                    risk_label="low",
                    component_scores={"liquidity": 10, "market_size": 30},
                    component_weights={"liquidity": 0.5, "market_size": 0.5},
                    data_confidence=0.3,
                    missing_inputs=[
                        "volatility",
                        "drawdown",
                        "trend_instability",
                        "anomaly",
                    ],
                    limitations=["Fixture response."],
                ),
            ),
            meta=AggregateProviderMeta(
                source="coingecko",
                source_timestamp=datetime(2026, 8, 4, 8, 0, tzinfo=UTC),
                fetched_at=datetime(2026, 8, 4, 8, 1, tzinfo=UTC),
                cache_status=CacheStatus.MISS,
                freshness=Freshness.DELAYED,
                staleness_seconds=60,
                partial=True,
                warnings=[],
                sources=[],
            ),
        )


async def test_crypto_research_route_preserves_id_range_and_source_contract(
    application: FastAPI,
    client: AsyncClient,
) -> None:
    service = StubCryptoService()
    application.dependency_overrides[get_crypto_service] = lambda: service

    response = await client.get("/api/v1/crypto/bitcoin/research?days=365")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["coin_id"] == "bitcoin"
    assert payload["data"]["days"] == 365
    assert payload["data"]["attribution"] == "Powered by CoinGecko"
    assert payload["meta"]["source"] == "coingecko"
    assert payload["meta"]["partial"] is True
    assert response.headers["cache-control"] == "no-store"
    assert service.calls == [{"coin_id": "bitcoin", "days": 365}]


async def test_crypto_identity_and_range_bounds_fail_before_service_work(
    application: FastAPI,
    client: AsyncClient,
) -> None:
    service = StubCryptoService()
    application.dependency_overrides[get_crypto_service] = lambda: service

    uppercase_symbol = await client.get("/api/v1/crypto/BTC/research")
    slash_pair = await client.get("/api/v1/crypto/BTC-USDT/research")
    excessive_history = await client.get("/api/v1/crypto/bitcoin/research?days=2000")

    assert uppercase_symbol.status_code == 422
    assert slash_pair.status_code == 422
    assert excessive_history.status_code == 422
    assert service.calls == []


async def test_crypto_routes_are_documented_and_service_can_be_disabled(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/v1/crypto/global")
    openapi = (await client.get("/openapi.json")).json()

    assert response.status_code == 503
    assert response.json()["errors"][0]["code"] == "SERVICE_UNAVAILABLE"
    expected_paths = {
        "/api/v1/crypto/search",
        "/api/v1/crypto/global",
        "/api/v1/crypto/trending",
        "/api/v1/crypto/markets",
        "/api/v1/crypto/{coin_id}",
        "/api/v1/crypto/{coin_id}/history",
        "/api/v1/crypto/{coin_id}/technicals",
        "/api/v1/crypto/{coin_id}/trend",
        "/api/v1/crypto/{coin_id}/anomalies",
        "/api/v1/crypto/{coin_id}/risk",
        "/api/v1/crypto/{coin_id}/research",
    }
    assert expected_paths <= set(openapi["paths"])
