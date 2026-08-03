"""Binance Spot orchestration, weights, symbol validation, and partial tests."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pytest
from pydantic import AnyHttpUrl

from backend.app.cache import CacheStatus
from backend.app.core.exceptions import (
    ApplicationValidationError,
    ResourceNotFoundError,
)
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
from backend.app.providers.binance_spot import BinanceSpotInterval
from backend.app.services import BinanceSpotService

_BASE_URL = "https://data-api.binance.vision"
_FETCHED_AT = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)


class FixtureManager:
    """Normalize fixture payloads through real adapters without network or Redis."""

    def __init__(
        self,
        payloads: dict[str, Any],
        *,
        fail_operations: set[str] | None = None,
    ) -> None:
        self.payloads = payloads
        self.fail_operations = fail_operations or set()
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
            "spot.symbols": ("exchange_info", "/api/v3/exchangeInfo"),
            "spot.ticker": ("ticker", "/api/v3/ticker/24hr"),
            "spot.candles": ("klines", "/api/v3/klines"),
            "spot.order_book": ("depth", "/api/v3/depth"),
            "spot.trades": ("trades", "/api/v3/trades"),
        }[request.operation]
        response = ProviderHttpResponse(
            payload=self.payloads[fixture_name],
            fetched_at=_FETCHED_AT,
            source_url=AnyHttpUrl(f"{_BASE_URL}{path}"),
            headers={"x-mbx-used-weight-1m": "100"},
            raw_payload_sha256="d" * 64,
            provider_request_id=None,
            attempts=1,
        )
        normalized = adapter.normalize(response, request)
        return ProviderResponse(
            data=normalized.data,
            meta=ProviderMeta(
                source="binance_spot",
                source_timestamp=normalized.source_timestamp,
                fetched_at=_FETCHED_AT,
                cache_status=CacheStatus.MISS,
                freshness=Freshness.LIVE,
                staleness_seconds=0,
                partial=False,
                warnings=[],
                delay_class=DelayClass.LIVE,
                provenance=ProviderProvenance(
                    provider="binance_spot",
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


def _service(manager: FixtureManager) -> BinanceSpotService:
    return BinanceSpotService(
        cast(ProviderManager, manager),
        base_url=_BASE_URL,
    )


async def test_research_uses_documented_weights_and_bounded_parameters(
    binance_payloads: dict[str, Any],
) -> None:
    manager = FixtureManager(binance_payloads)

    result = await _service(manager).research(
        "btcusdt",
        interval=BinanceSpotInterval.ONE_HOUR,
        candle_limit=200,
        book_limit=100,
        trade_limit=100,
        slippage_notional_quote=Decimal("1000"),
    )

    requests = {item.operation: item for item in manager.requests}
    assert result.data.symbol == "BTCUSDT"
    assert result.meta.partial is False
    assert result.data.risk is not None
    assert {name: item.weight for name, item in requests.items()} == {
        "spot.symbols": 20,
        "spot.ticker": 2,
        "spot.candles": 2,
        "spot.order_book": 5,
        "spot.trades": 25,
    }
    assert requests["spot.candles"].parameters["limit"] == 200
    assert requests["spot.order_book"].parameters["limit"] == 100
    assert requests["spot.trades"].parameters["limit"] == 100


async def test_research_returns_partial_risk_when_one_provider_read_fails(
    binance_payloads: dict[str, Any],
) -> None:
    manager = FixtureManager(
        binance_payloads,
        fail_operations={"spot.trades"},
    )

    result = await _service(manager).research(
        "BTCUSDT",
        interval=BinanceSpotInterval.ONE_HOUR,
        candle_limit=200,
        book_limit=100,
        trade_limit=100,
        slippage_notional_quote=Decimal("1000"),
    )

    assert result.meta.partial is True
    assert result.data.trades is None
    assert result.data.risk is not None
    assert "trade_anomaly" in result.data.risk.missing_inputs
    assert {warning.code for warning in result.meta.warnings} == {"trades_unavailable"}


async def test_symbol_format_and_exchange_metadata_are_authoritative(
    binance_payloads: dict[str, Any],
) -> None:
    manager = FixtureManager(binance_payloads)
    service = _service(manager)

    with pytest.raises(ApplicationValidationError):
        await service.ticker("BTC/USDT")
    assert manager.requests == []

    with pytest.raises(ResourceNotFoundError):
        await service.ticker("ETHUSDT")
    assert [item.operation for item in manager.requests] == ["spot.symbols"]


async def test_short_live_symbol_shapes_are_supported(
    binance_payloads: dict[str, Any],
) -> None:
    payloads = deepcopy(binance_payloads)
    payloads["ticker"]["symbol"] = "REU"
    manager = FixtureManager(payloads)

    result = await _service(manager).ticker("reu")

    assert result.data.symbol == "REU"
    assert [item.operation for item in manager.requests] == [
        "spot.symbols",
        "spot.ticker",
    ]
