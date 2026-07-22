"""Persistent Phase 3 identity, session, and append-only audit records."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.database.base import Base


def utc_now() -> datetime:
    """Return an aware UTC timestamp for Python-side defaults."""
    return datetime.now(UTC)


class User(Base):
    """A registered principal with role and account lifecycle state."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'admin')", name="role_valid"),
        CheckConstraint(
            "status IN ('unverified', 'active', 'disabled')",
            name="status_valid",
        ),
        Index("ix_users_status_created_at", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    email: Mapped[str] = mapped_column(CITEXT(), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unverified"
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_token_digest: Mapped[str | None] = mapped_column(String(64))
    verification_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    password_reset_token_digest: Mapped[str | None] = mapped_column(String(64))
    password_reset_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class UserSession(Base):
    """One refresh-token generation in a rotating token family."""

    __tablename__ = "user_sessions"
    __table_args__ = (
        Index("ix_user_sessions_user_active", "user_id", "revoked_at"),
        Index("ix_user_sessions_family_id", "token_family_id"),
        Index("ix_user_sessions_expires_at", "expires_at"),
        Index(
            "uq_user_sessions_family_active",
            "token_family_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_family_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, default=uuid4
    )
    refresh_token_digest: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )
    parent_session_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("user_sessions.id", ondelete="SET NULL"),
    )
    replaced_by_session_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("user_sessions.id", ondelete="SET NULL"),
    )
    authenticated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    family_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revocation_reason: Mapped[str | None] = mapped_column(String(64))
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(256))


class AuditLog(Base):
    """Append-only sanitized evidence for security and administrative events."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_actor_created", "actor_user_id", "created_at"),
        Index("ix_audit_logs_action_created", "action", "created_at"),
        Index("ix_audit_logs_resource", "resource_type", "resource_id"),
        Index(
            "ix_audit_logs_created_brin",
            "created_at",
            postgresql_using="brin",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, unique=True, default=uuid4
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    request_id: Mapped[str | None] = mapped_column(String(128))
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
