"""Add owner-private stock price uploads.

Revision ID: 20260806_0003
Revises: 20260721_0002
Create Date: 2026-08-06 00:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260806_0003"
down_revision: str | None = "20260721_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stock_price_uploads",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exchange", sa.String(length=16), nullable=False),
        sa.Column("symbol", sa.String(length=12), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("original_filename", sa.String(length=160), nullable=False),
        sa.Column("source_label", sa.String(length=160), nullable=False),
        sa.Column("source_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("data_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candles", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "exchange IN ('PSX', 'NASDAQ', 'NYSE')",
            name="stock_price_upload_exchange_valid",
        ),
        sa.CheckConstraint(
            "row_count BETWEEN 20 AND 1500",
            name="stock_price_upload_row_count_valid",
        ),
        sa.CheckConstraint(
            "data_end >= data_start",
            name="stock_price_upload_date_range_valid",
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_stock_price_uploads"),
        sa.UniqueConstraint(
            "owner_user_id",
            "exchange",
            "symbol",
            "content_sha256",
            name="uq_stock_price_uploads_owner_asset_content_unique",
        ),
    )
    op.create_index(
        "ix_stock_price_uploads_owner_asset_created",
        "stock_price_uploads",
        ["owner_user_id", "exchange", "symbol", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("stock_price_uploads")
