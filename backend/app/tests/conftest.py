"""Shared test application and HTTP client fixtures."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pytest_asyncio import fixture as async_fixture

from backend.app.core.config import Environment, LogFormat, Settings
from backend.app.main import create_application


@pytest.fixture
def test_settings() -> Settings:
    """Return deterministic settings without reading a developer's .env file."""
    return Settings(
        _env_file=None,
        environment=Environment.TESTING,
        debug=False,
        log_format=LogFormat.JSON,
        allowed_origins="http://localhost:8501",
    )


@pytest.fixture
def application(test_settings: Settings) -> FastAPI:
    """Build an isolated application instance for each test."""
    return create_application(test_settings)


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
