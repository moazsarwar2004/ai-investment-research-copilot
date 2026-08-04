# Phase 6 — General cryptocurrency research

## 1. Outcome

Phase 6 adds provider-ID-based general cryptocurrency research using CoinGecko
Demo or the lower-volume keyless public API. The normal test suite is entirely
fixture-driven and never consumes provider credits.

Implemented:

- Name, symbol, and provider-ID search with explicit symbol ambiguity.
- Global market cap, volume, BTC/ETH dominance, trending assets, and paged
  markets.
- Coin overview, supply, 24-hour range, ATH/ATL distance, and bounded history.
- Deterministic technicals, trend evidence, rolling anomalies, drawdown,
  volatility, and six-component crypto risk.
- Eleven read-only FastAPI routes and a partial-tolerant aggregate response.
- A General crypto mode in Streamlit with search, canonical-ID selection,
  attribution, freshness, partial, stale, empty, and error states.
- Atomic per-minute and 30-day local budget windows with capacity reserved for
  interactive requests.

General crypto identity is a canonical CoinGecko ID such as `bitcoin`. It is
never a Binance pair, ticker symbol, contract address, or user-supplied URL.

## 2. Terms and API review

Reviewed on 2026-08-04:

- [CoinGecko API pricing](https://www.coingecko.com/en/api/pricing): Demo has
  10,000 call credits/month, 100 calls/minute, 50+ endpoints, and freshness
  from 60 seconds.
- [CoinGecko API terms](https://www.coingecko.com/en/api_terms): attribution is
  required and API output is general information, not investment advice.
- [Keyless public API](https://docs.coingecko.com/docs/keyless-public-api): the
  public root is `https://api.coingecko.com/api/v3`, has dynamic shared-pool
  throttling, and is intended for light testing and non-commercial education.
- [Demo setup](https://support.coingecko.com/hc/en-us/articles/21880397454233-User-Guide-How-to-sign-up-for-CoinGecko-Demo-API-and-generate-an-API-key):
  Demo uses the same root and supports the `x-cg-demo-api-key` header.

Provenance records
`coingecko-api-terms-2025-09-05-reviewed-2026-08-04`, and every research
payload/UI view displays `Powered by CoinGecko`.

## 3. Module boundaries

| Module | Responsibility |
| --- | --- |
| `providers/coingecko.py` | Pinned requests, Demo-key header, strict core wire validation, Decimal/UTC normalization, identity resolution, attribution |
| `analytics/crypto.py` | Pure technical, trend, anomaly, drawdown, volatility, and risk calculations |
| `services/crypto_service.py` | Product bounds, CoinGecko-ID enforcement, cache policies, partial aggregation |
| `api/crypto_routes.py` | Query/path validation, response models, read-only route catalog |
| `frontend/` | Search/selection workflow, cached research rendering, UI-state classification |

Routes contain no provider mapping or calculations. Adapters accept no arbitrary
host or path. Analytics perform no I/O.

## 4. Public API

All paths are below `/api/v1`.

| Route | Upstream | Product bound | Cache soft / hard TTL |
| --- | --- | --- | --- |
| `GET /crypto/search?q=` | `/search` | 2–80 characters; up to 100 ranked coins | 5 / 30 min |
| `GET /crypto/global` | `/global` | USD aggregate fields | 30 / 120 min |
| `GET /crypto/trending` | `/search/trending` | Coin entries only | 30 / 120 min |
| `GET /crypto/markets` | `/coins/markets` | pages 1–10; 1–100 rows | 15 / 60 min |
| `GET /crypto/{coin_id}` | `/coins/markets?ids=` | one canonical provider ID | 5 / 30 min |
| `GET /crypto/{coin_id}/history` | `/coins/{id}/market_chart` | 1, 7, 30, 90, or 365 days | 5 / 60 min |
| `GET /crypto/{coin_id}/technicals` | cached/fetched history | at least 20 points | history TTL |
| `GET /crypto/{coin_id}/trend` | deterministic technicals | evidence list | history TTL |
| `GET /crypto/{coin_id}/anomalies` | cached/fetched history | rolling prior-30 baseline | history TTL |
| `GET /crypto/{coin_id}/risk` | overview + history | bounded two-call fan-out | component TTLs |
| `GET /crypto/{coin_id}/research` | overview + history | bounded two-call fan-out | component TTLs |

Coin IDs must match lowercase letters/digits separated by single hyphens. A
query like `BTC` may return several exact symbol matches; the response lists all
matching IDs and sets `ambiguous_symbol: true` instead of choosing one.

## 5. Quota and secret controls

- Demo API key is optional, held as `SecretStr`, and sent only in the
  `x-cg-demo-api-key` header.
- With a Demo key, the configured local minute ceiling defaults to 100. Without
  one, keyless mode defaults to a conservative 10 calls/minute.
- The product ceiling is 9,000 calls per rolling 30-day process window, leaving
  headroom under the 10,000-credit Demo allowance.
- Scheduled work is limited to 8 calls/minute in keyless mode and 8,000 calls
  per 30-day window; the remainder is reserved for interactive reads.
- Each outbound attempt, including a retry, reserves one unit. Cache hits use
  no provider credit.
- All active windows are preflighted before incrementing any counter, preventing
  a rejected long-window reservation from consuming minute capacity.

The counters are process-local like the Phase 4/5 quota framework. A restart
resets them; distributed/durable accounting remains an operations hardening
item before an internet-facing multi-process deployment. CoinGecko's own plan
limit remains the upstream fail-safe.

## 6. Deterministic analytics

`crypto-technicals-v1` calculates SMA(20/50), EMA(12/26), RSI(14), MACD and
signal/histogram, interval-aware annualized volatility, maximum drawdown,
latest return, and a reproducible trend/confidence rule.

`crypto-anomalies-v1` compares return and log-volume changes with the preceding
30 observations (minimum 10), flags absolute z-scores of at least 3, and emits
timestamped return/volume events. Flags are statistical observations, not
causal explanations or signals.

`crypto-risk-v1` uses the approved initial weights:

| Component | Weight |
| --- | ---: |
| Volatility | 30% |
| Drawdown | 20% |
| Liquidity | 15% |
| Market size | 15% |
| Trend instability | 10% |
| Anomaly | 10% |

Scores are bounded 0–100. Missing components are omitted, remaining weights are
renormalized to 1.0, and coverage/freshness reduce `data_confidence`.

## 7. Exit-gate evidence

| Required scenario | Evidence |
| --- | --- |
| Terms recheck | Current official pricing, terms, keyless, and Demo setup reviewed above |
| Call budget | Compound-window test covers minute exhaustion, reset, monthly exhaustion, and atomic accounting |
| Symbol ambiguity | `BTC` fixture returns `bitcoin` and `bitcoin-wrapped`, with no silent selection |
| Provider controls | Pinned HTTPS host, header-only optional key, bounded paths/parameters, strict core schema tests |
| Analytics | Reproducibility, trend evidence, return/volume spike, six weights, and missing-input renormalization tests |
| Partial response | History failure retains overview and two-component renormalized risk |
| Cached UI demo | Streamlit fixture renders CoinGecko attribution and partial state with no exception |
| No live dependency | All CoinGecko tests use the committed recorded-shape fixture |

Focused verification:

```powershell
python -m pytest -q `
  backend/app/tests/test_coingecko_provider.py `
  backend/app/tests/test_crypto_analytics.py `
  backend/app/tests/test_crypto_service.py `
  backend/app/tests/test_crypto_api.py `
  backend/app/tests/test_frontend_state.py
```

## 8. Common errors

| Symptom | Meaning / correction |
| --- | --- |
| `422` for a coin path | Use a lowercase CoinGecko provider ID such as `bitcoin`, not `BTC` or `BTCUSDT` |
| Ambiguous symbol warning | Select one of the returned provider IDs; the service will not guess |
| `RESOURCE_NOT_FOUND` | CoinGecko returned no market entry for the requested ID |
| `provider_quota_exceeded` | The local minute or 30-day budget is exhausted; use cache or wait for reset |
| `provider_schema_changed` | A required CoinGecko core field changed; review the adapter before serving it |
| Stale badge | Refresh failed and a still-permitted cached snapshot is shown |
| Partial badge | History/analytics are unavailable; overview and renormalized risk remain usable |

## 9. Checklist

- [x] Terms, pricing, authentication, public-host, and attribution review.
- [x] Optional secret Demo key and conservative keyless fallback.
- [x] Atomic minute plus 30-day local call budgets.
- [x] Provider-ID search and explicit symbol ambiguity.
- [x] Global, trending, markets, overview, and history adapters.
- [x] Decimal-safe normalized schemas and UTC timestamps.
- [x] Technical, trend, volatility, drawdown, and anomaly analytics.
- [x] Six-component explainable risk with missing-input renormalization.
- [x] Eleven read-only routes and bounded aggregate fan-out.
- [x] General crypto Streamlit workflow and required UI states.
- [x] Fixture, analytics, service, API, configuration, quota, and UI tests.
- [x] No live provider dependency in normal tests.

Recommended phase-completion commit:

```text
feat: complete phase 6 general crypto research
```

## 10. Phase 7 boundary

Phase 7 remains separate. It adds stock identity/profile and quote/candle
abstractions only when external-display licensing is recorded. SEC-backed
research remains independent of a quote feed.
