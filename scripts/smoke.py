"""Dependency-free post-deployment health and contract smoke check."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit


def _read_json(base_url: str, path: str) -> dict[str, object]:
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RuntimeError("SMOKE_BASE_URL must be an absolute HTTP(S) URL")
    request = urllib.request.Request(  # noqa: S310 - scheme validated above
        f"{base_url.rstrip('/')}{path}",
        headers={"User-Agent": "investment-copilot-smoke/0.8"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
        if response.status != 200:
            raise RuntimeError(f"{path} returned HTTP {response.status}")
        payload = json.loads(response.read(256_000))
    if not isinstance(payload, dict):
        raise RuntimeError(f"{path} returned a non-object response")
    return payload


def main() -> int:
    base_url = os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:8000")
    try:
        live = _read_json(base_url, "/livez")
        ready = _read_json(base_url, "/readyz")
        unavailable_stock = _read_json(
            base_url,
            "/api/v1/stocks/OGDC/research?exchange=PSX&interval=1d&days=365",
        )
    except (OSError, ValueError, RuntimeError, urllib.error.URLError) as error:
        print(f"Smoke check failed: {error}", file=sys.stderr)
        return 1

    if live.get("status") != "alive" or ready.get("status") != "ready":
        print("Smoke check failed: health contract is not ready", file=sys.stderr)
        return 1
    data = unavailable_stock.get("data")
    if not isinstance(data, dict) or data.get("symbol") != "OGDC":
        print("Smoke check failed: stock contract is invalid", file=sys.stderr)
        return 1
    print("Smoke check passed: liveness, readiness, and stock contract are healthy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
