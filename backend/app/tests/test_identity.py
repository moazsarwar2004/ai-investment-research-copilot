"""Phase 3 identity security, rotation, ownership, RBAC, and rate-limit tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.dependencies import get_identity_service
from backend.app.core.config import Environment, Settings
from backend.app.core.exceptions import (
    AuthenticationError,
    ConflictError,
    PermissionDeniedError,
    RateLimitExceededError,
    ResourceNotFoundError,
)
from backend.app.core.identity_security import IdentitySecurity
from backend.app.core.rate_limits import AuthRateLimiter
from backend.app.models import AuditLog, User, UserSession
from backend.app.repositories import IdentityRepository
from backend.app.services import IdentityService, RequestContext


class FakeSession:
    """Minimal transaction boundary for the in-memory identity repository."""

    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class MemoryIdentityRepository(IdentityRepository):
    """Behavioral repository double preserving every rotated token generation."""

    def __init__(self) -> None:
        self.session = cast(AsyncSession, FakeSession())
        self.users: dict[UUID, User] = {}
        self.sessions: dict[UUID, UserSession] = {}
        self.audits: list[AuditLog] = []

    async def get_user_by_email(self, email: str, *, lock: bool = False) -> User | None:
        del lock
        return next((item for item in self.users.values() if item.email == email), None)

    async def get_user_by_id(self, user_id: UUID, *, lock: bool = False) -> User | None:
        del lock
        return self.users.get(user_id)

    async def get_user_by_verification_digest(self, digest: str) -> User | None:
        return next(
            (
                item
                for item in self.users.values()
                if item.verification_token_digest == digest
            ),
            None,
        )

    async def get_user_by_reset_digest(self, digest: str) -> User | None:
        return next(
            (
                item
                for item in self.users.values()
                if item.password_reset_token_digest == digest
            ),
            None,
        )

    def add_user(self, user: User) -> None:
        self.users[user.id] = user

    def add_session(self, user_session: UserSession) -> None:
        self.sessions[user_session.id] = user_session

    async def get_session_by_digest(
        self, digest: str, *, lock: bool = False
    ) -> UserSession | None:
        del lock
        return next(
            (
                item
                for item in self.sessions.values()
                if item.refresh_token_digest == digest
            ),
            None,
        )

    async def get_session_and_user(
        self, session_id: UUID, user_id: UUID
    ) -> tuple[UserSession, User] | None:
        user_session = self.sessions.get(session_id)
        user = self.users.get(user_id)
        if user_session is None or user is None or user_session.user_id != user_id:
            return None
        return user_session, user

    async def get_owned_session(
        self, *, session_id: UUID, owner_user_id: UUID, lock: bool = False
    ) -> UserSession | None:
        del lock
        user_session = self.sessions.get(session_id)
        if user_session is None or user_session.user_id != owner_user_id:
            return None
        return user_session

    async def list_active_sessions(
        self, *, owner_user_id: UUID, now: datetime
    ) -> list[UserSession]:
        return [
            item
            for item in self.sessions.values()
            if item.user_id == owner_user_id
            and item.revoked_at is None
            and item.expires_at > now
            and item.family_expires_at > now
        ]

    async def revoke_family(
        self, *, family_id: UUID, now: datetime, reason: str
    ) -> int:
        count = 0
        for item in self.sessions.values():
            if item.token_family_id == family_id and item.revoked_at is None:
                item.revoked_at = now
                item.revocation_reason = reason
                count += 1
        return count

    async def revoke_all_for_user(
        self, *, user_id: UUID, now: datetime, reason: str
    ) -> int:
        count = 0
        for item in self.sessions.values():
            if item.user_id == user_id and item.revoked_at is None:
                item.revoked_at = now
                item.revocation_reason = reason
                count += 1
        return count

    def add_audit(self, audit: AuditLog) -> None:
        self.audits.append(audit)

    async def list_users(self, *, limit: int, offset: int) -> list[User]:
        return list(self.users.values())[offset : offset + limit]

    async def list_audits(self, *, limit: int, offset: int) -> list[AuditLog]:
        return self.audits[offset : offset + limit]


def identity_settings(
    *,
    auth_rate_limit_attempts: int = 5,
    auth_rate_limit_window_seconds: int = 900,
) -> Settings:
    """Return explicit test-only identity settings."""
    return Settings(
        _env_file=None,
        environment=Environment.TESTING,
        auth_expose_test_tokens=True,
        auth_rate_limit_attempts=auth_rate_limit_attempts,
        auth_rate_limit_window_seconds=auth_rate_limit_window_seconds,
        argon2_time_cost=1,
        argon2_memory_cost_kib=8_192,
        argon2_parallelism=1,
    )


def service_fixture() -> (
    tuple[IdentityService, MemoryIdentityRepository, list[datetime], RequestContext]
):
    """Build a deterministic in-memory identity boundary."""
    clock = [datetime.now(UTC)]
    repository = MemoryIdentityRepository()
    service = IdentityService(
        repository,
        identity_settings(),
        clock=lambda: clock[0],
    )
    context = RequestContext(
        request_id="phase-3-test",
        client_ip="127.0.0.1",
        user_agent="pytest",
    )
    return service, repository, clock, context


async def create_active_login(
    service: IdentityService,
    *,
    email: str,
    context: RequestContext,
) -> tuple[User, str, str]:
    """Register, verify, and log in one deterministic test account."""
    password = "Correct-Horse-42!"
    user, verification_token = await service.register(
        email=email,
        password=password,
        display_name="Phase Three",
        context=context,
    )
    assert verification_token is not None
    await service.verify_email(token=verification_token, context=context)
    pair = await service.login(email=email, password=password, context=context)
    return user, pair.access_token, pair.refresh_token


def test_password_and_token_primitives_are_one_way_and_typed() -> None:
    settings = identity_settings()
    security = IdentitySecurity(settings)
    password = "Correct-Horse-42!"
    password_hash = security.hash_password(password)
    opaque = security.new_opaque_token()
    digest = security.digest_token(opaque)

    assert password_hash.startswith("$argon2id$")
    assert security.verify_password(password_hash, password) is True
    assert security.verify_password(password_hash, "wrong") is False
    assert opaque not in digest
    assert len(digest) == 64


async def test_refresh_rotation_and_replay_revoke_the_entire_family() -> None:
    service, repository, _, context = service_fixture()
    user, _, first_refresh = await create_active_login(
        service, email="rotation@example.com", context=context
    )

    rotated = await service.refresh(refresh_token=first_refresh, context=context)

    with pytest.raises(AuthenticationError):
        await service.refresh(refresh_token=first_refresh, context=context)
    with pytest.raises(AuthenticationError):
        await service.refresh(refresh_token=rotated.refresh_token, context=context)

    family_sessions = [
        item for item in repository.sessions.values() if item.user_id == user.id
    ]
    assert len(family_sessions) == 2
    assert all(item.revoked_at is not None for item in family_sessions)
    assert any(
        item.action == "auth.refresh_replay_detected" for item in repository.audits
    )


async def test_owner_predicate_and_admin_role_are_enforced() -> None:
    service, repository, _, context = service_fixture()
    first_user, first_access, _ = await create_active_login(
        service, email="owner@example.com", context=context
    )
    _, second_access, _ = await create_active_login(
        service, email="other@example.com", context=context
    )
    first_principal = await service.authenticate_access(first_access)
    second_principal = await service.authenticate_access(second_access)

    with pytest.raises(ResourceNotFoundError):
        await service.revoke_owned_session(
            principal=first_principal,
            session_id=second_principal.session.id,
            context=context,
        )
    with pytest.raises(PermissionDeniedError):
        service.require_admin(first_principal)

    first_user.role = "admin"
    with pytest.raises(ConflictError):
        await service.admin_update_user(
            principal=first_principal,
            target_user_id=first_user.id,
            role="user",
            status=None,
            context=context,
        )
    assert second_principal.session.revoked_at is None
    assert repository.sessions[second_principal.session.id].user_id != first_user.id


async def test_password_reset_is_single_use_and_revokes_sessions() -> None:
    service, _, _, context = service_fixture()
    _, access_token, _ = await create_active_login(
        service, email="reset@example.com", context=context
    )
    reset_token = await service.request_password_reset(
        email="reset@example.com", context=context
    )
    assert reset_token is not None

    await service.confirm_password_reset(
        token=reset_token,
        new_password="Replacement-Pass-84!",
        context=context,
    )

    with pytest.raises(AuthenticationError):
        await service.authenticate_access(access_token)
    with pytest.raises(AuthenticationError):
        await service.confirm_password_reset(
            token=reset_token,
            new_password="Another-Replacement-12!",
            context=context,
        )


async def test_auth_rate_limit_returns_retry_window() -> None:
    settings = identity_settings(
        auth_rate_limit_attempts=2,
        auth_rate_limit_window_seconds=60,
    )
    limiter = AuthRateLimiter(settings, None)

    await limiter.check("same-ip-and-identity")
    await limiter.check("same-ip-and-identity")

    with pytest.raises(RateLimitExceededError) as captured:
        await limiter.check("same-ip-and-identity")
    assert 1 <= captured.value.retry_after_seconds <= 60


class RejectingLoginService:
    """API double used to prove throttling occurs before repeated auth work."""

    def __init__(self, settings: Settings) -> None:
        self.security = IdentitySecurity(settings)

    async def login(self, **_: object) -> None:
        raise AuthenticationError("The email or password is incorrect.")


async def test_login_route_returns_429_and_retry_after(
    application: FastAPI,
    client: AsyncClient,
    test_settings: Settings,
) -> None:
    fake = RejectingLoginService(test_settings)

    def override_service() -> IdentityService:
        return cast(IdentityService, fake)

    application.dependency_overrides[get_identity_service] = override_service
    payload = {"email": "limited@example.com", "password": "wrong"}

    responses = [
        await client.post("/api/v1/auth/login", json=payload) for _ in range(6)
    ]

    assert all(item.status_code == 401 for item in responses[:5])
    assert responses[0].headers["www-authenticate"] == "Bearer"
    assert responses[5].status_code == 429
    assert int(responses[5].headers["retry-after"]) >= 1
