"""SQLAlchemy queries for users, rotating sessions, and audit evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Select, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import AuditLog, User, UserSession


class IdentityRepository:
    """Perform identity persistence without embedding authorization decisions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_user_by_email(self, email: str, *, lock: bool = False) -> User | None:
        statement: Select[tuple[User]] = select(User).where(User.email == email)
        if lock:
            statement = statement.with_for_update()
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def get_user_by_id(self, user_id: UUID, *, lock: bool = False) -> User | None:
        statement: Select[tuple[User]] = select(User).where(User.id == user_id)
        if lock:
            statement = statement.with_for_update()
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def get_user_by_verification_digest(self, digest: str) -> User | None:
        statement = (
            select(User)
            .where(User.verification_token_digest == digest)
            .with_for_update()
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def get_user_by_reset_digest(self, digest: str) -> User | None:
        statement = (
            select(User)
            .where(User.password_reset_token_digest == digest)
            .with_for_update()
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    def add_user(self, user: User) -> None:
        self.session.add(user)

    def add_session(self, user_session: UserSession) -> None:
        self.session.add(user_session)

    async def get_session_by_digest(
        self, digest: str, *, lock: bool = False
    ) -> UserSession | None:
        statement: Select[tuple[UserSession]] = select(UserSession).where(
            UserSession.refresh_token_digest == digest
        )
        if lock:
            statement = statement.with_for_update()
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def get_session_and_user(
        self, session_id: UUID, user_id: UUID
    ) -> tuple[UserSession, User] | None:
        statement = (
            select(UserSession, User)
            .join(User, User.id == UserSession.user_id)
            .where(UserSession.id == session_id, UserSession.user_id == user_id)
        )
        row = (await self.session.execute(statement)).one_or_none()
        return None if row is None else (row[0], row[1])

    async def get_owned_session(
        self, *, session_id: UUID, owner_user_id: UUID, lock: bool = False
    ) -> UserSession | None:
        statement: Select[tuple[UserSession]] = select(UserSession).where(
            UserSession.id == session_id,
            UserSession.user_id == owner_user_id,
        )
        if lock:
            statement = statement.with_for_update()
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def list_active_sessions(
        self, *, owner_user_id: UUID, now: datetime
    ) -> list[UserSession]:
        statement = (
            select(UserSession)
            .where(
                UserSession.user_id == owner_user_id,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > now,
                UserSession.family_expires_at > now,
            )
            .order_by(UserSession.last_used_at.desc())
        )
        return list((await self.session.scalars(statement)).all())

    async def revoke_family(
        self, *, family_id: UUID, now: datetime, reason: str
    ) -> int:
        statement = (
            update(UserSession)
            .where(
                UserSession.token_family_id == family_id,
                UserSession.revoked_at.is_(None),
            )
            .values(revoked_at=now, revocation_reason=reason)
        )
        result = cast(CursorResult[Any], await self.session.execute(statement))
        return int(result.rowcount or 0)

    async def revoke_all_for_user(
        self, *, user_id: UUID, now: datetime, reason: str
    ) -> int:
        statement = (
            update(UserSession)
            .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
            .values(revoked_at=now, revocation_reason=reason)
        )
        result = cast(CursorResult[Any], await self.session.execute(statement))
        return int(result.rowcount or 0)

    def add_audit(self, audit: AuditLog) -> None:
        self.session.add(audit)

    async def list_users(self, *, limit: int, offset: int) -> list[User]:
        statement = (
            select(User).order_by(User.created_at.desc()).limit(limit).offset(offset)
        )
        return list((await self.session.scalars(statement)).all())

    async def list_audits(self, *, limit: int, offset: int) -> list[AuditLog]:
        statement = (
            select(AuditLog)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list((await self.session.scalars(statement)).all())
