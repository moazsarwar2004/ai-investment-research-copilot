"""Recorded-shape tests for official SEC adapters without live calls."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import AnyHttpUrl

from backend.app.providers.models import (
    AssetType,
    CanonicalAsset,
    ProviderHttpResponse,
    ProviderRequest,
)
from backend.app.providers.sec import (
    SecCompanyFactsAdapter,
    SecSubmissionsAdapter,
    SecTickerMapAdapter,
    _periods_from_facts,
)
from backend.app.providers.stock_fundamentals import FinancialFactProvenance


def _response(payload: object, url: str) -> ProviderHttpResponse:
    return ProviderHttpResponse(
        payload=payload,
        fetched_at=datetime(2026, 2, 2, tzinfo=UTC),
        source_url=AnyHttpUrl(url),
        headers={},
        raw_payload_sha256="b" * 64,
        provider_request_id=None,
        attempts=1,
    )


def _request(operation: str, *, cik: str | None = None) -> ProviderRequest:
    return ProviderRequest(
        operation=operation,
        asset=CanonicalAsset(
            asset_type=AssetType.STOCK,
            key="NASDAQ:AAPL",
            provider_id=cik,
        ),
        soft_ttl_seconds=60,
        hard_ttl_seconds=120,
    )


def test_sec_ticker_and_submission_shapes_are_normalized() -> None:
    user_agent = "Research Copilot ops@example.com"
    tickers = SecTickerMapAdapter(user_agent=user_agent).normalize(
        _response(
            {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}},
            "https://www.sec.gov/files/company_tickers.json",
        ),
        _request("sec.tickers"),
    )
    assert tickers.data.companies[0].cik == 320193

    submissions = SecSubmissionsAdapter(user_agent=user_agent).normalize(
        _response(
            {
                "cik": "0000320193",
                "name": "Apple Inc.",
                "sicDescription": "Electronic Computers",
                "fiscalYearEnd": "0927",
                "website": "https://www.apple.com",
                "filings": {
                    "recent": {
                        "accessionNumber": ["0000320193-25-000079"],
                        "form": ["10-K"],
                        "filingDate": ["2025-10-31"],
                        "reportDate": ["2025-09-27"],
                        "primaryDocument": ["aapl-20250927.htm"],
                    }
                },
            },
            "https://data.sec.gov/submissions/CIK0000320193.json",
        ),
        _request("sec.submissions", cik="0000320193"),
    )
    assert submissions.data.reports[0].report_type == "10-K"
    assert "Archives/edgar/data/320193" in str(submissions.data.reports[0].source_url)


def test_sec_company_facts_rejects_stale_comparative_duplicates() -> None:
    payload = {
        "cik": 320193,
        "entityName": "Apple Inc.",
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            {
                                "start": "2024-09-29",
                                "end": "2025-09-27",
                                "val": 100,
                                "accn": "0000320193-25-000079",
                                "fy": 2025,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2025-10-31",
                            },
                            {
                                "start": "2020-01-01",
                                "end": "2020-12-31",
                                "val": 50,
                                "accn": "0000320193-25-000079",
                                "fy": 2025,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2025-10-31",
                            },
                        ]
                    }
                }
            }
        },
    }
    normalized = SecCompanyFactsAdapter(
        user_agent="Research Copilot ops@example.com"
    ).normalize(
        _response(
            payload,
            "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
        ),
        _request("sec.company_facts", cik="0000320193"),
    )
    assert len(normalized.data.facts) == 1
    assert normalized.data.facts[0].value == 100


def test_sec_periods_do_not_mix_quarter_and_year_to_date_contexts() -> None:
    def values(quarter: int, year_to_date: int) -> list[dict[str, object]]:
        common = {
            "end": "2025-06-30",
            "accn": "0000000001-25-000010",
            "fy": 2025,
            "fp": "Q2",
            "form": "10-Q",
            "filed": "2025-08-01",
        }
        return [
            {
                **common,
                "start": "2025-04-01",
                "val": quarter,
                "frame": "CY2025Q2",
            },
            {**common, "start": "2025-01-01", "val": year_to_date},
        ]

    payload = {
        "cik": 1,
        "entityName": "Context Test Inc.",
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {"USD": values(350, 600)}
                },
                "NetIncomeLoss": {"units": {"USD": values(40, 70)}},
                "Assets": {
                    "units": {
                        "USD": [
                            {
                                "end": "2025-06-30",
                                "val": 2000,
                                "accn": "0000000001-25-000010",
                                "fy": 2025,
                                "fp": "Q2",
                                "form": "10-Q",
                                "filed": "2025-08-01",
                            }
                        ]
                    }
                },
            }
        },
    }
    normalized = SecCompanyFactsAdapter(
        user_agent="Research Copilot ops@example.com"
    ).normalize(
        _response(payload, "https://data.sec.gov/api/xbrl/companyfacts/CIK1.json"),
        _request("sec.company_facts", cik="0000000001"),
    )

    periods = _periods_from_facts("0000000001", normalized.data.facts)

    assert len(periods) == 1
    assert periods[0].period_start is not None
    assert periods[0].period_start.isoformat() == "2025-04-01"
    assert periods[0].revenue == 350
    assert periods[0].net_income == 40
    assert periods[0].assets == 2000
    sources = list(periods[0].fact_sources.values())
    assert all(isinstance(source, FinancialFactProvenance) for source in sources)
    assert {
        source.accession_number
        for source in sources
        if isinstance(source, FinancialFactProvenance)
    } == {"0000000001-25-000010"}


def test_sec_aliases_are_selected_per_period_and_accessions_are_not_mixed() -> None:
    payload = {
        "cik": 1,
        "entityName": "Alias Test Inc.",
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            {
                                "start": "2024-01-01",
                                "end": "2024-12-31",
                                "val": 120,
                                "accn": "0000000001-25-000001",
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2025-02-01",
                            }
                        ]
                    }
                },
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "start": "2023-01-01",
                                "end": "2023-12-31",
                                "val": 100,
                                "accn": "0000000001-24-000001",
                                "fy": 2023,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2024-02-01",
                            }
                        ]
                    }
                },
                "Assets": {
                    "units": {
                        "USD": [
                            {
                                "end": "2024-12-31",
                                "val": 999,
                                "accn": "0000000001-25-999999",
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2025-02-02",
                            }
                        ]
                    }
                },
            }
        },
    }
    normalized = SecCompanyFactsAdapter(
        user_agent="Research Copilot ops@example.com"
    ).normalize(
        _response(payload, "https://data.sec.gov/api/xbrl/companyfacts/CIK1.json"),
        _request("sec.company_facts", cik="0000000001"),
    )

    periods = _periods_from_facts("0000000001", normalized.data.facts)

    assert [item.revenue for item in periods] == [100, 120]
    assert periods[-1].assets is None
    revenue_source = periods[0].fact_sources["revenue"]
    assert isinstance(revenue_source, FinancialFactProvenance)
    assert revenue_source.concept == "Revenues"


def test_sec_period_prefers_a_later_amendment_with_anchor_facts() -> None:
    payload = {
        "cik": 1,
        "entityName": "Amendment Test Inc.",
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            {
                                "start": "2024-01-01",
                                "end": "2024-12-31",
                                "val": 100,
                                "accn": "0000000001-25-000001",
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2025-02-01",
                            },
                            {
                                "start": "2024-01-01",
                                "end": "2024-12-31",
                                "val": 105,
                                "accn": "0000000001-25-000002",
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K/A",
                                "filed": "2025-03-01",
                            },
                        ]
                    }
                },
                "Assets": {
                    "units": {
                        "USD": [
                            {
                                "end": "2024-12-31",
                                "val": 500,
                                "accn": "0000000001-25-000001",
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2025-02-01",
                            }
                        ]
                    }
                },
            }
        },
    }
    normalized = SecCompanyFactsAdapter(
        user_agent="Research Copilot ops@example.com"
    ).normalize(
        _response(payload, "https://data.sec.gov/api/xbrl/companyfacts/CIK1.json"),
        _request("sec.company_facts", cik="0000000001"),
    )

    periods = _periods_from_facts("0000000001", normalized.data.facts)

    assert len(periods) == 1
    assert periods[0].revenue == 105
    assert periods[0].assets is None
    assert periods[0].source_label.startswith("SEC 10-K/A")
