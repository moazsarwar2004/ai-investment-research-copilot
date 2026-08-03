"""Reproducible technical, liquidity, trade-pressure, and Spot risk analytics."""

from __future__ import annotations

import math
import statistics
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.providers.binance_spot import (
    BinanceSpotInterval,
    SpotBookLevel,
    SpotCandlesData,
    SpotOrderBookData,
    SpotTrade,
    SpotTradesData,
)

TECHNICALS_VERSION = "spot-technicals-v1"
LIQUIDITY_VERSION = "spot-liquidity-v1"
TRADE_ANALYSIS_VERSION = "spot-trades-v1"
SPOT_RISK_VERSION = "spot-risk-v1"

_PERIODS_PER_YEAR: dict[BinanceSpotInterval, float] = {
    BinanceSpotInterval.ONE_MINUTE: 365.0 * 24 * 60,
    BinanceSpotInterval.FIVE_MINUTES: 365.0 * 24 * 12,
    BinanceSpotInterval.FIFTEEN_MINUTES: 365.0 * 24 * 4,
    BinanceSpotInterval.ONE_HOUR: 365.0 * 24,
    BinanceSpotInterval.FOUR_HOURS: 365.0 * 6,
    BinanceSpotInterval.ONE_DAY: 365.0,
    BinanceSpotInterval.ONE_WEEK: 52.0,
}


class _AnalyticsModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


class TechnicalAnalysis(_AnalyticsModel):
    symbol: str
    interval: BinanceSpotInterval
    points: int = Field(ge=15)
    latest_close: Decimal = Field(gt=0)
    sma_20: Decimal = Field(gt=0)
    ema_20: Decimal = Field(gt=0)
    rsi_14: float = Field(ge=0, le=100)
    atr_14: Decimal = Field(ge=0)
    annualized_volatility_percent: float = Field(ge=0)
    latest_return_percent: float
    trend: Literal["bullish", "neutral", "bearish"]
    confidence: float = Field(ge=0, le=1)
    methodology_version: str = TECHNICALS_VERSION


class OrderBookAnalysis(_AnalyticsModel):
    symbol: str
    last_update_id: int = Field(ge=0)
    bids: list[SpotBookLevel]
    asks: list[SpotBookLevel]
    best_bid: Decimal = Field(gt=0)
    best_ask: Decimal = Field(gt=0)
    spread: Decimal = Field(gt=0)
    spread_bps: float = Field(ge=0)
    bid_depth_quote: Decimal = Field(ge=0)
    ask_depth_quote: Decimal = Field(ge=0)
    imbalance: float = Field(ge=-1, le=1)
    pressure: Literal["buy", "balanced", "sell"]
    slippage_notional_quote: Decimal = Field(gt=0)
    estimated_buy_slippage_bps: float | None = Field(default=None, ge=0)
    estimated_sell_slippage_bps: float | None = Field(default=None, ge=0)
    liquidity_warnings: list[str] = Field(default_factory=list)
    methodology_version: str = LIQUIDITY_VERSION


class LargeTradeAnomaly(_AnalyticsModel):
    trade_id: int
    time: datetime
    side: Literal["buy", "sell"]
    quote_quantity: Decimal
    threshold_quote: Decimal


class TradeAnalysis(_AnalyticsModel):
    symbol: str
    trades: list[SpotTrade]
    buy_quote_volume: Decimal = Field(ge=0)
    sell_quote_volume: Decimal = Field(ge=0)
    buy_pressure: float = Field(ge=-1, le=1)
    pressure: Literal["buy", "balanced", "sell"]
    large_trade_threshold_quote: Decimal = Field(gt=0)
    large_trade_count: int = Field(ge=0)
    large_trade_share: float = Field(ge=0, le=1)
    large_trades: list[LargeTradeAnomaly]
    methodology_version: str = TRADE_ANALYSIS_VERSION


class SpotRisk(_AnalyticsModel):
    overall_score: float = Field(ge=0, le=100)
    risk_label: Literal["low", "moderate", "high", "severe"]
    component_scores: dict[str, float]
    component_weights: dict[str, float]
    methodology_version: str = SPOT_RISK_VERSION
    data_confidence: float = Field(ge=0, le=1)
    missing_inputs: list[str]
    limitations: list[str]


def _rounded(value: float, digits: int = 6) -> float:
    return round(value, digits)


def _rsi(closes: list[Decimal], period: int = 14) -> float:
    changes = [closes[index] - closes[index - 1] for index in range(1, len(closes))]
    sample = changes[-period:]
    gains = sum((change for change in sample if change > 0), Decimal("0"))
    losses = -sum((change for change in sample if change < 0), Decimal("0"))
    if gains == 0 and losses == 0:
        return 50.0
    if losses == 0:
        return 100.0
    relative_strength = gains / losses
    return float(Decimal("100") - Decimal("100") / (Decimal("1") + relative_strength))


def _ema(values: list[Decimal], period: int) -> Decimal:
    multiplier = Decimal("2") / Decimal(period + 1)
    current = values[0]
    for value in values[1:]:
        current = (value - current) * multiplier + current
    return current


def _atr(data: SpotCandlesData, period: int = 14) -> Decimal:
    ranges: list[Decimal] = []
    candles = data.candles
    for index in range(1, len(candles)):
        candle = candles[index]
        previous_close = candles[index - 1].close
        ranges.append(
            max(
                candle.high - candle.low,
                abs(candle.high - previous_close),
                abs(candle.low - previous_close),
            )
        )
    return sum(ranges[-period:], Decimal("0")) / Decimal(period)


def analyze_technicals(data: SpotCandlesData) -> TechnicalAnalysis:
    """Calculate a stable indicator set from at least 20 completed candles."""
    if len(data.candles) < 20:
        raise ValueError("at least 20 candles are required for technical analysis")
    closes = [item.close for item in data.candles]
    sma_20 = sum(closes[-20:], Decimal("0")) / Decimal("20")
    ema_20 = _ema(closes, 20)
    rsi_14 = _rsi(closes)
    returns = [
        math.log(float(closes[index] / closes[index - 1]))
        for index in range(1, len(closes))
    ]
    volatility = (
        statistics.stdev(returns) * math.sqrt(_PERIODS_PER_YEAR[data.interval]) * 100
        if len(returns) >= 2
        else 0.0
    )
    latest_return = float((closes[-1] / closes[-2] - 1) * 100)
    if closes[-1] > sma_20 and rsi_14 >= 55:
        trend: Literal["bullish", "neutral", "bearish"] = "bullish"
    elif closes[-1] < sma_20 and rsi_14 <= 45:
        trend = "bearish"
    else:
        trend = "neutral"
    distance = abs(float(closes[-1] / sma_20 - 1))
    rsi_conviction = abs(rsi_14 - 50) / 50
    confidence = min(1.0, 0.25 + distance * 8 + rsi_conviction * 0.5)
    return TechnicalAnalysis(
        symbol=data.symbol,
        interval=data.interval,
        points=len(closes),
        latest_close=closes[-1],
        sma_20=sma_20,
        ema_20=ema_20,
        rsi_14=_rounded(rsi_14),
        atr_14=_atr(data),
        annualized_volatility_percent=_rounded(volatility),
        latest_return_percent=_rounded(latest_return),
        trend=trend,
        confidence=_rounded(confidence),
    )


def _buy_slippage_bps(
    asks: list[SpotBookLevel],
    notional: Decimal,
) -> float | None:
    remaining = notional
    base_bought = Decimal("0")
    for level in asks:
        spend = min(remaining, level.price * level.quantity)
        base_bought += spend / level.price
        remaining -= spend
        if remaining <= 0:
            average = notional / base_bought
            return max(0.0, float((average / asks[0].price - 1) * 10_000))
    return None


def _sell_slippage_bps(
    bids: list[SpotBookLevel],
    notional: Decimal,
) -> float | None:
    target_base = notional / bids[0].price
    remaining_base = target_base
    quote_received = Decimal("0")
    for level in bids:
        sold = min(remaining_base, level.quantity)
        quote_received += sold * level.price
        remaining_base -= sold
        if remaining_base <= 0:
            average = quote_received / target_base
            return max(0.0, float((1 - average / bids[0].price) * 10_000))
    return None


def analyze_order_book(
    data: SpotOrderBookData,
    *,
    slippage_notional_quote: Decimal,
) -> OrderBookAnalysis:
    """Calculate bounded depth, spread, imbalance, pressure, and slippage."""
    if not slippage_notional_quote.is_finite() or slippage_notional_quote <= 0:
        raise ValueError("slippage notional must be a positive finite decimal")
    if slippage_notional_quote > Decimal("1000000"):
        raise ValueError("slippage notional cannot exceed 1,000,000 quote units")
    best_bid = data.bids[0].price
    best_ask = data.asks[0].price
    spread = best_ask - best_bid
    midpoint = (best_ask + best_bid) / Decimal("2")
    bid_depth = sum(
        (level.price * level.quantity for level in data.bids),
        Decimal("0"),
    )
    ask_depth = sum(
        (level.price * level.quantity for level in data.asks),
        Decimal("0"),
    )
    total_depth = bid_depth + ask_depth
    imbalance = float((bid_depth - ask_depth) / total_depth) if total_depth > 0 else 0.0
    if imbalance >= 0.1:
        pressure: Literal["buy", "balanced", "sell"] = "buy"
    elif imbalance <= -0.1:
        pressure = "sell"
    else:
        pressure = "balanced"
    buy_slippage = _buy_slippage_bps(data.asks, slippage_notional_quote)
    sell_slippage = _sell_slippage_bps(data.bids, slippage_notional_quote)
    warnings: list[str] = []
    if buy_slippage is None:
        warnings.append("insufficient_ask_depth_for_slippage_notional")
    if sell_slippage is None:
        warnings.append("insufficient_bid_depth_for_slippage_notional")
    return OrderBookAnalysis(
        symbol=data.symbol,
        last_update_id=data.last_update_id,
        bids=data.bids,
        asks=data.asks,
        best_bid=best_bid,
        best_ask=best_ask,
        spread=spread,
        spread_bps=_rounded(float(spread / midpoint * 10_000)),
        bid_depth_quote=bid_depth,
        ask_depth_quote=ask_depth,
        imbalance=_rounded(imbalance),
        pressure=pressure,
        slippage_notional_quote=slippage_notional_quote,
        estimated_buy_slippage_bps=(
            _rounded(buy_slippage) if buy_slippage is not None else None
        ),
        estimated_sell_slippage_bps=(
            _rounded(sell_slippage) if sell_slippage is not None else None
        ),
        liquidity_warnings=warnings,
    )


def analyze_trades(data: SpotTradesData) -> TradeAnalysis:
    """Classify aggressor pressure and median-relative large public trades."""
    quote_sizes = [item.quote_quantity for item in data.trades]
    threshold = statistics.median(quote_sizes) * Decimal("5")
    buy_volume = sum(
        (item.quote_quantity for item in data.trades if not item.is_buyer_maker),
        Decimal("0"),
    )
    sell_volume = sum(
        (item.quote_quantity for item in data.trades if item.is_buyer_maker),
        Decimal("0"),
    )
    total = buy_volume + sell_volume
    buy_pressure = float((buy_volume - sell_volume) / total) if total > 0 else 0.0
    if buy_pressure >= 0.1:
        pressure: Literal["buy", "balanced", "sell"] = "buy"
    elif buy_pressure <= -0.1:
        pressure = "sell"
    else:
        pressure = "balanced"
    anomalies = [
        LargeTradeAnomaly(
            trade_id=item.trade_id,
            time=item.time,
            side="sell" if item.is_buyer_maker else "buy",
            quote_quantity=item.quote_quantity,
            threshold_quote=threshold,
        )
        for item in data.trades
        if item.quote_quantity >= threshold
    ]
    return TradeAnalysis(
        symbol=data.symbol,
        trades=data.trades,
        buy_quote_volume=buy_volume,
        sell_quote_volume=sell_volume,
        buy_pressure=_rounded(buy_pressure),
        pressure=pressure,
        large_trade_threshold_quote=threshold,
        large_trade_count=len(anomalies),
        large_trade_share=_rounded(len(anomalies) / len(data.trades)),
        large_trades=anomalies,
    )


def _clamp_score(value: float) -> float:
    return _rounded(min(100.0, max(0.0, value)), 4)


def build_spot_risk(
    *,
    technicals: TechnicalAnalysis | None,
    order_book: OrderBookAnalysis | None,
    trades: TradeAnalysis | None,
    freshness_confidence: float = 1.0,
) -> SpotRisk:
    """Build the explainable Phase 5 Spot risk score with missing-data handling."""
    base_weights = {
        "volatility": 0.35,
        "liquidity": 0.35,
        "trade_anomaly": 0.20,
        "trend_instability": 0.10,
    }
    scores: dict[str, float] = {}
    missing: list[str] = []

    if technicals is None:
        missing.extend(["volatility", "trend_instability"])
    else:
        scores["volatility"] = _clamp_score(
            technicals.annualized_volatility_percent / 2
        )
        scores["trend_instability"] = _clamp_score(
            (1 - technicals.confidence) * 70 + abs(technicals.rsi_14 - 50) * 0.6
        )

    if order_book is None:
        missing.append("liquidity")
    else:
        available_slippage = [
            value
            for value in (
                order_book.estimated_buy_slippage_bps,
                order_book.estimated_sell_slippage_bps,
            )
            if value is not None
        ]
        slippage = statistics.mean(available_slippage) if available_slippage else 25.0
        depth_penalty = 20.0 if order_book.liquidity_warnings else 0.0
        scores["liquidity"] = _clamp_score(
            order_book.spread_bps * 3 + slippage * 2 + depth_penalty
        )

    if trades is None:
        missing.append("trade_anomaly")
    else:
        scores["trade_anomaly"] = _clamp_score(
            trades.large_trade_share * 150 + abs(trades.buy_pressure) * 25
        )

    available_weight = sum(base_weights[name] for name in scores)
    if available_weight <= 0:
        raise ValueError("at least one risk component is required")
    weights = {name: _rounded(base_weights[name] / available_weight) for name in scores}
    overall = _clamp_score(sum(scores[name] * weights[name] for name in scores))
    if overall < 25:
        label: Literal["low", "moderate", "high", "severe"] = "low"
    elif overall < 50:
        label = "moderate"
    elif overall < 75:
        label = "high"
    else:
        label = "severe"
    coverage = available_weight / sum(base_weights.values())
    confidence = min(1.0, max(0.0, coverage * freshness_confidence))
    return SpotRisk(
        overall_score=overall,
        risk_label=label,
        component_scores=scores,
        component_weights=weights,
        data_confidence=_rounded(confidence),
        missing_inputs=missing,
        limitations=[
            "Score uses recent public market snapshots, not account exposure.",
            "Order-book depth is a bounded REST snapshot and may change rapidly.",
            "This deterministic score is research information, not advice.",
        ],
    )
