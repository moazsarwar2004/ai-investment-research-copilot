"""Health, metadata, and documentation endpoint tests."""

from __future__ import annotations

from datetime import datetime

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_root_returns_service_metadata(client: AsyncClient) -> None:
    response = await client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "service": "AI Investment Research Co-Pilot",
        "version": "0.1.0",
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
        "version": "0.1.0",
    }


async def test_readiness_checks_startup_and_configuration(client: AsyncClient) -> None:
    response = await client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"application": "ok", "configuration": "ok"},
    }


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
    assert payload["version"] == "0.1.0"
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
    assert response.json()["info"]["version"] == "0.1.0"
