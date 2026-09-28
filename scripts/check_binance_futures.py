"""Read-only production gate for Binance USD-M public endpoint reachability."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime

import httpx

BASE_URL = "https://fapi.binance.com"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check the free public USD-M host without credentials."
    )
    parser.add_argument("--timeout", type=float, default=8.0)
    args = parser.parse_args()
    try:
        with httpx.Client(
            base_url=BASE_URL,
            timeout=httpx.Timeout(args.timeout, connect=min(3.0, args.timeout)),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            time_response = client.get("/fapi/v1/time")
            time_response.raise_for_status()
            exchange_response = client.get("/fapi/v1/exchangeInfo")
            exchange_response.raise_for_status()
        time_payload = time_response.json()
        exchange_payload = exchange_response.json()
        server_time = time_payload.get("serverTime")
        symbols = exchange_payload.get("symbols")
        if not isinstance(server_time, int) or not isinstance(symbols, list):
            raise ValueError("unexpected public endpoint schema")
        perpetuals = [
            item
            for item in symbols
            if isinstance(item, dict)
            and item.get("contractType") == "PERPETUAL"
            and item.get("status") == "TRADING"
        ]
        print(
            json.dumps(
                {
                    "reachable": True,
                    "host": BASE_URL,
                    "authentication_used": False,
                    "checked_at": datetime.now(UTC).isoformat(),
                    "server_time": datetime.fromtimestamp(
                        server_time / 1_000, tz=UTC
                    ).isoformat(),
                    "tradable_perpetual_count": len(perpetuals),
                },
                sort_keys=True,
            )
        )
        return 0 if perpetuals else 1
    except (httpx.HTTPError, ValueError, TypeError) as error:
        print(
            json.dumps(
                {
                    "reachable": False,
                    "host": BASE_URL,
                    "authentication_used": False,
                    "error": type(error).__name__,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
