"""Mock-only provider HTTP resilience, allowlist, and retry tests."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import cast

import httpx
import pytest
from pydantic import AnyHttpUrl

from backend.app.providers import (
    OutboundRequest,
    ProviderHostNotAllowedError,
    ProviderHttpClient,
    ProviderHttpPolicy,
    ProviderPayloadTooLargeError,
    ProviderTimeoutError,
)


def _policy(
    *,
    attempts: int = 3,
    response_max_bytes: int = 1024,
) -> ProviderHttpPolicy:
    return ProviderHttpPolicy(
        connect_timeout_seconds=1,
        read_timeout_seconds=1,
        write_timeout_seconds=1,
        pool_timeout_seconds=1,
        total_deadline_seconds=10,
        max_attempts=attempts,
        retry_base_seconds=0,
        retry_max_seconds=0,
        retry_after_max_seconds=5,
        response_max_bytes=response_max_bytes,
    )


async def _no_sleep(_: float) -> None:
    return None


async def test_timeout_retries_are_bounded_without_live_network() -> None:
    calls = 0

    def timeout_handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("fixture timeout", request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(timeout_handler)
    ) as transport_client:
        client = ProviderHttpClient(
            _policy(),
            client=transport_client,
            sleep=_no_sleep,
            random_value=lambda: 0,
        )
        with pytest.raises(ProviderTimeoutError):
            await client.request(
                provider="fixture",
                operation="quote",
                outbound=OutboundRequest(
                    url=AnyHttpUrl("https://fixture.example/quote")
                ),
                allowed_hosts={"fixture.example"},
            )

    assert calls == 3


async def test_429_obeys_retry_after_before_retrying() -> None:
    calls = 0
    waits: list[float] = []
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "2"},
                request=request,
            )
        return httpx.Response(
            200,
            json={"price": 10.25},
            headers={"X-Request-ID": "provider-request-1"},
            request=request,
        )

    async def record_sleep(seconds: float) -> None:
        waits.append(seconds)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as transport_client:
        client = ProviderHttpClient(
            _policy(attempts=2),
            client=transport_client,
            sleep=record_sleep,
        )
        response = await client.request(
            provider="fixture",
            operation="quote",
            outbound=OutboundRequest(
                url=AnyHttpUrl("https://fixture.example/quote"),
                params={"api_key": "not-retained-in-source-url"},
            ),
            allowed_hosts={"fixture.example"},
            on_attempt=attempts.append,
        )

    assert calls == 2
    assert waits == [2.0]
    assert attempts == [1, 2]
    assert response.attempts == 2
    assert response.provider_request_id == "provider-request-1"
    assert str(response.source_url) == "https://fixture.example/quote"
    assert "api_key" not in str(response.source_url)


async def test_non_allowlisted_or_insecure_destination_is_rejected_before_io() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={}, request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as transport_client:
        client = ProviderHttpClient(_policy(), client=transport_client)
        with pytest.raises(ProviderHostNotAllowedError):
            await client.request(
                provider="fixture",
                operation="quote",
                outbound=OutboundRequest(
                    url=AnyHttpUrl("http://fixture.example/quote")
                ),
                allowed_hosts={"fixture.example"},
            )

    assert called is False


async def test_oversized_payload_is_rejected_before_adapter_parsing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'{"value":"' + b"x" * 100 + b'"}')

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as transport_client:
        client = ProviderHttpClient(
            _policy(response_max_bytes=32),
            client=transport_client,
        )
        with pytest.raises(ProviderPayloadTooLargeError):
            await client.request(
                provider="fixture",
                operation="quote",
                outbound=OutboundRequest(
                    url=AnyHttpUrl("https://fixture.example/quote")
                ),
                allowed_hosts={"fixture.example"},
            )


def test_http_client_accepts_an_injectable_async_sleep_contract() -> None:
    sleep = cast(Callable[[float], Awaitable[None]], _no_sleep)
    assert callable(sleep)
