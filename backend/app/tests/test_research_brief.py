"""Deterministic frontend evidence assistant and API target tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from frontend.client import ResearchApiError, _api_base_url
from frontend.research_brief import answer_stock_question, build_stock_research_brief


def _payload() -> dict[str, object]:
    return {
        "data": {
            "exchange": "NASDAQ",
            "symbol": "TEST",
            "data_modes": ["official_reports"],
            "fundamentals": {
                "profile": {"company_name": "Test Company"},
                "periods": [
                    {
                        "fiscal_year": 2025,
                        "fiscal_period": "FY",
                        "period_end": "2025-12-31",
                        "currency": "USD",
                        "revenue": "1000",
                        "net_income": "100",
                        "eps": "2.5",
                        "assets": "800",
                        "liabilities": "300",
                        "equity": "500",
                        "source_label": "SEC 10-K test accession",
                        "source_url": "https://www.sec.gov/Archives/test.htm",
                    }
                ],
                "ratios": [
                    {
                        "period_end": "2025-12-31",
                        "revenue_growth_percent": 10,
                        "net_margin_percent": 10,
                        "current_ratio": 1.5,
                        "debt_to_equity": 0.4,
                        "methodology_version": "stock-fundamentals-v2",
                    }
                ],
                "reports": [
                    {
                        "title": "2025 Form 10-K",
                        "report_type": "10-K",
                        "published_at": "2026-02-01",
                        "source_url": "https://www.sec.gov/Archives/test.htm",
                    }
                ],
                "risk": {
                    "overall_score": 25,
                    "risk_label": "moderate",
                    "data_confidence": 1,
                    "methodology_version": "stock-fundamental-risk-v2",
                    "component_scores": {"leverage_liquidity": 20},
                    "component_explanations": {
                        "leverage_liquidity": "Uses reported balance-sheet facts."
                    },
                    "missing_inputs": [],
                    "limitations": ["Not a return forecast."],
                },
            },
        },
        "meta": {"freshness": "cached", "cache_status": "hit"},
    }


def test_research_brief_separates_facts_metrics_risk_and_sources() -> None:
    payload = _payload()

    brief = build_stock_research_brief(
        payload, generated_at=datetime(2026, 9, 17, tzinfo=UTC)
    )
    answer = answer_stock_question(payload, "performance")

    assert "## Reported facts" in brief
    assert "## Calculated metrics" in brief
    assert "## Deterministic risk interpretation" in brief
    assert "https://www.sec.gov/Archives/test.htm" in brief
    assert "does not predict or promise returns" in brief
    assert "Like-period revenue growth was 10.00%" in answer


def test_frontend_rejects_nonconfigured_api_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COPILOT_API_URL", "https://research.example.com")

    assert _api_base_url("https://research.example.com/") == (
        "https://research.example.com"
    )
    with pytest.raises(ResearchApiError, match="not allowed"):
        _api_base_url("http://169.254.169.254")
