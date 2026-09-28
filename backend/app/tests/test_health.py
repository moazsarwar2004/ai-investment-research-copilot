"""Health, metadata, and documentation endpoint tests."""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend import __version__
from backend.app.core.config import Settings
from backend.app.core.resources import ApplicationResources
from backend.app.main import create_application
from backend.app.tests.conftest import StubCloseResource, StubHealthResource

pytestmark = pytest.mark.asyncio


async def test_root_returns_service_metadata(client: AsyncClient) -> None:
    response = await client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "service": "AI Investment Research Co-Pilot",
        "version": __version__,
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
        "version": __version__,
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
    provider_http_resource: StubCloseResource,
) -> None:
    async with application.router.lifespan_context(application):
        started_during_lifespan = application.state.started

    started_after_lifespan = application.state.started

    assert started_during_lifespan is True
    assert started_after_lifespan is False
    assert database_resource.closed is True
    assert cache_resource.closed is True
    assert provider_http_resource.closed is True


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
    assert payload["version"] == __version__
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
    assert response.json()["info"]["version"] == __version__


async def test_metrics_use_route_templates_without_asset_labels(
    client: AsyncClient,
) -> None:
    research = await client.get(
        "/api/v1/stocks/OGDC/research",
        params={"exchange": "PSX", "interval": "1d", "days": 365},
    )
    response = await client.get("/metrics")

    assert research.status_code == 200
    assert response.status_code == 200
    assert "copilot_http_requests_total" in response.text
    assert 'route="/api/v1/stocks/{symbol}/research"' in response.text
    assert "OGDC" not in response.text


async def test_global_api_rate_limit_exempts_health_probes(
    test_settings: Settings,
    resources: ApplicationResources,
) -> None:
    settings = test_settings.model_copy(
        update={
            "api_rate_limit_requests": 2,
            "api_rate_limit_window_seconds": 60,
        }
    )
    application = create_application(settings, resources)
    async with (
        application.router.lifespan_context(application),
        AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://testserver",
        ) as limited_client,
    ):
        first = await limited_client.get("/api/v1/health")
        second = await limited_client.get("/api/v1/health")
        limited = await limited_client.get("/api/v1/health")
        live = await limited_client.get("/livez")

    assert first.status_code == second.status_code == 200
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) >= 1
    assert live.status_code == 200
