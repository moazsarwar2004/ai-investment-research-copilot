"""Provider-neutral request, normalization, provenance, and response contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, cast

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from backend.app.cache import CacheStatus, JsonScalar, JsonValue


class AssetType(StrEnum):
    """Canonical asset classes understood by provider cache keys."""

    STOCK = "stock"
    CRYPTO = "crypto"
    BINANCE_SPOT = "binance_spot"
    BINANCE_FUTURES = "binance_futures"
    FILING = "filing"
    SYSTEM = "system"


class DelayClass(StrEnum):
    """Provider-declared delay classification retained with normalized data."""

    LIVE = "live"
    DELAYED = "delayed"
    END_OF_DAY = "end_of_day"
    FILING = "filing"
    OFFLINE = "offline"


class Freshness(StrEnum):
    """User-facing freshness states from the requirements contract."""

    LIVE = "live"
    DELAYED = "delayed"
    CACHED = "cached"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


class RequestKind(StrEnum):
    """Quota priority classes used by provider managers."""

    INTERACTIVE = "interactive"
    SCHEDULED = "scheduled"


class CanonicalAsset(BaseModel):
    """Unambiguous internal asset identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    asset_type: AssetType
    key: str = Field(min_length=1, max_length=120)
    provider_id: str | None = Field(default=None, min_length=1, max_length=160)

    @field_validator("key", "provider_id")
    @classmethod
    def normalize_identifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("asset identifiers must not be blank")
        return normalized

    @property
    def cache_identity(self) -> str:
        """Return an asset-type-qualified key to prevent symbol collisions."""
        return f"{self.asset_type.value}:{self.key.lower()}"


class ProviderRequest(BaseModel):
    """One bounded, cache-aware provider operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9._-]+$")
    asset: CanonicalAsset
    interval: str | None = Field(default=None, min_length=1, max_length=40)
    parameters: dict[str, JsonScalar] = Field(default_factory=dict)
    weight: int = Field(default=1, ge=1, le=10_000)
    kind: RequestKind = RequestKind.INTERACTIVE
    soft_ttl_seconds: int = Field(ge=1, le=604_800)
    hard_ttl_seconds: int = Field(ge=1, le=2_592_000)

    @model_validator(mode="after")
    def validate_ttls(self) -> ProviderRequest:
        if self.hard_ttl_seconds < self.soft_ttl_seconds:
            raise ValueError("hard TTL must be at least soft TTL")
        return self


class OutboundRequest(BaseModel):
    """Adapter-built request restricted to safe, idempotent provider reads."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    method: Literal["GET", "HEAD"] = "GET"
    url: AnyHttpUrl
    params: dict[str, str | int | float | bool] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)


class ProviderWarning(BaseModel):
    """Stable warning suitable for APIs, reports, and UI badges."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9._-]+$")
    message: str = Field(min_length=1, max_length=300)


class NormalizedPayload[DataT: BaseModel](BaseModel):
    """Adapter output before framework-owned provenance is attached."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    data: DataT
    source_timestamp: datetime | None = None
    delay_class: DelayClass
    partial: bool = False
    warnings: list[ProviderWarning] = Field(default_factory=list)

    @field_validator("source_timestamp")
    @classmethod
    def timestamp_must_be_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("source timestamp must include a timezone")
        return value.astimezone(UTC)


class ProviderProvenance(BaseModel):
    """Audit metadata proving where and how a normalized payload was obtained."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1, max_length=80)
    operation: str = Field(min_length=1, max_length=80)
    source_url: AnyHttpUrl
    provider_request_id: str | None = Field(default=None, max_length=200)
    raw_payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    schema_version: str = Field(min_length=1, max_length=40)
    terms_review_version: str = Field(min_length=1, max_length=80)
    attribution: str = Field(min_length=1, max_length=300)


class ProviderMeta(BaseModel):
    """Cross-provider response metadata required by the public API contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str = Field(min_length=1, max_length=80)
    source_timestamp: datetime | None
    fetched_at: datetime
    cache_status: CacheStatus
    freshness: Freshness
    staleness_seconds: int = Field(ge=0)
    partial: bool
    warnings: list[ProviderWarning]
    delay_class: DelayClass
    provenance: ProviderProvenance

    @field_validator("source_timestamp", "fetched_at")
    @classmethod
    def metadata_timestamp_must_be_aware(
        cls, value: datetime | None
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("provider timestamps must include a timezone")
        return value.astimezone(UTC)


class ProviderResponse[DataT: BaseModel](BaseModel):
    """Normalized data paired with complete freshness and provenance metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    data: DataT
    meta: ProviderMeta

    def as_cache_value(self) -> JsonValue:
        """Render a JSON-safe value without retaining a raw provider payload."""
        rendered = self.model_dump(mode="json")
        return cast(JsonValue, rendered)


class ProviderHttpResponse(BaseModel):
    """Bounded HTTP response passed from the client to an adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    payload: object
    fetched_at: datetime
    source_url: AnyHttpUrl
    headers: dict[str, str]
    raw_payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    provider_request_id: str | None
    attempts: int = Field(ge=1, le=10)


def decimal_as_string(value: Decimal | None) -> str | None:
    """Serialize a finite Decimal without introducing binary-float rounding."""
    if value is None:
        return None
    if not value.is_finite():
        raise ValueError("provider decimals must be finite")
    return format(value, "f")
