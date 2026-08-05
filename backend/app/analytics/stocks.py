"""Pure, deterministic stock technical, trend, and risk analytics."""

from __future__ import annotations

import math
import statistics
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.providers.stocks import StockCandlesData, StockQuote

STOCK_TECHNICALS_VERSION = "stock-technicals-v1"
STOCK_TREND_VERSION = "stock-trend-rules-v1"
STOCK_RISK_VERSION = "stock-risk-v1"


class _AnalyticsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class StockTechnicalAnalysis(_AnalyticsModel):
    symbol: str
    interval: str
    points: int = Field(ge=20)
    latest_close: Decimal = Field(gt=0)
    sma_20: Decimal = Field(gt=0)
    sma_50: Decimal | None = Field(default=None, gt=0)
    sma_200: Decimal | None = Field(default=None, gt=0)
    ema_12: Decimal = Field(gt=0)
    ema_26: Decimal = Field(gt=0)
    rsi_14: float = Field(ge=0, le=100)
    macd: Decimal
    macd_signal: Decimal
    macd_histogram: Decimal
    bollinger_upper: Decimal = Field(gt=0)
    bollinger_middle: Decimal = Field(gt=0)
    bollinger_lower: Decimal = Field(gt=0)
    atr_14: Decimal = Field(ge=0)
    roc_20_percent: float | None
    momentum_20: Decimal | None
    annualized_volatility_percent: float = Field(ge=0)
    maximum_drawdown_percent: float = Field(le=0)
    support_20: Decimal = Field(gt=0)
    resistance_20: Decimal = Field(gt=0)
    trend: Literal["bullish", "neutral", "bearish"]
    confidence: float = Field(ge=0, le=1)
    methodology_version: str = STOCK_TECHNICALS_VERSION


class StockTrendAnalysis(_AnalyticsModel):
    symbol: str
    trend: Literal["bullish", "neutral", "bearish"]
    confidence: float = Field(ge=0, le=1)
    evidence: list[str]
    methodology_version: str = STOCK_TREND_VERSION


class StockRisk(_AnalyticsModel):
    overall_score: float = Field(ge=0, le=100)
    risk_label: Literal["low", "moderate", "high", "severe"]
    component_scores: dict[str, float]
    component_weights: dict[str, float]
    methodology_version: str = STOCK_RISK_VERSION
    data_confidence: float = Field(ge=0, le=1)
    missing_inputs: list[str]
    limitations: list[str]


def _rounded(value: float, digits: int = 6) -> float:
    return round(value, digits)


def _clamp(value: float) -> float:
    return _rounded(min(100.0, max(0.0, value)), 4)


def _ema_series(values: list[Decimal], period: int) -> list[Decimal]:
    multiplier = Decimal("2") / Decimal(period + 1)
    current = values[0]
    result = [current]
    for value in values[1:]:
        current = (value - current) * multiplier + current
        result.append(current)
    return result


def _rsi(values: list[Decimal], period: int = 14) -> float:
    changes = [values[index] - values[index - 1] for index in range(1, len(values))]
    sample = changes[-period:]
    gains = sum((change for change in sample if change > 0), Decimal("0"))
    losses = -sum((change for change in sample if change < 0), Decimal("0"))
    if gains == 0 and losses == 0:
        return 50.0
    if losses == 0:
        return 100.0
    relative_strength = gains / losses
    return float(Decimal("100") - Decimal("100") / (1 + relative_strength))


def _maximum_drawdown(values: list[Decimal]) -> float:
    peak = values[0]
    maximum = Decimal("0")
    for value in values:
        peak = max(peak, value)
        maximum = min(maximum, value / peak - Decimal("1"))
    return float(maximum * Decimal("100"))


def _annualized_volatility(values: list[Decimal], periods_per_year: float) -> float:
    returns = [
        math.log(float(values[index] / values[index - 1]))
        for index in range(1, len(values))
    ]
    if len(returns) < 2:
        return 0.0
    return statistics.stdev(returns) * math.sqrt(periods_per_year) * 100


def analyze_stock_technicals(data: StockCandlesData) -> StockTechnicalAnalysis:
    """Calculate the documented Phase 7 indicator set from normalized candles."""
    if len(data.candles) < 20:
        raise ValueError("at least 20 stock candles are required")
    closes = [item.close for item in data.candles]
    latest = closes[-1]
    sma_20 = sum(closes[-20:], Decimal("0")) / Decimal("20")
    sma_50 = (
        sum(closes[-50:], Decimal("0")) / Decimal("50") if len(closes) >= 50 else None
    )
    sma_200 = (
        sum(closes[-200:], Decimal("0")) / Decimal("200")
        if len(closes) >= 200
        else None
    )
    ema_12_series = _ema_series(closes, 12)
    ema_26_series = _ema_series(closes, 26)
    macd_series = [
        fast - slow for fast, slow in zip(ema_12_series, ema_26_series, strict=True)
    ]
    signal_series = _ema_series(macd_series, 9)
    macd = macd_series[-1]
    signal = signal_series[-1]

    last_twenty = closes[-20:]
    standard_deviation = Decimal(str(statistics.pstdev(float(v) for v in last_twenty)))
    bollinger_offset = standard_deviation * Decimal("2")

    true_ranges: list[Decimal] = []
    for index, candle in enumerate(data.candles):
        if index == 0:
            true_ranges.append(candle.high - candle.low)
            continue
        previous_close = data.candles[index - 1].close
        true_ranges.append(
            max(
                candle.high - candle.low,
                abs(candle.high - previous_close),
                abs(candle.low - previous_close),
            )
        )
    atr_14 = sum(true_ranges[-14:], Decimal("0")) / Decimal("14")

    roc_20: float | None = None
    momentum_20: Decimal | None = None
    if len(closes) >= 21:
        base = closes[-21]
        roc_20 = float((latest / base - Decimal("1")) * Decimal("100"))
        momentum_20 = latest - base

    score = 0
    score += 1 if latest > sma_20 else -1
    if sma_50 is not None:
        score += 1 if latest > sma_50 else -1
    if sma_200 is not None:
        score += 1 if latest > sma_200 else -1
    score += 1 if macd > signal else -1
    rsi = _rsi(closes)
    if rsi > 60:
        score += 1
    elif rsi < 40:
        score -= 1
    if score >= 2:
        trend: Literal["bullish", "neutral", "bearish"] = "bullish"
    elif score <= -2:
        trend = "bearish"
    else:
        trend = "neutral"
    evaluated_rules = 3 + int(sma_50 is not None) + int(sma_200 is not None)
    confidence = min(1.0, abs(score) / evaluated_rules)

    periods_per_year = 52.0 if data.interval.value == "1w" else 252.0
    return StockTechnicalAnalysis(
        symbol=data.symbol,
        interval=data.interval.value,
        points=len(data.candles),
        latest_close=latest,
        sma_20=sma_20,
        sma_50=sma_50,
        sma_200=sma_200,
        ema_12=ema_12_series[-1],
        ema_26=ema_26_series[-1],
        rsi_14=_rounded(rsi),
        macd=macd,
        macd_signal=signal,
        macd_histogram=macd - signal,
        bollinger_upper=sma_20 + bollinger_offset,
        bollinger_middle=sma_20,
        bollinger_lower=max(Decimal("0.00000001"), sma_20 - bollinger_offset),
        atr_14=atr_14,
        roc_20_percent=_rounded(roc_20) if roc_20 is not None else None,
        momentum_20=momentum_20,
        annualized_volatility_percent=_rounded(
            _annualized_volatility(closes, periods_per_year)
        ),
        maximum_drawdown_percent=_rounded(_maximum_drawdown(closes)),
        support_20=min(item.low for item in data.candles[-20:]),
        resistance_20=max(item.high for item in data.candles[-20:]),
        trend=trend,
        confidence=_rounded(confidence),
    )


def build_stock_trend(technicals: StockTechnicalAnalysis) -> StockTrendAnalysis:
    """Explain the deterministic stock trend classification."""
    sma_20_relation = (
        "above" if technicals.latest_close > technicals.sma_20 else "at or below"
    )
    macd_relation = (
        "above" if technicals.macd > technicals.macd_signal else "at or below"
    )
    evidence = [
        f"Latest close is {sma_20_relation} SMA(20).",
        f"MACD is {macd_relation} its signal line.",
        f"RSI(14) is {technicals.rsi_14:.2f}.",
    ]
    if technicals.sma_50 is not None:
        sma_50_relation = (
            "above" if technicals.latest_close > technicals.sma_50 else "at or below"
        )
        evidence.append(f"Latest close is {sma_50_relation} SMA(50).")
    if technicals.sma_200 is not None:
        sma_200_relation = (
            "above" if technicals.latest_close > technicals.sma_200 else "at or below"
        )
        evidence.append(f"Latest close is {sma_200_relation} SMA(200).")
    return StockTrendAnalysis(
        symbol=technicals.symbol,
        trend=technicals.trend,
        confidence=technicals.confidence,
        evidence=evidence,
    )


def build_stock_risk(
    *,
    quote: StockQuote | None,
    technicals: StockTechnicalAnalysis | None,
    freshness_confidence: float = 1.0,
) -> StockRisk:
    """Build an explainable price-data risk score with weight renormalization."""
    base_weights = {
        "volatility": 0.35,
        "drawdown": 0.25,
        "trend_instability": 0.20,
        "liquidity": 0.20,
    }
    scores: dict[str, float] = {}
    missing: list[str] = []
    if technicals is None:
        missing.extend(["volatility", "drawdown", "trend_instability"])
    else:
        scores["volatility"] = _clamp(technicals.annualized_volatility_percent * 2)
        scores["drawdown"] = _clamp(abs(technicals.maximum_drawdown_percent) * 2)
        trend_base = {"bullish": 20.0, "neutral": 50.0, "bearish": 80.0}[
            technicals.trend
        ]
        scores["trend_instability"] = _clamp(
            trend_base + (1 - technicals.confidence) * 15
        )
    if quote is None or quote.volume is None or quote.market_cap in {None, 0}:
        missing.append("liquidity")
    else:
        daily_turnover = float(quote.volume * quote.latest_price / quote.market_cap)
        scores["liquidity"] = _clamp(100 - daily_turnover * 2_000)

    available_weight = sum(base_weights[name] for name in scores)
    if available_weight <= 0:
        raise ValueError("at least one stock risk component is required")
    weights = {name: _rounded(base_weights[name] / available_weight) for name in scores}
    overall = _clamp(sum(scores[name] * weights[name] for name in scores))
    if overall < 25:
        label: Literal["low", "moderate", "high", "severe"] = "low"
    elif overall < 50:
        label = "moderate"
    elif overall < 75:
        label = "high"
    else:
        label = "severe"
    coverage = available_weight / sum(base_weights.values())
    return StockRisk(
        overall_score=overall,
        risk_label=label,
        component_scores=scores,
        component_weights=weights,
        data_confidence=_rounded(max(0.0, min(1.0, coverage * freshness_confidence))),
        missing_inputs=missing,
        limitations=[
            "Risk is deterministic price/volume context, not a recommendation.",
            "SEC fundamental risk components are added in Phase 8.",
        ],
    )


__all__ = [
    "STOCK_RISK_VERSION",
    "STOCK_TECHNICALS_VERSION",
    "STOCK_TREND_VERSION",
    "StockRisk",
    "StockTechnicalAnalysis",
    "StockTrendAnalysis",
    "analyze_stock_technicals",
    "build_stock_risk",
    "build_stock_trend",
]
