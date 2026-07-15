"""Request correlation behavior tests."""

from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_missing_request_id_is_generated(client: AsyncClient) -> None:
    response = await client.get("/livez")

    assert response.status_code == 200
    assert (
        str(UUID(response.headers["X-Request-ID"])) == response.headers["X-Request-ID"]
    )


async def test_valid_caller_request_id_is_preserved(client: AsyncClient) -> None:
    request_id = "1c35a02e-5261-4e8c-a50e-32b6b47fd167"

    response = await client.get("/livez", headers={"X-Request-ID": request_id})

    assert response.headers["X-Request-ID"] == request_id


async def test_invalid_request_id_is_replaced(client: AsyncClient) -> None:
    response = await client.get(
        "/does-not-exist", headers={"X-Request-ID": "not-a-valid-uuid"}
    )
    returned = response.headers["X-Request-ID"]

    assert returned != "not-a-valid-uuid"
    assert str(UUID(returned)) == returned
    assert response.json()["meta"]["request_id"] == returned
