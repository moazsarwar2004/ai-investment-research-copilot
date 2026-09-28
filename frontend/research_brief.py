"""Deterministic, source-backed stock questions and downloadable briefs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

GUIDED_QUESTIONS = {
    "performance": "How did the latest reported performance change?",
    "risk": "What drives the fundamental risk indicator?",
    "evidence": "Which official reports support this research?",
    "limitations": "What information is missing or uncertain?",
}


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _latest(items: object) -> dict[str, Any]:
    if not isinstance(items, list):
        return {}
    mappings = [item for item in items if isinstance(item, dict)]
    return max(mappings, key=lambda item: str(item.get("period_end", "")), default={})


def _number(value: object, *, suffix: str = "") -> str:
    if value is None:
        return "unavailable"
    try:
        rendered = f"{float(str(value)):,.2f}"
    except (TypeError, ValueError):
        return "unavailable"
    return f"{rendered}{suffix}"


def _escape_label(value: object) -> str:
    return str(value or "Official source").replace("[", "\\[").replace("]", "\\]")


def _source_link(label: object, url: object) -> str:
    rendered = str(url or "")
    if not rendered.startswith("https://"):
        return _escape_label(label)
    safe_url = rendered.replace("(", "%28").replace(")", "%29")
    return f"[{_escape_label(label)}]({safe_url})"


def answer_stock_question(payload: dict[str, Any], question: str) -> str:
    """Answer a bounded question only from structured response evidence."""
    data = _mapping(payload.get("data"))
    fundamentals = _mapping(data.get("fundamentals"))
    period = _latest(fundamentals.get("periods"))
    ratio = _latest(fundamentals.get("ratios"))
    risk = _mapping(fundamentals.get("risk"))
    fundamental_model = str(fundamentals.get("fundamental_model", "corporate"))

    if question == "performance":
        if not period:
            return "No verified financial period is available for this company."
        source = _source_link(period.get("source_label"), period.get("source_url"))
        if fundamental_model == "bank":
            return (
                f"For {period.get('fiscal_period', '?')} "
                f"{period.get('fiscal_year', '?')}, reported total income was "
                f"{_number(period.get('total_income'))} "
                f"{period.get('currency', '')}, net income was "
                f"{_number(period.get('net_income'))}, and deposits were "
                f"{_number(period.get('deposits'))}. Like-period total-income "
                "growth was "
                f"{_number(ratio.get('total_income_growth_percent'), suffix='%')} "
                f"and deposit growth was "
                f"{_number(ratio.get('deposit_growth_percent'), suffix='%')}. "
                f"Source: {source}."
            )
        return (
            f"For {period.get('fiscal_period', '?')} {period.get('fiscal_year', '?')}, "
            f"reported revenue was {_number(period.get('revenue'))} "
            f"{period.get('currency', '')} and net income was "
            f"{_number(period.get('net_income'))}. Like-period revenue growth was "
            f"{_number(ratio.get('revenue_growth_percent'), suffix='%')} and net "
            f"margin was {_number(ratio.get('net_margin_percent'), suffix='%')}. "
            f"Source: {source}."
        )

    if question == "risk":
        if not risk:
            return "The deterministic fundamental risk indicator is unavailable."
        components = _mapping(risk.get("component_scores"))
        explanations = _mapping(risk.get("component_explanations"))
        details = "; ".join(
            f"{name.replace('_', ' ')} {_number(score)} — "
            f"{explanations.get(name, 'methodology explanation unavailable')}"
            for name, score in components.items()
        )
        return (
            f"The heuristic score is {_number(risk.get('overall_score'))}/100 "
            f"({risk.get('risk_label', 'unknown')}) with data confidence "
            f"{_number(risk.get('data_confidence'))}. {details}. This describes "
            "historical reported inputs; it is not a forecast or recommendation."
        )

    if question == "evidence":
        reports = fundamentals.get("reports")
        if not isinstance(reports, list) or not reports:
            return "No verified report links are available for this company."
        links = [
            _source_link(item.get("title"), item.get("source_url"))
            for item in reports[:5]
            if isinstance(item, dict)
        ]
        return "Supporting official reports: " + ", ".join(links) + "."

    if question == "limitations":
        missing = risk.get("missing_inputs")
        warnings = fundamentals.get("source_warnings")
        parts = [
            "Current stock prices may be unavailable without reviewed display rights.",
            "Reported fundamentals are historical and may be amended.",
        ]
        if isinstance(missing, list) and missing:
            parts.append("Missing risk inputs: " + ", ".join(map(str, missing)) + ".")
        if isinstance(warnings, list):
            parts.extend(str(item) for item in warnings[:3])
        return " ".join(parts)

    return "Select one of the supported evidence questions."


def build_stock_research_brief(
    payload: dict[str, Any], *, generated_at: datetime | None = None
) -> str:
    """Build a reproducible Markdown brief without an LLM or invented facts."""
    generated = (generated_at or datetime.now(UTC)).astimezone(UTC)
    data = _mapping(payload.get("data"))
    meta = _mapping(payload.get("meta"))
    fundamentals = _mapping(data.get("fundamentals"))
    profile = _mapping(fundamentals.get("profile")) or _mapping(data.get("profile"))
    period = _latest(fundamentals.get("periods"))
    ratio = _latest(fundamentals.get("ratios"))
    risk = _mapping(fundamentals.get("risk"))
    fundamental_model = str(fundamentals.get("fundamental_model", "corporate"))
    identity = f"{data.get('exchange', '?')}:{data.get('symbol', '?')}"
    title = profile.get("company_name") or identity

    lines = [
        f"# {title} — research brief",
        "",
        f"- Identity: `{identity}`",
        f"- Generated: {generated.isoformat()}",
        f"- Data modes: {', '.join(map(str, data.get('data_modes', []))) or 'none'}",
        f"- Freshness: {meta.get('freshness', 'unknown')}",
        f"- Cache state: {meta.get('cache_status', 'unknown')}",
        "",
        "## Reported facts",
        "",
    ]
    if period:
        period_heading = (
            f"Period: {period.get('fiscal_period', '?')} "
            f"{period.get('fiscal_year', '?')} ending {period.get('period_end', '?')}"
        )
        currency = str(period.get("currency", ""))
        evidence = _source_link(period.get("source_label"), period.get("source_url"))
        facts = (
            [
                ("Total income", period.get("total_income")),
                ("Net income", period.get("net_income")),
                ("Deposits", period.get("deposits")),
                ("Financing and advances", period.get("financing_and_advances")),
                ("Investments", period.get("investments")),
                ("Assets", period.get("assets")),
                ("Liabilities", period.get("liabilities")),
                ("Equity", period.get("equity")),
            ]
            if fundamental_model == "bank"
            else [
                ("Revenue", period.get("revenue")),
                ("Net income", period.get("net_income")),
                ("EPS", period.get("eps")),
                ("Assets", period.get("assets")),
                ("Liabilities", period.get("liabilities")),
                ("Equity", period.get("equity")),
            ]
        )
        lines.extend(
            [period_heading, "", "| Fact | Reported value |", "| --- | ---: |"]
        )
        lines.extend(
            f"| {label} | {_number(value)} {currency if label != 'EPS' else ''} |"
            for label, value in facts
        )
        lines.extend(["", f"Evidence: {evidence}"])
    else:
        lines.append("No verified financial period is available.")

    lines.extend(["", "## Calculated metrics", ""])
    if ratio:
        if fundamental_model == "bank":
            financing_to_deposits = _number(
                ratio.get("financing_to_deposits_percent"), suffix="%"
            )
            lines.extend(
                [
                    "- Like-period total-income growth: "
                    f"{_number(ratio.get('total_income_growth_percent'), suffix='%')}",
                    "- Deposit growth: "
                    f"{_number(ratio.get('deposit_growth_percent'), suffix='%')}",
                    "- Financing growth: "
                    f"{_number(ratio.get('financing_growth_percent'), suffix='%')}",
                    "- Equity to assets: "
                    f"{_number(ratio.get('equity_to_assets_percent'), suffix='%')}",
                    f"- Financing to deposits: {financing_to_deposits}",
                    f"- Methodology: `{ratio.get('methodology_version', 'unknown')}`",
                ]
            )
        else:
            revenue_growth = _number(ratio.get("revenue_growth_percent"), suffix="%")
            lines.extend(
                [
                    f"- Like-period revenue growth: {revenue_growth}",
                    "- Net margin: "
                    f"{_number(ratio.get('net_margin_percent'), suffix='%')}",
                    f"- Current ratio: {_number(ratio.get('current_ratio'))}",
                    f"- Debt to equity: {_number(ratio.get('debt_to_equity'))}",
                    f"- Methodology: `{ratio.get('methodology_version', 'unknown')}`",
                ]
            )
    else:
        lines.append("Calculated financial ratios are unavailable.")

    lines.extend(["", "## Deterministic risk interpretation", ""])
    if risk:
        risk_score = _number(risk.get("overall_score"))
        risk_label = risk.get("risk_label", "unknown")
        lines.extend(
            [
                f"- Score: {risk_score}/100 ({risk_label})",
                f"- Data confidence: {_number(risk.get('data_confidence'))}",
                f"- Methodology: `{risk.get('methodology_version', 'unknown')}`",
            ]
        )
        for limitation in risk.get("limitations", []):
            lines.append(f"- Limitation: {limitation}")
    else:
        lines.append("The fundamental risk indicator is unavailable.")

    lines.extend(["", "## Official sources", ""])
    reports = fundamentals.get("reports")
    if isinstance(reports, list) and reports:
        for item in reports[:10]:
            if isinstance(item, dict):
                report_type = item.get("report_type", "report")
                published_at = item.get("published_at") or item.get(
                    "publication_period", "?"
                )
                lines.append(
                    f"- {_source_link(item.get('title'), item.get('source_url'))} "
                    f"({report_type}, {published_at})"
                )
    else:
        lines.append("- No verified report links are available.")

    lines.extend(
        [
            "",
            "## Responsible-use notice",
            "",
            "This brief separates reported facts, deterministic calculations, and "
            "methodology-based interpretation. It is research and education only, "
            "not personalized financial advice, and does not predict or promise "
            "returns.",
        ]
    )
    return "\n".join(lines) + "\n"


__all__ = ["GUIDED_QUESTIONS", "answer_stock_question", "build_stock_research_brief"]
