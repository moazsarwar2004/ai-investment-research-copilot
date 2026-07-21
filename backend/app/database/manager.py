"""Bounded async database connections and request-scoped sessions."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from fastapi import Request
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.app.core.config import Settings
from backend.app.core.logger import get_logger

logger = get_logger(__name__)


class DatabaseManager:
    """Own one async engine and create isolated sessions per unit of work."""

    def __init__(self, settings: Settings) -> None:
        self._probe_timeout_seconds = settings.database_probe_timeout_seconds
        self._probe_task: asyncio.Task[bool] | None = None
        self._engine: AsyncEngine = create_async_engine(
            settings.database_dsn,
            pool_pre_ping=True,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_timeout=settings.database_pool_timeout_seconds,
            pool_recycle=settings.database_pool_recycle_seconds,
            connect_args={
                "timeout": settings.database_connect_timeout_seconds,
                "command_timeout": settings.database_command_timeout_seconds,
            },
        )
        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
        self._probe_engine: AsyncEngine = create_async_engine(
            settings.database_dsn,
            poolclass=pool.NullPool,
            connect_args={
                "timeout": settings.database_connect_timeout_seconds,
                "command_timeout": settings.database_command_timeout_seconds,
            },
        )

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Yield a session without hiding transaction commit decisions."""
        async with self._session_factory() as session:
            yield session

    async def ping(self) -> bool:
        """Run a database round trip without exceeding the readiness deadline."""
        probe = self._probe_task
        if probe is None or probe.done():
            probe = asyncio.create_task(self._execute_ping())
            probe.add_done_callback(_consume_probe_result)
            self._probe_task = probe
        done, _ = await asyncio.wait({probe}, timeout=self._probe_timeout_seconds)
        if probe not in done:
            logger.warning(
                "database_probe_timed_out",
                extra={"exception_type": "TimeoutError"},
            )
            return False

        try:
            return probe.result()
        except Exception as error:
            logger.warning(
                "database_probe_failed",
                extra={"exception_type": type(error).__name__},
            )
            return False

    async def _execute_ping(self) -> bool:
        """Probe through a no-pool engine so stale app connections cannot delay it."""
        async with self._probe_engine.connect() as connection:
            result = await connection.execute(text("SELECT 1"))
            return cast(int, result.scalar_one()) == 1

    async def close(self) -> None:
        """Dispose pooled connections during application shutdown."""
        await asyncio.gather(self._probe_engine.dispose(), self._engine.dispose())


def _consume_probe_result(probe: asyncio.Task[bool]) -> None:
    """Retrieve late probe results so no task exception is orphaned."""
    try:
        probe.result()
    except asyncio.CancelledError:
        return
    except Exception:
        return


async def get_database_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields one request-scoped database session."""
    manager = getattr(request.app.state, "database_manager", None)
    if not isinstance(manager, DatabaseManager):
        raise RuntimeError("Database manager is unavailable")
    async with manager.session() as session:
        yield session
