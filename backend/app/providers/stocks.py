"""Provider-neutral stock identity and market-data contracts.

No external stock feed is selected in Phase 7.  A future adapter must implement
``StockMarketDataProvider`` and carry reviewed display-license metadata before
the service will expose its data.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from backend.app.providers.models import ProviderResponse


class _StockModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class StockInterval(StrEnum):
    """Intervals supported by the first stock analytics surface."""

    DAY = "1d"
    WEEK = "1w"


class StockExchange(StrEnum):
    """Explicit exchange identity preventing cross-market symbol collisions."""

    PSX = "PSX"
    NASDAQ = "NASDAQ"
    NYSE = "NYSE"


class StockMarketDataStatus(StrEnum):
    """Whether externally displayable stock market data is available."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class StockProviderLicense(_StockModel):
    """Reviewed terms evidence required before an adapter can be activated."""

    provider: str = Field(min_length=1, max_length=80)
    plan: str = Field(min_length=1, max_length=120)
    terms_url: AnyHttpUrl
    terms_reviewed_on: date
    display_authorized: bool
    quote_delay_minutes: int = Field(ge=0, le=1_440)
    attribution: str = Field(min_length=1, max_length=300)

    @field_validator("provider", "plan", "attribution")
    @classmethod
    def strip_text(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("license text must not be blank")
        return normalized


class StockLicenseDisclosure(_StockModel):
    """Safe public disclosure for configured and unavailable states."""

    status: StockMarketDataStatus
    display_authorized: bool
    provider: str | None = None
    plan: str | None = None
    terms_url: AnyHttpUrl | None = None
    terms_reviewed_on: date | None = None
    quote_delay_minutes: int | None = Field(default=None, ge=0, le=1_440)
    attribution: str | None = None
    message: str = Field(min_length=1, max_length=500)


class StockSearchResult(_StockModel):
    """One provider-normalized company identity candidate."""

    symbol: str = Field(min_length=1, max_length=12)
    company_name: str = Field(min_length=1, max_length=240)
    exchange: StockExchange
    country: str | None = Field(default=None, max_length=80)
    provider_id: str | None = Field(default=None, max_length=160)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("stock symbol must not be blank")
        return normalized


class StockSearchData(_StockModel):
    query: str = Field(min_length=1, max_length=80)
    results: list[StockSearchResult] = Field(max_length=100)


class StockProfile(_StockModel):
    """Provider-neutral company profile; SEC identity joins arrive in Phase 8."""

    symbol: str = Field(min_length=1, max_length=12)
    company_name: str = Field(min_length=1, max_length=240)
    exchange: StockExchange
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    country: str | None = Field(default=None, max_length=80)
    sector: str | None = Field(default=None, max_length=120)
    industry: str | None = Field(default=None, max_length=160)
    website: AnyHttpUrl | None = None
    description: str | None = Field(default=None, max_length=4_000)
    provider_id: str | None = Field(default=None, max_length=160)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None


class StockQuote(_StockModel):
    """Latest or delayed quote with an explicit provider source timestamp."""

    symbol: str = Field(min_length=1, max_length=12)
    exchange: StockExchange
    currency: str = Field(min_length=3, max_length=3)
    latest_price: Decimal = Field(gt=0)
    open: Decimal | None = Field(default=None, gt=0)
    high: Decimal | None = Field(default=None, gt=0)
    low: Decimal | None = Field(default=None, gt=0)
    previous_close: Decimal | None = Field(default=None, gt=0)
    change: Decimal | None = None
    change_percent: Decimal | None = None
    volume: Decimal | None = Field(default=None, ge=0)
    market_cap: Decimal | None = Field(default=None, ge=0)
    fifty_two_week_high: Decimal | None = Field(default=None, gt=0)
    fifty_two_week_low: Decimal | None = Field(default=None, gt=0)
    source_timestamp: datetime

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("source_timestamp")
    @classmethod
    def source_time_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("quote source timestamp must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_ranges(self) -> StockQuote:
        if self.high is not None and self.low is not None and self.high < self.low:
            raise ValueError("quote high must be at least low")
        if (
            self.fifty_two_week_high is not None
            and self.fifty_two_week_low is not None
            and self.fifty_two_week_high < self.fifty_two_week_low
        ):
            raise ValueError("52-week high must be at least 52-week low")
        return self


class StockCandle(_StockModel):
    timestamp: datetime
    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    volume: Decimal = Field(ge=0)

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("candle timestamp must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_ohlc(self) -> StockCandle:
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("candle high is inconsistent with OHLC values")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("candle low is inconsistent with OHLC values")
        return self


class StockCandlesData(_StockModel):
    symbol: str = Field(min_length=1, max_length=12)
    exchange: StockExchange
    currency: str = Field(min_length=3, max_length=3)
    interval: StockInterval
    days: int = Field(ge=30, le=1_825)
    candles: list[StockCandle] = Field(max_length=1_500)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def candles_are_ordered(self) -> StockCandlesData:
        timestamps = [item.timestamp for item in self.candles]
        if timestamps != sorted(timestamps) or len(timestamps) != len(set(timestamps)):
            raise ValueError("stock candles must be unique and chronological")
        return self


class StockMarketDataProvider(ABC):
    """Interface for a legally reviewed, normalized stock-data adapter."""

    license: StockProviderLicense

    @abstractmethod
    async def search(
        self,
        query: str,
        *,
        exchange: StockExchange,
    ) -> ProviderResponse[StockSearchData]: ...

    @abstractmethod
    async def profile(
        self,
        exchange: StockExchange,
        symbol: str,
    ) -> ProviderResponse[StockProfile]: ...

    @abstractmethod
    async def quote(
        self,
        exchange: StockExchange,
        symbol: str,
    ) -> ProviderResponse[StockQuote]: ...

    @abstractmethod
    async def candles(
        self,
        exchange: StockExchange,
        symbol: str,
        *,
        interval: StockInterval,
        days: int,
    ) -> ProviderResponse[StockCandlesData]: ...


__all__ = [
    "StockCandle",
    "StockCandlesData",
    "StockExchange",
    "StockInterval",
    "StockLicenseDisclosure",
    "StockMarketDataProvider",
    "StockMarketDataStatus",
    "StockProfile",
    "StockProviderLicense",
    "StockQuote",
    "StockSearchData",
    "StockSearchResult",
]
