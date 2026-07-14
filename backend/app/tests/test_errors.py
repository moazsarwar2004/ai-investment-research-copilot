"""Safe and consistent exception handling tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pytest_asyncio import fixture as async_fixture

from backend.app.core.exceptions import ResourceNotFoundError


@async_fixture
async def error_client(application: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    @application.get("/_test/expected")
    async def expected_error() -> None:
        raise ResourceNotFoundError("The requested company was not found.")

    @application.get("/_test/unexpected")
    async def unexpected_error() -> None:
        raise RuntimeError("PRIVATE_MARKER database-password=/server/secret")

    async with application.router.lifespan_context(application):
        transport = ASGITransport(app=application, raise_app_exceptions=False)
        async with AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as test_client:
            yield test_client


async def test_expected_application_error_uses_standard_contract(
    error_client: AsyncClient,
) -> None:
    response = await error_client.get("/_test/expected")
    payload = response.json()

    assert response.status_code == 404
    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["errors"] == [
        {
            "code": "RESOURCE_NOT_FOUND",
            "message": "The requested company was not found.",
        }
    ]
    assert payload["meta"]["request_id"] == response.headers["X-Request-ID"]


async def test_unexpected_error_never_leaks_exception_details(
    error_client: AsyncClient,
) -> None:
    response = await error_client.get("/_test/unexpected")
    rendered = response.text

    assert response.status_code == 500
    assert response.json()["errors"] == [
        {
            "code": "INTERNAL_SERVER_ERROR",
            "message": "An unexpected error occurred.",
        }
    ]
    assert "PRIVATE_MARKER" not in rendered
    assert "database-password" not in rendered
    assert "RuntimeError" not in rendered
    assert "Traceback" not in rendered


async def test_unknown_route_uses_standard_contract(client: AsyncClient) -> None:
    response = await client.get("/does-not-exist")
    payload = response.json()

    assert response.status_code == 404
    assert payload["errors"][0] == {
        "code": "RESOURCE_NOT_FOUND",
        "message": "The requested resource was not found.",
    }
    assert payload["meta"]["request_id"] == response.headers["X-Request-ID"]
