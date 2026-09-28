"""Small synchronous API client used only by the Streamlit server process."""

from __future__ import annotations

import os
import re
from datetime import UTC, date, datetime, time
from typing import Any
from urllib.parse import urlsplit

import httpx


class ResearchApiError(Exception):
    """Safe UI-facing API failure."""


def _normalize_api_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ResearchApiError("The API URL must be an absolute HTTP(S) URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ResearchApiError("The API URL must not include credentials or a query.")
    return normalized


def _api_base_url(value: str) -> str:
    """Allow only the operator-configured backend when one is supplied."""
    normalized = _normalize_api_base_url(value)
    configured = os.getenv("COPILOT_API_URL")
    if configured and normalized != _normalize_api_base_url(configured):
        raise ResearchApiError("The API URL is not allowed by this deployment.")
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


def fetch_futures_research(
    *,
    api_base_url: str,
    symbol: str,
    period: str,
) -> dict[str, Any]:
    """Fetch bounded, public USD-M Futures research without credentials."""
    normalized = symbol.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{5,20}", normalized):
        raise ResearchApiError("Enter a valid USD-M Futures symbol.")
    allowed_periods = {"5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"}
    if period not in allowed_periods:
        raise ResearchApiError("Select a supported Futures period.")
    return _get_json(
        api_base_url=api_base_url,
        path=f"/api/v1/binance/futures/{normalized}/research",
        params={"period": period, "limit": 30},
        timeout_seconds=10.0,
    )


def _get_json(
    *,
    api_base_url: str,
    path: str,
    params: dict[str, str | int | float],
    access_token: str | None = None,
    timeout_seconds: float = 8.0,
) -> dict[str, Any]:
    base_url = _api_base_url(api_base_url)
    headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
    try:
        response = httpx.get(
            f"{base_url}{path}",
            params=params,
            headers=headers,
            timeout=httpx.Timeout(timeout_seconds, connect=2.0),
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


def _post_json(
    *,
    api_base_url: str,
    path: str,
    body: dict[str, Any],
    access_token: str | None = None,
) -> dict[str, Any]:
    base_url = _api_base_url(api_base_url)
    headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
    try:
        response = httpx.post(
            f"{base_url}{path}",
            json=body,
            headers=headers,
            timeout=httpx.Timeout(15.0, connect=2.0),
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
        message = "The request could not be completed."
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


def _get_list_json(
    *,
    api_base_url: str,
    path: str,
    params: dict[str, str | int | float],
    access_token: str,
) -> list[dict[str, Any]]:
    base_url = _api_base_url(api_base_url)
    try:
        response = httpx.get(
            f"{base_url}{path}",
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=httpx.Timeout(8.0, connect=2.0),
            follow_redirects=False,
        )
    except (httpx.TimeoutException, httpx.NetworkError) as error:
        raise ResearchApiError(
            "The research API could not be reached within the time limit."
        ) from error
    if response.is_error:
        raise ResearchApiError("Private uploads could not be loaded.")
    try:
        payload: object = response.json()
    except ValueError as error:
        raise ResearchApiError("The research API returned invalid JSON.") from error
    if not isinstance(payload, list) or not all(
        isinstance(item, dict) for item in payload
    ):
        raise ResearchApiError("The research API returned an invalid upload list.")
    return payload


def _delete(
    *,
    api_base_url: str,
    path: str,
    params: dict[str, str | int | float],
    access_token: str,
) -> None:
    base_url = _api_base_url(api_base_url)
    try:
        response = httpx.delete(
            f"{base_url}{path}",
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=httpx.Timeout(8.0, connect=2.0),
            follow_redirects=False,
        )
    except (httpx.TimeoutException, httpx.NetworkError) as error:
        raise ResearchApiError(
            "The research API could not be reached within the time limit."
        ) from error
    if response.is_error:
        raise ResearchApiError("The private upload could not be deleted.")


def login_user(*, api_base_url: str, email: str, password: str) -> dict[str, Any]:
    """Create a server-session-only login for private stock uploads."""
    return _post_json(
        api_base_url=api_base_url,
        path="/api/v1/auth/login",
        body={"email": email.strip(), "password": password},
    )


def refresh_user_session(*, api_base_url: str, refresh_token: str) -> dict[str, Any]:
    """Rotate a refresh token and return a replacement token pair."""
    return _post_json(
        api_base_url=api_base_url,
        path="/api/v1/auth/refresh",
        body={"refresh_token": refresh_token},
    )


def logout_user(*, api_base_url: str, refresh_token: str) -> None:
    """Revoke the server-side refresh-token family."""
    _post_json(
        api_base_url=api_base_url,
        path="/api/v1/auth/logout",
        body={"refresh_token": refresh_token},
    )


def upload_stock_prices(
    *,
    api_base_url: str,
    access_token: str,
    exchange: str,
    symbol: str,
    filename: str,
    csv_bytes: bytes,
    source_label: str,
    source_date: date,
    currency: str,
) -> dict[str, Any]:
    """Send a bounded UTF-8 CSV to the authenticated owner-private endpoint."""
    if len(csv_bytes) > 1024 * 1024:
        raise ResearchApiError("CSV exceeds the 1 MiB upload limit.")
    try:
        csv_text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ResearchApiError("CSV must be UTF-8 encoded text.") from error
    normalized = symbol.strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9]{0,5}(?:[.-][A-Z0-9]{1,4})?", normalized):
        raise ResearchApiError("Enter a valid uppercase stock symbol.")
    source_timestamp = datetime.combine(source_date, time.min, tzinfo=UTC)
    return _post_json(
        api_base_url=api_base_url,
        path=f"/api/v1/stocks/{normalized}/price-uploads?exchange={exchange}",
        access_token=access_token,
        body={
            "filename": filename,
            "source_label": source_label,
            "source_timestamp": source_timestamp.isoformat(),
            "currency": currency.strip().upper(),
            "csv_text": csv_text,
        },
    )


def list_stock_price_uploads(
    *,
    api_base_url: str,
    access_token: str,
    exchange: str,
    symbol: str,
) -> list[dict[str, Any]]:
    normalized = symbol.strip().upper()
    return _get_list_json(
        api_base_url=api_base_url,
        path=f"/api/v1/stocks/{normalized}/price-uploads",
        params={"exchange": exchange},
        access_token=access_token,
    )


def fetch_stock_price_upload(
    *,
    api_base_url: str,
    access_token: str,
    exchange: str,
    symbol: str,
    upload_id: str,
) -> dict[str, Any]:
    normalized = symbol.strip().upper()
    return _get_json(
        api_base_url=api_base_url,
        path=f"/api/v1/stocks/{normalized}/price-uploads/{upload_id}",
        params={"exchange": exchange},
        access_token=access_token,
    )


def delete_stock_price_upload(
    *,
    api_base_url: str,
    access_token: str,
    exchange: str,
    symbol: str,
    upload_id: str,
) -> None:
    normalized = symbol.strip().upper()
    _delete(
        api_base_url=api_base_url,
        path=f"/api/v1/stocks/{normalized}/price-uploads/{upload_id}",
        params={"exchange": exchange},
        access_token=access_token,
    )


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
        timeout_seconds=15.0,
    )
