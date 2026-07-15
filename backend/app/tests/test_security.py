"""Security header and browser-origin policy tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_security_headers_are_present(client: AsyncClient) -> None:
    response = await client.get("/livez")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert response.headers["Permissions-Policy"] == (
        "camera=(), microphone=(), geolocation=()"
    )
    assert "Strict-Transport-Security" not in response.headers


async def test_allowed_origin_receives_cors_headers(client: AsyncClient) -> None:
    response = await client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:8501",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Request-ID",
        },
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == ("http://localhost:8501")
    assert response.headers["X-Request-ID"]


async def test_unlisted_origin_does_not_receive_allow_origin(
    client: AsyncClient,
) -> None:
    response = await client.get(
        "/api/v1/health", headers={"Origin": "https://attacker.example"}
    )

    assert response.status_code == 200
    assert "Access-Control-Allow-Origin" not in response.headers
