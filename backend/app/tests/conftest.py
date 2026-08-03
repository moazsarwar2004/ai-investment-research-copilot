"""Shared test application and HTTP client fixtures."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pytest_asyncio import fixture as async_fixture

from backend.app.core.config import Environment, LogFormat, Settings
from backend.app.core.resources import ApplicationResources
from backend.app.main import create_application

_FIXTURE_DIRECTORY = Path(__file__).with_name("fixtures")


class StubHealthResource:
    """Deterministic dependency health and lifecycle test double."""

    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.closed = False

    async def ping(self) -> bool:
        return self.available

    async def close(self) -> None:
        self.closed = True


class StubCloseResource:
    """Lifecycle-only test double for the provider HTTP pool."""

    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def binance_payloads() -> dict[str, Any]:
    """Load recorded-shape Binance payloads without making a live request."""
    fixture_path = _FIXTURE_DIRECTORY / "binance_spot_payloads.json"
    payload: object = json.loads(fixture_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("Binance fixture root must be an object")
    return payload


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
def provider_http_resource() -> StubCloseResource:
    """Return a provider HTTP lifecycle test double."""
    return StubCloseResource()


@pytest.fixture
def resources(
    database_resource: StubHealthResource,
    cache_resource: StubHealthResource,
    provider_http_resource: StubCloseResource,
) -> ApplicationResources:
    """Inject deterministic infrastructure into the application factory."""
    return ApplicationResources(
        database=database_resource,
        cache=cache_resource,
        provider_http=provider_http_resource,
    )


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
