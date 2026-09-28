"""Strict adapters for Binance USD-M Futures public market data only."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from typing import ClassVar

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
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

BINANCE_FUTURES_PROVIDER = "binance_futures"
BINANCE_FUTURES_HOST = "fapi.binance.com"
BINANCE_FUTURES_TERMS_REVIEW = "binance-usdm-public-market-docs-2026-09-28"
BINANCE_FUTURES_ATTRIBUTION = "Public USD-M Futures market data provided by Binance"


class FuturesPeriod(StrEnum):
    FIVE_MINUTES = "5m"
    FIFTEEN_MINUTES = "15m"
    THIRTY_MINUTES = "30m"
    ONE_HOUR = "1h"
    TWO_HOURS = "2h"
    FOUR_HOURS = "4h"
    SIX_HOURS = "6h"
    TWELVE_HOURS = "12h"
    ONE_DAY = "1d"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    @model_validator(mode="after")
    def ordered_history(self) -> _Model:
        for name in ("points", "history", "account_ratio", "taker_flow"):
            points = getattr(self, name, None)
            if not points:
                continue
            times: list[datetime] = []
            for point in points:
                stamp = getattr(point, "timestamp", None) or getattr(
                    point, "funding_time", None
                )
                if not isinstance(stamp, datetime) or stamp.tzinfo is None:
                    raise ValueError("history requires timezone-aware timestamps")
                times.append(stamp)
            if any(left >= right for left, right in pairwise(times)):
                raise ValueError("history timestamps must be unique and increasing")
        return self


class FuturesSymbol(_Model):
    symbol: str
    pair: str
    base_asset: str
    quote_asset: str
    margin_asset: str
    contract_type: str
    status: str


class FuturesSymbolsData(_Model):
    server_time: datetime
    symbols: list[FuturesSymbol] = Field(min_length=1)


class FuturesMarketData(_Model):
    symbol: str
    mark_price: Decimal = Field(gt=0)
    index_price: Decimal = Field(gt=0)
    estimated_settle_price: Decimal | None = Field(default=None, gt=0)
    last_funding_rate: Decimal
    interest_rate: Decimal
    next_funding_time: datetime
    event_time: datetime


class FundingPoint(_Model):
    funding_time: datetime
    funding_rate: Decimal
    mark_price: Decimal = Field(gt=0)


class FuturesFundingData(_Model):
    symbol: str
    points: list[FundingPoint] = Field(min_length=1, max_length=100)


class OpenInterestPoint(_Model):
    timestamp: datetime
    open_interest: Decimal = Field(ge=0)
    open_interest_value: Decimal = Field(ge=0)


class FuturesOpenInterestData(_Model):
    symbol: str
    current_open_interest: Decimal | None = Field(default=None, ge=0)
    current_timestamp: datetime | None = None
    period: FuturesPeriod
    history: list[OpenInterestPoint] = Field(default_factory=list, max_length=100)


class OpenInterestCurrentData(_Model):
    symbol: str
    open_interest: Decimal = Field(ge=0)
    timestamp: datetime


class OpenInterestHistoryData(_Model):
    symbol: str
    period: FuturesPeriod
    points: list[OpenInterestPoint] = Field(min_length=1, max_length=100)


class BasisPoint(_Model):
    timestamp: datetime
    index_price: Decimal = Field(gt=0)
    futures_price: Decimal = Field(gt=0)
    basis: Decimal
    basis_rate: Decimal
    annualized_basis_rate: Decimal | None = None

    @model_validator(mode="after")
    def consistent_basis(self) -> BasisPoint:
        # Provider values are rounded; allow one basis point of rate tolerance.
        expected = self.futures_price - self.index_price
        if abs(self.basis - expected) > max(
            Decimal("0.0000001"), self.index_price * Decimal("0.0001")
        ):
            raise ValueError("basis does not match futures minus index price")
        if abs(self.basis_rate - expected / self.index_price) > Decimal("0.0001"):
            raise ValueError("basis rate does not match prices")
        return self


class FuturesBasisData(_Model):
    symbol: str
    pair: str
    contract_type: str
    period: FuturesPeriod
    points: list[BasisPoint] = Field(min_length=1, max_length=100)


class PositioningPoint(_Model):
    timestamp: datetime
    long_short_ratio: Decimal = Field(gt=0)
    long_account_share: Decimal = Field(ge=0, le=1)
    short_account_share: Decimal = Field(ge=0, le=1)

    @model_validator(mode="after")
    def consistent_shares(self) -> PositioningPoint:
        if abs(self.long_account_share + self.short_account_share - 1) > Decimal(
            "0.001"
        ):
            raise ValueError("long and short account shares must sum to one")
        return self


class TakerFlowPoint(_Model):
    timestamp: datetime
    buy_sell_ratio: Decimal = Field(ge=0)
    buy_volume: Decimal = Field(ge=0)
    sell_volume: Decimal = Field(ge=0)


class FuturesPositioningData(_Model):
    symbol: str
    period: FuturesPeriod
    account_ratio: list[PositioningPoint] = Field(default_factory=list, max_length=100)
    taker_flow: list[TakerFlowPoint] = Field(default_factory=list, max_length=100)


class AccountRatioData(_Model):
    symbol: str
    period: FuturesPeriod
    points: list[PositioningPoint] = Field(min_length=1, max_length=100)


class TakerFlowData(_Model):
    symbol: str
    period: FuturesPeriod
    points: list[TakerFlowPoint] = Field(min_length=1, max_length=100)


class _SymbolWire(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str
    pair: str
    contractType: str
    status: str
    baseAsset: str
    quoteAsset: str
    marginAsset: str


class _MarketWire(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str
    markPrice: Decimal
    indexPrice: Decimal
    estimatedSettlePrice: Decimal | None = None
    lastFundingRate: Decimal
    interestRate: Decimal
    nextFundingTime: int = Field(ge=0)
    time: int = Field(ge=0)


class _FundingWire(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str
    fundingTime: int = Field(ge=0)
    fundingRate: Decimal
    markPrice: Decimal


class _OpenInterestWire(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str
    openInterest: Decimal
    time: int = Field(ge=0)


class _OpenInterestHistoryWire(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str
    sumOpenInterest: Decimal
    sumOpenInterestValue: Decimal
    timestamp: int = Field(ge=0)


class _BasisWire(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pair: str
    contractType: str
    indexPrice: Decimal
    futuresPrice: Decimal
    basis: Decimal
    basisRate: Decimal
    annualizedBasisRate: Decimal | str | None = None
    timestamp: int = Field(ge=0)


class _PositioningWire(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str
    longShortRatio: Decimal
    longAccount: Decimal
    shortAccount: Decimal
    timestamp: int = Field(ge=0)


class _TakerFlowWire(BaseModel):
    model_config = ConfigDict(extra="forbid")
    buySellRatio: Decimal
    buyVol: Decimal
    sellVol: Decimal
    timestamp: int = Field(ge=0)


_FUNDING_ADAPTER = TypeAdapter(list[_FundingWire])
_OI_HISTORY_ADAPTER = TypeAdapter(list[_OpenInterestHistoryWire])
_BASIS_ADAPTER = TypeAdapter(list[_BasisWire])
_POSITIONING_ADAPTER = TypeAdapter(list[_PositioningWire])
_TAKER_ADAPTER = TypeAdapter(list[_TakerFlowWire])


def _utc(milliseconds: int) -> datetime:
    if not 0 <= milliseconds <= 253402300799000:
        raise ValueError("timestamp is outside the supported range")
    return datetime.fromtimestamp(milliseconds / 1_000, tz=UTC)


def _history(
    response: ProviderHttpResponse,
    request: ProviderRequest,
    fields: frozenset[str],
    *,
    identity: str | None = "symbol",
) -> list[dict[str, object]]:
    if not isinstance(response.payload, list) or not 1 <= len(
        response.payload
    ) <= _bounded_limit(request):
        raise ValueError("history must be nonempty and within the requested limit")
    rows = [_project(item, fields) for item in response.payload]
    for row in rows:
        if identity and row.get(identity) != request.asset.key:
            raise ValueError("history returned a different asset")
        if "contractType" in row and row["contractType"] != "PERPETUAL":
            raise ValueError("history returned a different contract type")
        stamp = row.get("timestamp", row.get("fundingTime"))
        if not isinstance(stamp, int) or isinstance(stamp, bool):
            raise ValueError("history timestamp must be integer milliseconds")
        if (_utc(stamp) - response.fetched_at).total_seconds() > 60:
            raise ValueError("history contains a future observation")
    return rows


def _project(value: object, fields: frozenset[str]) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError("Binance payload entry must be an object")
    return {name: value[name] for name in fields if name in value}


def _bounded_limit(request: ProviderRequest) -> int:
    value = request.parameters.get("limit", 30)
    if not isinstance(value, int) or isinstance(value, bool) or not 2 <= value <= 100:
        raise ValueError("limit must be an integer between 2 and 100")
    return value


def _period(request: ProviderRequest) -> FuturesPeriod:
    if request.interval is None:
        raise ValueError("a supported period is required")
    return FuturesPeriod(request.interval)


class _FuturesAdapter[DataT: BaseModel](ProviderAdapter[DataT]):
    provider: ClassVar[str] = BINANCE_FUTURES_PROVIDER
    terms_review_version: ClassVar[str] = BINANCE_FUTURES_TERMS_REVIEW
    attribution: ClassVar[str] = BINANCE_FUTURES_ATTRIBUTION
    allowed_hosts: ClassVar[frozenset[str]] = frozenset({BINANCE_FUTURES_HOST})

    def __init__(self, base_url: str) -> None:
        if base_url.rstrip("/") != "https://fapi.binance.com":
            raise ValueError("Futures adapters require the official HTTPS host")
        self._base_url = base_url.rstrip("/")

    def _url(self, path: str) -> AnyHttpUrl:
        return AnyHttpUrl(f"{self._base_url}{path}")

    def reported_used_weight(self, response: ProviderHttpResponse) -> int | None:
        value = response.headers.get("x-mbx-used-weight-1m")
        return int(value) if value is not None else None


class BinanceFuturesSymbolsAdapter(_FuturesAdapter[FuturesSymbolsData]):
    schema_version: ClassVar[str] = "binance-futures-symbols-v1"
    data_model: ClassVar[type[BaseModel]] = FuturesSymbolsData

    def build_request(self, request: ProviderRequest) -> OutboundRequest:
        if request.operation != "futures.symbols":
            raise ValueError("symbols adapter received an unsupported operation")
        return OutboundRequest(url=self._url("/fapi/v1/exchangeInfo"))

    def normalize(
        self, response: ProviderHttpResponse, request: ProviderRequest
    ) -> NormalizedPayload[FuturesSymbolsData]:
        fields = frozenset(
            {
                "symbol",
                "pair",
                "contractType",
                "status",
                "baseAsset",
                "quoteAsset",
                "marginAsset",
            }
        )
        try:
            if not isinstance(response.payload, dict):
                raise TypeError("exchange info must be an object")
            server_time = int(response.payload["serverTime"])
            wires = [
                _SymbolWire.model_validate(_project(item, fields))
                for item in response.payload.get("symbols", [])
            ]
            symbols = sorted(
                [
                    FuturesSymbol(
                        symbol=item.symbol,
                        pair=item.pair,
                        base_asset=item.baseAsset,
                        quote_asset=item.quoteAsset,
                        margin_asset=item.marginAsset,
                        contract_type=item.contractType,
                        status=item.status,
                    )
                    for item in wires
                    if item.status == "TRADING" and item.contractType == "PERPETUAL"
                ],
                key=lambda item: item.symbol,
            )
            data = FuturesSymbolsData(server_time=_utc(server_time), symbols=symbols)
        except (KeyError, TypeError, ValueError, ValidationError) as error:
            raise ProviderSchemaError(
                "Binance Futures exchange-info schema changed."
            ) from error
        return NormalizedPayload(
            data=data, source_timestamp=data.server_time, delay_class=DelayClass.LIVE
        )


class BinanceFuturesMarketAdapter(_FuturesAdapter[FuturesMarketData]):
    schema_version: ClassVar[str] = "binance-futures-market-v1"
    data_model: ClassVar[type[BaseModel]] = FuturesMarketData

    def build_request(self, request: ProviderRequest) -> OutboundRequest:
        if request.operation != "futures.market":
            raise ValueError("market adapter received an unsupported operation")
        return OutboundRequest(
            url=self._url("/fapi/v1/premiumIndex"), params={"symbol": request.asset.key}
        )

    def normalize(
        self, response: ProviderHttpResponse, request: ProviderRequest
    ) -> NormalizedPayload[FuturesMarketData]:
        fields = frozenset(
            {
                "symbol",
                "markPrice",
                "indexPrice",
                "estimatedSettlePrice",
                "lastFundingRate",
                "interestRate",
                "nextFundingTime",
                "time",
            }
        )
        try:
            wire = _MarketWire.model_validate(_project(response.payload, fields))
            data = FuturesMarketData(
                symbol=wire.symbol,
                mark_price=wire.markPrice,
                index_price=wire.indexPrice,
                estimated_settle_price=(
                    wire.estimatedSettlePrice
                    if wire.estimatedSettlePrice and wire.estimatedSettlePrice > 0
                    else None
                ),
                last_funding_rate=wire.lastFundingRate,
                interest_rate=wire.interestRate,
                next_funding_time=_utc(wire.nextFundingTime),
                event_time=_utc(wire.time),
            )
        except (TypeError, ValueError) as error:
            raise ProviderSchemaError(
                "Binance Futures premium-index schema changed."
            ) from error
        if data.symbol != request.asset.key:
            raise ProviderSchemaError("Binance Futures returned a different symbol.")
        return NormalizedPayload(
            data=data, source_timestamp=data.event_time, delay_class=DelayClass.LIVE
        )


class BinanceFuturesFundingAdapter(_FuturesAdapter[FuturesFundingData]):
    schema_version: ClassVar[str] = "binance-futures-funding-v1"
    data_model: ClassVar[type[BaseModel]] = FuturesFundingData

    def build_request(self, request: ProviderRequest) -> OutboundRequest:
        if request.operation != "futures.funding":
            raise ValueError("funding adapter received an unsupported operation")
        return OutboundRequest(
            url=self._url("/fapi/v1/fundingRate"),
            params={"symbol": request.asset.key, "limit": _bounded_limit(request)},
        )

    def normalize(
        self, response: ProviderHttpResponse, request: ProviderRequest
    ) -> NormalizedPayload[FuturesFundingData]:
        fields = frozenset({"symbol", "fundingTime", "fundingRate", "markPrice"})
        try:
            if not isinstance(response.payload, list):
                raise TypeError("funding history must be a list")
            wires = _FUNDING_ADAPTER.validate_python(
                _history(response, request, fields)
            )
            points = [
                FundingPoint(
                    funding_time=_utc(item.fundingTime),
                    funding_rate=item.fundingRate,
                    mark_price=item.markPrice,
                )
                for item in wires
                if item.symbol == request.asset.key
            ]
            data = FuturesFundingData(symbol=request.asset.key, points=points)
        except (TypeError, ValueError) as error:
            raise ProviderSchemaError(
                "Binance Futures funding schema changed."
            ) from error
        return NormalizedPayload(
            data=data,
            source_timestamp=data.points[-1].funding_time,
            delay_class=DelayClass.LIVE,
        )


class BinanceFuturesCurrentOpenInterestAdapter(
    _FuturesAdapter[OpenInterestCurrentData]
):
    schema_version: ClassVar[str] = "binance-futures-open-interest-current-v1"
    data_model: ClassVar[type[BaseModel]] = OpenInterestCurrentData

    def build_request(self, request: ProviderRequest) -> OutboundRequest:
        if request.operation != "futures.open_interest.current":
            raise ValueError(
                "current open-interest adapter received an unsupported operation"
            )
        return OutboundRequest(
            url=self._url("/fapi/v1/openInterest"), params={"symbol": request.asset.key}
        )

    def normalize(
        self, response: ProviderHttpResponse, request: ProviderRequest
    ) -> NormalizedPayload[OpenInterestCurrentData]:
        fields = frozenset({"symbol", "openInterest", "time"})
        try:
            wire = _OpenInterestWire.model_validate(_project(response.payload, fields))
            data = OpenInterestCurrentData(
                symbol=wire.symbol,
                open_interest=wire.openInterest,
                timestamp=_utc(wire.time),
            )
        except (TypeError, ValueError) as error:
            raise ProviderSchemaError(
                "Binance Futures open-interest schema changed."
            ) from error
        if data.symbol != request.asset.key:
            raise ProviderSchemaError("Binance Futures returned a different symbol.")
        return NormalizedPayload(
            data=data, source_timestamp=data.timestamp, delay_class=DelayClass.LIVE
        )


class BinanceFuturesOpenInterestHistoryAdapter(
    _FuturesAdapter[OpenInterestHistoryData]
):
    schema_version: ClassVar[str] = "binance-futures-open-interest-history-v1"
    data_model: ClassVar[type[BaseModel]] = OpenInterestHistoryData

    def build_request(self, request: ProviderRequest) -> OutboundRequest:
        if request.operation != "futures.open_interest.history":
            raise ValueError(
                "open-interest history adapter received an unsupported operation"
            )
        return OutboundRequest(
            url=self._url("/futures/data/openInterestHist"),
            params={
                "symbol": request.asset.key,
                "period": _period(request).value,
                "limit": _bounded_limit(request),
            },
        )

    def normalize(
        self, response: ProviderHttpResponse, request: ProviderRequest
    ) -> NormalizedPayload[OpenInterestHistoryData]:
        fields = frozenset(
            {"symbol", "sumOpenInterest", "sumOpenInterestValue", "timestamp"}
        )
        try:
            if not isinstance(response.payload, list):
                raise TypeError("open-interest history must be a list")
            wires = _OI_HISTORY_ADAPTER.validate_python(
                _history(response, request, fields)
            )
            data = OpenInterestHistoryData(
                symbol=request.asset.key,
                period=_period(request),
                points=[
                    OpenInterestPoint(
                        timestamp=_utc(item.timestamp),
                        open_interest=item.sumOpenInterest,
                        open_interest_value=item.sumOpenInterestValue,
                    )
                    for item in wires
                    if item.symbol == request.asset.key
                ],
            )
        except (TypeError, ValueError, ValidationError) as error:
            raise ProviderSchemaError(
                "Binance Futures open-interest history schema changed."
            ) from error
        return NormalizedPayload(
            data=data,
            source_timestamp=data.points[-1].timestamp,
            delay_class=DelayClass.LIVE,
        )


class BinanceFuturesBasisAdapter(_FuturesAdapter[FuturesBasisData]):
    schema_version: ClassVar[str] = "binance-futures-basis-v1"
    data_model: ClassVar[type[BaseModel]] = FuturesBasisData

    def build_request(self, request: ProviderRequest) -> OutboundRequest:
        if request.operation != "futures.basis":
            raise ValueError("basis adapter received an unsupported operation")
        return OutboundRequest(
            url=self._url("/futures/data/basis"),
            params={
                "pair": request.asset.key,
                "contractType": "PERPETUAL",
                "period": _period(request).value,
                "limit": _bounded_limit(request),
            },
        )

    def normalize(
        self, response: ProviderHttpResponse, request: ProviderRequest
    ) -> NormalizedPayload[FuturesBasisData]:
        fields = frozenset(
            {
                "pair",
                "contractType",
                "indexPrice",
                "futuresPrice",
                "basis",
                "basisRate",
                "annualizedBasisRate",
                "timestamp",
            }
        )
        try:
            if not isinstance(response.payload, list):
                raise TypeError("basis history must be a list")
            wires = _BASIS_ADAPTER.validate_python(
                _history(response, request, fields, identity="pair")
            )
            data = FuturesBasisData(
                symbol=request.asset.key,
                pair=request.asset.key,
                contract_type="PERPETUAL",
                period=_period(request),
                points=[
                    BasisPoint(
                        timestamp=_utc(item.timestamp),
                        index_price=item.indexPrice,
                        futures_price=item.futuresPrice,
                        basis=item.basis,
                        basis_rate=item.basisRate,
                        annualized_basis_rate=None,
                    )
                    for item in wires
                    if item.pair == request.asset.key
                    and item.contractType == "PERPETUAL"
                ],
            )
        except (TypeError, ValueError, ValidationError) as error:
            raise ProviderSchemaError(
                "Binance Futures basis schema changed."
            ) from error
        return NormalizedPayload(
            data=data,
            source_timestamp=data.points[-1].timestamp,
            delay_class=DelayClass.LIVE,
        )


class BinanceFuturesAccountRatioAdapter(_FuturesAdapter[AccountRatioData]):
    schema_version: ClassVar[str] = "binance-futures-account-ratio-v1"
    data_model: ClassVar[type[BaseModel]] = AccountRatioData

    def build_request(self, request: ProviderRequest) -> OutboundRequest:
        period = _period(request)
        limit = _bounded_limit(request)
        if request.operation != "futures.positioning.accounts":
            raise ValueError("account-ratio adapter received an unsupported operation")
        return OutboundRequest(
            url=self._url("/futures/data/globalLongShortAccountRatio"),
            params={
                "symbol": request.asset.key,
                "period": period.value,
                "limit": limit,
            },
        )

    def normalize(
        self, response: ProviderHttpResponse, request: ProviderRequest
    ) -> NormalizedPayload[AccountRatioData]:
        fields = frozenset(
            {"symbol", "longShortRatio", "longAccount", "shortAccount", "timestamp"}
        )
        try:
            if not isinstance(response.payload, list):
                raise TypeError("account-ratio history must be a list")
            wires = _POSITIONING_ADAPTER.validate_python(
                _history(response, request, fields)
            )
            data = AccountRatioData(
                symbol=request.asset.key,
                period=_period(request),
                points=[
                    PositioningPoint(
                        timestamp=_utc(item.timestamp),
                        long_short_ratio=item.longShortRatio,
                        long_account_share=item.longAccount,
                        short_account_share=item.shortAccount,
                    )
                    for item in wires
                    if item.symbol == request.asset.key
                ],
            )
        except (TypeError, ValueError, ValidationError) as error:
            raise ProviderSchemaError(
                "Binance Futures account-ratio schema changed."
            ) from error
        return NormalizedPayload(
            data=data,
            source_timestamp=data.points[-1].timestamp,
            delay_class=DelayClass.LIVE,
        )


class BinanceFuturesTakerFlowAdapter(_FuturesAdapter[TakerFlowData]):
    schema_version: ClassVar[str] = "binance-futures-taker-flow-v1"
    data_model: ClassVar[type[BaseModel]] = TakerFlowData

    def build_request(self, request: ProviderRequest) -> OutboundRequest:
        if request.operation != "futures.positioning.taker":
            raise ValueError("taker-flow adapter received an unsupported operation")
        return OutboundRequest(
            url=self._url("/futures/data/takerlongshortRatio"),
            params={
                "symbol": request.asset.key,
                "period": _period(request).value,
                "limit": _bounded_limit(request),
            },
        )

    def normalize(
        self, response: ProviderHttpResponse, request: ProviderRequest
    ) -> NormalizedPayload[TakerFlowData]:
        fields = frozenset({"buySellRatio", "buyVol", "sellVol", "timestamp"})
        try:
            if not isinstance(response.payload, list):
                raise TypeError("taker-flow history must be a list")
            wires = _TAKER_ADAPTER.validate_python(
                _history(response, request, fields, identity=None)
            )
            data = TakerFlowData(
                symbol=request.asset.key,
                period=_period(request),
                points=[
                    TakerFlowPoint(
                        timestamp=_utc(item.timestamp),
                        buy_sell_ratio=item.buySellRatio,
                        buy_volume=item.buyVol,
                        sell_volume=item.sellVol,
                    )
                    for item in wires
                ],
            )
        except (TypeError, ValueError, ValidationError) as error:
            raise ProviderSchemaError(
                "Binance Futures taker-flow schema changed."
            ) from error
        return NormalizedPayload(
            data=data,
            source_timestamp=data.points[-1].timestamp,
            delay_class=DelayClass.LIVE,
        )
