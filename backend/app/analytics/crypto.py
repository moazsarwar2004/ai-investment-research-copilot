"""Deterministic technical, anomaly, trend, and risk analytics for crypto."""

from __future__ import annotations

import math
import statistics
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.providers.coingecko import CryptoHistoryData, CryptoMarket

CRYPTO_TECHNICALS_VERSION = "crypto-technicals-v1"
CRYPTO_ANOMALY_VERSION = "crypto-anomalies-v1"
CRYPTO_TREND_VERSION = "crypto-trend-v1"
CRYPTO_RISK_VERSION = "crypto-risk-v1"


class _AnalyticsModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


class CryptoTechnicalAnalysis(_AnalyticsModel):
    coin_id: str
    days: int
    points: int = Field(ge=20)
    latest_price: Decimal = Field(gt=0)
    sma_20: Decimal = Field(gt=0)
    sma_50: Decimal | None = Field(default=None, gt=0)
    ema_12: Decimal = Field(gt=0)
    ema_26: Decimal = Field(gt=0)
    rsi_14: float = Field(ge=0, le=100)
    macd: Decimal
    macd_signal: Decimal
    macd_histogram: Decimal
    annualized_volatility_percent: float = Field(ge=0)
    maximum_drawdown_percent: float = Field(le=0)
    latest_return_percent: float
    trend: Literal["bullish", "neutral", "bearish"]
    confidence: float = Field(ge=0, le=1)
    methodology_version: str = CRYPTO_TECHNICALS_VERSION


class CryptoTrendAnalysis(_AnalyticsModel):
    coin_id: str
    trend: Literal["bullish", "neutral", "bearish"]
    confidence: float = Field(ge=0, le=1)
    evidence: list[str]
    methodology_version: str = CRYPTO_TREND_VERSION


class CryptoAnomalyEvent(_AnalyticsModel):
    timestamp: datetime
    kind: Literal["return", "volume"]
    direction: Literal["positive", "negative"]
    z_score: float
    observed_change_percent: float


class CryptoAnomalyAnalysis(_AnalyticsModel):
    coin_id: str
    points: int = Field(ge=20)
    anomaly_score: float = Field(ge=0, le=100)
    status: Literal["normal", "elevated", "extreme"]
    latest_return_z_score: float | None
    latest_volume_z_score: float | None
    events: list[CryptoAnomalyEvent]
    limitations: list[str]
    methodology_version: str = CRYPTO_ANOMALY_VERSION


class CryptoRisk(_AnalyticsModel):
    overall_score: float = Field(ge=0, le=100)
    risk_label: Literal["low", "moderate", "high", "severe"]
    component_scores: dict[str, float]
    component_weights: dict[str, float]
    methodology_version: str = CRYPTO_RISK_VERSION
    data_confidence: float = Field(ge=0, le=1)
    missing_inputs: list[str]
    limitations: list[str]


def _rounded(value: float, digits: int = 6) -> float:
    return round(value, digits)


def _clamp_score(value: float) -> float:
    return _rounded(min(100.0, max(0.0, value)), 4)


def _ema(values: list[Decimal], period: int) -> Decimal:
    multiplier = Decimal("2") / Decimal(period + 1)
    current = values[0]
    for value in values[1:]:
        current = (value - current) * multiplier + current
    return current


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
        drawdown = value / peak - Decimal("1")
        maximum = min(maximum, drawdown)
    return float(maximum * Decimal("100"))


def _periods_per_year(data: CryptoHistoryData) -> float:
    intervals = [
        (
            data.points[index].timestamp - data.points[index - 1].timestamp
        ).total_seconds()
        for index in range(1, len(data.points))
    ]
    median_seconds = max(60.0, statistics.median(intervals))
    return 365.0 * 24 * 60 * 60 / median_seconds


def analyze_crypto_technicals(data: CryptoHistoryData) -> CryptoTechnicalAnalysis:
    """Calculate interval-aware indicators from normalized CoinGecko history."""
    if len(data.points) < 20:
        raise ValueError("at least 20 history points are required")
    prices = [item.price for item in data.points]
    sma_20 = sum(prices[-20:], Decimal("0")) / Decimal("20")
    sma_50 = (
        sum(prices[-50:], Decimal("0")) / Decimal("50") if len(prices) >= 50 else None
    )
    ema_12_series = _ema_series(prices, 12)
    ema_26_series = _ema_series(prices, 26)
    macd_series = [
        fast - slow for fast, slow in zip(ema_12_series, ema_26_series, strict=True)
    ]
    macd = macd_series[-1]
    macd_signal = _ema(macd_series, 9)
    rsi = _rsi(prices)
    log_returns = [
        math.log(float(prices[index] / prices[index - 1]))
        for index in range(1, len(prices))
    ]
    volatility = (
        statistics.stdev(log_returns) * math.sqrt(_periods_per_year(data)) * 100
        if len(log_returns) >= 2
        else 0.0
    )
    latest_return = float((prices[-1] / prices[-2] - 1) * 100)
    long_average = sma_50 or sma_20
    bullish_evidence = sum(
        (
            prices[-1] > sma_20,
            sma_20 > long_average or sma_50 is None,
            macd > macd_signal,
            rsi >= 55,
        )
    )
    bearish_evidence = sum(
        (
            prices[-1] < sma_20,
            sma_20 < long_average or sma_50 is None,
            macd < macd_signal,
            rsi <= 45,
        )
    )
    if bullish_evidence >= 3 and bullish_evidence > bearish_evidence:
        trend: Literal["bullish", "neutral", "bearish"] = "bullish"
    elif bearish_evidence >= 3 and bearish_evidence > bullish_evidence:
        trend = "bearish"
    else:
        trend = "neutral"
    evidence_gap = abs(bullish_evidence - bearish_evidence) / 4
    distance = abs(float(prices[-1] / sma_20 - 1))
    confidence = min(1.0, 0.25 + evidence_gap * 0.55 + distance * 4)
    return CryptoTechnicalAnalysis(
        coin_id=data.coin_id,
        days=data.days,
        points=len(data.points),
        latest_price=prices[-1],
        sma_20=sma_20,
        sma_50=sma_50,
        ema_12=ema_12_series[-1],
        ema_26=ema_26_series[-1],
        rsi_14=_rounded(rsi),
        macd=macd,
        macd_signal=macd_signal,
        macd_histogram=macd - macd_signal,
        annualized_volatility_percent=_rounded(volatility),
        maximum_drawdown_percent=_rounded(_maximum_drawdown(prices)),
        latest_return_percent=_rounded(latest_return),
        trend=trend,
        confidence=_rounded(confidence),
    )


def build_crypto_trend(
    technicals: CryptoTechnicalAnalysis,
) -> CryptoTrendAnalysis:
    """Explain the deterministic trend classification in stable terms."""
    evidence = [
        (
            "Latest price is above SMA(20)."
            if technicals.latest_price > technicals.sma_20
            else "Latest price is at or below SMA(20)."
        ),
        (
            "MACD is above its signal."
            if technicals.macd > technicals.macd_signal
            else "MACD is at or below its signal."
        ),
        f"RSI(14) is {technicals.rsi_14:.2f}.",
    ]
    if technicals.sma_50 is None:
        evidence.append("SMA(50) is unavailable for this history range.")
    else:
        evidence.append(
            "SMA(20) is above SMA(50)."
            if technicals.sma_20 > technicals.sma_50
            else "SMA(20) is at or below SMA(50)."
        )
    return CryptoTrendAnalysis(
        coin_id=technicals.coin_id,
        trend=technicals.trend,
        confidence=technicals.confidence,
        evidence=evidence,
    )


def _rolling_z_scores(
    values: list[float],
    *,
    minimum_baseline: int = 10,
) -> list[float | None]:
    scores: list[float | None] = [None] * len(values)
    for index, value in enumerate(values):
        baseline = values[max(0, index - 30) : index]
        if len(baseline) < minimum_baseline:
            continue
        deviation = statistics.stdev(baseline)
        if deviation == 0:
            scores[index] = 0.0
        else:
            scores[index] = (value - statistics.mean(baseline)) / deviation
    return scores


def analyze_crypto_anomalies(data: CryptoHistoryData) -> CryptoAnomalyAnalysis:
    """Flag return and volume changes against their preceding rolling baseline."""
    if len(data.points) < 20:
        raise ValueError("at least 20 history points are required")
    returns = [
        float((data.points[index].price / data.points[index - 1].price - 1) * 100)
        for index in range(1, len(data.points))
    ]
    return_z = _rolling_z_scores(returns)

    volume_changes: list[float] = []
    volume_indexes: list[int] = []
    for index in range(1, len(data.points)):
        current = data.points[index].total_volume_24h
        previous = data.points[index - 1].total_volume_24h
        if current is None or previous is None or current <= 0 or previous <= 0:
            continue
        volume_changes.append(math.log(float(current / previous)) * 100)
        volume_indexes.append(index)
    volume_z_values = _rolling_z_scores(volume_changes)
    volume_z_by_point = {
        point_index: z_score
        for point_index, z_score in zip(
            volume_indexes,
            volume_z_values,
            strict=True,
        )
    }

    events: list[CryptoAnomalyEvent] = []
    for return_index, z_score in enumerate(return_z):
        if z_score is None or abs(z_score) < 3:
            continue
        point_index = return_index + 1
        events.append(
            CryptoAnomalyEvent(
                timestamp=data.points[point_index].timestamp,
                kind="return",
                direction="positive" if returns[return_index] >= 0 else "negative",
                z_score=_rounded(z_score),
                observed_change_percent=_rounded(returns[return_index]),
            )
        )
    for change, point_index in zip(volume_changes, volume_indexes, strict=True):
        z_score = volume_z_by_point[point_index]
        if z_score is None or abs(z_score) < 3:
            continue
        events.append(
            CryptoAnomalyEvent(
                timestamp=data.points[point_index].timestamp,
                kind="volume",
                direction="positive" if change >= 0 else "negative",
                z_score=_rounded(z_score),
                observed_change_percent=_rounded(change),
            )
        )
    events.sort(key=lambda event: (event.timestamp, event.kind))
    latest_return_z = return_z[-1] if return_z else None
    latest_volume_z = volume_z_by_point.get(len(data.points) - 1)
    recent_events = [
        event
        for event in events
        if event.timestamp >= data.points[max(0, len(data.points) - 10)].timestamp
    ]
    maximum_recent_z = max(
        (abs(event.z_score) for event in recent_events),
        default=0.0,
    )
    score = _clamp_score(maximum_recent_z * 20 + len(recent_events) * 5)
    if score >= 75:
        status: Literal["normal", "elevated", "extreme"] = "extreme"
    elif score >= 35:
        status = "elevated"
    else:
        status = "normal"
    return CryptoAnomalyAnalysis(
        coin_id=data.coin_id,
        points=len(data.points),
        anomaly_score=score,
        status=status,
        latest_return_z_score=(
            _rounded(latest_return_z) if latest_return_z is not None else None
        ),
        latest_volume_z_score=(
            _rounded(latest_volume_z) if latest_volume_z is not None else None
        ),
        events=events[-50:],
        limitations=[
            "Anomalies are statistical flags, not explanations or trade signals.",
            "Volume is aggregated by the provider and can include venue noise.",
        ],
    )


def build_crypto_risk(
    *,
    overview: CryptoMarket | None,
    technicals: CryptoTechnicalAnalysis | None,
    anomalies: CryptoAnomalyAnalysis | None,
    freshness_confidence: float = 1.0,
) -> CryptoRisk:
    """Build the documented six-component crypto risk score."""
    base_weights = {
        "volatility": 0.30,
        "drawdown": 0.20,
        "liquidity": 0.15,
        "market_size": 0.15,
        "trend_instability": 0.10,
        "anomaly": 0.10,
    }
    scores: dict[str, float] = {}
    missing: list[str] = []

    if technicals is None:
        missing.extend(["volatility", "drawdown", "trend_instability"])
    else:
        scores["volatility"] = _clamp_score(
            technicals.annualized_volatility_percent / 1.5
        )
        scores["drawdown"] = _clamp_score(
            abs(technicals.maximum_drawdown_percent) * 1.5
        )
        trend_base = {"bullish": 20.0, "neutral": 45.0, "bearish": 75.0}[
            technicals.trend
        ]
        scores["trend_instability"] = _clamp_score(
            trend_base + (1 - technicals.confidence) * 20
        )

    if overview is None:
        missing.extend(["liquidity", "market_size"])
    else:
        if (
            overview.market_cap is None
            or overview.market_cap <= 0
            or overview.total_volume_24h is None
        ):
            missing.append("liquidity")
        else:
            turnover = float(overview.total_volume_24h / overview.market_cap)
            scores["liquidity"] = _clamp_score(100 - turnover * 1_000)
        if overview.market_cap is None or overview.market_cap <= 0:
            missing.append("market_size")
        else:
            scores["market_size"] = _clamp_score(
                (12 - math.log10(float(overview.market_cap))) * 12.5
            )

    if anomalies is None:
        missing.append("anomaly")
    else:
        scores["anomaly"] = anomalies.anomaly_score

    available_weight = sum(base_weights[name] for name in scores)
    if available_weight <= 0:
        raise ValueError("at least one crypto risk component is required")
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
    return CryptoRisk(
        overall_score=overall,
        risk_label=label,
        component_scores=scores,
        component_weights=weights,
        data_confidence=_rounded(confidence),
        missing_inputs=missing,
        limitations=[
            "The score uses public market history, not holdings or suitability.",
            "Market cap and volume may change materially between provider updates.",
            "This deterministic score is research information, not advice.",
        ],
    )


__all__ = [
    "CRYPTO_ANOMALY_VERSION",
    "CRYPTO_RISK_VERSION",
    "CRYPTO_TECHNICALS_VERSION",
    "CRYPTO_TREND_VERSION",
    "CryptoAnomalyAnalysis",
    "CryptoAnomalyEvent",
    "CryptoRisk",
    "CryptoTechnicalAnalysis",
    "CryptoTrendAnalysis",
    "analyze_crypto_anomalies",
    "analyze_crypto_technicals",
    "build_crypto_risk",
    "build_crypto_trend",
]
