"""CoinGecko orchestration, identity separation, and partial research tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest
from pydantic import AnyHttpUrl

from backend.app.cache import CacheStatus
from backend.app.core.exceptions import ResourceNotFoundError
from backend.app.providers import (
    DelayClass,
    Freshness,
    ProviderHttpResponse,
    ProviderManager,
    ProviderMeta,
    ProviderProvenance,
    ProviderRequest,
    ProviderResponse,
    ProviderUnavailableError,
)
from backend.app.providers.adapters import ProviderAdapter
from backend.app.services import CryptoService

_BASE_URL = "https://api.coingecko.com/api/v3"
_FETCHED_AT = datetime(2026, 8, 4, 8, 1, tzinfo=UTC)


class FixtureManager:
    """Normalize recorded CoinGecko shapes without network or Redis access."""

    def __init__(
        self,
        payloads: dict[str, Any],
        *,
        fail_operations: set[str] | None = None,
        missing_coin: bool = False,
    ) -> None:
        self.payloads = payloads
        self.fail_operations = fail_operations or set()
        self.missing_coin = missing_coin
        self.requests: list[ProviderRequest] = []

    async def fetch(
        self,
        adapter: ProviderAdapter[Any],
        request: ProviderRequest,
    ) -> ProviderResponse[Any]:
        self.requests.append(request)
        if request.operation in self.fail_operations:
            raise ProviderUnavailableError(cause_code="provider_timeout")
        fixture_name, path = {
            "crypto.search": ("search", "/search"),
            "crypto.global": ("global", "/global"),
            "crypto.trending": ("trending", "/search/trending"),
            "crypto.markets": ("markets", "/coins/markets"),
            "crypto.overview": ("markets", "/coins/markets"),
            "crypto.history": ("history", "/coins/bitcoin/market_chart"),
        }[request.operation]
        payload = self.payloads[fixture_name]
        if request.operation == "crypto.overview":
            payload = [] if self.missing_coin else [self.payloads["markets"][0]]
        response = ProviderHttpResponse(
            payload=payload,
            fetched_at=_FETCHED_AT,
            source_url=AnyHttpUrl(f"{_BASE_URL}{path}"),
            headers={},
            raw_payload_sha256="e" * 64,
            provider_request_id=None,
            attempts=1,
        )
        normalized = adapter.normalize(response, request)
        return ProviderResponse(
            data=normalized.data,
            meta=ProviderMeta(
                source="coingecko",
                source_timestamp=normalized.source_timestamp,
                fetched_at=_FETCHED_AT,
                cache_status=CacheStatus.MISS,
                freshness=Freshness.DELAYED,
                staleness_seconds=60,
                partial=normalized.partial,
                warnings=normalized.warnings,
                delay_class=DelayClass.DELAYED,
                provenance=ProviderProvenance(
                    provider="coingecko",
                    operation=request.operation,
                    source_url=response.source_url,
                    provider_request_id=None,
                    raw_payload_sha256=response.raw_payload_sha256,
                    schema_version=adapter.schema_version,
                    terms_review_version=adapter.terms_review_version,
                    attribution=adapter.attribution,
                ),
            ),
        )


def _service(manager: FixtureManager) -> CryptoService:
    return CryptoService(
        cast(ProviderManager, manager),
        base_url=_BASE_URL,
        demo_api_key=None,
    )


async def test_research_uses_coin_id_and_only_two_provider_calls(
    coingecko_payloads: dict[str, Any],
) -> None:
    manager = FixtureManager(coingecko_payloads)

    result = await _service(manager).research("bitcoin", days=90)

    assert result.data.coin_id == "bitcoin"
    assert result.data.overview.symbol == "BTC"
    assert result.data.technicals is not None
    assert result.data.anomalies is not None
    assert result.data.risk.methodology_version == "crypto-risk-v1"
    assert result.meta.source == "coingecko"
    assert result.meta.freshness is Freshness.DELAYED
    assert [request.operation for request in manager.requests] == [
        "crypto.overview",
        "crypto.history",
    ]
    assert all(request.weight == 1 for request in manager.requests)
    assert manager.requests[0].asset.cache_identity == "crypto:bitcoin"


async def test_research_keeps_overview_and_renormalizes_when_history_fails(
    coingecko_payloads: dict[str, Any],
) -> None:
    manager = FixtureManager(
        coingecko_payloads,
        fail_operations={"crypto.history"},
    )

    result = await _service(manager).research("bitcoin", days=90)

    assert result.meta.partial is True
    assert result.data.history is None
    assert result.data.technicals is None
    assert set(result.data.risk.component_scores) == {"liquidity", "market_size"}
    assert "volatility" in result.data.risk.missing_inputs
    assert {warning.code for warning in result.meta.warnings} == {"history_unavailable"}


async def test_unknown_provider_id_returns_not_found(
    coingecko_payloads: dict[str, Any],
) -> None:
    manager = FixtureManager(coingecko_payloads, missing_coin=True)

    with pytest.raises(ResourceNotFoundError):
        await _service(manager).overview("not-a-real-coin")


async def test_search_does_not_silently_choose_an_ambiguous_symbol(
    coingecko_payloads: dict[str, Any],
) -> None:
    manager = FixtureManager(coingecko_payloads)

    result = await _service(manager).search("btc")

    assert result.data.resolution.ambiguous_symbol is True
    assert result.data.resolution.exact_provider_id is None
    assert result.data.resolution.exact_symbol_coin_ids == [
        "bitcoin",
        "bitcoin-wrapped",
    ]
