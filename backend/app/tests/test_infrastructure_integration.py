"""Opt-in integration checks for the real Phase 2/3 infrastructure."""

from __future__ import annotations

import os
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import delete, or_, text, update
from sqlalchemy.exc import DBAPIError

from backend.app.cache import CacheStatus, RedisCache
from backend.app.core.config import Environment, Settings
from backend.app.core.resources import create_resources
from backend.app.database import DatabaseManager
from backend.app.main import create_application
from backend.app.models import AuditLog, User

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INFRASTRUCTURE_TESTS") != "1",
        reason="set RUN_INFRASTRUCTURE_TESTS=1 after starting Compose and migrating",
    ),
]


async def test_postgres_pgvector_and_redis_round_trip() -> None:
    settings = Settings()
    database = DatabaseManager(settings)
    cache = RedisCache.from_settings(settings)

    try:
        assert await database.ping() is True
        async with database.session() as session:
            vector_version = await session.scalar(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            )
            migration_revision = await session.scalar(
                text("SELECT version_num FROM alembic_version")
            )

        assert isinstance(vector_version, str)
        assert migration_revision == "20260721_0002"
        assert await cache.ping() is True
        assert await cache.write(
            "integration:cache:phase2:none:roundtrip",
            {"phase": 2},
            soft_ttl_seconds=5,
            hard_ttl_seconds=10,
        )
        cached = await cache.read("integration:cache:phase2:none:roundtrip")
        assert cached.status is CacheStatus.HIT
        assert cached.value == {"phase": 2}
        assert await cache.delete("integration:cache:phase2:none:roundtrip")
    finally:
        await cache.close()
        await database.close()


async def _register_verify_login(
    client: AsyncClient, *, email: str
) -> tuple[UUID, str, str]:
    registration = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "Integration-Pass-42!",
            "display_name": "Integration User",
        },
    )
    assert registration.status_code == 201
    verification_token = registration.json()["test_token"]
    assert isinstance(verification_token, str)
    verification = await client.post(
        "/api/v1/auth/verify-email", json={"token": verification_token}
    )
    assert verification.status_code == 200
    user_id = UUID(verification.json()["id"])
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Integration-Pass-42!"},
    )
    assert login.status_code == 200
    return user_id, login.json()["access_token"], login.json()["refresh_token"]


async def test_identity_rotation_rate_limit_rbac_and_ownership() -> None:
    suffix = uuid4().hex[:10]
    admin_email = f"phase3-admin-{suffix}@example.com"
    owner_email = f"phase3-owner-{suffix}@example.com"
    other_email = f"phase3-other-{suffix}@example.com"
    base_settings = Settings()
    settings = Settings(
        _env_file=None,
        environment=Environment.TESTING,
        database_url=base_settings.database_url,
        migration_database_url=base_settings.migration_database_url,
        redis_url=base_settings.redis_url,
        auth_expose_test_tokens=True,
        redis_key_prefix=f"copilot:test:{suffix}",
        argon2_time_cost=1,
        argon2_memory_cost_kib=8_192,
        argon2_parallelism=1,
    )
    resources = create_resources(settings)
    application = create_application(settings, resources)
    manager = resources.database
    assert isinstance(manager, DatabaseManager)
    created_user_ids: list[UUID] = []
    test_request_id = str(uuid4())

    async with application.router.lifespan_context(application):
        transport = ASGITransport(app=application)
        async with AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers={"X-Request-ID": test_request_id},
        ) as client:
            try:
                admin_id, _, _ = await _register_verify_login(client, email=admin_email)
                created_user_ids.append(admin_id)
                async with manager.session() as session:
                    await session.execute(
                        update(User).where(User.id == admin_id).values(role="admin")
                    )
                    await session.commit()
                admin_login = await client.post(
                    "/api/v1/auth/login",
                    json={
                        "email": admin_email,
                        "password": "Integration-Pass-42!",
                    },
                )
                assert admin_login.status_code == 200
                admin_access = admin_login.json()["access_token"]

                owner_id, owner_access, owner_refresh = await _register_verify_login(
                    client, email=owner_email
                )
                other_id, other_access, _ = await _register_verify_login(
                    client, email=other_email
                )
                created_user_ids.extend([owner_id, other_id])

                other_sessions = await client.get(
                    "/api/v1/users/me/sessions",
                    headers={"Authorization": f"Bearer {other_access}"},
                )
                assert other_sessions.status_code == 200
                other_session_id = other_sessions.json()[0]["id"]
                cross_user = await client.delete(
                    f"/api/v1/users/me/sessions/{other_session_id}",
                    headers={"Authorization": f"Bearer {owner_access}"},
                )
                assert cross_user.status_code == 404

                normal_admin_read = await client.get(
                    "/api/v1/admin/users",
                    headers={"Authorization": f"Bearer {owner_access}"},
                )
                assert normal_admin_read.status_code == 403
                admin_read = await client.get(
                    "/api/v1/admin/users",
                    headers={"Authorization": f"Bearer {admin_access}"},
                )
                assert admin_read.status_code == 200

                rotated = await client.post(
                    "/api/v1/auth/refresh",
                    json={"refresh_token": owner_refresh},
                )
                assert rotated.status_code == 200
                rotated_refresh = rotated.json()["refresh_token"]
                replay = await client.post(
                    "/api/v1/auth/refresh",
                    json={"refresh_token": owner_refresh},
                )
                assert replay.status_code == 401
                family_revoked = await client.post(
                    "/api/v1/auth/refresh",
                    json={"refresh_token": rotated_refresh},
                )
                assert family_revoked.status_code == 401

                limited_email = f"limited-{suffix}@example.com"
                attempts = [
                    await client.post(
                        "/api/v1/auth/login",
                        json={"email": limited_email, "password": "wrong"},
                    )
                    for _ in range(6)
                ]
                assert all(item.status_code == 401 for item in attempts[:5])
                assert attempts[5].status_code == 429
                assert int(attempts[5].headers["retry-after"]) >= 1

                audit_read = await client.get(
                    "/api/v1/admin/audit-logs",
                    headers={"Authorization": f"Bearer {admin_access}"},
                )
                assert audit_read.status_code == 200
                assert any(
                    item["action"] == "auth.refresh_replay_detected"
                    for item in audit_read.json()
                )
                async with manager.session() as session:
                    with pytest.raises(DBAPIError):
                        await session.execute(
                            update(AuditLog)
                            .where(AuditLog.request_id == test_request_id)
                            .values(action="tampered")
                        )
                    await session.rollback()
            finally:
                migration_settings = settings.model_copy(
                    update={"database_url": SecretStr(settings.migration_database_dsn)}
                )
                cleanup_manager = DatabaseManager(migration_settings)
                try:
                    async with cleanup_manager.session() as session:
                        await session.execute(
                            delete(AuditLog).where(
                                or_(
                                    AuditLog.request_id == test_request_id,
                                    AuditLog.actor_user_id.in_(created_user_ids),
                                    AuditLog.resource_id.in_(created_user_ids),
                                )
                            )
                        )
                        if created_user_ids:
                            await session.execute(
                                delete(User).where(User.id.in_(created_user_ids))
                            )
                        await session.commit()
                finally:
                    await cleanup_manager.close()
