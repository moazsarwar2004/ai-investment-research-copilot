"""Database readiness deadline tests independent of a live database."""

from __future__ import annotations

import asyncio

from backend.app.database import DatabaseManager


class SlowDatabaseManager(DatabaseManager):
    """Probe double that ignores availability longer than the allowed deadline."""

    def __init__(self) -> None:
        self._probe_timeout_seconds = 0.01
        self._probe_task = None

    async def _execute_ping(self) -> bool:
        await asyncio.sleep(60)
        return True


async def test_database_probe_returns_false_at_hard_deadline() -> None:
    manager = SlowDatabaseManager()

    result = await asyncio.wait_for(manager.ping(), timeout=0.25)

    assert result is False

    second_result = await asyncio.wait_for(manager.ping(), timeout=0.25)

    assert second_result is False
    assert manager._probe_task is not None
    assert manager._probe_task.done() is False
    manager._probe_task.cancel()
    await asyncio.sleep(0)
