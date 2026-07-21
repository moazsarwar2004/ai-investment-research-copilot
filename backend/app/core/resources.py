"""Lifecycle-owned infrastructure resources and injectable health contracts."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from backend.app.cache import RedisCache
from backend.app.core.config import Settings
from backend.app.core.logger import get_logger
from backend.app.database import DatabaseManager

logger = get_logger(__name__)


class HealthResource(Protocol):
    """Minimal lifecycle and readiness behavior for an infrastructure client."""

    async def ping(self) -> bool: ...

    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ApplicationResources:
    """Infrastructure clients shared by one application instance."""

    database: HealthResource
    cache: HealthResource

    async def close(self) -> None:
        """Close all clients even when one shutdown path fails."""
        results = await asyncio.gather(
            self.cache.close(),
            self.database.close(),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                logger.warning(
                    "infrastructure_close_failed",
                    extra={"exception_type": type(result).__name__},
                )


def create_resources(settings: Settings) -> ApplicationResources:
    """Create lazy infrastructure clients from validated settings."""
    return ApplicationResources(
        database=DatabaseManager(settings),
        cache=RedisCache.from_settings(settings),
    )
