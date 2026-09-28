"""Authenticated CSV ingestion and private stock technical research."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from pathlib import PurePath
from statistics import median
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError

from backend.app.analytics.stocks import (
    StockRisk,
    StockTechnicalAnalysis,
    StockTrendAnalysis,
    analyze_stock_technicals,
    build_stock_risk,
    build_stock_trend,
)
from backend.app.core.config import Settings
from backend.app.core.exceptions import (
    ApplicationValidationError,
    ConflictError,
    ResourceNotFoundError,
)
from backend.app.core.identity_security import IdentitySecurity
from backend.app.models import AuditLog, StockPriceUpload
from backend.app.providers.stock_fundamentals import StockDataMode
from backend.app.providers.stocks import (
    StockCandle,
    StockCandlesData,
    StockExchange,
    StockInterval,
)
from backend.app.repositories import StockUploadRepository
from backend.app.services.identity_service import CurrentPrincipal, RequestContext
from backend.app.services.stock_service import validate_stock_symbol

CSV_MAX_BYTES = 1024 * 1024
CSV_MAX_ROWS = 1_500
CSV_REQUIRED_COLUMNS = ("date", "open", "high", "low", "close", "volume")
_MAX_NUMERIC_MAGNITUDE = Decimal("1000000000000000")
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")


class _UploadModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class StockPriceUploadRequest(_UploadModel):
    filename: str = Field(min_length=1, max_length=160)
    source_label: str = Field(min_length=1, max_length=160)
    source_timestamp: datetime
    currency: str = Field(default="PKR", min_length=3, max_length=3)
    csv_text: str = Field(min_length=1, max_length=CSV_MAX_BYTES)

    @field_validator("filename")
    @classmethod
    def csv_filename_only(cls, value: str) -> str:
        name = PurePath(value).name
        if (
            name != value
            or "/" in value
            or "\\" in value
            or not name.casefold().endswith(".csv")
        ):
            raise ValueError("filename must be a plain .csv name")
        return name

    @field_validator("source_label")
    @classmethod
    def normalize_source_label(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("source label must not be blank")
        return normalized

    @field_validator("source_timestamp")
    @classmethod
    def source_time_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("source timestamp must include a timezone")
        return value.astimezone(UTC)

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip().upper()
        if not _CURRENCY_PATTERN.fullmatch(normalized):
            raise ValueError("currency must be a three-letter ISO-style code")
        return normalized


class StockUploadSummary(_UploadModel):
    upload_id: UUID
    exchange: StockExchange
    symbol: str
    currency: str
    filename: str
    source_label: str
    source_timestamp: datetime
    uploaded_at: datetime
    data_start: datetime
    data_end: datetime
    row_count: int
    data_mode: str = StockDataMode.USER_SUPPLIED
    owner_private: bool = True


class PrivateStockResearch(_UploadModel):
    upload: StockUploadSummary
    candles: StockCandlesData
    technicals: StockTechnicalAnalysis
    trend: StockTrendAnalysis
    risk: StockRisk
    warnings: list[str]
    disclaimer: str = (
        "User-supplied data is analyzed locally and is not independently verified. "
        "Research and education only; not financial advice."
    )


def _parse_date(value: str, *, row_number: int) -> datetime:
    try:
        parsed = date.fromisoformat(value.strip())
    except ValueError as error:
        raise ApplicationValidationError(
            f"CSV row {row_number}: date must use YYYY-MM-DD."
        ) from error
    return datetime.combine(parsed, time.min, tzinfo=UTC)


def _parse_decimal(value: str | None, *, column: str, row_number: int) -> Decimal:
    if value is None or not value.strip():
        raise ApplicationValidationError(f"CSV row {row_number}: {column} is required.")
    try:
        parsed = Decimal(value.strip())
    except InvalidOperation as error:
        raise ApplicationValidationError(
            f"CSV row {row_number}: {column} must be a number."
        ) from error
    if not parsed.is_finite():
        raise ApplicationValidationError(
            f"CSV row {row_number}: {column} must be finite."
        )
    if abs(parsed) > _MAX_NUMERIC_MAGNITUDE:
        raise ApplicationValidationError(
            f"CSV row {row_number}: {column} exceeds the supported magnitude."
        )
    exponent = parsed.as_tuple().exponent
    if isinstance(exponent, int) and max(0, -exponent) > 8:
        raise ApplicationValidationError(
            f"CSV row {row_number}: {column} may have at most 8 decimal places."
        )
    return parsed


def parse_price_csv(csv_text: str) -> list[StockCandle]:
    """Parse a small, formula-free OHLCV CSV into strict candle contracts."""
    if "\x00" in csv_text:
        raise ApplicationValidationError("CSV must be plain UTF-8 text.")
    if len(csv_text.encode("utf-8")) > CSV_MAX_BYTES:
        raise ApplicationValidationError("CSV exceeds the 1 MiB upload limit.")
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff"), newline=""))
    headers = [item.strip().casefold() for item in (reader.fieldnames or [])]
    if headers != list(CSV_REQUIRED_COLUMNS):
        raise ApplicationValidationError(
            "CSV columns must be exactly: date,open,high,low,close,volume."
        )
    candles: list[StockCandle] = []
    for row_number, raw in enumerate(reader, start=2):
        if row_number > CSV_MAX_ROWS + 1:
            raise ApplicationValidationError(
                f"CSV may contain at most {CSV_MAX_ROWS} data rows."
            )
        if None in raw:
            raise ApplicationValidationError(
                f"CSV row {row_number}: unexpected extra columns were supplied."
            )
        row = {str(key).strip().casefold(): value for key, value in raw.items()}
        try:
            candles.append(
                StockCandle(
                    timestamp=_parse_date(str(row["date"]), row_number=row_number),
                    open=_parse_decimal(
                        row["open"], column="open", row_number=row_number
                    ),
                    high=_parse_decimal(
                        row["high"], column="high", row_number=row_number
                    ),
                    low=_parse_decimal(row["low"], column="low", row_number=row_number),
                    close=_parse_decimal(
                        row["close"], column="close", row_number=row_number
                    ),
                    volume=_parse_decimal(
                        row["volume"], column="volume", row_number=row_number
                    ),
                )
            )
        except ValueError as error:
            raise ApplicationValidationError(
                f"CSV row {row_number}: {error}"
            ) from error
    if len(candles) < 20:
        raise ApplicationValidationError(
            "CSV must contain at least 20 daily price rows for technical analysis."
        )
    candles.sort(key=lambda item: item.timestamp)
    timestamps = [item.timestamp for item in candles]
    if len(timestamps) != len(set(timestamps)):
        raise ApplicationValidationError("CSV dates must be unique.")
    if (candles[-1].timestamp - candles[0].timestamp).days > 1_825:
        raise ApplicationValidationError("CSV history may span at most 1,825 days.")
    gaps = [
        (current.timestamp - previous.timestamp).days
        for previous, current in pairwise(candles)
    ]
    if gaps and (median(gaps) > 4 or sum(gaps) > len(candles) * 5):
        raise ApplicationValidationError(
            "CSV must contain daily or near-daily market observations; sparse "
            "weekly/monthly data would make daily technicals misleading."
        )
    return candles


class StockUploadService:
    def __init__(
        self,
        repository: StockUploadRepository,
        settings: Settings | None = None,
        *,
        security: IdentitySecurity | None = None,
    ) -> None:
        self.repository = repository
        self._settings = settings
        self._security = security

    @property
    def _max_per_user(self) -> int:
        return self._settings.stock_upload_max_per_user if self._settings else 50

    @property
    def _max_per_asset(self) -> int:
        return self._settings.stock_upload_max_per_asset if self._settings else 10

    @property
    def _max_rows_per_user(self) -> int:
        return (
            self._settings.stock_upload_max_rows_per_user if self._settings else 50_000
        )

    @property
    def _retention_days(self) -> int:
        return self._settings.stock_upload_retention_days if self._settings else 90

    def _audit(
        self,
        *,
        action: str,
        principal: CurrentPrincipal,
        upload: StockPriceUpload,
        context: RequestContext | None,
    ) -> None:
        if context is None or self._security is None:
            return
        self.repository.add_audit(
            AuditLog(
                actor_user_id=principal.user.id,
                action=action,
                resource_type="stock_price_upload",
                resource_id=upload.id,
                request_id=context.request_id,
                ip_hash=self._security.digest_client_value(context.client_ip),
                details={
                    "exchange": upload.exchange,
                    "symbol": upload.symbol,
                    "row_count": upload.row_count,
                    "data_start": upload.data_start.date().isoformat(),
                    "data_end": upload.data_end.date().isoformat(),
                },
            )
        )

    @staticmethod
    def _summary(upload: StockPriceUpload) -> StockUploadSummary:
        return StockUploadSummary(
            upload_id=upload.id,
            exchange=StockExchange(upload.exchange),
            symbol=upload.symbol,
            currency=upload.currency,
            filename=upload.original_filename,
            source_label=upload.source_label,
            source_timestamp=upload.source_timestamp,
            uploaded_at=upload.created_at,
            data_start=upload.data_start,
            data_end=upload.data_end,
            row_count=upload.row_count,
        )

    @staticmethod
    def _research(upload: StockPriceUpload) -> PrivateStockResearch:
        candles = StockCandlesData.model_validate(
            {
                "symbol": upload.symbol,
                "exchange": upload.exchange,
                "currency": upload.currency,
                "interval": StockInterval.DAY,
                "days": max(
                    30,
                    min(1_825, (upload.data_end - upload.data_start).days + 1),
                ),
                "candles": upload.candles,
            }
        )
        technicals = analyze_stock_technicals(candles)
        return PrivateStockResearch(
            upload=StockUploadService._summary(upload),
            candles=candles,
            technicals=technicals,
            trend=build_stock_trend(technicals),
            risk=build_stock_risk(quote=None, technicals=technicals),
            warnings=[
                "Prices are user-supplied, private, and not verified by the platform.",
                "Liquidity risk is unavailable because the CSV has no licensed "
                "quote snapshot.",
            ],
        )

    async def create(
        self,
        *,
        principal: CurrentPrincipal,
        exchange: StockExchange,
        symbol: str,
        request: StockPriceUploadRequest,
        context: RequestContext | None = None,
    ) -> PrivateStockResearch:
        normalized = validate_stock_symbol(symbol)
        candles = parse_price_csv(request.csv_text)
        now = datetime.now(UTC)
        if request.source_timestamp > now + timedelta(minutes=5):
            raise ApplicationValidationError(
                "Source timestamp cannot be in the future."
            )
        if candles[-1].timestamp.date() > request.source_timestamp.date():
            raise ApplicationValidationError(
                "CSV cannot contain prices after the recorded source date."
            )
        digest = hashlib.sha256(request.csv_text.encode("utf-8")).hexdigest()
        duplicate = await self.repository.find_duplicate(
            owner_user_id=principal.user.id,
            exchange=exchange.value,
            symbol=normalized,
            content_sha256=digest,
        )
        if duplicate is not None:
            return self._research(duplicate)
        await self.repository.lock_owner(principal.user.id)
        await self.repository.delete_expired_owned(
            owner_user_id=principal.user.id,
            created_before=now - timedelta(days=self._retention_days),
        )
        user_count, user_rows = await self.repository.usage(
            owner_user_id=principal.user.id
        )
        asset_count, _ = await self.repository.usage(
            owner_user_id=principal.user.id,
            exchange=exchange.value,
            symbol=normalized,
        )
        if user_count >= self._max_per_user:
            raise ConflictError(
                "Private upload limit reached; delete an older upload first."
            )
        if asset_count >= self._max_per_asset:
            raise ConflictError(
                "Private upload limit reached for this asset; delete an older "
                "upload first."
            )
        if user_rows + len(candles) > self._max_rows_per_user:
            raise ConflictError(
                "Private upload row budget reached; delete older uploads first."
            )
        upload = StockPriceUpload(
            id=uuid4(),
            owner_user_id=principal.user.id,
            exchange=exchange.value,
            symbol=normalized,
            currency=request.currency,
            original_filename=request.filename,
            source_label=request.source_label,
            source_timestamp=request.source_timestamp,
            content_sha256=digest,
            row_count=len(candles),
            data_start=candles[0].timestamp,
            data_end=candles[-1].timestamp,
            candles=[item.model_dump(mode="json") for item in candles],
            created_at=now,
        )
        self.repository.add(upload)
        self._audit(
            action="stock_price_upload.created",
            principal=principal,
            upload=upload,
            context=context,
        )
        try:
            await self.repository.session.commit()
        except IntegrityError as error:
            await self.repository.session.rollback()
            raise ConflictError("This CSV has already been uploaded.") from error
        return self._research(upload)

    async def get(
        self, *, principal: CurrentPrincipal, upload_id: UUID
    ) -> PrivateStockResearch:
        upload = await self.repository.get_owned(
            upload_id=upload_id, owner_user_id=principal.user.id
        )
        if upload is None:
            raise ResourceNotFoundError("The private price upload was not found.")
        return self._research(upload)

    async def list(
        self,
        *,
        principal: CurrentPrincipal,
        exchange: StockExchange,
        symbol: str,
    ) -> list[StockUploadSummary]:
        normalized = validate_stock_symbol(symbol)
        uploads = await self.repository.list_owned(
            owner_user_id=principal.user.id,
            exchange=exchange.value,
            symbol=normalized,
        )
        return [self._summary(item) for item in uploads]

    async def delete(
        self,
        *,
        principal: CurrentPrincipal,
        upload_id: UUID,
        context: RequestContext | None = None,
    ) -> None:
        upload = await self.repository.get_owned(
            upload_id=upload_id, owner_user_id=principal.user.id
        )
        if upload is None:
            raise ResourceNotFoundError("The private price upload was not found.")
        self._audit(
            action="stock_price_upload.deleted",
            principal=principal,
            upload=upload,
            context=context,
        )
        await self.repository.delete_owned(
            upload_id=upload_id, owner_user_id=principal.user.id
        )
        await self.repository.session.commit()


__all__ = [
    "CSV_MAX_BYTES",
    "CSV_MAX_ROWS",
    "PrivateStockResearch",
    "StockPriceUploadRequest",
    "StockUploadService",
    "StockUploadSummary",
    "parse_price_csv",
]
