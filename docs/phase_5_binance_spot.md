# Phase 5 — Binance Spot MVP

## 1. Outcome

Phase 5 delivers the first end-to-end research product slice. It uses only
Binance public Spot market data, performs no authenticated exchange operation,
and remains fully testable without live provider access.

Implemented:

- Tradable pair discovery and validation from cached `/api/v3/exchangeInfo`.
  The request asks only for `TRADING` symbols and omits unused permission sets
  to keep the public catalog response bounded.
- Normalized 24-hour ticker, UTC candles, order-book snapshots, and recent
  public trades from the official market-data-only host.
- Exact request-weight reservations and authoritative
  `X-MBX-USED-WEIGHT-1M` reconciliation.
- Product bounds that prevent users from amplifying provider weight or response
  size.
- Deterministic technical, volatility, liquidity, order-pressure, slippage,
  trade-anomaly, and explainable Spot risk calculations.
- Eight read-only FastAPI routes, including partial-tolerant aggregate research.
- A first Streamlit research page with loading, empty, ready, partial, stale,
  and error states.
- Recorded-shape fixture tests; normal CI never calls Binance.

Official contracts reviewed for this phase:

- [Binance general API and rate-limit behavior](https://developers.binance.com/en/docs/products/spot/rest-api)
- [Binance Spot market endpoints](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/market)
- [Binance Spot general endpoints](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/general)
- [Binance market-data-only URLs](https://developers.binance.com/en/docs/products/spot/faqs/market_data_only)

Terms/schema review version retained in provenance:
`binance-spot-docs-2026-07-23`.

## 2. Module boundaries

| Module | Responsibility |
| --- | --- |
| `providers/binance_spot.py` | Vendor requests, strict core wire validation, normalized Decimal/UTC contracts, usage-header parsing |
| `analytics/binance_spot.py` | Pure technical, liquidity, trade-pressure, anomaly, slippage, and risk calculations |
| `services/binance_spot_service.py` | Pair validation, request policies, partial aggregation, freshness/source merging |
| `api/binance_spot_routes.py` | Query/path validation, response models, HTTP route catalog |
| `frontend/` | Local API client, UI-state classifier, and first Streamlit research page |

Routes contain no provider mapping or calculations. Adapters contain no UI
formatting or authorization behavior. Analytics perform no I/O.

## 3. Public API

All paths are below `/api/v1`.

| Route | Upstream source | Local bound | Upstream weight |
| --- | --- | ---: | ---: |
| `GET /binance/spot/symbols` | `/api/v3/exchangeInfo` | Tradable Spot pairs only | 20 |
| `GET /binance/spot/{symbol}/ticker` | `/api/v3/ticker/24hr` | Exactly one validated pair | 2 |
| `GET /binance/spot/{symbol}/candles` | `/api/v3/klines` | 50–500 bars, seven intervals | 2 |
| `GET /binance/spot/{symbol}/order-book` | `/api/v3/depth` | 20, 50, or 100 levels | 5 |
| `GET /binance/spot/{symbol}/trades` | `/api/v3/trades` | 1–200 trades | 25 |
| `GET /binance/spot/{symbol}/technicals` | Cached/fetched candles | 50–500 bars | candle weight |
| `GET /binance/spot/{symbol}/risk` | Candles + depth + trades | Bounded fan-out | 32 |
| `GET /binance/spot/{symbol}/research` | Ticker + candles + depth + trades | Bounded fan-out | 34 |

Exchange metadata is fetched first and normally served from its 5-minute soft /
1-hour hard cache. Market routes cannot accept an arbitrary provider URL,
authenticated header, key, signature, account identifier, or order payload.

## 4. Cache and weight policy

| Data | Soft TTL | Hard TTL |
| --- | ---: | ---: |
| Exchange metadata | 5 min | 1 h |
| 24-hour ticker | 15 s | 30 s |
| Candles | 1 min | 5 min |
| Order book | 5 s | 10 s |
| Recent trades | 10 s | 30 s |

The application defaults to a conservative local budget of 1,000 request-weight
units per minute, with 200 units reserved from future scheduled work for
interactive users. Binance's response header can raise the local used count to
the authoritative IP-wide value. `429` and `418` behavior remains governed by
the Phase 4 bounded retry and `Retry-After` controls.

## 5. Deterministic analytics

### 5.1 Technicals

`spot-technicals-v1` calculates:

- SMA(20) and EMA(20).
- RSI(14), including stable flat-market and zero-loss handling.
- ATR(14).
- Log-return annualized volatility using an interval-specific periods-per-year
  factor.
- Latest return plus a reproducible bullish/neutral/bearish rule and confidence.

At least 20 points are required; the API enforces a minimum provider request of
50 bars.

### 5.2 Liquidity and public trade pressure

`spot-liquidity-v1` returns:

- Best bid/ask, absolute spread, and midpoint spread in basis points.
- Bounded bid/ask quote depth and normalized imbalance from -1 to 1.
- Buy/balanced/sell order-book pressure.
- Estimated market-buy and market-sell slippage at a caller-selected bounded
  quote notional.
- Explicit insufficient-depth warnings instead of invented slippage.

`spot-trades-v1` classifies aggressive buys/sells from `isBuyerMaker`, calculates
normalized pressure, and marks trades at least five times the sample median
quote size as large-trade anomalies.

### 5.3 Spot risk

`spot-risk-v1` returns the required deterministic risk contract:

```text
overall_score, risk_label, component_scores, component_weights,
methodology_version, data_confidence, missing_inputs, limitations
```

Initial Spot weights:

| Component | Weight |
| --- | ---: |
| Volatility | 35% |
| Liquidity | 35% |
| Public trade anomaly/pressure | 20% |
| Trend instability | 10% |

Scores are bounded 0–100. When a component is unavailable, it is omitted and
the remaining weights are renormalized to 1.0. Coverage and stale input reduce
`data_confidence`. The calculation does not know holdings, leverage, objectives,
or user suitability and cannot be interpreted as personalized advice.

## 6. Streamlit states

Run the API, then:

```powershell
python -m streamlit run frontend/app.py
```

The page:

- Shows a neutral empty state before the first request.
- Uses a spinner while the aggregate request is in flight.
- Shows a prominent stale badge from API freshness/cache metadata.
- Shows a partial warning while retaining available components.
- Shows a safe error message for API, timeout, network, or malformed-response
  failures.
- Renders price history, technicals, depth/liquidity, recent trades, risk,
  source provenance, warnings, and the research disclaimer.

The frontend calls the local API only. It neither accepts nor stores Binance
credentials.

## 7. Exit-gate evidence

| Required scenario | Evidence |
| --- | --- |
| Mock/API contracts | Strict adapter fixtures plus route/OpenAPI response tests |
| Symbol controls | Format rejection and exchange-metadata membership tests |
| Weight controls | Exact 20/2/2/5/25 request assertions and limit-amplification rejection |
| Schema change | Missing/renamed ticker core field raises `provider_schema_changed` |
| Technicals | Golden fixture SMA/RSI/ATR/trend assertions |
| Liquidity/anomaly/risk | Bounded spread/slippage/pressure/anomaly and missing-weight tests |
| Partial behavior | One failed provider component returns usable partial aggregate and renormalized risk |
| UI states | Empty/ready/partial/stale/error classifier tests plus a zero-exception Streamlit render smoke test |
| No live dependency | All provider tests use committed JSON fixtures |
| No trading surface | OpenAPI namespace audit plus fixed public market-data-only host |

Run the focused Phase 5 tests:

```powershell
python -m pytest -q `
  backend/app/tests/test_binance_spot_provider.py `
  backend/app/tests/test_binance_spot_analytics.py `
  backend/app/tests/test_binance_spot_service.py `
  backend/app/tests/test_binance_spot_api.py `
  backend/app/tests/test_frontend_state.py
```

Expected: all focused tests pass, including the Streamlit render smoke test.

Run all local quality gates:

```powershell
python -m ruff check .
python -m black --check --workers 1 .
python -m mypy backend
python -m pytest -m "not integration"
python -m pip check
python -m alembic upgrade head --sql
docker compose config --quiet
```

## 8. Common errors

| Symptom | Meaning / correction |
| --- | --- |
| `VALIDATION_ERROR` | Symbol shape is invalid; use a 5–20 character letters/digits pair |
| `RESOURCE_NOT_FOUND` | Pair is absent or not tradable in cached exchange metadata |
| `REQUEST_VALIDATION_ERROR` | Interval, limit, depth, trade count, or slippage notional is outside the public bound |
| `provider_quota_exceeded` | Local request-weight budget is exhausted; wait for its minute window/cache |
| `provider_schema_changed` | A required Binance core field changed; review the adapter before serving it |
| `provider_unavailable` | No responsible cached/provider result exists |
| Stale UI badge | Refresh failed and a labelled, still-permitted cached snapshot is shown |
| Partial UI badge | At least one aggregate component failed; inspect warnings and missing risk inputs |

## 9. Phase checklist

- [x] Market-data-only Binance host and feature flag.
- [x] Exchange metadata and tradable-symbol validation.
- [x] Public ticker, candles, order book, and recent trades.
- [x] Seven product-approved candle intervals.
- [x] Exact weight and usage-header controls.
- [x] Bounded provider fan-out and input amplification protection.
- [x] Decimal-safe normalized schemas and UTC timestamps.
- [x] Technical, liquidity, pressure, anomaly, slippage, and Spot risk analytics.
- [x] Missing-input risk renormalization and confidence.
- [x] Eight read-only API routes and OpenAPI audit.
- [x] Aggregate partial/stale response behavior.
- [x] First Streamlit page and required UI states.
- [x] Fixture, analytics, service, API, configuration, and UI tests.
- [x] No live provider dependency or exchange credential in CI.
- [x] Documentation, demo, common errors, and exit evidence.

Recommended phase-completion commit:

```text
feat: complete phase 5 Binance Spot MVP
```

## 10. Phase 6 boundary

Phase 6 remains separate. It adds general cryptocurrency search, identity
disambiguation, global/market/history data, CoinGecko attribution and monthly
budgeting, broader crypto analytics/anomalies/risk, and corresponding UI. It
must not reuse a Binance trading pair as a general-crypto identity.
