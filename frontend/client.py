"""Small synchronous API client used only by the Streamlit server process."""

from __future__ import annotations

import re
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


def _get_json(
    *,
    api_base_url: str,
    path: str,
    params: dict[str, str | int | float],
) -> dict[str, Any]:
    base_url = _api_base_url(api_base_url)
    try:
        response = httpx.get(
            f"{base_url}{path}",
            params=params,
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


def search_crypto(
    *,
    api_base_url: str,
    query: str,
) -> dict[str, Any]:
    """Search CoinGecko identities without selecting an ambiguous symbol."""
    normalized = " ".join(query.strip().split())
    if not 2 <= len(normalized) <= 80:
        raise ResearchApiError("Crypto search must contain 2-80 characters.")
    return _get_json(
        api_base_url=api_base_url,
        path="/api/v1/crypto/search",
        params={"q": normalized},
    )


def fetch_crypto_research(
    *,
    api_base_url: str,
    coin_id: str,
    days: int,
) -> dict[str, Any]:
    """Fetch general crypto research using a canonical CoinGecko provider ID."""
    normalized = coin_id.strip().lower()
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", normalized):
        raise ResearchApiError(
            "Select a lowercase CoinGecko provider ID, not a ticker or pair."
        )
    if days not in {1, 7, 30, 90, 365}:
        raise ResearchApiError("Crypto history must be 1, 7, 30, 90, or 365 days.")
    return _get_json(
        api_base_url=api_base_url,
        path=f"/api/v1/crypto/{normalized}/research",
        params={"days": days},
    )


def search_stocks(
    *,
    api_base_url: str,
    query: str,
    exchange: str = "PSX",
) -> dict[str, Any]:
    """Search exchange-qualified stock identities through the local API."""
    normalized = " ".join(query.strip().split())
    if not 1 <= len(normalized) <= 80:
        raise ResearchApiError("Stock search must contain 1-80 characters.")
    if exchange not in {"PSX", "NASDAQ", "NYSE"}:
        raise ResearchApiError("Select PSX, NASDAQ, or NYSE.")
    return _get_json(
        api_base_url=api_base_url,
        path="/api/v1/stocks/search",
        params={"q": normalized, "exchange": exchange},
    )


def fetch_stock_research(
    *,
    api_base_url: str,
    exchange: str,
    symbol: str,
    interval: str,
    days: int,
) -> dict[str, Any]:
    """Fetch an exchange-qualified aggregate with an explicit licensing state."""
    normalized = symbol.strip().upper()
    if exchange not in {"PSX", "NASDAQ", "NYSE"}:
        raise ResearchApiError("Select PSX, NASDAQ, or NYSE.")
    if not re.fullmatch(r"[A-Z][A-Z0-9]{0,5}(?:[.-][A-Z0-9]{1,4})?", normalized):
        raise ResearchApiError("Enter a valid uppercase stock symbol.")
    if interval not in {"1d", "1w"}:
        raise ResearchApiError("Stock interval must be 1d or 1w.")
    if days not in {30, 90, 180, 365, 730, 1825}:
        raise ResearchApiError("Select a supported stock history range.")
    return _get_json(
        api_base_url=api_base_url,
        path=f"/api/v1/stocks/{normalized}/research",
        params={"exchange": exchange, "interval": interval, "days": days},
    )
