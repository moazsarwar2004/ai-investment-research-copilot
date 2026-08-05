"""Golden and missing-input tests for deterministic stock analytics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from backend.app.analytics.stocks import (
    analyze_stock_technicals,
    build_stock_risk,
    build_stock_trend,
)
from backend.app.providers.stocks import (
    StockCandle,
    StockCandlesData,
    StockExchange,
    StockInterval,
    StockQuote,
)


def stock_candles(*, points: int = 220) -> StockCandlesData:
    """Build deterministic, dated offline demonstration candles."""
    start = datetime(2025, 1, 1, tzinfo=UTC)
    candles: list[StockCandle] = []
    for index in range(points):
        close = Decimal("100") + Decimal(index) * Decimal("0.25")
        close += Decimal((index % 7) - 3) * Decimal("0.20")
        open_price = close - Decimal("0.15")
        candles.append(
            StockCandle(
                timestamp=start + timedelta(days=index),
                open=open_price,
                high=max(open_price, close) + Decimal("0.80"),
                low=min(open_price, close) - Decimal("0.80"),
                close=close,
                volume=Decimal("1000000") + Decimal(index * 1000),
            )
        )
    return StockCandlesData(
        symbol="OGDC",
        exchange=StockExchange.PSX,
        currency="PKR",
        interval=StockInterval.DAY,
        days=365,
        candles=candles,
    )


def stock_quote() -> StockQuote:
    return StockQuote(
        symbol="OGDC",
        exchange=StockExchange.PSX,
        currency="PKR",
        latest_price=Decimal("154.25"),
        open=Decimal("153.50"),
        high=Decimal("155.00"),
        low=Decimal("152.75"),
        previous_close=Decimal("153.00"),
        change=Decimal("1.25"),
        change_percent=Decimal("0.8169"),
        volume=Decimal("5000000"),
        market_cap=Decimal("663000000000"),
        fifty_two_week_high=Decimal("170"),
        fifty_two_week_low=Decimal("105"),
        source_timestamp=datetime(2025, 8, 8, 10, 0, tzinfo=UTC),
    )


def test_stock_technicals_include_long_horizon_indicators() -> None:
    data = stock_candles()

    first = analyze_stock_technicals(data)
    second = analyze_stock_technicals(data)
    trend = build_stock_trend(first)

    assert first == second
    assert first.points == 220
    assert first.sma_20 > 0
    assert first.sma_50 is not None
    assert first.sma_200 is not None
    assert first.bollinger_upper > first.bollinger_middle > first.bollinger_lower
    assert first.atr_14 > 0
    assert first.support_20 < first.resistance_20
    assert first.maximum_drawdown_percent <= 0
    assert 0 <= first.rsi_14 <= 100
    assert trend.symbol == "OGDC"
    assert len(trend.evidence) == 5


def test_stock_technicals_require_twenty_points() -> None:
    data = stock_candles(points=19)

    try:
        analyze_stock_technicals(data)
    except ValueError as error:
        assert str(error) == "at least 20 stock candles are required"
    else:
        raise AssertionError("short stock history should fail")


def test_stock_risk_renormalizes_missing_quote_inputs() -> None:
    technicals = analyze_stock_technicals(stock_candles())

    complete = build_stock_risk(quote=stock_quote(), technicals=technicals)
    partial = build_stock_risk(
        quote=None,
        technicals=technicals,
        freshness_confidence=0.6,
    )

    assert set(complete.component_scores) == {
        "volatility",
        "drawdown",
        "trend_instability",
        "liquidity",
    }
    assert abs(sum(complete.component_weights.values()) - 1) < 0.00001
    assert "liquidity" not in partial.component_scores
    assert partial.missing_inputs == ["liquidity"]
    assert abs(sum(partial.component_weights.values()) - 1) < 0.00001
    assert partial.data_confidence < complete.data_confidence
