# Phase 9 — Public Binance USD-M Futures Research

## Scope and free-data rule

Phase 9 uses only Binance's documented, unauthenticated USD-M public market-data
endpoints. It has no API key fields, signed requests, account reads, order routes,
position controls or paid provider dependency. The production feature flag is off
by default. Enable it only when the production host passes the reachability check
and the operator has confirmed that displaying public derivatives research is
allowed in the deployment jurisdiction.

The integration covers currently trading perpetual symbols, mark/index price,
funding history and next-funding time, current and historical open interest,
perpetual basis, aggregate account ratios and taker buy/sell volume. Every result
includes its provider URL, source timestamp, fetch timestamp, payload hash, cache
state and freshness. A partial response keeps successful components and names
failed components; it never fills a missing observation with zero.
`GET /api/v1/binance/futures/status` exposes the safe feature/reachability state,
credential requirement and no-trading boundary for deployment checks.

## Analytics contract

- Funding is annualized only when the latest two observed settlement gaps agree.
  Binance can change settlement frequency, so a fixed eight-hour assumption is
  prohibited. The value is a simple projection of the latest historical rate.
- Perpetual basis is `(futures price / index price - 1) × 100`. It is not
  annualized because a perpetual contract has no expiry.
- Open-interest change uses base-asset quantity over the selected history window.
  USD value is retained as evidence but is not used for quantity growth because
  price changes would distort it.
- Aggregate account shares count accounts, not position size or capital. Taker
  flow is a bounded historical aggregate.
- The risk score is a deterministic market-condition heuristic. Its confidence
  is weighted input coverage, reduced for stale data; it is not predictive
  confidence or liquidation probability.

## Running and enabling

Run the technical gate from the deployment host:

```powershell
.venv\Scripts\python.exe scripts\check_binance_futures.py
```

A successful result has `reachable: true`, `authentication_used: false`, a UTC
server time and a positive perpetual count. Then set:

```dotenv
BINANCE_FUTURES_ENABLED=true
BINANCE_FUTURES_BASE_URL=https://fapi.binance.com
```

Keep the flag false if the endpoint is blocked or local availability has not been
reviewed. The rest of the application remains available.

Run Phase 9 verification:

```powershell
.venv\Scripts\python.exe -m pytest backend/app/tests/test_binance_futures.py -q
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m black --check .
.venv\Scripts\python.exe -m mypy backend
.venv\Scripts\python.exe -m pytest -m "not integration"
```

Normal tests use invented fixtures and do not call Binance. The live script is a
manual deployment check, not a CI dependency.

## Operations

The application applies endpoint-specific TTLs, an IP-weight budget, a separate
five-minute request limit for market-statistics endpoints, bounded limits, retry
deadlines, `Retry-After` handling, a circuit breaker and stale-cache fallback.
Disable `BINANCE_FUTURES_ENABLED` if provider terms, regional availability or
endpoint behavior changes. Recheck the official documentation before production
deployment and record the new review date in the adapter and data-source policy.

Official references:

- [USD-M public market data](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data)
- [Funding-rate explanation](https://www.binance.com/en/support/faq/detail/360033525031)

Phase 9 provides research and education. It does not execute trades or recommend
whether a user should take a leveraged position.
