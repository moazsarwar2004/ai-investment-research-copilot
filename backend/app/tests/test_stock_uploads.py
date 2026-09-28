"""Private CSV validation, analytics, idempotency, and ownership tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import pytest

from backend.app.core.config import Environment, Settings
from backend.app.core.exceptions import (
    ApplicationValidationError,
    ConflictError,
    ResourceNotFoundError,
)
from backend.app.models import AuditLog, StockPriceUpload
from backend.app.providers.stocks import StockExchange
from backend.app.repositories import StockUploadRepository
from backend.app.services.identity_service import CurrentPrincipal
from backend.app.services.stock_upload_service import (
    StockPriceUploadRequest,
    StockUploadService,
    parse_price_csv,
)


def _csv(rows: int = 30) -> str:
    lines = ["date,open,high,low,close,volume"]
    start = datetime(2026, 1, 1, tzinfo=UTC)
    for index in range(rows):
        day = (start + timedelta(days=index)).date().isoformat()
        close = 100 + index
        lines.append(f"{day},{close - 1},{close + 2},{close - 2},{close},500000")
    return "\n".join(lines)


class _MemorySession:
    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class _MemoryRepository:
    def __init__(self) -> None:
        self.session = _MemorySession()
        self.uploads: dict[UUID, StockPriceUpload] = {}
        self.audits: list[AuditLog] = []

    def add(self, upload: StockPriceUpload) -> None:
        self.uploads[upload.id] = upload

    def add_audit(self, audit: AuditLog) -> None:
        self.audits.append(audit)

    async def lock_owner(self, owner_user_id: UUID) -> None:
        del owner_user_id

    async def usage(self, **filters: object) -> tuple[int, int]:
        uploads = [
            item
            for item in self.uploads.values()
            if item.owner_user_id == filters["owner_user_id"]
        ]
        if filters.get("exchange") is not None:
            uploads = [item for item in uploads if item.exchange == filters["exchange"]]
        if filters.get("symbol") is not None:
            uploads = [item for item in uploads if item.symbol == filters["symbol"]]
        return len(uploads), sum(item.row_count for item in uploads)

    async def delete_expired_owned(self, **filters: object) -> int:
        created_before = cast(datetime, filters["created_before"])
        expired = [
            upload_id
            for upload_id, item in self.uploads.items()
            if item.owner_user_id == filters["owner_user_id"]
            and item.created_at < created_before
        ]
        for upload_id in expired:
            del self.uploads[upload_id]
        return len(expired)

    async def find_duplicate(self, **filters: object) -> StockPriceUpload | None:
        return next(
            (
                item
                for item in self.uploads.values()
                if item.owner_user_id == filters["owner_user_id"]
                and item.exchange == filters["exchange"]
                and item.symbol == filters["symbol"]
                and item.content_sha256 == filters["content_sha256"]
            ),
            None,
        )

    async def get_owned(
        self, *, upload_id: UUID, owner_user_id: UUID
    ) -> StockPriceUpload | None:
        upload = self.uploads.get(upload_id)
        return (
            upload
            if upload is not None and upload.owner_user_id == owner_user_id
            else None
        )

    async def list_owned(self, **filters: object) -> list[StockPriceUpload]:
        return [
            item
            for item in self.uploads.values()
            if item.owner_user_id == filters["owner_user_id"]
            and item.exchange == filters["exchange"]
            and item.symbol == filters["symbol"]
        ]

    async def delete_owned(self, *, upload_id: UUID, owner_user_id: UUID) -> bool:
        upload = await self.get_owned(upload_id=upload_id, owner_user_id=owner_user_id)
        if upload is None:
            return False
        del self.uploads[upload_id]
        return True


def _principal(user_id: UUID) -> CurrentPrincipal:
    return cast(
        CurrentPrincipal,
        SimpleNamespace(user=SimpleNamespace(id=user_id)),
    )


def test_csv_parser_requires_exact_schema_and_valid_ohlc() -> None:
    candles = parse_price_csv(_csv())
    assert len(candles) == 30
    assert candles[0].close == 100

    with pytest.raises(ApplicationValidationError, match="columns must be exactly"):
        parse_price_csv(_csv().replace("volume", "turnover", 1))
    with pytest.raises(ApplicationValidationError, match="at least 20"):
        parse_price_csv(_csv(19))
    with pytest.raises(ApplicationValidationError, match="high is inconsistent"):
        parse_price_csv(_csv().replace("99,102,98,100", "99,90,98,100", 1))
    with pytest.raises(ApplicationValidationError, match="extra columns"):
        parse_price_csv(_csv().replace("500000", "500000,unexpected", 1))
    with pytest.raises(ApplicationValidationError, match="supported magnitude"):
        parse_price_csv(_csv().replace("500000", "1e30", 1))

    sparse = ["date,open,high,low,close,volume"]
    sparse.extend(
        f"{(datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=30 * index)).date()},"
        "99,102,98,100,500000"
        for index in range(20)
    )
    with pytest.raises(ApplicationValidationError, match="near-daily"):
        parse_price_csv("\n".join(sparse))


async def test_upload_is_idempotent_private_and_uses_phase7_analytics() -> None:
    memory = _MemoryRepository()
    service = StockUploadService(cast(StockUploadRepository, memory))
    owner = _principal(uuid4())
    other = _principal(uuid4())
    request = StockPriceUploadRequest(
        filename="ogdc-history.csv",
        source_label="Licensed personal export",
        source_timestamp=datetime(2026, 2, 1, tzinfo=UTC),
        currency="PKR",
        csv_text=_csv(),
    )

    first = await service.create(
        principal=owner,
        exchange=StockExchange.PSX,
        symbol="OGDC",
        request=request,
    )
    repeated = await service.create(
        principal=owner,
        exchange=StockExchange.PSX,
        symbol="OGDC",
        request=request,
    )

    assert first.upload.upload_id == repeated.upload.upload_id
    assert first.upload.owner_private is True
    assert first.technicals.points == 30
    assert first.risk.missing_inputs == ["liquidity"]
    with pytest.raises(ResourceNotFoundError):
        await service.get(principal=other, upload_id=first.upload.upload_id)


async def test_upload_quota_is_enforced_after_owner_lock() -> None:
    memory = _MemoryRepository()
    settings = Settings(
        _env_file=None,
        environment=Environment.TESTING,
        stock_upload_max_per_user=1,
        stock_upload_max_per_asset=1,
    )
    service = StockUploadService(cast(StockUploadRepository, memory), settings)
    owner = _principal(uuid4())
    first = StockPriceUploadRequest(
        filename="first.csv",
        source_label="First fixture",
        source_timestamp=datetime(2026, 2, 1, tzinfo=UTC),
        currency="pkr",
        csv_text=_csv(),
    )
    second = first.model_copy(
        update={
            "filename": "second.csv",
            "csv_text": _csv().replace("500000", "500001"),
        }
    )
    await service.create(
        principal=owner,
        exchange=StockExchange.PSX,
        symbol="OGDC",
        request=first,
    )
    with pytest.raises(ConflictError, match="limit reached"):
        await service.create(
            principal=owner,
            exchange=StockExchange.PSX,
            symbol="OGDC",
            request=second,
        )
