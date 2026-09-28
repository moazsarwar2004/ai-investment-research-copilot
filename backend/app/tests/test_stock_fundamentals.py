"""Phase 8 official-report fundamentals and deterministic analytics tests."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import AnyHttpUrl

from backend.app.analytics.stock_fundamentals import (
    build_fundamental_risk,
    calculate_financial_ratios,
)
from backend.app.core.exceptions import ResourceNotFoundError
from backend.app.providers.stock_fundamentals import (
    CompanyReport,
    FactReviewStatus,
    FinancialPeriod,
    ManifestReview,
    OfficialReportFactProvenance,
    OfficialReportManifest,
    OfficialReportManifestCompany,
    OfficialReportManifestProvider,
    PublicationStatus,
    ReportingBasis,
    StockDataMode,
    StockFundamentalsSnapshot,
)
from backend.app.providers.stocks import StockExchange, StockInterval, StockProfile
from backend.app.services.stock_service import StockService


def _period(year: int, *, revenue: str, income: str, debt: str) -> FinancialPeriod:
    url = AnyHttpUrl("https://example.invalid/reports/2025.pdf")
    period = FinancialPeriod(
        fiscal_year=year,
        fiscal_period="FY",
        period_start=date(year, 1, 1),
        period_end=date(year, 12, 31),
        currency="PKR",
        reporting_basis=ReportingBasis.CONSOLIDATED,
        revenue=Decimal(revenue),
        cost_of_revenue=Decimal(revenue) * Decimal("0.55"),
        operating_profit=Decimal(income) * Decimal("1.25"),
        net_income=Decimal(income),
        eps=Decimal("12.5"),
        assets=Decimal("5000"),
        current_assets=Decimal("1800"),
        liabilities=Decimal("2200"),
        current_liabilities=Decimal("1000"),
        equity=Decimal("2800"),
        debt=Decimal(debt),
        cash=Decimal("600"),
        operating_cash_flow=Decimal("900"),
        source_url=url,
        source_label=f"Illustrative official annual report {year}",
    )
    populated = {
        name: value
        for name in (
            "revenue",
            "cost_of_revenue",
            "operating_profit",
            "net_income",
            "eps",
            "assets",
            "current_assets",
            "liabilities",
            "current_liabilities",
            "equity",
            "debt",
            "cash",
            "operating_cash_flow",
        )
        if (value := getattr(period, name)) is not None
    }
    evidence = {
        name: OfficialReportFactProvenance(
            report_id="illustrative-2025",
            document_page=10,
            printed_page="10",
            source_table="Illustrative statements",
            reported_label=name,
            reported_value=value,
            reported_unit="PKR",
            unit_scale=1,
            reporting_basis=ReportingBasis.CONSOLIDATED,
            extraction_method="manual_transcription",
            review_status=FactReviewStatus.HUMAN_VERIFIED,
        )
        for name, value in populated.items()
    }
    return period.model_copy(update={"fact_sources": evidence})


def _provider() -> OfficialReportManifestProvider:
    report_url = AnyHttpUrl("https://example.invalid/reports/2025.pdf")
    snapshot = StockFundamentalsSnapshot(
        symbol="OGDC",
        exchange=StockExchange.PSX,
        profile=StockProfile(
            symbol="OGDC",
            company_name="Illustrative Energy Limited",
            exchange=StockExchange.PSX,
            currency="PKR",
            country="Pakistan",
            provider_id="PSX:OGDC",
        ),
        periods=[
            _period(2024, revenue="10000", income="1000", debt="1200"),
            _period(2025, revenue="11500", income="1250", debt="1000"),
        ],
        reports=[
            CompanyReport(
                report_id="illustrative-2025",
                report_type="annual",
                title="Illustrative annual report 2025",
                published_at=date(2026, 2, 1),
                period_end=date(2025, 12, 31),
                source_url=report_url,
                source_name="Illustrative official company source",
                reporting_basis=ReportingBasis.CONSOLIDATED,
                document_sha256="b" * 64,
                document_page_count=20,
            )
        ],
    )
    manifest = OfficialReportManifest(
        schema_version="official-report-manifest-v2",
        generated_at=datetime(2026, 2, 2, tzinfo=UTC),
        source_name="official-report-fixture",
        attribution="Illustrative official-report test fixture",
        terms_review_version="fixture-review-v1",
        allowed_source_hosts=["example.invalid"],
        companies=[
            OfficialReportManifestCompany(
                review=ManifestReview(
                    status=PublicationStatus.APPROVED,
                    human_reviewer="Test fixture reviewer",
                    reviewed_at=datetime(2026, 2, 2, tzinfo=UTC),
                    source_identity_checked=True,
                    statement_basis_checked=True,
                    figures_checked=True,
                    unit_conversion_checked=True,
                    accounting_checks_checked=True,
                ),
                fundamentals=snapshot,
            )
        ],
    )
    return OfficialReportManifestProvider(manifest, raw_sha256="a" * 64)


def test_ratios_compare_like_periods_and_risk_is_reproducible() -> None:
    periods = [
        _period(2024, revenue="10000", income="1000", debt="1200"),
        _period(2025, revenue="11500", income="1250", debt="1000"),
    ]

    first = calculate_financial_ratios(periods)
    second = calculate_financial_ratios(periods)
    risk = build_fundamental_risk(periods, first)

    assert first == second
    assert first[-1].revenue_growth_percent == 15.0
    assert first[-1].net_margin_percent is not None
    assert first[-1].net_margin_percent > 10
    assert first[-1].current_ratio == 1.8
    assert risk is not None
    assert set(risk.component_scores) == {
        "leverage_liquidity",
        "earnings_stability",
        "filing_risk",
    }
    assert risk.data_confidence == 1
    assert first[-1].comparison_period_end == "2024-12-31"


def test_negative_equity_is_not_reported_as_low_leverage_risk() -> None:
    periods = [
        _period(2024, revenue="10000", income="1000", debt="1200"),
        _period(2025, revenue="9000", income="-500", debt="1500").model_copy(
            update={"equity": Decimal("-200")}
        ),
    ]
    ratios = calculate_financial_ratios(periods)

    risk = build_fundamental_risk(periods, ratios)

    assert ratios[-1].debt_to_equity is None
    assert ratios[-1].return_on_equity_percent is None
    assert risk is not None
    assert risk.component_scores["leverage_liquidity"] == 100
    assert "non-positive" in risk.component_explanations["leverage_liquidity"]


async def test_official_fundamentals_survive_unavailable_market_prices() -> None:
    service = StockService(fundamentals_provider=_provider())

    result = await service.research(
        StockExchange.PSX,
        "OGDC",
        interval=StockInterval.DAY,
        days=365,
    )

    assert result.data.quote is None
    assert result.data.technicals is None
    assert result.data.profile is not None
    assert result.data.fundamentals is not None
    assert result.data.fundamentals.ratios[-1].revenue_growth_percent == 15
    assert result.data.data_modes == [StockDataMode.OFFICIAL_REPORTS]
    assert result.meta.partial is True
    assert any(
        warning.code == "stock_quote_unavailable" for warning in result.meta.warnings
    )


def _candidate_manifest_path() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "data"
        / "psx"
        / "psx_fundamentals.candidate.json"
    )


async def test_real_psx_candidates_validate_but_are_not_published() -> None:
    provider = OfficialReportManifestProvider.from_file(_candidate_manifest_path())

    assert provider.publication_summary.total == 2
    assert provider.publication_summary.approved == 0
    assert provider.publication_summary.gated_symbols == ["MEBL", "SYS"]
    with pytest.raises(ResourceNotFoundError, match="Human-approved"):
        await provider.fundamentals(StockExchange.PSX, "SYS")


def test_meezan_candidate_uses_bank_ratios_not_corporate_ratios() -> None:
    manifest = OfficialReportManifest.model_validate_json(
        _candidate_manifest_path().read_text(encoding="utf-8")
    )
    mebl = next(
        item.fundamentals
        for item in manifest.companies
        if item.fundamentals.symbol == "MEBL"
    )

    ratios = calculate_financial_ratios(
        mebl.periods,
        fundamental_model=mebl.fundamental_model,
    )
    risk = build_fundamental_risk(
        mebl.periods,
        ratios,
        fundamental_model=mebl.fundamental_model,
    )

    assert ratios[-1].current_ratio is None
    assert ratios[-1].debt_to_equity is None
    assert ratios[-1].deposit_growth_percent == pytest.approx(27.77, abs=0.01)
    assert ratios[-1].total_income_growth_percent is not None
    assert ratios[-1].total_income_growth_percent < 0
    assert risk is not None
    assert "capital_structure" in risk.component_scores
    assert "leverage_liquidity" not in risk.component_scores


def test_manifest_rejects_broken_unit_conversion() -> None:
    payload = json.loads(_candidate_manifest_path().read_text(encoding="utf-8"))
    payload["companies"][1]["fundamentals"]["periods"][1]["assets"] = "1"

    with pytest.raises(ValueError, match="normalized assets"):
        OfficialReportManifest.model_validate(payload)


def test_manifest_cannot_claim_approval_without_human_review() -> None:
    payload = json.loads(_candidate_manifest_path().read_text(encoding="utf-8"))
    payload["companies"][0]["review"]["status"] = "approved"

    with pytest.raises(ValueError, match="named human reviewer"):
        OfficialReportManifest.model_validate(payload)
