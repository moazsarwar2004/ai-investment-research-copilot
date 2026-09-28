"""Durable owner-private stock price uploads."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.database.base import Base
from backend.app.models.identity import utc_now


class StockPriceUpload(Base):
    """Validated user-supplied OHLCV history, private to one account."""

    __tablename__ = "stock_price_uploads"
    __table_args__ = (
        CheckConstraint(
            "exchange IN ('PSX', 'NASDAQ', 'NYSE')",
            name="stock_price_upload_exchange_valid",
        ),
        CheckConstraint(
            "row_count BETWEEN 20 AND 1500",
            name="stock_price_upload_row_count_valid",
        ),
        CheckConstraint(
            "data_end >= data_start",
            name="stock_price_upload_date_range_valid",
        ),
        UniqueConstraint(
            "owner_user_id",
            "exchange",
            "symbol",
            "content_sha256",
            name="uq_stock_price_uploads_owner_asset_content_unique",
        ),
        Index(
            "ix_stock_price_uploads_owner_asset_created",
            "owner_user_id",
            "exchange",
            "symbol",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    owner_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    exchange: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(12), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(160), nullable=False)
    source_label: Mapped[str] = mapped_column(String(160), nullable=False)
    source_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    data_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    data_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    candles: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


__all__ = ["StockPriceUpload"]
