"""HTTP contract tests for the exchange-neutral stock surface."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from httpx import AsyncClient

from backend.app.providers.stock_fundamentals import OfficialReportManifestProvider
from backend.app.services.stock_service import StockService


def _approved_psx_manifest_path() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "data"
        / "psx"
        / "psx_fundamentals.approved.json"
    )


async def test_stock_research_defaults_to_psx_and_discloses_license_gate(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/v1/stocks/OGDC/research")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["exchange"] == "PSX"
    assert payload["data"]["symbol"] == "OGDC"
    assert payload["data"]["market_data_status"] == "unavailable"
    assert payload["data"]["quote"] is None
    assert payload["data"]["candles"] is None
    assert payload["data"]["license"]["display_authorized"] is False
    assert payload["meta"]["freshness"] == "unavailable"
    assert payload["meta"]["partial"] is True
    assert response.headers["cache-control"] == "no-store"


async def test_human_approved_psx_fundamentals_are_published_without_prices(
    client: AsyncClient,
    application: FastAPI,
) -> None:
    provider = OfficialReportManifestProvider.from_file(_approved_psx_manifest_path())
    application.state.stock_service = StockService(fundamentals_provider=provider)

    systems = await client.get("/api/v1/stocks/SYS/research")
    meezan = await client.get("/api/v1/stocks/MEBL/research")

    assert systems.status_code == 200
    systems_data = systems.json()["data"]
    assert systems_data["quote"] is None
    assert systems_data["market_data_status"] == "unavailable"
    assert systems_data["fundamentals"]["fundamental_model"] == "corporate"
    assert systems_data["fundamentals"]["periods"][-1]["revenue"] == "80391884594"
    assert systems_data["data_modes"] == ["official_reports"]

    assert meezan.status_code == 200
    meezan_data = meezan.json()["data"]
    assert meezan_data["quote"] is None
    assert meezan_data["fundamentals"]["fundamental_model"] == "bank"
    assert meezan_data["fundamentals"]["periods"][-1]["deposits"] == "3302337407000"
    assert meezan_data["data_modes"] == ["official_reports"]


async def test_stock_identity_can_select_another_exchange_without_route_changes(
    client: AsyncClient,
) -> None:
    response = await client.get(
        "/api/v1/stocks/AAPL/research",
        params={"exchange": "NASDAQ", "interval": "1w", "days": 730},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["exchange"] == "NASDAQ"
    assert payload["data"]["symbol"] == "AAPL"
    assert payload["data"]["interval"] == "1w"
    assert payload["data"]["days"] == 730


async def test_stock_search_is_empty_not_misleading_when_unlicensed(
    client: AsyncClient,
) -> None:
    response = await client.get(
        "/api/v1/stocks/search",
        params={"q": "OGDC", "exchange": "PSX"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["query"] == "OGDC"
    assert payload["data"]["exchange"] == "PSX"
    assert payload["data"]["results"] == []
    assert payload["meta"]["freshness"] == "unavailable"


async def test_stock_bounds_fail_before_service_work(client: AsyncClient) -> None:
    lowercase = await client.get("/api/v1/stocks/ogdc/research")
    unknown_exchange = await client.get("/api/v1/stocks/OGDC/research?exchange=LSE")
    unknown_interval = await client.get("/api/v1/stocks/OGDC/research?interval=1m")
    unknown_range = await client.get("/api/v1/stocks/OGDC/research?days=200")

    assert lowercase.status_code == 422
    assert unknown_exchange.status_code == 422
    assert unknown_interval.status_code == 422
    assert unknown_range.status_code == 422


async def test_phase_7_stock_routes_are_documented(client: AsyncClient) -> None:
    openapi = (await client.get("/openapi.json")).json()

    expected_paths = {
        "/api/v1/stocks/search",
        "/api/v1/stocks/{symbol}",
        "/api/v1/stocks/{symbol}/candles",
        "/api/v1/stocks/{symbol}/technicals",
        "/api/v1/stocks/{symbol}/trend",
        "/api/v1/stocks/{symbol}/risk",
        "/api/v1/stocks/{symbol}/research",
        "/api/v1/stocks/{symbol}/financials",
        "/api/v1/stocks/{symbol}/ratios",
        "/api/v1/stocks/{symbol}/filings",
        "/api/v1/stocks/{symbol}/price-uploads",
        "/api/v1/stocks/{symbol}/price-uploads/{upload_id}",
    }
    assert expected_paths <= set(openapi["paths"])
