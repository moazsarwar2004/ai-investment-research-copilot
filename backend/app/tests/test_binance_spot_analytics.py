"""Golden-behavior tests for deterministic Binance Spot analytics."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import AnyHttpUrl

from backend.app.analytics import (
    analyze_order_book,
    analyze_technicals,
    analyze_trades,
    build_spot_risk,
)
from backend.app.providers import AssetType, CanonicalAsset, ProviderHttpResponse
from backend.app.providers.binance_spot import (
    BinanceSpotCandlesAdapter,
    BinanceSpotOrderBookAdapter,
    BinanceSpotTradesAdapter,
)
from backend.app.providers.models import ProviderRequest

_BASE_URL = "https://data-api.binance.vision"


def _http(payload: object, path: str) -> ProviderHttpResponse:
    return ProviderHttpResponse(
        payload=payload,
        fetched_at=datetime(2026, 7, 24, 12, 0, tzinfo=UTC),
        source_url=AnyHttpUrl(f"{_BASE_URL}{path}"),
        headers={},
        raw_payload_sha256="c" * 64,
        provider_request_id=None,
        attempts=1,
    )


def _request(
    operation: str,
    *,
    interval: str | None = None,
    limit: int,
) -> ProviderRequest:
    return ProviderRequest(
        operation=operation,
        asset=CanonicalAsset(
            asset_type=AssetType.BINANCE_SPOT,
            key="BTCUSDT",
        ),
        interval=interval,
        parameters={"limit": limit},
        soft_ttl_seconds=10,
        hard_ttl_seconds=30,
    )


def test_technicals_are_reproducible_for_fixture_candles(
    binance_payloads: dict[str, Any],
) -> None:
    adapter = BinanceSpotCandlesAdapter(_BASE_URL)
    request = _request("spot.candles", interval="1h", limit=200)
    candles = adapter.normalize(
        _http(binance_payloads["klines"], "/api/v3/klines"),
        request,
    ).data

    result = analyze_technicals(candles)

    assert result.latest_close == Decimal("119")
    assert result.sma_20 == Decimal("109.5")
    assert result.rsi_14 == 100
    assert result.atr_14 == Decimal("3")
    assert result.trend == "bullish"
    assert 0 <= result.confidence <= 1
    assert result.methodology_version == "spot-technicals-v1"


def test_liquidity_and_trade_anomaly_outputs_are_bounded(
    binance_payloads: dict[str, Any],
) -> None:
    book_request = _request("spot.order_book", limit=100)
    trade_request = _request("spot.trades", limit=100)
    book = (
        BinanceSpotOrderBookAdapter(_BASE_URL)
        .normalize(
            _http(binance_payloads["depth"], "/api/v3/depth"),
            book_request,
        )
        .data
    )
    trades = (
        BinanceSpotTradesAdapter(_BASE_URL)
        .normalize(
            _http(binance_payloads["trades"], "/api/v3/trades"),
            trade_request,
        )
        .data
    )

    liquidity = analyze_order_book(
        book,
        slippage_notional_quote=Decimal("1000"),
    )
    pressure = analyze_trades(trades)

    assert liquidity.spread == Decimal("0.20")
    assert liquidity.spread_bps == pytest.approx(16.806723)
    assert -1 <= liquidity.imbalance <= 1
    assert liquidity.estimated_buy_slippage_bps is not None
    assert liquidity.estimated_sell_slippage_bps is not None
    assert pressure.pressure == "buy"
    assert pressure.large_trade_count == 1
    assert pressure.large_trades[0].trade_id == 4


def test_spot_risk_renormalizes_missing_components(
    binance_payloads: dict[str, Any],
) -> None:
    request = _request("spot.candles", interval="1h", limit=200)
    candles = (
        BinanceSpotCandlesAdapter(_BASE_URL)
        .normalize(
            _http(binance_payloads["klines"], "/api/v3/klines"),
            request,
        )
        .data
    )
    technicals = analyze_technicals(candles)

    risk = build_spot_risk(
        technicals=technicals,
        order_book=None,
        trades=None,
        freshness_confidence=0.6,
    )

    assert set(risk.component_scores) == {"volatility", "trend_instability"}
    assert sum(risk.component_weights.values()) == pytest.approx(1)
    assert set(risk.missing_inputs) == {"liquidity", "trade_anomaly"}
    assert risk.data_confidence == pytest.approx(0.27)
    assert 0 <= risk.overall_score <= 100
