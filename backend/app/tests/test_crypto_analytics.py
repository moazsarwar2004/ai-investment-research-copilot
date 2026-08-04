"""Golden and missing-input tests for deterministic crypto analytics."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from backend.app.analytics.crypto import (
    analyze_crypto_anomalies,
    analyze_crypto_technicals,
    build_crypto_risk,
    build_crypto_trend,
)
from backend.app.providers.coingecko import (
    CryptoHistoryData,
    CryptoHistoryPoint,
    CryptoMarket,
)


def _history(payloads: dict[str, Any]) -> CryptoHistoryData:
    raw = payloads["history"]
    market_caps = dict(raw["market_caps"])
    volumes = dict(raw["total_volumes"])
    return CryptoHistoryData(
        coin_id="bitcoin",
        days=90,
        points=[
            CryptoHistoryPoint(
                timestamp=datetime.fromtimestamp(timestamp / 1_000, tz=UTC),
                price=Decimal(str(price)),
                market_cap=Decimal(str(market_caps[timestamp])),
                total_volume_24h=Decimal(str(volumes[timestamp])),
            )
            for timestamp, price in raw["prices"]
        ],
    )


def _overview() -> CryptoMarket:
    return CryptoMarket(
        coin_id="bitcoin",
        symbol="BTC",
        name="Bitcoin",
        current_price=Decimal("170"),
        market_cap=Decimal("1700000000"),
        market_cap_rank=1,
        fully_diluted_valuation=Decimal("1800000000"),
        total_volume_24h=Decimal("100000000"),
        high_24h=Decimal("175"),
        low_24h=Decimal("135"),
        circulating_supply=Decimal("10000000"),
        total_supply=Decimal("10000000"),
        max_supply=Decimal("11000000"),
        all_time_high=Decimal("200"),
        distance_from_ath_percent=Decimal("15"),
        all_time_low=Decimal("1"),
        last_updated=datetime(2026, 8, 4, 8, 0, tzinfo=UTC),
    )


def test_crypto_technicals_and_trend_are_reproducible(
    coingecko_payloads: dict[str, Any],
) -> None:
    history = _history(coingecko_payloads)

    first = analyze_crypto_technicals(history)
    second = analyze_crypto_technicals(history)
    trend = build_crypto_trend(first)

    assert first == second
    assert first.points == 30
    assert first.latest_price == 170
    assert first.sma_20 == Decimal("127.3")
    assert first.sma_50 is None
    assert first.maximum_drawdown_percent < 0
    assert first.annualized_volatility_percent > 0
    assert trend.trend == first.trend
    assert len(trend.evidence) == 4


def test_return_and_volume_spike_produce_layered_anomalies(
    coingecko_payloads: dict[str, Any],
) -> None:
    anomalies = analyze_crypto_anomalies(_history(coingecko_payloads))

    assert anomalies.status in {"elevated", "extreme"}
    assert anomalies.anomaly_score >= 35
    assert {event.kind for event in anomalies.events} == {"return", "volume"}
    assert anomalies.latest_return_z_score is not None
    assert anomalies.latest_volume_z_score is not None


def test_crypto_risk_uses_six_weights_and_renormalizes_missing_inputs(
    coingecko_payloads: dict[str, Any],
) -> None:
    history = _history(coingecko_payloads)
    technicals = analyze_crypto_technicals(history)
    anomalies = analyze_crypto_anomalies(history)

    complete = build_crypto_risk(
        overview=_overview(),
        technicals=technicals,
        anomalies=anomalies,
    )
    partial = build_crypto_risk(
        overview=_overview(),
        technicals=None,
        anomalies=None,
        freshness_confidence=0.6,
    )

    assert set(complete.component_scores) == {
        "volatility",
        "drawdown",
        "liquidity",
        "market_size",
        "trend_instability",
        "anomaly",
    }
    assert abs(sum(complete.component_weights.values()) - 1) < 0.00001
    assert set(partial.component_scores) == {"liquidity", "market_size"}
    assert abs(sum(partial.component_weights.values()) - 1) < 0.00001
    assert set(partial.missing_inputs) == {
        "volatility",
        "drawdown",
        "trend_instability",
        "anomaly",
    }
    assert partial.data_confidence < complete.data_confidence
