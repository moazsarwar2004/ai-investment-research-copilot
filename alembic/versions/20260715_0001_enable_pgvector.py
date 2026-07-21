"""Enable the pgvector extension.

Revision ID: 20260715_0001
Revises:
Create Date: 2026-07-15 00:00:00+00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260715_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Install vector support before any embedding model is introduced."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    """Remove vector support only while no dependent schema exists."""
    op.execute("DROP EXTENSION IF EXISTS vector")
