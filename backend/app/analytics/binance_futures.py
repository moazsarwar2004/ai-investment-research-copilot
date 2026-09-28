"""Explainable derivatives indicators; missing observations remain missing."""

from __future__ import annotations

import statistics
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.providers.binance_futures import (
    FuturesBasisData,
    FuturesFundingData,
    FuturesMarketData,
    FuturesOpenInterestData,
    FuturesPositioningData,
)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class FuturesAnalytics(_Model):
    funding_rate_percent: float | None = None
    average_funding_rate_percent: float | None = None
    observed_funding_interval_hours: float | None = None
    annualized_funding_percent: float | None = None
    open_interest_change_percent: float | None = None
    open_interest_latest_z_score: float | None = None
    open_interest_window_hours: float | None = None
    basis_percent: float | None = None
    mark_index_premium_percent: float | None = None
    long_account_percent: float | None = None
    taker_buy_share_percent: float | None = None
    crowding: Literal["long", "balanced", "short", "mixed", "unavailable"]
    anomalies: list[str]
    limitations: list[str]
    methodology_version: str = "futures-analytics-v1"


class FuturesRisk(_Model):
    overall_score: float = Field(ge=0, le=100)
    risk_label: Literal["low", "moderate", "high", "severe"]
    component_scores: dict[str, float]
    component_weights: dict[str, float]
    data_confidence: float = Field(ge=0, le=1)
    missing_inputs: list[str]
    explanations: list[str]
    limitations: list[str]
    methodology_version: str = "futures-risk-v1"


def analyze_futures(
    *,
    funding: FuturesFundingData | None,
    open_interest: FuturesOpenInterestData | None,
    basis: FuturesBasisData | None,
    positioning: FuturesPositioningData | None,
    market: FuturesMarketData | None = None,
) -> FuturesAnalytics:
    """Use actual settlement spacing; never annualize a perpetual basis."""
    values: dict[str, float | None] = {}
    notes = [
        "Funding annualization is a historical-rate projection, not a return forecast.",
        "Perpetual basis is not annualized. Index is not a spot trade price.",
        "Open-interest change uses base quantity over the selected window.",
    ]
    anomalies: list[str] = []
    if funding:
        rates = [float(point.funding_rate) for point in funding.points]
        values["funding_rate_percent"] = rates[-1] * 100
        values["average_funding_rate_percent"] = statistics.mean(rates) * 100
        if len(funding.points) >= 3:
            gaps = [
                (right.funding_time - left.funding_time).total_seconds() / 3600
                for left, right in zip(
                    funding.points[-3:-1], funding.points[-2:], strict=True
                )
            ]
            # Consistent settlements reduce the risk of annualizing a gap or
            # interval transition; this does not claim the current schedule.
            if gaps[-1] > 0 and abs(gaps[0] - gaps[1]) < 0.001:
                values["observed_funding_interval_hours"] = gaps[-1]
                values["annualized_funding_percent"] = (
                    rates[-1] * 100 * 24 * 365 / gaps[-1]
                )
            else:
                notes.append(
                    "Recent funding spacing changed; annualization is unavailable."
                )
        else:
            notes.append("Fewer than three settlements; annualization is unavailable.")
    if open_interest and len(open_interest.history) >= 2:
        points = open_interest.history
        quantities = [float(point.open_interest) for point in points]
        values["open_interest_window_hours"] = (
            points[-1].timestamp - points[0].timestamp
        ).total_seconds() / 3600
        if quantities[0] > 0:
            values["open_interest_change_percent"] = (
                quantities[-1] / quantities[0] - 1
            ) * 100
        baseline = quantities[:-1]
        if len(baseline) >= 4 and (deviation := statistics.pstdev(baseline)) > 0:
            values["open_interest_latest_z_score"] = (
                quantities[-1] - statistics.mean(baseline)
            ) / deviation
    if basis:
        point = basis.points[-1]
        values["basis_percent"] = float(
            (point.futures_price / point.index_price - 1) * 100
        )
    if market:
        values["mark_index_premium_percent"] = float(
            (market.mark_price / market.index_price - 1) * 100
        )
    if positioning:
        if positioning.account_ratio:
            values["long_account_percent"] = float(
                positioning.account_ratio[-1].long_account_share * 100
            )
        if positioning.taker_flow:
            flow = positioning.taker_flow[-1]
            total = flow.buy_volume + flow.sell_volume
            if total > 0:
                values["taker_buy_share_percent"] = float(flow.buy_volume / total * 100)
            else:
                notes.append("Zero taker volume; buy share is unavailable.")

    directions: set[str] = set()
    for name, centre, threshold, anomaly in (
        ("annualized_funding_percent", 0, 30, "elevated_annualized_funding"),
        ("long_account_percent", 50, 15, "account_positioning_extreme"),
        ("taker_buy_share_percent", 50, 15, "taker_flow_imbalance"),
    ):
        value = values.get(name)
        if value is not None and abs(value - centre) >= threshold:
            anomalies.append(anomaly)
            directions.add("long" if value > centre else "short")
    for name, anomaly_threshold, anomaly in (
        ("basis_percent", 0.5, "basis_dislocation"),
        ("open_interest_latest_z_score", 2, "open_interest_outlier"),
    ):
        value = values.get(name)
        if value is not None and abs(value) >= anomaly_threshold:
            anomalies.append(anomaly)
    crowding: Literal["long", "balanced", "short", "mixed", "unavailable"]
    if len(directions) == 2:
        crowding = "mixed"
    elif "long" in directions:
        crowding = "long"
    elif "short" in directions:
        crowding = "short"
    elif any(
        values.get(key) is not None
        for key in (
            "annualized_funding_percent",
            "long_account_percent",
            "taker_buy_share_percent",
        )
    ):
        crowding = "balanced"
    else:
        crowding = "unavailable"
    return FuturesAnalytics.model_validate(
        {
            **{
                key: round(value, 6) if value is not None else None
                for key, value in values.items()
            },
            "crowding": crowding,
            "anomalies": anomalies,
            "limitations": notes,
        }
    )


def build_futures_risk(
    *,
    analytics: FuturesAnalytics,
    freshness_confidence: float = 1.0,
) -> FuturesRisk | None:
    """Heuristic conditions with weighted evidence coverage, not probabilities."""
    base_weights = {
        "funding_crowding": 0.30,
        "open_interest_instability": 0.25,
        "basis_dislocation": 0.20,
        "positioning_imbalance": 0.25,
    }
    scores: dict[str, float] = {}
    if analytics.annualized_funding_percent is not None:
        scores["funding_crowding"] = abs(analytics.annualized_funding_percent) * 2
    if analytics.open_interest_change_percent is not None:
        scores["open_interest_instability"] = (
            abs(analytics.open_interest_change_percent) * 2
            + abs(analytics.open_interest_latest_z_score or 0) * 15
        )
    if analytics.basis_percent is not None:
        scores["basis_dislocation"] = abs(analytics.basis_percent) * 100
    if (
        analytics.long_account_percent is not None
        and analytics.taker_buy_share_percent is not None
    ):
        scores["positioning_imbalance"] = (
            abs(analytics.long_account_percent - 50) * 2
            + abs(analytics.taker_buy_share_percent - 50) * 2
        )
    if not scores:
        return None
    scores = {key: round(min(100, max(0, value)), 4) for key, value in scores.items()}
    coverage = sum(base_weights[key] for key in scores)
    weights = {key: base_weights[key] / coverage for key in scores}
    overall = round(sum(scores[key] * weights[key] for key in scores), 4)
    label: Literal["low", "moderate", "high", "severe"]
    if overall < 25:
        label = "low"
    elif overall < 50:
        label = "moderate"
    elif overall < 75:
        label = "high"
    else:
        label = "severe"
    return FuturesRisk(
        overall_score=overall,
        risk_label=label,
        component_scores=scores,
        component_weights=weights,
        data_confidence=round(coverage * min(1, max(0, freshness_confidence)), 6),
        missing_inputs=[key for key in base_weights if key not in scores],
        explanations=[
            f"{key.replace('_', ' ')}: {scores[key]:.1f}/100 "
            f"at {weights[key] * 100:.1f}% weight."
            for key in scores
        ],
        limitations=[
            "Heuristic conditions; not calibrated loss or liquidation probability.",
            "Data confidence means input coverage adjusted for stale data.",
            "Scores depend on the history window; compare only matching windows.",
            "Low signal intensity does not mean futures trading is safe.",
            "Account shares do not measure position size. "
            "Missing weights are excluded.",
            *analytics.limitations,
        ],
    )
