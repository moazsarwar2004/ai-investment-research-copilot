"""Owner-scoped persistence for private stock price uploads."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Select, delete, func, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import AuditLog, StockPriceUpload, User


class StockUploadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, upload: StockPriceUpload) -> None:
        self.session.add(upload)

    def add_audit(self, audit: AuditLog) -> None:
        self.session.add(audit)

    async def lock_owner(self, owner_user_id: UUID) -> None:
        """Serialize quota checks and inserts for one user inside the transaction."""
        statement = select(User.id).where(User.id == owner_user_id).with_for_update()
        await self.session.execute(statement)

    async def usage(
        self,
        *,
        owner_user_id: UUID,
        exchange: str | None = None,
        symbol: str | None = None,
    ) -> tuple[int, int]:
        statement = select(
            func.count(StockPriceUpload.id),
            func.coalesce(func.sum(StockPriceUpload.row_count), 0),
        ).where(StockPriceUpload.owner_user_id == owner_user_id)
        if exchange is not None:
            statement = statement.where(StockPriceUpload.exchange == exchange)
        if symbol is not None:
            statement = statement.where(StockPriceUpload.symbol == symbol)
        row = (await self.session.execute(statement)).one()
        return int(row[0]), int(row[1])

    async def delete_expired_owned(
        self, *, owner_user_id: UUID, created_before: datetime
    ) -> int:
        statement = delete(StockPriceUpload).where(
            StockPriceUpload.owner_user_id == owner_user_id,
            StockPriceUpload.created_at < created_before,
        )
        result = await self.session.execute(statement)
        return int(cast(CursorResult[Any], result).rowcount or 0)

    async def find_duplicate(
        self,
        *,
        owner_user_id: UUID,
        exchange: str,
        symbol: str,
        content_sha256: str,
    ) -> StockPriceUpload | None:
        statement: Select[tuple[StockPriceUpload]] = select(StockPriceUpload).where(
            StockPriceUpload.owner_user_id == owner_user_id,
            StockPriceUpload.exchange == exchange,
            StockPriceUpload.symbol == symbol,
            StockPriceUpload.content_sha256 == content_sha256,
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def get_owned(
        self, *, upload_id: UUID, owner_user_id: UUID
    ) -> StockPriceUpload | None:
        statement: Select[tuple[StockPriceUpload]] = select(StockPriceUpload).where(
            StockPriceUpload.id == upload_id,
            StockPriceUpload.owner_user_id == owner_user_id,
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def list_owned(
        self,
        *,
        owner_user_id: UUID,
        exchange: str,
        symbol: str,
        limit: int = 20,
    ) -> list[StockPriceUpload]:
        statement = (
            select(StockPriceUpload)
            .where(
                StockPriceUpload.owner_user_id == owner_user_id,
                StockPriceUpload.exchange == exchange,
                StockPriceUpload.symbol == symbol,
            )
            .order_by(StockPriceUpload.created_at.desc())
            .limit(limit)
        )
        return list((await self.session.scalars(statement)).all())

    async def delete_owned(self, *, upload_id: UUID, owner_user_id: UUID) -> bool:
        statement = delete(StockPriceUpload).where(
            StockPriceUpload.id == upload_id,
            StockPriceUpload.owner_user_id == owner_user_id,
        )
        result = await self.session.execute(statement)
        return bool(cast(CursorResult[Any], result).rowcount)


__all__ = ["StockUploadRepository"]
