"""Identity use cases, refresh rotation, RBAC, ownership, and audit policy."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from backend.app.core.config import Settings
from backend.app.core.exceptions import (
    AuthenticationError,
    ConflictError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from backend.app.core.identity_security import AccessTokenClaims, IdentitySecurity
from backend.app.models import AuditLog, User, UserSession
from backend.app.repositories import IdentityRepository


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Sanitized request evidence passed into the service boundary."""

    request_id: str | None
    client_ip: str | None
    user_agent: str | None


@dataclass(frozen=True, slots=True)
class CurrentPrincipal:
    """Database-validated user/session identity for authorization decisions."""

    user: User
    session: UserSession
    claims: AccessTokenClaims


@dataclass(frozen=True, slots=True)
class TokenPair:
    """New bearer and refresh credentials returned only at authentication edges."""

    access_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime
    user: User


class IdentityService:
    """Own all Phase 3 identity state transitions and authorization checks."""

    def __init__(
        self,
        repository: IdentityRepository,
        settings: Settings,
        *,
        security: IdentitySecurity | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings
        self.security = security or IdentitySecurity(settings)
        self._clock = clock or (lambda: datetime.now(UTC))

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise TypeError("identity clock must return a datetime")
        if value.tzinfo is None:
            raise ValueError("identity clock must return an aware datetime")
        return value.astimezone(UTC)

    def _audit(
        self,
        *,
        action: str,
        resource_type: str,
        context: RequestContext,
        actor_user_id: UUID | None = None,
        resource_id: UUID | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        self.repository.add_audit(
            AuditLog(
                actor_user_id=actor_user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                request_id=context.request_id,
                ip_hash=self.security.digest_client_value(context.client_ip),
                details=details or {},
            )
        )

    async def register(
        self,
        *,
        email: str,
        password: str,
        display_name: str | None,
        context: RequestContext,
    ) -> tuple[User, str | None]:
        """Create an unverified account and a hashed single-use verification token."""
        now = self._now()
        verification_token = self.security.new_opaque_token()
        user = User(
            id=uuid4(),
            email=email,
            password_hash=self.security.hash_password(password),
            display_name=display_name,
            role="user",
            status="unverified",
            verification_token_digest=self.security.digest_token(verification_token),
            verification_token_expires_at=now
            + timedelta(hours=self.settings.email_verification_ttl_hours),
            password_changed_at=now,
            created_at=now,
            updated_at=now,
        )
        self.repository.add_user(user)
        try:
            await self.repository.session.flush()
        except IntegrityError as error:
            await self.repository.session.rollback()
            raise ConflictError("An account with this email already exists.") from error
        self._audit(
            action="auth.registered",
            resource_type="user",
            actor_user_id=user.id,
            resource_id=user.id,
            context=context,
        )
        await self.repository.session.commit()
        return user, (
            verification_token if self.settings.auth_expose_test_tokens else None
        )

    async def verify_email(self, *, token: str, context: RequestContext) -> User:
        """Consume a valid verification token once and activate the account."""
        now = self._now()
        user = await self.repository.get_user_by_verification_digest(
            self.security.digest_token(token)
        )
        if (
            user is None
            or user.verification_token_expires_at is None
            or user.verification_token_expires_at <= now
        ):
            raise AuthenticationError("The verification token is invalid or expired.")
        user.status = "active"
        user.email_verified_at = now
        user.verification_token_digest = None
        user.verification_token_expires_at = None
        user.updated_at = now
        self._audit(
            action="auth.email_verified",
            resource_type="user",
            actor_user_id=user.id,
            resource_id=user.id,
            context=context,
        )
        await self.repository.session.commit()
        return user

    async def resend_verification(
        self, *, email: str, context: RequestContext
    ) -> str | None:
        """Rotate verification material without revealing whether an email exists."""
        now = self._now()
        user = await self.repository.get_user_by_email(email, lock=True)
        token: str | None = None
        if user is not None and user.status == "unverified":
            token = self.security.new_opaque_token()
            user.verification_token_digest = self.security.digest_token(token)
            user.verification_token_expires_at = now + timedelta(
                hours=self.settings.email_verification_ttl_hours
            )
            user.updated_at = now
            self._audit(
                action="auth.verification_requested",
                resource_type="user",
                actor_user_id=user.id,
                resource_id=user.id,
                context=context,
            )
            await self.repository.session.commit()
        return token if self.settings.auth_expose_test_tokens else None

    async def login(
        self,
        *,
        email: str,
        password: str,
        context: RequestContext,
    ) -> TokenPair:
        """Verify credentials and create a new refresh-token family."""
        now = self._now()
        user = await self.repository.get_user_by_email(email, lock=True)
        password_hash = user.password_hash if user is not None else None
        if not self.security.verify_password(password_hash, password):
            self._audit(
                action="auth.login_failed",
                resource_type="user",
                actor_user_id=user.id if user is not None else None,
                resource_id=user.id if user is not None else None,
                context=context,
                details={"reason": "invalid_credentials"},
            )
            await self.repository.session.commit()
            raise AuthenticationError("The email or password is incorrect.")
        if user is None:
            raise AuthenticationError("The email or password is incorrect.")
        if user.status != "active":
            self._audit(
                action="auth.login_failed",
                resource_type="user",
                actor_user_id=user.id,
                resource_id=user.id,
                context=context,
                details={"reason": "account_unavailable"},
            )
            await self.repository.session.commit()
            raise AuthenticationError("The account is not available for login.")
        if self.security.password_needs_rehash(user.password_hash):
            user.password_hash = self.security.hash_password(password)
            user.updated_at = now
        pair = self._new_token_family(user=user, now=now, context=context)
        self._audit(
            action="auth.login_succeeded",
            resource_type="session",
            actor_user_id=user.id,
            resource_id=pair[0].id,
            context=context,
        )
        await self.repository.session.commit()
        return self._token_pair(
            user=user, user_session=pair[0], raw_refresh=pair[1], now=now
        )

    def _new_token_family(
        self, *, user: User, now: datetime, context: RequestContext
    ) -> tuple[UserSession, str]:
        raw_refresh = self.security.new_opaque_token()
        user_session = UserSession(
            id=uuid4(),
            user_id=user.id,
            token_family_id=uuid4(),
            refresh_token_digest=self.security.digest_token(raw_refresh),
            authenticated_at=now,
            created_at=now,
            last_used_at=now,
            expires_at=now + timedelta(days=self.settings.refresh_token_ttl_days),
            family_expires_at=now
            + timedelta(days=self.settings.refresh_family_ttl_days),
            ip_hash=self.security.digest_client_value(context.client_ip),
            user_agent=(context.user_agent or "")[:256] or None,
        )
        self.repository.add_session(user_session)
        return user_session, raw_refresh

    def _token_pair(
        self,
        *,
        user: User,
        user_session: UserSession,
        raw_refresh: str,
        now: datetime,
    ) -> TokenPair:
        access_token, access_expires_at = self.security.create_access_token(
            user_id=user.id,
            session_id=user_session.id,
            role=user.role,
            authenticated_at=user_session.authenticated_at,
            now=now,
        )
        return TokenPair(
            access_token=access_token,
            refresh_token=raw_refresh,
            access_expires_at=access_expires_at,
            refresh_expires_at=user_session.expires_at,
            user=user,
        )

    async def refresh(
        self, *, refresh_token: str, context: RequestContext
    ) -> TokenPair:
        """Rotate once; any reuse revokes the entire token family."""
        now = self._now()
        digest = self.security.digest_token(refresh_token)
        old_session = await self.repository.get_session_by_digest(digest, lock=True)
        if old_session is None:
            raise AuthenticationError("The refresh token is invalid or expired.")
        if old_session.revoked_at is not None:
            await self.repository.revoke_family(
                family_id=old_session.token_family_id,
                now=now,
                reason="refresh_replay",
            )
            self._audit(
                action="auth.refresh_replay_detected",
                resource_type="session_family",
                actor_user_id=old_session.user_id,
                resource_id=old_session.token_family_id,
                context=context,
            )
            await self.repository.session.commit()
            raise AuthenticationError("The refresh token is invalid or expired.")
        if old_session.expires_at <= now or old_session.family_expires_at <= now:
            await self.repository.revoke_family(
                family_id=old_session.token_family_id,
                now=now,
                reason="expired",
            )
            await self.repository.session.commit()
            raise AuthenticationError("The refresh token is invalid or expired.")
        user = await self.repository.get_user_by_id(old_session.user_id, lock=True)
        if user is None or user.status != "active":
            await self.repository.revoke_family(
                family_id=old_session.token_family_id,
                now=now,
                reason="account_unavailable",
            )
            await self.repository.session.commit()
            raise AuthenticationError("The refresh token is invalid or expired.")

        raw_refresh = self.security.new_opaque_token()
        new_session = UserSession(
            id=uuid4(),
            user_id=user.id,
            token_family_id=old_session.token_family_id,
            refresh_token_digest=self.security.digest_token(raw_refresh),
            parent_session_id=old_session.id,
            authenticated_at=old_session.authenticated_at,
            created_at=now,
            last_used_at=now,
            expires_at=min(
                now + timedelta(days=self.settings.refresh_token_ttl_days),
                old_session.family_expires_at,
            ),
            family_expires_at=old_session.family_expires_at,
            ip_hash=self.security.digest_client_value(context.client_ip),
            user_agent=(context.user_agent or "")[:256] or None,
        )
        old_session.revoked_at = now
        old_session.revocation_reason = "rotated"
        old_session.last_used_at = now
        await self.repository.session.flush()
        self.repository.add_session(new_session)
        await self.repository.session.flush()
        old_session.replaced_by_session_id = new_session.id
        self._audit(
            action="auth.refresh_rotated",
            resource_type="session",
            actor_user_id=user.id,
            resource_id=new_session.id,
            context=context,
            details={"family_id": str(new_session.token_family_id)},
        )
        await self.repository.session.commit()
        return self._token_pair(
            user=user,
            user_session=new_session,
            raw_refresh=raw_refresh,
            now=now,
        )

    async def authenticate_access(self, access_token: str) -> CurrentPrincipal:
        """Validate JWT claims against current durable user and session state."""
        now = self._now()
        claims = self.security.decode_access_token(access_token)
        record = await self.repository.get_session_and_user(
            claims.session_id, claims.user_id
        )
        if record is None:
            raise AuthenticationError("The access token is invalid or expired.")
        user_session, user = record
        if (
            user.status != "active"
            or user.role != claims.role
            or user_session.revoked_at is not None
            or user_session.expires_at <= now
            or user_session.family_expires_at <= now
        ):
            raise AuthenticationError("The access token is invalid or expired.")
        return CurrentPrincipal(user=user, session=user_session, claims=claims)

    async def logout(self, *, refresh_token: str, context: RequestContext) -> None:
        """Revoke the session family identified by a refresh token."""
        now = self._now()
        user_session = await self.repository.get_session_by_digest(
            self.security.digest_token(refresh_token), lock=True
        )
        if user_session is not None:
            await self.repository.revoke_family(
                family_id=user_session.token_family_id,
                now=now,
                reason="logout",
            )
            self._audit(
                action="auth.logout",
                resource_type="session_family",
                actor_user_id=user_session.user_id,
                resource_id=user_session.token_family_id,
                context=context,
            )
            await self.repository.session.commit()

    async def logout_all(
        self, *, principal: CurrentPrincipal, context: RequestContext
    ) -> int:
        """Revoke every active session owned by the current user."""
        count = await self.repository.revoke_all_for_user(
            user_id=principal.user.id,
            now=self._now(),
            reason="logout_all",
        )
        self._audit(
            action="auth.logout_all",
            resource_type="user",
            actor_user_id=principal.user.id,
            resource_id=principal.user.id,
            context=context,
            details={"revoked_sessions": count},
        )
        await self.repository.session.commit()
        return count

    async def request_password_reset(
        self, *, email: str, context: RequestContext
    ) -> str | None:
        """Rotate reset material while keeping the public result non-enumerating."""
        now = self._now()
        user = await self.repository.get_user_by_email(email, lock=True)
        token: str | None = None
        if user is not None and user.status != "disabled":
            token = self.security.new_opaque_token()
            user.password_reset_token_digest = self.security.digest_token(token)
            user.password_reset_token_expires_at = now + timedelta(
                minutes=self.settings.password_reset_ttl_minutes
            )
            user.updated_at = now
            self._audit(
                action="auth.password_reset_requested",
                resource_type="user",
                actor_user_id=user.id,
                resource_id=user.id,
                context=context,
            )
            await self.repository.session.commit()
        return token if self.settings.auth_expose_test_tokens else None

    async def confirm_password_reset(
        self, *, token: str, new_password: str, context: RequestContext
    ) -> None:
        """Consume reset material, replace the hash, and revoke every session."""
        now = self._now()
        user = await self.repository.get_user_by_reset_digest(
            self.security.digest_token(token)
        )
        if (
            user is None
            or user.password_reset_token_expires_at is None
            or user.password_reset_token_expires_at <= now
        ):
            raise AuthenticationError("The password reset token is invalid or expired.")
        user.password_hash = self.security.hash_password(new_password)
        user.password_changed_at = now
        user.password_reset_token_digest = None
        user.password_reset_token_expires_at = None
        user.updated_at = now
        revoked = await self.repository.revoke_all_for_user(
            user_id=user.id, now=now, reason="password_reset"
        )
        self._audit(
            action="auth.password_reset_completed",
            resource_type="user",
            actor_user_id=user.id,
            resource_id=user.id,
            context=context,
            details={"revoked_sessions": revoked},
        )
        await self.repository.session.commit()

    async def update_profile(
        self,
        *,
        principal: CurrentPrincipal,
        display_name: str | None,
        context: RequestContext,
    ) -> User:
        """Update the small owner-editable profile surface."""
        principal.user.display_name = display_name
        principal.user.updated_at = self._now()
        self._audit(
            action="user.profile_updated",
            resource_type="user",
            actor_user_id=principal.user.id,
            resource_id=principal.user.id,
            context=context,
        )
        await self.repository.session.commit()
        return principal.user

    async def list_sessions(self, *, principal: CurrentPrincipal) -> list[UserSession]:
        """List only sessions owned by the authenticated user."""
        return await self.repository.list_active_sessions(
            owner_user_id=principal.user.id, now=self._now()
        )

    async def revoke_owned_session(
        self,
        *,
        principal: CurrentPrincipal,
        session_id: UUID,
        context: RequestContext,
    ) -> None:
        """Enforce ownership in the query before revoking a selected family."""
        user_session = await self.repository.get_owned_session(
            session_id=session_id,
            owner_user_id=principal.user.id,
            lock=True,
        )
        if user_session is None:
            raise ResourceNotFoundError("The requested session was not found.")
        await self.repository.revoke_family(
            family_id=user_session.token_family_id,
            now=self._now(),
            reason="owner_revoked",
        )
        self._audit(
            action="auth.session_revoked",
            resource_type="session",
            actor_user_id=principal.user.id,
            resource_id=user_session.id,
            context=context,
        )
        await self.repository.session.commit()

    @staticmethod
    def require_admin(principal: CurrentPrincipal) -> None:
        """Require the current durable role rather than trusting UI visibility."""
        if principal.user.role != "admin":
            raise PermissionDeniedError("Administrator access is required.")

    def require_fresh_auth(self, principal: CurrentPrincipal) -> None:
        """Require recent primary authentication for sensitive admin changes."""
        age = self._now() - principal.session.authenticated_at.astimezone(UTC)
        if age > timedelta(minutes=self.settings.fresh_auth_ttl_minutes):
            raise AuthenticationError("Fresh authentication is required.")

    async def admin_update_user(
        self,
        *,
        principal: CurrentPrincipal,
        target_user_id: UUID,
        role: str | None,
        status: str | None,
        context: RequestContext,
    ) -> User:
        """Apply an audited role/status change with a self-lockout guard."""
        self.require_admin(principal)
        self.require_fresh_auth(principal)
        target = await self.repository.get_user_by_id(target_user_id, lock=True)
        if target is None:
            raise ResourceNotFoundError("The requested user was not found.")
        if target.id == principal.user.id and (role == "user" or status == "disabled"):
            raise ConflictError("An administrator cannot remove their own access.")
        changes: dict[str, object] = {}
        if role is not None and role != target.role:
            changes["role"] = {"from": target.role, "to": role}
            target.role = role
        if status is not None and status != target.status:
            changes["status"] = {"from": target.status, "to": status}
            target.status = status
        target.updated_at = self._now()
        if changes:
            await self.repository.revoke_all_for_user(
                user_id=target.id,
                now=self._now(),
                reason="admin_account_change",
            )
        self._audit(
            action="admin.user_updated",
            resource_type="user",
            actor_user_id=principal.user.id,
            resource_id=target.id,
            context=context,
            details={"changes": changes},
        )
        await self.repository.session.commit()
        return target

    async def admin_list_users(
        self, *, principal: CurrentPrincipal, limit: int, offset: int
    ) -> list[User]:
        """Return a bounded sanitized user catalog to administrators only."""
        self.require_admin(principal)
        return await self.repository.list_users(limit=limit, offset=offset)

    async def admin_list_audits(
        self, *, principal: CurrentPrincipal, limit: int, offset: int
    ) -> list[AuditLog]:
        """Return append-only security evidence to administrators only."""
        self.require_admin(principal)
        return await self.repository.list_audits(limit=limit, offset=offset)
