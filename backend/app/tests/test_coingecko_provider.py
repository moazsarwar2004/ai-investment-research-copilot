"""Fixture-driven CoinGecko adapter, identity, and budget tests."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import AnyHttpUrl, ValidationError

from backend.app.providers import (
    AssetType,
    CanonicalAsset,
    ProviderHttpResponse,
    ProviderQuotaExceededError,
    ProviderQuotaManager,
    ProviderRequest,
    QuotaPolicy,
    RequestKind,
)
from backend.app.providers.coingecko import (
    CoinGeckoGlobalAdapter,
    CoinGeckoHistoryAdapter,
    CoinGeckoMarketsAdapter,
    CoinGeckoSearchAdapter,
    CoinGeckoTrendingAdapter,
)

_BASE_URL = "https://api.coingecko.com/api/v3"
_FETCHED_AT = datetime(2026, 8, 4, 8, 1, tzinfo=UTC)


def _response(payload: object, path: str) -> ProviderHttpResponse:
    return ProviderHttpResponse(
        payload=payload,
        fetched_at=_FETCHED_AT,
        source_url=AnyHttpUrl(f"{_BASE_URL}{path}"),
        headers={},
        raw_payload_sha256="c" * 64,
        provider_request_id=None,
        attempts=1,
    )


def _request(
    operation: str,
    *,
    key: str = "bitcoin",
    parameters: dict[str, str | int | float | bool | None] | None = None,
) -> ProviderRequest:
    return ProviderRequest(
        operation=operation,
        asset=CanonicalAsset(
            asset_type=(
                AssetType.SYSTEM if operation != "crypto.history" else AssetType.CRYPTO
            ),
            key=key,
            provider_id=key if operation == "crypto.history" else None,
        ),
        parameters=parameters or {},
        weight=1,
        soft_ttl_seconds=300,
        hard_ttl_seconds=1_800,
    )


def test_search_preserves_provider_ids_and_exposes_symbol_ambiguity(
    coingecko_payloads: dict[str, Any],
) -> None:
    adapter = CoinGeckoSearchAdapter(_BASE_URL, demo_api_key="demo-secret")
    request = _request(
        "crypto.search",
        key="btc-search",
        parameters={"query": "BTC"},
    )

    outbound = adapter.build_request(request)
    normalized = adapter.normalize(
        _response(coingecko_payloads["search"], "/search"),
        request,
    )

    assert str(outbound.url) == f"{_BASE_URL}/search"
    assert outbound.params == {"query": "BTC"}
    assert outbound.headers["x-cg-demo-api-key"] == "demo-secret"
    assert "demo-secret" not in str(outbound.url)
    assert normalized.data.resolution.ambiguous_symbol is True
    assert normalized.data.resolution.exact_symbol_coin_ids == [
        "bitcoin",
        "bitcoin-wrapped",
    ]
    assert normalized.data.coins[0].coin_id == "bitcoin"


def test_market_overview_is_decimal_safe_and_uses_provider_id_filter(
    coingecko_payloads: dict[str, Any],
) -> None:
    adapter = CoinGeckoMarketsAdapter(_BASE_URL)
    request = _request(
        "crypto.overview",
        parameters={
            "coin_id": "bitcoin",
            "page": 1,
            "per_page": 1,
            "order": "market_cap_desc",
        },
    )
    outbound = adapter.build_request(request)
    normalized = adapter.normalize(
        _response([coingecko_payloads["markets"][0]], "/coins/markets"),
        request,
    )

    assert outbound.params["ids"] == "bitcoin"
    assert "symbol" not in outbound.params
    assert str(normalized.data.markets[0].current_price) == "119000.25"
    assert str(normalized.data.markets[0].distance_from_ath_percent).startswith("5.555")
    assert normalized.data.markets[0].symbol == "BTC"


def test_history_range_is_bounded_and_core_schema_change_is_rejected(
    coingecko_payloads: dict[str, Any],
) -> None:
    adapter = CoinGeckoHistoryAdapter(_BASE_URL)
    request = _request("crypto.history", parameters={"days": 90})
    outbound = adapter.build_request(request)
    normalized = adapter.normalize(
        _response(coingecko_payloads["history"], "/coins/bitcoin/market_chart"),
        request,
    )

    assert outbound.params == {"vs_currency": "usd", "days": 90}
    assert len(normalized.data.points) == 30
    assert normalized.data.points[-1].price == 170

    with pytest.raises(ValueError, match="1, 7, 30, 90, or 365"):
        adapter.build_request(_request("crypto.history", parameters={"days": 2_000}))

    changed = deepcopy(coingecko_payloads["history"])
    changed.pop("prices")
    with pytest.raises(ValidationError):
        adapter.normalize(
            _response(changed, "/coins/bitcoin/market_chart"),
            request,
        )


def test_global_and_trending_contracts_normalize_current_shapes(
    coingecko_payloads: dict[str, Any],
) -> None:
    global_adapter = CoinGeckoGlobalAdapter(_BASE_URL)
    trending_adapter = CoinGeckoTrendingAdapter(_BASE_URL)
    global_request = _request("crypto.global", key="global")
    trending_request = _request("crypto.trending", key="trending")

    global_result = global_adapter.normalize(
        _response(coingecko_payloads["global"], "/global"),
        global_request,
    )
    trending_result = trending_adapter.normalize(
        _response(coingecko_payloads["trending"], "/search/trending"),
        trending_request,
    )

    assert str(global_result.data.bitcoin_dominance_percent) == "56.2"
    assert global_result.data.total_market_cap_usd == 4_200_000_000_000
    assert trending_result.data.coins[0].coin_id == "bitcoin"


def test_compound_call_budget_checks_minute_and_month_atomically() -> None:
    clock = [0.0]
    quotas = ProviderQuotaManager(
        {
            "coingecko": (
                QuotaPolicy(limit=2, window_seconds=60),
                QuotaPolicy(limit=3, window_seconds=30 * 24 * 60 * 60),
            )
        },
        clock=lambda: clock[0],
    )

    quotas.reserve("coingecko", weight=1, kind=RequestKind.INTERACTIVE)
    quotas.reserve("coingecko", weight=1, kind=RequestKind.INTERACTIVE)
    with pytest.raises(ProviderQuotaExceededError) as minute_error:
        quotas.reserve("coingecko", weight=1, kind=RequestKind.INTERACTIVE)
    assert minute_error.value.retry_after_seconds == 60

    clock[0] = 60
    quotas.reserve("coingecko", weight=1, kind=RequestKind.INTERACTIVE)
    with pytest.raises(ProviderQuotaExceededError) as month_error:
        quotas.reserve("coingecko", weight=1, kind=RequestKind.INTERACTIVE)
    assert month_error.value.retry_after_seconds > 2_500_000
    minute, monthly = quotas.snapshots("coingecko")
    assert minute.used == 1
    assert monthly.used == 3
