"""Strict CoinGecko Demo/keyless adapters for general crypto research."""

from __future__ import annotations

import re
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
    model_validator,
)

from backend.app.providers.adapters import ProviderAdapter
from backend.app.providers.models import (
    DelayClass,
    NormalizedPayload,
    OutboundRequest,
    ProviderHttpResponse,
    ProviderRequest,
    ProviderWarning,
)

COINGECKO_PROVIDER = "coingecko"
COINGECKO_HOST = "api.coingecko.com"
COINGECKO_TERMS_REVIEW = "coingecko-api-terms-2025-09-05-reviewed-2026-08-04"
COINGECKO_ATTRIBUTION = "Powered by CoinGecko"

_COIN_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


CRYPTO_HISTORY_DAYS = frozenset({1, 7, 30, 90, 365})


class CryptoMarketOrder(StrEnum):
    MARKET_CAP_DESC = "market_cap_desc"
    MARKET_CAP_ASC = "market_cap_asc"
    VOLUME_DESC = "volume_desc"
    VOLUME_ASC = "volume_asc"


class _NormalizedModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


class CoinSearchResult(_NormalizedModel):
    coin_id: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=200)
    symbol: str = Field(min_length=1, max_length=40)
    market_cap_rank: int | None = Field(default=None, ge=1)
    image_url: AnyHttpUrl | None = None


class CoinSearchResolution(_NormalizedModel):
    exact_provider_id: str | None = None
    exact_name_coin_ids: list[str]
    exact_symbol_coin_ids: list[str]
    ambiguous_symbol: bool
    message: str


class CoinSearchData(_NormalizedModel):
    query: str
    coins: list[CoinSearchResult] = Field(max_length=100)
    resolution: CoinSearchResolution


class CryptoMarket(_NormalizedModel):
    coin_id: str = Field(min_length=1, max_length=160)
    symbol: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=200)
    image_url: AnyHttpUrl | None = None
    currency: str = "usd"
    current_price: Decimal | None = Field(default=None, gt=0)
    market_cap: Decimal | None = Field(default=None, ge=0)
    market_cap_rank: int | None = Field(default=None, ge=1)
    fully_diluted_valuation: Decimal | None = Field(default=None, ge=0)
    total_volume_24h: Decimal | None = Field(default=None, ge=0)
    high_24h: Decimal | None = Field(default=None, gt=0)
    low_24h: Decimal | None = Field(default=None, gt=0)
    price_change_24h: Decimal | None = None
    price_change_percentage_24h: Decimal | None = None
    price_change_percentage_7d: Decimal | None = None
    price_change_percentage_30d: Decimal | None = None
    circulating_supply: Decimal | None = Field(default=None, ge=0)
    total_supply: Decimal | None = Field(default=None, ge=0)
    max_supply: Decimal | None = Field(default=None, ge=0)
    all_time_high: Decimal | None = Field(default=None, gt=0)
    all_time_high_date: datetime | None = None
    distance_from_ath_percent: Decimal | None = Field(default=None, ge=0)
    all_time_low: Decimal | None = Field(default=None, ge=0)
    all_time_low_date: datetime | None = None
    last_updated: datetime

    @model_validator(mode="after")
    def validate_market_ranges(self) -> CryptoMarket:
        if (
            self.low_24h is not None
            and self.high_24h is not None
            and self.low_24h > self.high_24h
        ):
            raise ValueError("24-hour low cannot exceed the high")
        return self


class CryptoMarketsData(_NormalizedModel):
    currency: str = "usd"
    page: int = Field(ge=1)
    per_page: int = Field(ge=1, le=100)
    order: CryptoMarketOrder
    markets: list[CryptoMarket] = Field(max_length=100)


class CryptoHistoryPoint(_NormalizedModel):
    timestamp: datetime
    price: Decimal = Field(gt=0)
    market_cap: Decimal | None = Field(default=None, ge=0)
    total_volume_24h: Decimal | None = Field(default=None, ge=0)


class CryptoHistoryData(_NormalizedModel):
    coin_id: str
    currency: str = "usd"
    days: int
    points: list[CryptoHistoryPoint] = Field(min_length=2, max_length=10_000)


class CryptoGlobalData(_NormalizedModel):
    active_cryptocurrencies: int = Field(ge=0)
    markets: int = Field(ge=0)
    total_market_cap_usd: Decimal = Field(ge=0)
    total_volume_24h_usd: Decimal = Field(ge=0)
    bitcoin_dominance_percent: Decimal = Field(ge=0, le=100)
    ethereum_dominance_percent: Decimal = Field(ge=0, le=100)
    market_cap_change_percentage_24h_usd: Decimal | None = None
    volume_change_percentage_24h_usd: Decimal | None = None
    updated_at: datetime


class TrendingCoin(_NormalizedModel):
    coin_id: str
    name: str
    symbol: str
    market_cap_rank: int | None = Field(default=None, ge=1)
    score: int = Field(ge=0)
    image_url: AnyHttpUrl | None = None


class CryptoTrendingData(_NormalizedModel):
    coins: list[TrendingCoin] = Field(max_length=30)


class _SearchCoinWire(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    symbol: str
    market_cap_rank: int | None = Field(default=None, ge=1)
    thumb: AnyHttpUrl | None = None


class _SearchWire(BaseModel):
    model_config = ConfigDict(extra="ignore")

    coins: list[_SearchCoinWire]


class _MarketWire(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    symbol: str
    name: str
    image: AnyHttpUrl | None = None
    current_price: Decimal | None = None
    market_cap: Decimal | None = None
    market_cap_rank: int | None = None
    fully_diluted_valuation: Decimal | None = None
    total_volume: Decimal | None = None
    high_24h: Decimal | None = None
    low_24h: Decimal | None = None
    price_change_24h: Decimal | None = None
    price_change_percentage_24h: Decimal | None = None
    price_change_percentage_7d_in_currency: Decimal | None = None
    price_change_percentage_30d_in_currency: Decimal | None = None
    circulating_supply: Decimal | None = None
    total_supply: Decimal | None = None
    max_supply: Decimal | None = None
    ath: Decimal | None = None
    ath_date: datetime | None = None
    atl: Decimal | None = None
    atl_date: datetime | None = None
    last_updated: datetime


_MARKETS_ADAPTER = TypeAdapter(list[_MarketWire])
type _ChartPair = tuple[int, Decimal]
_CHART_PAIRS_ADAPTER = TypeAdapter(list[_ChartPair])


class _HistoryWire(BaseModel):
    model_config = ConfigDict(extra="ignore")

    prices: list[tuple[int, Decimal]]
    market_caps: list[tuple[int, Decimal]]
    total_volumes: list[tuple[int, Decimal]]


class _GlobalWireData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    active_cryptocurrencies: int = Field(ge=0)
    markets: int = Field(ge=0)
    total_market_cap: dict[str, Decimal]
    total_volume: dict[str, Decimal]
    market_cap_percentage: dict[str, Decimal]
    market_cap_change_percentage_24h_usd: Decimal | None = None
    volume_change_percentage_24h_usd: Decimal | None = None
    updated_at: int = Field(ge=0)


class _GlobalWire(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data: _GlobalWireData


class _TrendingCoinWire(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    symbol: str
    market_cap_rank: int | None = None
    score: int = Field(ge=0)
    thumb: AnyHttpUrl | None = None


class _TrendingItemWire(BaseModel):
    model_config = ConfigDict(extra="ignore")

    item: _TrendingCoinWire


class _TrendingWire(BaseModel):
    model_config = ConfigDict(extra="ignore")

    coins: list[_TrendingItemWire]


def validate_coin_id(value: str) -> str:
    """Return one canonical CoinGecko ID; symbols are never accepted as IDs."""
    normalized = value.strip().lower()
    if not 1 <= len(normalized) <= 160 or not _COIN_ID_PATTERN.fullmatch(normalized):
        raise ValueError(
            "CoinGecko IDs must use lowercase letters, digits, and single hyphens."
        )
    return normalized


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


def _utc_from_milliseconds(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1_000, tz=UTC)


class _CoinGeckoAdapter[DataT: BaseModel](ProviderAdapter[DataT]):
    provider: ClassVar[str] = COINGECKO_PROVIDER
    terms_review_version: ClassVar[str] = COINGECKO_TERMS_REVIEW
    attribution: ClassVar[str] = COINGECKO_ATTRIBUTION
    allowed_hosts: ClassVar[frozenset[str]] = frozenset({COINGECKO_HOST})

    def __init__(self, base_url: str, *, demo_api_key: str | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._demo_api_key = demo_api_key

    def _url(self, path: str) -> AnyHttpUrl:
        return AnyHttpUrl(f"{self._base_url}{path}")

    def _headers(self) -> dict[str, str]:
        headers = {"accept": "application/json"}
        if self._demo_api_key is not None:
            headers["x-cg-demo-api-key"] = self._demo_api_key
        return headers


class CoinGeckoSearchAdapter(_CoinGeckoAdapter[CoinSearchData]):
    schema_version: ClassVar[str] = "coingecko-search-v1"
    data_model: ClassVar[type[BaseModel]] = CoinSearchData

    def build_request(self, request: ProviderRequest) -> OutboundRequest:
        if request.operation != "crypto.search":
            raise ValueError("search adapter received an unsupported operation")
        query = request.parameters.get("query")
        if not isinstance(query, str) or not 2 <= len(query.strip()) <= 80:
            raise ValueError("search query must contain 2-80 characters")
        return OutboundRequest(
            url=self._url("/search"),
            params={"query": query.strip()},
            headers=self._headers(),
        )

    def normalize(
        self,
        response: ProviderHttpResponse,
        request: ProviderRequest,
    ) -> NormalizedPayload[CoinSearchData]:
        query_value = request.parameters.get("query")
        if not isinstance(query_value, str):
            raise ValueError("search query is missing")
        query = query_value.strip()
        wire = _SearchWire.model_validate(response.payload)
        coins = [
            CoinSearchResult(
                coin_id=item.id,
                name=item.name,
                symbol=item.symbol.upper(),
                market_cap_rank=item.market_cap_rank,
                image_url=item.thumb,
            )
            for item in wire.coins[:100]
        ]
        folded = query.casefold()
        exact_ids = [
            item.coin_id for item in coins if item.coin_id.casefold() == folded
        ]
        exact_names = [item.coin_id for item in coins if item.name.casefold() == folded]
        exact_symbols = [
            item.coin_id for item in coins if item.symbol.casefold() == folded
        ]
        ambiguous = len(exact_symbols) > 1
        if ambiguous:
            message = (
                "The symbol matches multiple assets; select a CoinGecko provider ID."
            )
        elif exact_symbols:
            message = (
                "The symbol has one exact match; use its provider ID for research."
            )
        elif exact_ids:
            message = "The query exactly matches a CoinGecko provider ID."
        else:
            message = "Select a CoinGecko provider ID from the ranked results."
        return NormalizedPayload(
            data=CoinSearchData(
                query=query,
                coins=coins,
                resolution=CoinSearchResolution(
                    exact_provider_id=exact_ids[0] if exact_ids else None,
                    exact_name_coin_ids=exact_names,
                    exact_symbol_coin_ids=exact_symbols,
                    ambiguous_symbol=ambiguous,
                    message=message,
                ),
            ),
            source_timestamp=None,
            delay_class=DelayClass.DELAYED,
        )


class CoinGeckoMarketsAdapter(_CoinGeckoAdapter[CryptoMarketsData]):
    schema_version: ClassVar[str] = "coingecko-markets-v1"
    data_model: ClassVar[type[BaseModel]] = CryptoMarketsData

    def build_request(self, request: ProviderRequest) -> OutboundRequest:
        if request.operation not in {"crypto.markets", "crypto.overview"}:
            raise ValueError("markets adapter received an unsupported operation")
        page = _integer_parameter(request, "page", default=1)
        per_page = _integer_parameter(request, "per_page", default=50)
        order_value = request.parameters.get(
            "order", CryptoMarketOrder.MARKET_CAP_DESC.value
        )
        order = CryptoMarketOrder(str(order_value))
        if not 1 <= page <= 10 or not 1 <= per_page <= 100:
            raise ValueError("market pagination exceeds product bounds")
        params: dict[str, str | int | float | bool] = {
            "vs_currency": "usd",
            "order": order.value,
            "page": page,
            "per_page": per_page,
            "sparkline": "false",
            "price_change_percentage": "24h,7d,30d",
        }
        coin_id = request.parameters.get("coin_id")
        if coin_id is not None:
            if not isinstance(coin_id, str):
                raise ValueError("coin_id must be a string")
            params["ids"] = validate_coin_id(coin_id)
        return OutboundRequest(
            url=self._url("/coins/markets"),
            params=params,
            headers=self._headers(),
        )

    def normalize(
        self,
        response: ProviderHttpResponse,
        request: ProviderRequest,
    ) -> NormalizedPayload[CryptoMarketsData]:
        wire = _MARKETS_ADAPTER.validate_python(response.payload)
        markets: list[CryptoMarket] = []
        missing_market_fields = False
        for item in wire:
            distance_from_ath: Decimal | None = None
            if item.current_price is not None and item.ath is not None and item.ath > 0:
                distance_from_ath = max(
                    Decimal("0"),
                    (Decimal("1") - item.current_price / item.ath) * Decimal("100"),
                )
            if any(
                value is None
                for value in (item.current_price, item.market_cap, item.total_volume)
            ):
                missing_market_fields = True
            markets.append(
                CryptoMarket(
                    coin_id=item.id,
                    symbol=item.symbol.upper(),
                    name=item.name,
                    image_url=item.image,
                    current_price=item.current_price,
                    market_cap=item.market_cap,
                    market_cap_rank=item.market_cap_rank,
                    fully_diluted_valuation=item.fully_diluted_valuation,
                    total_volume_24h=item.total_volume,
                    high_24h=item.high_24h,
                    low_24h=item.low_24h,
                    price_change_24h=item.price_change_24h,
                    price_change_percentage_24h=(item.price_change_percentage_24h),
                    price_change_percentage_7d=(
                        item.price_change_percentage_7d_in_currency
                    ),
                    price_change_percentage_30d=(
                        item.price_change_percentage_30d_in_currency
                    ),
                    circulating_supply=item.circulating_supply,
                    total_supply=item.total_supply,
                    max_supply=item.max_supply,
                    all_time_high=item.ath,
                    all_time_high_date=item.ath_date,
                    distance_from_ath_percent=distance_from_ath,
                    all_time_low=item.atl,
                    all_time_low_date=item.atl_date,
                    last_updated=item.last_updated,
                )
            )
        warnings = (
            [
                ProviderWarning(
                    code="coingecko_market_fields_missing",
                    message="CoinGecko omitted one or more optional market fields.",
                )
            ]
            if missing_market_fields
            else []
        )
        page = _integer_parameter(request, "page", default=1)
        per_page = _integer_parameter(request, "per_page", default=50)
        order = CryptoMarketOrder(
            str(
                request.parameters.get("order", CryptoMarketOrder.MARKET_CAP_DESC.value)
            )
        )
        source_timestamp = max(
            (item.last_updated for item in markets),
            default=None,
        )
        return NormalizedPayload(
            data=CryptoMarketsData(
                page=page,
                per_page=per_page,
                order=order,
                markets=markets,
            ),
            source_timestamp=source_timestamp,
            delay_class=DelayClass.DELAYED,
            partial=missing_market_fields,
            warnings=warnings,
        )


class CoinGeckoHistoryAdapter(_CoinGeckoAdapter[CryptoHistoryData]):
    schema_version: ClassVar[str] = "coingecko-history-v1"
    data_model: ClassVar[type[BaseModel]] = CryptoHistoryData

    def build_request(self, request: ProviderRequest) -> OutboundRequest:
        if request.operation != "crypto.history":
            raise ValueError("history adapter received an unsupported operation")
        coin_id = validate_coin_id(request.asset.key)
        days = _integer_parameter(request, "days", default=90)
        if days not in CRYPTO_HISTORY_DAYS:
            raise ValueError("history days must be 1, 7, 30, 90, or 365")
        return OutboundRequest(
            url=self._url(f"/coins/{coin_id}/market_chart"),
            params={"vs_currency": "usd", "days": days},
            headers=self._headers(),
        )

    def normalize(
        self,
        response: ProviderHttpResponse,
        request: ProviderRequest,
    ) -> NormalizedPayload[CryptoHistoryData]:
        wire = _HistoryWire.model_validate(response.payload)
        prices = dict(_CHART_PAIRS_ADAPTER.validate_python(wire.prices))
        market_caps = dict(_CHART_PAIRS_ADAPTER.validate_python(wire.market_caps))
        volumes = dict(_CHART_PAIRS_ADAPTER.validate_python(wire.total_volumes))
        points = [
            CryptoHistoryPoint(
                timestamp=_utc_from_milliseconds(timestamp),
                price=price,
                market_cap=market_caps.get(timestamp),
                total_volume_24h=volumes.get(timestamp),
            )
            for timestamp, price in sorted(prices.items())
            if price > 0
        ]
        if len(points) < 2:
            raise ValueError("history payload must contain at least two price points")
        missing_parallel_values = any(
            item.market_cap is None or item.total_volume_24h is None for item in points
        )
        warnings = (
            [
                ProviderWarning(
                    code="coingecko_history_series_misaligned",
                    message=(
                        "Some market-cap or volume points did not align with prices."
                    ),
                )
            ]
            if missing_parallel_values
            else []
        )
        return NormalizedPayload(
            data=CryptoHistoryData(
                coin_id=validate_coin_id(request.asset.key),
                days=_integer_parameter(request, "days", default=90),
                points=points,
            ),
            source_timestamp=points[-1].timestamp,
            delay_class=DelayClass.DELAYED,
            partial=missing_parallel_values,
            warnings=warnings,
        )


class CoinGeckoGlobalAdapter(_CoinGeckoAdapter[CryptoGlobalData]):
    schema_version: ClassVar[str] = "coingecko-global-v1"
    data_model: ClassVar[type[BaseModel]] = CryptoGlobalData

    def build_request(self, request: ProviderRequest) -> OutboundRequest:
        if request.operation != "crypto.global":
            raise ValueError("global adapter received an unsupported operation")
        return OutboundRequest(url=self._url("/global"), headers=self._headers())

    def normalize(
        self,
        response: ProviderHttpResponse,
        request: ProviderRequest,
    ) -> NormalizedPayload[CryptoGlobalData]:
        del request
        wire = _GlobalWire.model_validate(response.payload).data
        data = CryptoGlobalData(
            active_cryptocurrencies=wire.active_cryptocurrencies,
            markets=wire.markets,
            total_market_cap_usd=wire.total_market_cap["usd"],
            total_volume_24h_usd=wire.total_volume["usd"],
            bitcoin_dominance_percent=wire.market_cap_percentage["btc"],
            ethereum_dominance_percent=wire.market_cap_percentage["eth"],
            market_cap_change_percentage_24h_usd=(
                wire.market_cap_change_percentage_24h_usd
            ),
            volume_change_percentage_24h_usd=(wire.volume_change_percentage_24h_usd),
            updated_at=datetime.fromtimestamp(wire.updated_at, tz=UTC),
        )
        return NormalizedPayload(
            data=data,
            source_timestamp=data.updated_at,
            delay_class=DelayClass.DELAYED,
        )


class CoinGeckoTrendingAdapter(_CoinGeckoAdapter[CryptoTrendingData]):
    schema_version: ClassVar[str] = "coingecko-trending-v1"
    data_model: ClassVar[type[BaseModel]] = CryptoTrendingData

    def build_request(self, request: ProviderRequest) -> OutboundRequest:
        if request.operation != "crypto.trending":
            raise ValueError("trending adapter received an unsupported operation")
        return OutboundRequest(
            url=self._url("/search/trending"),
            headers=self._headers(),
        )

    def normalize(
        self,
        response: ProviderHttpResponse,
        request: ProviderRequest,
    ) -> NormalizedPayload[CryptoTrendingData]:
        del request
        wire = _TrendingWire.model_validate(response.payload)
        return NormalizedPayload(
            data=CryptoTrendingData(
                coins=[
                    TrendingCoin(
                        coin_id=entry.item.id,
                        name=entry.item.name,
                        symbol=entry.item.symbol.upper(),
                        market_cap_rank=entry.item.market_cap_rank,
                        score=entry.item.score,
                        image_url=entry.item.thumb,
                    )
                    for entry in wire.coins[:30]
                ]
            ),
            source_timestamp=None,
            delay_class=DelayClass.DELAYED,
        )


__all__ = [
    "COINGECKO_ATTRIBUTION",
    "COINGECKO_HOST",
    "COINGECKO_PROVIDER",
    "COINGECKO_TERMS_REVIEW",
    "CRYPTO_HISTORY_DAYS",
    "CoinGeckoGlobalAdapter",
    "CoinGeckoHistoryAdapter",
    "CoinGeckoMarketsAdapter",
    "CoinGeckoSearchAdapter",
    "CoinGeckoTrendingAdapter",
    "CoinSearchData",
    "CoinSearchResolution",
    "CoinSearchResult",
    "CryptoGlobalData",
    "CryptoHistoryData",
    "CryptoHistoryPoint",
    "CryptoMarket",
    "CryptoMarketOrder",
    "CryptoMarketsData",
    "CryptoTrendingData",
    "TrendingCoin",
    "validate_coin_id",
]
