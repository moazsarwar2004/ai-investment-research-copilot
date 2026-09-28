"""Deterministic financial ratios and fundamental stock risk."""

from __future__ import annotations

from decimal import Decimal
from itertools import pairwise

from pydantic import BaseModel, ConfigDict, Field

from backend.app.providers.stock_fundamentals import FinancialPeriod, FundamentalModel

FUNDAMENTAL_ANALYTICS_VERSION = "stock-fundamentals-v3"
FUNDAMENTAL_RISK_VERSION = "stock-fundamental-risk-v3"


class _FundamentalAnalyticsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class FinancialRatios(_FundamentalAnalyticsModel):
    period_end: str
    fiscal_year: int
    fiscal_period: str
    revenue_growth_percent: float | None = None
    net_income_growth_percent: float | None = None
    gross_margin_percent: float | None = None
    operating_margin_percent: float | None = None
    net_margin_percent: float | None = None
    return_on_assets_percent: float | None = None
    return_on_equity_percent: float | None = None
    current_ratio: float | None = None
    debt_to_equity: float | None = None
    operating_cash_flow_margin_percent: float | None = None
    total_income_growth_percent: float | None = None
    deposit_growth_percent: float | None = None
    financing_growth_percent: float | None = None
    equity_to_assets_percent: float | None = None
    financing_to_deposits_percent: float | None = None
    capital_adequacy_ratio_percent: float | None = None
    non_performing_financing_ratio_percent: float | None = None
    fundamental_model: FundamentalModel = FundamentalModel.CORPORATE
    comparison_period_end: str | None = None
    methodology_version: str = FUNDAMENTAL_ANALYTICS_VERSION


class FundamentalRisk(_FundamentalAnalyticsModel):
    overall_score: float = Field(ge=0, le=100)
    risk_label: str
    component_scores: dict[str, float]
    component_weights: dict[str, float]
    component_explanations: dict[str, str]
    methodology_version: str = FUNDAMENTAL_RISK_VERSION
    data_confidence: float = Field(ge=0, le=1)
    missing_inputs: list[str]
    limitations: list[str]


def _ratio(numerator: Decimal | None, denominator: Decimal | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return round(float(numerator / denominator), 6)


def _percent(numerator: Decimal | None, denominator: Decimal | None) -> float | None:
    value = _ratio(numerator, denominator)
    return None if value is None else round(value * 100, 4)


def _average_percent(
    numerator: Decimal | None,
    current_balance: Decimal | None,
    previous_balance: Decimal | None,
) -> float | None:
    """Use an average positive balance when a comparable prior period exists."""
    if (
        numerator is None
        or current_balance is None
        or previous_balance is None
        or current_balance <= 0
        or previous_balance <= 0
    ):
        return None
    return _percent(numerator, (current_balance + previous_balance) / Decimal("2"))


def _positive_ratio(
    numerator: Decimal | None, denominator: Decimal | None
) -> float | None:
    if denominator is None or denominator <= 0:
        return None
    return _ratio(numerator, denominator)


def _growth(current: Decimal | None, previous: Decimal | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return round(float((current - previous) / abs(previous) * Decimal("100")), 4)


def calculate_financial_ratios(
    periods: list[FinancialPeriod],
    *,
    fundamental_model: FundamentalModel = FundamentalModel.CORPORATE,
) -> list[FinancialRatios]:
    """Calculate period ratios while preserving missing inputs as null."""
    ordered = sorted(periods, key=lambda item: item.period_end)
    results: list[FinancialRatios] = []
    previous_by_period: dict[str, FinancialPeriod] = {}
    for period in ordered:
        previous = previous_by_period.get(period.fiscal_period)
        gross_profit = (
            period.gross_profit
            if period.gross_profit is not None
            else (
                period.revenue - period.cost_of_revenue
                if period.revenue is not None and period.cost_of_revenue is not None
                else None
            )
        )
        is_bank = fundamental_model is FundamentalModel.BANK
        results.append(
            FinancialRatios(
                period_end=period.period_end.isoformat(),
                fiscal_year=period.fiscal_year,
                fiscal_period=period.fiscal_period,
                revenue_growth_percent=(
                    None
                    if is_bank
                    else _growth(period.revenue, previous.revenue if previous else None)
                ),
                net_income_growth_percent=_growth(
                    period.net_income, previous.net_income if previous else None
                ),
                gross_margin_percent=(
                    None if is_bank else _percent(gross_profit, period.revenue)
                ),
                operating_margin_percent=(
                    None
                    if is_bank
                    else _percent(period.operating_profit, period.revenue)
                ),
                net_margin_percent=(
                    None if is_bank else _percent(period.net_income, period.revenue)
                ),
                return_on_assets_percent=_average_percent(
                    period.net_income,
                    period.assets,
                    previous.assets if previous else None,
                ),
                return_on_equity_percent=_average_percent(
                    period.net_income,
                    period.equity,
                    previous.equity if previous else None,
                ),
                current_ratio=(
                    None
                    if is_bank
                    else _positive_ratio(
                        period.current_assets, period.current_liabilities
                    )
                ),
                debt_to_equity=(
                    None if is_bank else _positive_ratio(period.debt, period.equity)
                ),
                operating_cash_flow_margin_percent=(
                    None
                    if is_bank
                    else _percent(period.operating_cash_flow, period.revenue)
                ),
                total_income_growth_percent=(
                    _growth(
                        period.total_income,
                        previous.total_income if previous else None,
                    )
                    if is_bank
                    else None
                ),
                deposit_growth_percent=(
                    _growth(period.deposits, previous.deposits if previous else None)
                    if is_bank
                    else None
                ),
                financing_growth_percent=(
                    _growth(
                        period.financing_and_advances,
                        previous.financing_and_advances if previous else None,
                    )
                    if is_bank
                    else None
                ),
                equity_to_assets_percent=(
                    _percent(period.equity, period.assets) if is_bank else None
                ),
                financing_to_deposits_percent=(
                    _percent(period.financing_and_advances, period.deposits)
                    if is_bank
                    else None
                ),
                capital_adequacy_ratio_percent=(
                    float(period.capital_adequacy_ratio_percent)
                    if period.capital_adequacy_ratio_percent is not None
                    else None
                ),
                non_performing_financing_ratio_percent=(
                    float(period.non_performing_financing_ratio_percent)
                    if period.non_performing_financing_ratio_percent is not None
                    else None
                ),
                fundamental_model=fundamental_model,
                comparison_period_end=(
                    previous.period_end.isoformat() if previous is not None else None
                ),
            )
        )
        previous_by_period[period.fiscal_period] = period
    return results


def _clamp(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 4)


def build_fundamental_risk(
    periods: list[FinancialPeriod],
    ratios: list[FinancialRatios],
    *,
    report_warning_count: int = 0,
    fundamental_model: FundamentalModel = FundamentalModel.CORPORATE,
) -> FundamentalRisk | None:
    """Build an explainable, sector-aware historical fundamental heuristic."""
    if not periods or not ratios:
        return None
    ordered_periods = sorted(periods, key=lambda item: item.period_end)
    ordered_ratios = sorted(ratios, key=lambda item: item.period_end)
    latest = ordered_ratios[-1]
    latest_period = ordered_periods[-1]
    scores: dict[str, float] = {}
    explanations: dict[str, str] = {}
    missing: list[str] = []

    if fundamental_model is FundamentalModel.BANK:
        if latest.capital_adequacy_ratio_percent is not None:
            scores["capital_structure"] = _clamp(
                (20.0 - latest.capital_adequacy_ratio_percent) * 5.0
            )
            explanations["capital_structure"] = (
                "Uses the reported regulatory capital-adequacy ratio; the score "
                "is a transparent heuristic, not a regulatory conclusion."
            )
        elif latest.equity_to_assets_percent is not None:
            scores["capital_structure"] = _clamp(
                (10.0 - latest.equity_to_assets_percent) * 10.0
            )
            explanations["capital_structure"] = (
                "Uses reported equity as a share of assets because a verified "
                "capital-adequacy ratio was not supplied."
            )
        else:
            missing.append("capital_structure")
    elif latest_period.equity is not None and latest_period.equity <= 0:
        scores["leverage_liquidity"] = 100.0
        explanations["leverage_liquidity"] = (
            "Reported equity is non-positive, so debt-to-equity is not meaningful "
            "and balance-sheet risk is treated as severe."
        )
    elif latest.debt_to_equity is not None or latest.current_ratio is not None:
        leverage_score = 0.0
        observations = 0
        if latest.debt_to_equity is not None:
            leverage_score += min(100.0, max(0.0, latest.debt_to_equity * 40.0))
            observations += 1
        if latest.current_ratio is not None:
            liquidity_penalty = max(0.0, min(100.0, (1.5 - latest.current_ratio) * 80))
            leverage_score += liquidity_penalty
            observations += 1
        scores["leverage_liquidity"] = _clamp(leverage_score / observations)
        explanations["leverage_liquidity"] = (
            "Uses long-term debt-to-equity and current ratio when reported."
        )
    else:
        missing.append("leverage_liquidity")

    annual_periods = [item for item in periods if item.fiscal_period == "FY"]
    stability_periods = annual_periods if len(annual_periods) >= 2 else periods
    incomes = [
        item.net_income for item in stability_periods if item.net_income is not None
    ]
    if len(incomes) >= 2:
        negative_share = sum(value < 0 for value in incomes) / len(incomes)
        changes: list[float] = []
        for previous, current in pairwise(incomes):
            if previous != 0:
                changes.append(float(abs((current - previous) / abs(previous))))
        variability = min(1.0, sum(changes) / len(changes)) if changes else 0.0
        scores["earnings_stability"] = _clamp(negative_share * 70 + variability * 30)
        explanations["earnings_stability"] = (
            "Uses the share of loss-making periods and absolute net-income changes."
        )
    else:
        missing.append("earnings_stability")

    scores["filing_risk"] = _clamp(float(report_warning_count * 20))
    explanations["filing_risk"] = (
        "Reflects source and normalization warnings only; filing text is not scored."
    )
    base_weights = (
        {
            "capital_structure": 0.45,
            "earnings_stability": 0.35,
            "filing_risk": 0.20,
        }
        if fundamental_model is FundamentalModel.BANK
        else {
            "leverage_liquidity": 0.45,
            "earnings_stability": 0.35,
            "filing_risk": 0.20,
        }
    )
    available_weight = sum(base_weights[name] for name in scores)
    weights = {name: round(base_weights[name] / available_weight, 6) for name in scores}
    overall = _clamp(sum(scores[name] * weights[name] for name in scores))
    if overall < 25:
        label = "low"
    elif overall < 50:
        label = "moderate"
    elif overall < 75:
        label = "high"
    else:
        label = "severe"
    return FundamentalRisk(
        overall_score=overall,
        risk_label=label,
        component_scores=scores,
        component_weights=weights,
        component_explanations=explanations,
        data_confidence=round(available_weight, 4),
        missing_inputs=missing,
        limitations=[
            "Fundamental risk uses reported historical facts, not current "
            "prices or forecasts.",
            "A low score is not a buy recommendation and does not predict returns.",
            (
                "Bank mode avoids corporate current-ratio and debt-to-equity "
                "metrics; corporate mode uses them only when reported."
            ),
            "The heuristic has not been statistically validated as a default-risk "
            "or return model.",
        ],
    )


__all__ = [
    "FUNDAMENTAL_ANALYTICS_VERSION",
    "FUNDAMENTAL_RISK_VERSION",
    "FinancialRatios",
    "FundamentalRisk",
    "build_fundamental_risk",
    "calculate_financial_ratios",
]
