"""HTTP contract tests for the exchange-neutral stock surface."""

from __future__ import annotations

from httpx import AsyncClient


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
    }
    assert expected_paths <= set(openapi["paths"])
