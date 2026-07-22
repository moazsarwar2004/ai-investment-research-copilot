"""Shared test application and HTTP client fixtures."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pytest_asyncio import fixture as async_fixture

from backend.app.core.config import Environment, LogFormat, Settings
from backend.app.core.resources import ApplicationResources
from backend.app.main import create_application


class StubHealthResource:
    """Deterministic dependency health and lifecycle test double."""

    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.closed = False

    async def ping(self) -> bool:
        return self.available

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def test_settings() -> Settings:
    """Return deterministic settings without reading a developer's .env file."""
    return Settings(
        _env_file=None,
        environment=Environment.TESTING,
        debug=False,
        log_format=LogFormat.JSON,
        allowed_origins="http://localhost:8501",
        argon2_time_cost=1,
        argon2_memory_cost_kib=8_192,
        argon2_parallelism=1,
    )


@pytest.fixture
def database_resource() -> StubHealthResource:
    """Return a healthy durable-store test double."""
    return StubHealthResource()


@pytest.fixture
def cache_resource() -> StubHealthResource:
    """Return a healthy disposable-cache test double."""
    return StubHealthResource()


@pytest.fixture
def resources(
    database_resource: StubHealthResource,
    cache_resource: StubHealthResource,
) -> ApplicationResources:
    """Inject deterministic infrastructure into the application factory."""
    return ApplicationResources(database=database_resource, cache=cache_resource)


@pytest.fixture
def application(
    test_settings: Settings,
    resources: ApplicationResources,
) -> FastAPI:
    """Build an isolated application instance for each test."""
    return create_application(test_settings, resources)


@async_fixture
async def client(application: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Run lifespan hooks while the test client is active."""
    async with application.router.lifespan_context(application):
        transport = ASGITransport(app=application)
        async with AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as test_client:
            yield test_client
