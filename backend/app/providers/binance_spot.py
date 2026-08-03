"""Strict public Binance Spot adapters for the market-data-only REST host."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import ClassVar

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from backend.app.providers.adapters import ProviderAdapter
from backend.app.providers.exceptions import ProviderSchemaError
from backend.app.providers.models import (
    DelayClass,
    NormalizedPayload,
    OutboundRequest,
    ProviderHttpResponse,
    ProviderRequest,
)

BINANCE_SPOT_PROVIDER = "binance_spot"
BINANCE_SPOT_HOST = "data-api.binance.vision"
BINANCE_SPOT_TERMS_REVIEW = "binance-spot-docs-2026-07-23"
BINANCE_SPOT_ATTRIBUTION = "Market data provided by Binance"


class BinanceSpotInterval(StrEnum):
    """Product-approved candle intervals, intentionally narrower than Binance."""

    ONE_MINUTE = "1m"
    FIVE_MINUTES = "5m"
    FIFTEEN_MINUTES = "15m"
    ONE_HOUR = "1h"
    FOUR_HOURS = "4h"
    ONE_DAY = "1d"
    ONE_WEEK = "1w"


class _NormalizedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SpotSymbol(_NormalizedModel):
    symbol: str = Field(min_length=3, max_length=20)
    base_asset: str = Field(min_length=1, max_length=12)
    quote_asset: str = Field(min_length=1, max_length=12)
    status: str

    @field_validator("symbol", "base_asset", "quote_asset")
    @classmethod
    def validate_asset_identifier(cls, value: str) -> str:
        """Allow Binance's documented Unicode names while rejecting punctuation."""
        if not value.isalnum():
            raise ValueError("Binance asset identifiers must be alphanumeric")
        return value


class SpotSymbolsData(_NormalizedModel):
    server_time: datetime
    request_weight_limit_per_minute: int | None = Field(default=None, ge=1)
    symbols: list[SpotSymbol] = Field(min_length=1)


class SpotTickerData(_NormalizedModel):
    symbol: str
    price_change: Decimal
    price_change_percent: Decimal
    weighted_average_price: Decimal = Field(ge=0)
    previous_close_price: Decimal = Field(ge=0)
    last_price: Decimal = Field(gt=0)
    last_quantity: Decimal = Field(ge=0)
    bid_price: Decimal = Field(ge=0)
    bid_quantity: Decimal = Field(ge=0)
    ask_price: Decimal = Field(ge=0)
    ask_quantity: Decimal = Field(ge=0)
    open_price: Decimal = Field(gt=0)
    high_price: Decimal = Field(gt=0)
    low_price: Decimal = Field(gt=0)
    base_volume: Decimal = Field(ge=0)
    quote_volume: Decimal = Field(ge=0)
    open_time: datetime
    close_time: datetime
    first_trade_id: int = Field(ge=0)
    last_trade_id: int = Field(ge=0)
    trade_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_market_range(self) -> SpotTickerData:
        if self.low_price > self.high_price:
            raise ValueError("ticker low price cannot exceed high price")
        if not self.low_price <= self.last_price <= self.high_price:
            raise ValueError("ticker last price must be within the 24-hour range")
        if self.open_time > self.close_time:
            raise ValueError("ticker open time cannot follow close time")
        return self


class SpotCandle(_NormalizedModel):
    open_time: datetime
    close_time: datetime
    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    base_volume: Decimal = Field(ge=0)
    quote_volume: Decimal = Field(ge=0)
    trade_count: int = Field(ge=0)
    taker_buy_base_volume: Decimal = Field(ge=0)
    taker_buy_quote_volume: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def validate_bar(self) -> SpotCandle:
        if self.open_time > self.close_time:
            raise ValueError("candle open time cannot follow close time")
        if self.low > self.high:
            raise ValueError("candle low cannot exceed high")
        if not self.low <= self.open <= self.high:
            raise ValueError("candle open must be within its range")
        if not self.low <= self.close <= self.high:
            raise ValueError("candle close must be within its range")
        return self


class SpotCandlesData(_NormalizedModel):
    symbol: str
    interval: BinanceSpotInterval
    candles: list[SpotCandle] = Field(min_length=1, max_length=500)


class SpotBookLevel(_NormalizedModel):
    price: Decimal = Field(gt=0)
    quantity: Decimal = Field(gt=0)


class SpotOrderBookData(_NormalizedModel):
    symbol: str
    last_update_id: int = Field(ge=0)
    bids: list[SpotBookLevel] = Field(min_length=1, max_length=100)
    asks: list[SpotBookLevel] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_book(self) -> SpotOrderBookData:
        if self.bids[0].price >= self.asks[0].price:
            raise ValueError("order book must not be crossed")
        return self


class SpotTrade(_NormalizedModel):
    trade_id: int = Field(ge=0)
    price: Decimal = Field(gt=0)
    quantity: Decimal = Field(gt=0)
    quote_quantity: Decimal = Field(gt=0)
    time: datetime
    is_buyer_maker: bool
    is_best_match: bool


class SpotTradesData(_NormalizedModel):
    symbol: str
    trades: list[SpotTrade] = Field(min_length=1, max_length=200)


class _RateLimitWire(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rateLimitType: str
    interval: str
    intervalNum: int = Field(ge=1)
    limit: int = Field(ge=1)
    count: int | None = Field(default=None, ge=0)


class _SymbolWire(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    status: str
    baseAsset: str
    quoteAsset: str
    isSpotTradingAllowed: bool


class _ExchangeInfoWire(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: str
    serverTime: int = Field(ge=0)
    rateLimits: list[_RateLimitWire]
    symbols: list[_SymbolWire]


class _TickerWire(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    priceChange: Decimal
    priceChangePercent: Decimal
    weightedAvgPrice: Decimal
    prevClosePrice: Decimal
    lastPrice: Decimal
    lastQty: Decimal
    bidPrice: Decimal
    bidQty: Decimal
    askPrice: Decimal
    askQty: Decimal
    openPrice: Decimal
    highPrice: Decimal
    lowPrice: Decimal
    volume: Decimal
    quoteVolume: Decimal
    openTime: int = Field(ge=0)
    closeTime: int = Field(ge=0)
    firstId: int = Field(ge=0)
    lastId: int = Field(ge=0)
    count: int = Field(ge=0)


type _KlineWire = tuple[
    int,
    Decimal,
    Decimal,
    Decimal,
    Decimal,
    Decimal,
    int,
    Decimal,
    int,
    Decimal,
    Decimal,
    str,
]
_KLINES_ADAPTER = TypeAdapter(list[_KlineWire])


class _DepthWire(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lastUpdateId: int = Field(ge=0)
    bids: list[tuple[Decimal, Decimal]]
    asks: list[tuple[Decimal, Decimal]]


class _TradeWire(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=0)
    price: Decimal
    qty: Decimal
    quoteQty: Decimal
    time: int = Field(ge=0)
    isBuyerMaker: bool
    isBestMatch: bool


_TRADES_ADAPTER = TypeAdapter(list[_TradeWire])


def _utc_from_milliseconds(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1_000, tz=UTC)


def _project_mapping(
    value: object,
    *,
    fields: frozenset[str],
) -> dict[str, object]:
    """Project documented core fields while ignoring irrelevant trading metadata."""
    if not isinstance(value, dict):
        raise TypeError("Binance payload entry must be an object")
    return {field: value[field] for field in fields if field in value}


def _integer_parameter(
    request: ProviderRequest,
    name: str,
    *,
    default: int,
) -> int:
    value = request.parameters.get(name, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    return value


class _BinanceSpotAdapter[DataT: BaseModel](ProviderAdapter[DataT]):
    provider: ClassVar[str] = BINANCE_SPOT_PROVIDER
    terms_review_version: ClassVar[str] = BINANCE_SPOT_TERMS_REVIEW
    attribution: ClassVar[str] = BINANCE_SPOT_ATTRIBUTION
    allowed_hosts: ClassVar[frozenset[str]] = frozenset({BINANCE_SPOT_HOST})

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    def _url(self, path: str) -> AnyHttpUrl:
        return AnyHttpUrl(f"{self._base_url}{path}")

    def reported_used_weight(self, response: ProviderHttpResponse) -> int | None:
        minute_weight = response.headers.get("x-mbx-used-weight-1m")
        if minute_weight is not None:
            return int(minute_weight)
        weights = [
            int(value)
            for key, value in response.headers.items()
            if key.startswith("x-mbx-used-weight-")
        ]
        return max(weights) if weights else None


class BinanceSpotSymbolsAdapter(_BinanceSpotAdapter[SpotSymbolsData]):
    schema_version: ClassVar[str] = "binance-spot-symbols-v1"
    data_model: ClassVar[type[BaseModel]] = SpotSymbolsData

    def build_request(self, request: ProviderRequest) -> OutboundRequest:
        if request.operation != "spot.symbols":
            raise ValueError("symbols adapter received an unsupported operation")
        return OutboundRequest(
            url=self._url("/api/v3/exchangeInfo"),
            params={
                "symbolStatus": "TRADING",
                "showPermissionSets": "false",
            },
        )

    def normalize(
        self,
        response: ProviderHttpResponse,
        request: ProviderRequest,
    ) -> NormalizedPayload[SpotSymbolsData]:
        try:
            if not isinstance(response.payload, dict):
                raise TypeError("exchange info must be an object")
            rate_fields = frozenset(
                {"rateLimitType", "interval", "intervalNum", "limit", "count"}
            )
            symbol_fields = frozenset(
                {
                    "symbol",
                    "status",
                    "baseAsset",
                    "quoteAsset",
                    "isSpotTradingAllowed",
                }
            )
            wire = _ExchangeInfoWire.model_validate(
                {
                    "timezone": response.payload.get("timezone"),
                    "serverTime": response.payload.get("serverTime"),
                    "rateLimits": [
                        _project_mapping(item, fields=rate_fields)
                        for item in response.payload.get("rateLimits", [])
                    ],
                    "symbols": [
                        _project_mapping(item, fields=symbol_fields)
                        for item in response.payload.get("symbols", [])
                    ],
                }
            )
        except (TypeError, ValidationError) as error:
            raise ProviderSchemaError(
                "Binance exchange-info schema changed."
            ) from error

        symbols = sorted(
            (
                SpotSymbol(
                    symbol=item.symbol,
                    base_asset=item.baseAsset,
                    quote_asset=item.quoteAsset,
                    status=item.status,
                )
                for item in wire.symbols
                if item.status == "TRADING" and item.isSpotTradingAllowed
            ),
            key=lambda item: item.symbol,
        )
        if not symbols:
            raise ProviderSchemaError(
                "Binance exchange info contained no tradable Spot symbols."
            )
        minute_limit = next(
            (
                item.limit
                for item in wire.rateLimits
                if item.rateLimitType == "REQUEST_WEIGHT"
                and item.interval == "MINUTE"
                and item.intervalNum == 1
            ),
            None,
        )
        return NormalizedPayload[SpotSymbolsData](
            data=SpotSymbolsData(
                server_time=_utc_from_milliseconds(wire.serverTime),
                request_weight_limit_per_minute=minute_limit,
                symbols=symbols,
            ),
            source_timestamp=_utc_from_milliseconds(wire.serverTime),
            delay_class=DelayClass.LIVE,
        )


class BinanceSpotTickerAdapter(_BinanceSpotAdapter[SpotTickerData]):
    schema_version: ClassVar[str] = "binance-spot-ticker-v1"
    data_model: ClassVar[type[BaseModel]] = SpotTickerData

    def build_request(self, request: ProviderRequest) -> OutboundRequest:
        if request.operation != "spot.ticker":
            raise ValueError("ticker adapter received an unsupported operation")
        return OutboundRequest(
            url=self._url("/api/v3/ticker/24hr"),
            params={"symbol": request.asset.key, "symbolStatus": "TRADING"},
        )

    def normalize(
        self,
        response: ProviderHttpResponse,
        request: ProviderRequest,
    ) -> NormalizedPayload[SpotTickerData]:
        try:
            wire = _TickerWire.model_validate(response.payload)
            data = SpotTickerData(
                symbol=wire.symbol,
                price_change=wire.priceChange,
                price_change_percent=wire.priceChangePercent,
                weighted_average_price=wire.weightedAvgPrice,
                previous_close_price=wire.prevClosePrice,
                last_price=wire.lastPrice,
                last_quantity=wire.lastQty,
                bid_price=wire.bidPrice,
                bid_quantity=wire.bidQty,
                ask_price=wire.askPrice,
                ask_quantity=wire.askQty,
                open_price=wire.openPrice,
                high_price=wire.highPrice,
                low_price=wire.lowPrice,
                base_volume=wire.volume,
                quote_volume=wire.quoteVolume,
                open_time=_utc_from_milliseconds(wire.openTime),
                close_time=_utc_from_milliseconds(wire.closeTime),
                first_trade_id=wire.firstId,
                last_trade_id=wire.lastId,
                trade_count=wire.count,
            )
        except ValidationError as error:
            raise ProviderSchemaError("Binance ticker schema changed.") from error
        if data.symbol != request.asset.key:
            raise ProviderSchemaError("Binance ticker returned a different symbol.")
        return NormalizedPayload[SpotTickerData](
            data=data,
            source_timestamp=data.close_time,
            delay_class=DelayClass.LIVE,
        )


class BinanceSpotCandlesAdapter(_BinanceSpotAdapter[SpotCandlesData]):
    schema_version: ClassVar[str] = "binance-spot-candles-v1"
    data_model: ClassVar[type[BaseModel]] = SpotCandlesData

    def build_request(self, request: ProviderRequest) -> OutboundRequest:
        if request.operation != "spot.candles" or request.interval is None:
            raise ValueError("candles adapter requires a supported interval")
        interval = BinanceSpotInterval(request.interval)
        limit = _integer_parameter(request, "limit", default=200)
        if not 50 <= limit <= 500:
            raise ValueError("candle limit must be between 50 and 500")
        return OutboundRequest(
            url=self._url("/api/v3/klines"),
            params={
                "symbol": request.asset.key,
                "interval": interval.value,
                "limit": limit,
                "timeZone": "0",
            },
        )

    def normalize(
        self,
        response: ProviderHttpResponse,
        request: ProviderRequest,
    ) -> NormalizedPayload[SpotCandlesData]:
        try:
            if request.interval is None:
                raise ValueError("candles request interval is missing")
            interval = BinanceSpotInterval(request.interval)
            wire = _KLINES_ADAPTER.validate_python(response.payload)
            candles = [
                SpotCandle(
                    open_time=_utc_from_milliseconds(item[0]),
                    open=item[1],
                    high=item[2],
                    low=item[3],
                    close=item[4],
                    base_volume=item[5],
                    close_time=_utc_from_milliseconds(item[6]),
                    quote_volume=item[7],
                    trade_count=item[8],
                    taker_buy_base_volume=item[9],
                    taker_buy_quote_volume=item[10],
                )
                for item in wire
            ]
            data = SpotCandlesData(
                symbol=request.asset.key,
                interval=interval,
                candles=candles,
            )
        except (TypeError, ValueError, ValidationError) as error:
            raise ProviderSchemaError("Binance candle schema changed.") from error
        return NormalizedPayload[SpotCandlesData](
            data=data,
            source_timestamp=data.candles[-1].close_time,
            delay_class=DelayClass.LIVE,
        )


class BinanceSpotOrderBookAdapter(_BinanceSpotAdapter[SpotOrderBookData]):
    schema_version: ClassVar[str] = "binance-spot-order-book-v1"
    data_model: ClassVar[type[BaseModel]] = SpotOrderBookData

    def build_request(self, request: ProviderRequest) -> OutboundRequest:
        if request.operation != "spot.order_book":
            raise ValueError("order-book adapter received an unsupported operation")
        limit = _integer_parameter(request, "limit", default=100)
        if limit not in {20, 50, 100}:
            raise ValueError("order-book limit must be 20, 50, or 100")
        return OutboundRequest(
            url=self._url("/api/v3/depth"),
            params={
                "symbol": request.asset.key,
                "limit": limit,
                "symbolStatus": "TRADING",
            },
        )

    def normalize(
        self,
        response: ProviderHttpResponse,
        request: ProviderRequest,
    ) -> NormalizedPayload[SpotOrderBookData]:
        try:
            wire = _DepthWire.model_validate(response.payload)
            bids = sorted(
                (
                    SpotBookLevel(price=price, quantity=quantity)
                    for price, quantity in wire.bids
                    if quantity > 0
                ),
                key=lambda item: item.price,
                reverse=True,
            )
            asks = sorted(
                (
                    SpotBookLevel(price=price, quantity=quantity)
                    for price, quantity in wire.asks
                    if quantity > 0
                ),
                key=lambda item: item.price,
            )
            data = SpotOrderBookData(
                symbol=request.asset.key,
                last_update_id=wire.lastUpdateId,
                bids=bids,
                asks=asks,
            )
        except ValidationError as error:
            raise ProviderSchemaError("Binance order-book schema changed.") from error
        return NormalizedPayload[SpotOrderBookData](
            data=data,
            source_timestamp=response.fetched_at,
            delay_class=DelayClass.LIVE,
        )


class BinanceSpotTradesAdapter(_BinanceSpotAdapter[SpotTradesData]):
    schema_version: ClassVar[str] = "binance-spot-trades-v1"
    data_model: ClassVar[type[BaseModel]] = SpotTradesData

    def build_request(self, request: ProviderRequest) -> OutboundRequest:
        if request.operation != "spot.trades":
            raise ValueError("trades adapter received an unsupported operation")
        limit = _integer_parameter(request, "limit", default=100)
        if not 1 <= limit <= 200:
            raise ValueError("trade limit must be between 1 and 200")
        return OutboundRequest(
            url=self._url("/api/v3/trades"),
            params={"symbol": request.asset.key, "limit": limit},
        )

    def normalize(
        self,
        response: ProviderHttpResponse,
        request: ProviderRequest,
    ) -> NormalizedPayload[SpotTradesData]:
        try:
            wire = _TRADES_ADAPTER.validate_python(response.payload)
            trades = [
                SpotTrade(
                    trade_id=item.id,
                    price=item.price,
                    quantity=item.qty,
                    quote_quantity=item.quoteQty,
                    time=_utc_from_milliseconds(item.time),
                    is_buyer_maker=item.isBuyerMaker,
                    is_best_match=item.isBestMatch,
                )
                for item in wire
            ]
            data = SpotTradesData(symbol=request.asset.key, trades=trades)
        except ValidationError as error:
            raise ProviderSchemaError(
                "Binance recent-trades schema changed."
            ) from error
        return NormalizedPayload[SpotTradesData](
            data=data,
            source_timestamp=max(item.time for item in data.trades),
            delay_class=DelayClass.LIVE,
        )


__all__ = [
    "BINANCE_SPOT_PROVIDER",
    "BinanceSpotCandlesAdapter",
    "BinanceSpotInterval",
    "BinanceSpotOrderBookAdapter",
    "BinanceSpotSymbolsAdapter",
    "BinanceSpotTickerAdapter",
    "BinanceSpotTradesAdapter",
    "SpotBookLevel",
    "SpotCandle",
    "SpotCandlesData",
    "SpotOrderBookData",
    "SpotSymbol",
    "SpotSymbolsData",
    "SpotTickerData",
    "SpotTrade",
    "SpotTradesData",
]
