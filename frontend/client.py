"""Small synchronous API client used only by the Streamlit server process."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import httpx


class ResearchApiError(Exception):
    """Safe UI-facing API failure."""


def _api_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ResearchApiError("The API URL must be an absolute HTTP(S) URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ResearchApiError("The API URL must not include credentials or a query.")
    return normalized


def fetch_spot_research(
    *,
    api_base_url: str,
    symbol: str,
    interval: str,
    slippage_notional_quote: float,
) -> dict[str, Any]:
    """Fetch one bounded aggregate response without retaining credentials."""
    base_url = _api_base_url(api_base_url)
    try:
        response = httpx.get(
            f"{base_url}/api/v1/binance/spot/{symbol}/research",
            params={
                "interval": interval,
                "candle_limit": 200,
                "book_limit": 100,
                "trade_limit": 100,
                "slippage_notional_quote": slippage_notional_quote,
            },
            timeout=httpx.Timeout(8.0, connect=2.0),
            follow_redirects=False,
        )
    except (httpx.TimeoutException, httpx.NetworkError) as error:
        raise ResearchApiError(
            "The research API could not be reached within the time limit."
        ) from error
    try:
        payload: object = response.json()
    except ValueError as error:
        raise ResearchApiError("The research API returned invalid JSON.") from error
    if response.is_error:
        message = "The research request could not be completed."
        if isinstance(payload, dict):
            errors = payload.get("errors")
            if isinstance(errors, list) and errors and isinstance(errors[0], dict):
                safe_message = errors[0].get("message")
                if isinstance(safe_message, str) and safe_message:
                    message = safe_message
        raise ResearchApiError(message)
    if not isinstance(payload, dict):
        raise ResearchApiError("The research API returned an invalid response.")
    return payload
