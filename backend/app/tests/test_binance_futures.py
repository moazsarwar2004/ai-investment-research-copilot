"""Synthetic public-response fixtures: no live calls or prices used in CI."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import AnyHttpUrl, ValidationError
from streamlit.testing.v1 import AppTest

from backend.app.analytics.binance_futures import analyze_futures, build_futures_risk
from backend.app.api.dependencies import get_binance_futures_service
from backend.app.cache import CacheStatus
from backend.app.core.config import Settings
from backend.app.core.exceptions import (
    ApplicationValidationError,
    ResourceNotFoundError,
)
from backend.app.providers import (
    AssetType,
    CanonicalAsset,
    Freshness,
    ProviderHttpResponse,
    ProviderManager,
    ProviderMeta,
    ProviderProvenance,
    ProviderRequest,
    ProviderResponse,
    ProviderSchemaError,
    ProviderUnavailableError,
)
from backend.app.providers.adapters import ProviderAdapter
from backend.app.providers.binance_futures import (
    BinanceFuturesBasisAdapter,
    BinanceFuturesFundingAdapter,
    FuturesPeriod,
)
from backend.app.services.binance_futures_service import BinanceFuturesService
from frontend.client import ResearchApiError, fetch_futures_research
from frontend.state import ResearchViewState, classify_futures_state

NOW = datetime(2026, 9, 28, 0, 0, tzinfo=UTC)
BASE = "https://fapi.binance.com"


def stamp(hours_ago: int = 0) -> int:
    return int((NOW - timedelta(hours=hours_ago)).timestamp() * 1000)


@pytest.fixture
def payloads() -> dict[str, Any]:
    """Small invented values with official field shapes, for tests only."""
    return {
        "futures.symbols": {
            "serverTime": stamp(),
            "symbols": [
                {
                    "symbol": "BTCUSDT",
                    "pair": "BTCUSDT",
                    "contractType": "PERPETUAL",
                    "status": "TRADING",
                    "baseAsset": "BTC",
                    "quoteAsset": "USDT",
                    "marginAsset": "USDT",
                },
                {
                    "symbol": "BTCUSDT_261225",
                    "pair": "BTCUSDT",
                    "contractType": "CURRENT_QUARTER",
                    "status": "TRADING",
                    "baseAsset": "BTC",
                    "quoteAsset": "USDT",
                    "marginAsset": "USDT",
                },
            ],
        },
        "futures.market": {
            "symbol": "BTCUSDT",
            "markPrice": "101",
            "indexPrice": "100",
            "estimatedSettlePrice": "0",
            "lastFundingRate": "0.0001",
            "interestRate": "0.0001",
            "nextFundingTime": stamp(-8),
            "time": stamp(),
        },
        "futures.funding": [
            {
                "symbol": "BTCUSDT",
                "fundingTime": stamp(i * 8),
                "fundingRate": "0.0001",
                "markPrice": "100",
            }
            for i in range(4, -1, -1)
        ],
        "futures.open_interest.current": {
            "symbol": "BTCUSDT",
            "openInterest": "140",
            "time": stamp(),
        },
        "futures.open_interest.history": [
            {
                "symbol": "BTCUSDT",
                "sumOpenInterest": str(100 + i * 10),
                "sumOpenInterestValue": str(10000 + i * 2000),
                "timestamp": stamp(4 - i),
            }
            for i in range(5)
        ],
        "futures.basis": [
            {
                "pair": "BTCUSDT",
                "contractType": "PERPETUAL",
                "indexPrice": "100",
                "futuresPrice": "100.1",
                "basis": "0.1",
                "basisRate": "0.001",
                "annualizedBasisRate": "",
                "timestamp": stamp(4 - i),
            }
            for i in range(5)
        ],
        "futures.positioning.accounts": [
            {
                "symbol": "BTCUSDT",
                "longShortRatio": "1.5",
                "longAccount": "0.6",
                "shortAccount": "0.4",
                "timestamp": stamp(4 - i),
            }
            for i in range(5)
        ],
        "futures.positioning.taker": [
            {
                "buySellRatio": "1.5",
                "buyVol": "60",
                "sellVol": "40",
                "timestamp": stamp(4 - i),
            }
            for i in range(5)
        ],
    }


class FixtureManager:
    def __init__(self, data: dict[str, Any], failures: set[str] | None = None) -> None:
        self.data = data
        self.failures = failures or set()
        self.requests: list[ProviderRequest] = []
        self.stale = False

    async def fetch(
        self, adapter: ProviderAdapter[Any], request: ProviderRequest
    ) -> ProviderResponse[Any]:
        self.requests.append(request)
        if request.operation in self.failures:
            raise ProviderUnavailableError(cause_code="provider_timeout")
        outbound = adapter.build_request(request)
        assert outbound.method == "GET"
        assert outbound.headers == {}
        assert outbound.url.host == "fapi.binance.com"
        raw = ProviderHttpResponse(
            payload=self.data[request.operation],
            fetched_at=NOW,
            source_url=outbound.url,
            headers={},
            raw_payload_sha256="a" * 64,
            provider_request_id=None,
            attempts=1,
        )
        normalized = adapter.normalize(raw, request)
        return ProviderResponse(
            data=normalized.data,
            meta=ProviderMeta(
                source="binance_futures",
                source_timestamp=normalized.source_timestamp,
                fetched_at=NOW,
                cache_status=CacheStatus.STALE if self.stale else CacheStatus.MISS,
                freshness=Freshness.STALE if self.stale else Freshness.LIVE,
                staleness_seconds=max(
                    0, int((NOW - (normalized.source_timestamp or NOW)).total_seconds())
                ),
                partial=False,
                warnings=[],
                delay_class=normalized.delay_class,
                provenance=ProviderProvenance(
                    provider=adapter.provider,
                    operation=request.operation,
                    source_url=outbound.url,
                    provider_request_id=None,
                    raw_payload_sha256="a" * 64,
                    schema_version=adapter.schema_version,
                    terms_review_version=adapter.terms_review_version,
                    attribution=adapter.attribution,
                ),
            ),
        )


def service(manager: FixtureManager) -> BinanceFuturesService:
    return BinanceFuturesService(cast(ProviderManager, manager), base_url=BASE)


async def test_complete_research_has_correct_math_and_source_identity(
    payloads: dict[str, Any],
) -> None:
    manager = FixtureManager(payloads)
    result = await service(manager).research("btcusdt", FuturesPeriod.ONE_HOUR, 5)
    data = result.data
    assert data.analytics is not None
    assert data.analytics.annualized_funding_percent == pytest.approx(10.95)
    assert data.analytics.observed_funding_interval_hours == 8
    assert data.analytics.open_interest_change_percent == pytest.approx(40)
    assert data.analytics.basis_percent == pytest.approx(0.1)
    assert data.analytics.mark_index_premium_percent == pytest.approx(1)
    assert data.analytics.taker_buy_share_percent == 60
    assert data.basis and data.basis.points[-1].annualized_basis_rate is None
    assert data.risk and data.risk.data_confidence == 1
    assert sum(data.risk.component_weights.values()) == pytest.approx(1)
    assert result.meta.source == "binance_futures" and not result.meta.partial
    assert len(result.meta.sources) == 7
    assert len(manager.requests) == 8
    limits = [
        item.parameters["limit"]
        for item in manager.requests
        if "limit" in item.parameters
    ]
    assert limits and all(isinstance(limit, int) and limit <= 100 for limit in limits)
    symbols = await service(manager).symbols()
    assert [item.symbol for item in symbols.data.symbols] == ["BTCUSDT"]


@pytest.mark.parametrize(
    "operation",
    [
        "futures.basis",
        "futures.funding",
        "futures.open_interest.current",
        "futures.positioning.taker",
    ],
)
async def test_partial_failures_preserve_available_evidence(
    payloads: dict[str, Any], operation: str
) -> None:
    result = await service(FixtureManager(payloads, {operation})).research(
        "BTCUSDT", FuturesPeriod.ONE_HOUR, 5
    )
    assert result.meta.partial
    assert result.data.market is not None
    assert result.data.analytics is not None
    assert result.data.risk is not None
    if operation != "futures.open_interest.current":
        assert result.data.risk.data_confidence < 1
    else:
        assert (
            result.data.open_interest
            and result.data.open_interest.current_open_interest is None
        )
        assert result.data.analytics.open_interest_change_percent == 40


async def test_total_outage_and_unknown_symbol_do_not_fabricate(
    payloads: dict[str, Any],
) -> None:
    manager = FixtureManager(payloads)
    with pytest.raises(ApplicationValidationError):
        await service(manager).market("BTC/USDT")
    assert not manager.requests
    with pytest.raises(ResourceNotFoundError):
        await service(manager).market("ETHUSDT")
    assert len(manager.requests) == 1
    manager.failures = set(payloads) - {"futures.symbols"}
    with pytest.raises(ProviderUnavailableError):
        await service(manager).research("BTCUSDT", FuturesPeriod.ONE_HOUR, 5)


async def test_stale_evidence_reduces_coverage_and_old_market_is_flagged(
    payloads: dict[str, Any],
) -> None:
    manager = FixtureManager(payloads)
    manager.stale = True
    result = await service(manager).research("BTCUSDT", FuturesPeriod.ONE_HOUR, 5)
    assert result.data.risk and result.data.risk.data_confidence == 0.6
    manager.stale = False
    payloads["futures.market"]["time"] = stamp(2)
    market_result = await service(manager).market("BTCUSDT")
    assert market_result.meta.freshness is Freshness.STALE
    assert market_result.meta.warnings[0].code == "upstream_observation_old"


async def test_variable_funding_and_zero_volume_are_not_assumed(
    payloads: dict[str, Any],
) -> None:
    for i, row in enumerate(payloads["futures.funding"]):
        row["fundingTime"] = stamp(4 - i)
    payloads["futures.positioning.taker"][-1].update(
        buyVol="0", sellVol="0", buySellRatio="0"
    )
    result = await service(FixtureManager(payloads)).research(
        "BTCUSDT", FuturesPeriod.ONE_HOUR, 5
    )
    assert (
        result.data.analytics
        and result.data.analytics.annualized_funding_percent == 87.6
    )
    assert result.data.analytics.taker_buy_share_percent is None
    assert (
        result.data.risk and "positioning_imbalance" in result.data.risk.missing_inputs
    )
    payloads["futures.funding"][-2]["fundingTime"] -= 1800000
    result = await service(FixtureManager(payloads)).research(
        "BTCUSDT", FuturesPeriod.ONE_HOUR, 5
    )
    assert (
        result.data.analytics
        and result.data.analytics.annualized_funding_percent is None
    )


@pytest.mark.parametrize(
    "change",
    ["identity", "duplicate", "reversed", "nan", "future", "empty", "too_many"],
)
def test_invalid_funding_history_is_rejected(
    payloads: dict[str, Any], change: str
) -> None:
    rows = deepcopy(payloads["futures.funding"])
    if change == "identity":
        rows[0]["symbol"] = "ETHUSDT"
    elif change == "duplicate":
        rows[1]["fundingTime"] = rows[0]["fundingTime"]
    elif change == "reversed":
        rows.reverse()
    elif change == "nan":
        rows[0]["fundingRate"] = "NaN"
    elif change == "future":
        rows[-1]["fundingTime"] = stamp(-1)
    elif change == "empty":
        rows = []
    else:
        rows *= 2
    request = ProviderRequest(
        operation="futures.funding",
        asset=CanonicalAsset(asset_type=AssetType.BINANCE_FUTURES, key="BTCUSDT"),
        parameters={"limit": 5},
        soft_ttl_seconds=10,
        hard_ttl_seconds=30,
    )
    raw = ProviderHttpResponse(
        payload=rows,
        fetched_at=NOW,
        source_url=AnyHttpUrl(BASE),
        headers={},
        raw_payload_sha256="a" * 64,
        provider_request_id=None,
        attempts=1,
    )
    with pytest.raises(ProviderSchemaError):
        BinanceFuturesFundingAdapter(BASE).normalize(raw, request)


def test_missing_signals_do_not_imply_low_risk() -> None:
    analytics = analyze_futures(
        funding=None, open_interest=None, basis=None, positioning=None
    )
    assert analytics.crowding == "unavailable"
    assert build_futures_risk(analytics=analytics) is None


def test_free_provider_boundary_rejects_alternate_hosts_and_bad_quota() -> None:
    with pytest.raises(ValueError):
        BinanceFuturesBasisAdapter("https://example.com")
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            binance_futures_base_url="https://fapi.binance.com.evil.test",
        )
    with pytest.raises(ValidationError):
        Settings(_env_file=None, binance_futures_weight_limit_per_minute=10)
    assert not Settings(_env_file=None).binance_futures_enabled


async def test_http_research_and_all_read_routes(
    application: FastAPI, client: AsyncClient, payloads: dict[str, Any]
) -> None:
    application.dependency_overrides[get_binance_futures_service] = lambda: service(
        FixtureManager(payloads)
    )
    for suffix in (
        "market",
        "funding",
        "basis",
        "open-interest",
        "positioning",
        "risk",
        "research",
    ):
        response = await client.get(f"/api/v1/binance/futures/BTCUSDT/{suffix}?limit=5")
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
    for query in ("period=3m", "limit=101", "limit=0"):
        assert (
            await client.get(f"/api/v1/binance/futures/BTCUSDT/research?{query}")
        ).status_code == 422
    assert (
        await client.get("/api/v1/binance/futures/BTC-USDT/research")
    ).status_code == 422


async def test_disabled_provider_and_no_trading_surface(client: AsyncClient) -> None:
    response = await client.get("/api/v1/binance/futures/symbols")
    assert response.status_code == 503
    paths = (await client.get("/openapi.json")).json()["paths"]
    futures = {
        path: methods for path, methods in paths.items() if "/binance/futures/" in path
    }
    assert len(futures) == 9
    assert all(set(methods) == {"get"} for methods in futures.values())
    assert {path.rsplit("/", 1)[-1] for path in futures} == {
        "symbols",
        "status",
        "market",
        "funding",
        "basis",
        "open-interest",
        "positioning",
        "risk",
        "research",
    }
    status = await client.get("/api/v1/binance/futures/status")
    assert status.status_code == 200
    assert status.json() == {
        "enabled": False,
        "reachable": None,
        "credentials_required": False,
        "trading_supported": False,
        "base_url": "https://fapi.binance.com",
        "perpetual_count": None,
        "checked_at": status.json()["checked_at"],
        "provider_timestamp": None,
        "message": "Public Futures research is disabled on this deployment.",
    }


async def test_enabled_status_checks_cached_public_symbols(
    application: FastAPI,
    client: AsyncClient,
    payloads: dict[str, Any],
) -> None:
    application.state.settings = application.state.settings.model_copy(
        update={"binance_futures_enabled": True}
    )
    application.state.binance_futures_service = service(FixtureManager(payloads))

    response = await client.get("/api/v1/binance/futures/status")

    assert response.status_code == 200
    assert response.json()["enabled"] is True
    assert response.json()["reachable"] is True
    assert response.json()["credentials_required"] is False
    assert response.json()["trading_supported"] is False
    assert response.json()["perpetual_count"] == 1


async def test_ui_click_uses_backend_and_renders_real_contract(
    payloads: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    result = await service(FixtureManager(payloads)).research(
        "BTCUSDT", FuturesPeriod.ONE_HOUR, 5
    )
    calls: list[dict[str, Any]] = []

    def fetch(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return result.model_dump(mode="json")

    monkeypatch.setattr("frontend.client.fetch_futures_research", fetch)
    app = AppTest.from_file(str(Path(__file__).parents[3] / "frontend" / "app.py"))
    app.session_state["research_mode"] = "Binance Futures"
    app.run(timeout=40)
    assert not app.exception
    assert any("Choose a USD-M" in item.value for item in app.info)
    next(
        button for button in app.button if button.label == "Load Futures research"
    ).click().run(timeout=40)
    assert not app.exception
    assert calls[0]["symbol"] == "BTCUSDT"
    assert any(item.label == "Perpetual basis" for item in app.metric)
    assert not any("Annualized basis" in item.label for item in app.metric)


def test_futures_client_input_and_ui_failure_states() -> None:
    with pytest.raises(ResearchApiError):
        fetch_futures_research(
            api_base_url="http://127.0.0.1:8000", symbol="../orders", period="1h"
        )
    assert classify_futures_state(None).state is ResearchViewState.EMPTY
    assert (
        classify_futures_state(None, error="disabled").state is ResearchViewState.ERROR
    )
    assert (
        classify_futures_state({"meta": {"partial": True}}).state
        is ResearchViewState.PARTIAL
    )
    assert (
        classify_futures_state({"meta": {"freshness": "stale"}}).state
        is ResearchViewState.STALE
    )
