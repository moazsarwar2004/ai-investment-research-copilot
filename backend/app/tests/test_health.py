"""Health, metadata, and documentation endpoint tests."""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from backend.app.tests.conftest import StubHealthResource

pytestmark = pytest.mark.asyncio


async def test_root_returns_service_metadata(client: AsyncClient) -> None:
    response = await client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "service": "AI Investment Research Co-Pilot",
        "version": "0.2.0",
        "environment": "testing",
        "documentation": "/docs",
        "health": "/api/v1/health",
    }


async def test_liveness_is_minimal_and_available(client: AsyncClient) -> None:
    response = await client.get("/livez")

    assert response.status_code == 200
    assert response.json() == {
        "status": "alive",
        "service": "AI Investment Research Co-Pilot",
        "version": "0.2.0",
    }


async def test_readiness_checks_startup_and_configuration(client: AsyncClient) -> None:
    response = await client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {
            "application": "ok",
            "configuration": "ok",
            "database": "ok",
            "redis": "ok",
        },
    }


async def test_readiness_degrades_without_redis(
    client: AsyncClient,
    cache_resource: StubHealthResource,
) -> None:
    cache_resource.available = False

    response = await client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["checks"]["database"] == "ok"
    assert response.json()["checks"]["redis"] == "degraded"


async def test_readiness_fails_without_database(
    client: AsyncClient,
    database_resource: StubHealthResource,
) -> None:
    database_resource.available = False

    response = await client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {
            "application": "ok",
            "configuration": "ok",
            "database": "error",
            "redis": "ok",
        },
    }


async def test_liveness_never_fans_out_to_dependencies(
    client: AsyncClient,
    database_resource: StubHealthResource,
    cache_resource: StubHealthResource,
) -> None:
    database_resource.available = False
    cache_resource.available = False

    response = await client.get("/livez")

    assert response.status_code == 200
    assert response.json()["status"] == "alive"


async def test_lifespan_closes_infrastructure_resources(
    application: FastAPI,
    database_resource: StubHealthResource,
    cache_resource: StubHealthResource,
) -> None:
    async with application.router.lifespan_context(application):
        started_during_lifespan = application.state.started

    started_after_lifespan = application.state.started

    assert started_during_lifespan is True
    assert started_after_lifespan is False
    assert database_resource.closed is True
    assert cache_resource.closed is True


async def test_versioned_health_has_utc_timestamp(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    payload = response.json()

    assert response.status_code == 200
    assert set(payload) == {
        "status",
        "service",
        "version",
        "environment",
        "timestamp",
    }
    assert payload["status"] == "healthy"
    assert payload["service"] == "AI Investment Research Co-Pilot"
    assert payload["version"] == "0.2.0"
    assert payload["environment"] == "testing"
    assert datetime.fromisoformat(payload["timestamp"]).utcoffset() is not None
    rendered = response.text.lower()
    for sensitive_term in ("password", "secret", "token", "filesystem", "traceback"):
        assert sensitive_term not in rendered


async def test_openapi_is_available_when_docs_are_enabled(
    client: AsyncClient,
) -> None:
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["version"] == "0.2.0"
