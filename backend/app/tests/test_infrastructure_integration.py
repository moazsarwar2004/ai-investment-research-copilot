"""Opt-in integration checks for the real Phase 2 services."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text

from backend.app.cache import CacheStatus, RedisCache
from backend.app.core.config import Settings
from backend.app.database import DatabaseManager

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
        assert migration_revision == "20260715_0001"
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
