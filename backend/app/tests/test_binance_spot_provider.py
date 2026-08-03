"""Fixture-driven Binance Spot adapter and request-control tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import AnyHttpUrl

from backend.app.cache import JsonScalar
from backend.app.providers import (
    AssetType,
    CanonicalAsset,
    ProviderHttpResponse,
    ProviderRequest,
    ProviderSchemaError,
)
from backend.app.providers.binance_spot import (
    BinanceSpotCandlesAdapter,
    BinanceSpotOrderBookAdapter,
    BinanceSpotSymbolsAdapter,
    BinanceSpotTickerAdapter,
    BinanceSpotTradesAdapter,
)

_BASE_URL = "https://data-api.binance.vision"
_FETCHED_AT = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)


def _response(payload: object, path: str) -> ProviderHttpResponse:
    return ProviderHttpResponse(
        payload=payload,
        fetched_at=_FETCHED_AT,
        source_url=AnyHttpUrl(f"{_BASE_URL}{path}"),
        headers={"x-mbx-used-weight-1m": "42"},
        raw_payload_sha256="b" * 64,
        provider_request_id=None,
        attempts=1,
    )


def _request(
    operation: str,
    *,
    interval: str | None = None,
    parameters: dict[str, JsonScalar] | None = None,
    weight: int = 1,
) -> ProviderRequest:
    return ProviderRequest(
        operation=operation,
        asset=CanonicalAsset(
            asset_type=(
                AssetType.SYSTEM
                if operation == "spot.symbols"
                else AssetType.BINANCE_SPOT
            ),
            key="spot-symbols" if operation == "spot.symbols" else "BTCUSDT",
        ),
        interval=interval,
        parameters=parameters or {},
        weight=weight,
        soft_ttl_seconds=10,
        hard_ttl_seconds=30,
    )


def test_exchange_info_filters_non_trading_pairs_and_reports_weight(
    binance_payloads: dict[str, Any],
) -> None:
    adapter = BinanceSpotSymbolsAdapter(_BASE_URL)
    request = _request("spot.symbols", weight=20)
    outbound = adapter.build_request(request)
    response = _response(binance_payloads["exchange_info"], "/api/v3/exchangeInfo")

    normalized = adapter.normalize(response, request)

    assert str(outbound.url) == f"{_BASE_URL}/api/v3/exchangeInfo"
    assert outbound.params == {
        "symbolStatus": "TRADING",
        "showPermissionSets": "false",
    }
    assert outbound.headers == {}
    assert [item.symbol for item in normalized.data.symbols] == [
        "BTCUSDT",
        "REU",
        "TUSDT",
        "币安人生USDT",
    ]
    assert normalized.data.symbols[1].quote_asset == "U"
    assert normalized.data.symbols[2].base_asset == "T"
    assert normalized.data.symbols[3].base_asset == "币安人生"
    assert normalized.data.request_weight_limit_per_minute == 6000
    assert adapter.reported_used_weight(response) == 42


def test_ticker_is_decimal_safe_and_rejects_core_schema_change(
    binance_payloads: dict[str, Any],
) -> None:
    adapter = BinanceSpotTickerAdapter(_BASE_URL)
    request = _request("spot.ticker", weight=2)

    normalized = adapter.normalize(
        _response(binance_payloads["ticker"], "/api/v3/ticker/24hr"),
        request,
    )
    changed = dict(binance_payloads["ticker"])
    changed["renamedLastPrice"] = changed.pop("lastPrice")

    assert str(normalized.data.last_price) == "119.00000000"
    assert normalized.data.trade_count == 1000
    with pytest.raises(ProviderSchemaError, match="ticker schema changed"):
        adapter.normalize(
            _response(changed, "/api/v3/ticker/24hr"),
            request,
        )


def test_candle_interval_and_limit_are_bounded(
    binance_payloads: dict[str, Any],
) -> None:
    adapter = BinanceSpotCandlesAdapter(_BASE_URL)
    request = _request(
        "spot.candles",
        interval="1h",
        parameters={"limit": 200},
        weight=2,
    )
    outbound = adapter.build_request(request)
    normalized = adapter.normalize(
        _response(binance_payloads["klines"], "/api/v3/klines"),
        request,
    )

    assert outbound.params == {
        "symbol": "BTCUSDT",
        "interval": "1h",
        "limit": 200,
        "timeZone": "0",
    }
    assert len(normalized.data.candles) == 20
    assert normalized.data.candles[-1].close == 119

    invalid = _request(
        "spot.candles",
        interval="30m",
        parameters={"limit": 1_000},
    )
    with pytest.raises(ValueError):
        adapter.build_request(invalid)


def test_depth_and_recent_trade_amplification_are_blocked(
    binance_payloads: dict[str, Any],
) -> None:
    depth_adapter = BinanceSpotOrderBookAdapter(_BASE_URL)
    trade_adapter = BinanceSpotTradesAdapter(_BASE_URL)
    depth_request = _request(
        "spot.order_book",
        parameters={"limit": 100},
        weight=5,
    )
    trade_request = _request(
        "spot.trades",
        parameters={"limit": 200},
        weight=25,
    )

    depth = depth_adapter.normalize(
        _response(binance_payloads["depth"], "/api/v3/depth"),
        depth_request,
    )
    trades = trade_adapter.normalize(
        _response(binance_payloads["trades"], "/api/v3/trades"),
        trade_request,
    )

    assert depth.data.bids[0].price == Decimal("118.90")
    assert depth.data.asks[0].price == Decimal("119.10")
    assert len(trades.data.trades) == 5

    with pytest.raises(ValueError, match="20, 50, or 100"):
        depth_adapter.build_request(
            _request("spot.order_book", parameters={"limit": 500})
        )
    with pytest.raises(ValueError, match="between 1 and 200"):
        trade_adapter.build_request(_request("spot.trades", parameters={"limit": 201}))
