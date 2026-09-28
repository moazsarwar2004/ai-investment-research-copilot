# API Route Catalog

Base path: `/api/v1`  
Format: JSON over HTTPS  
Authentication: bearer access token for protected API calls; rotating refresh token is accepted only by the refresh/logout flow.  
Dates/times: ISO 8601 UTC. Monetary values are JSON strings when decimal precision must be preserved.

## Implementation status

The application source and generated OpenAPI document are the route source of
truth. Through Phase 8, the implemented namespaces are health/probes, identity,
Binance Spot, general crypto, and stock research/private CSV uploads. Sections
explicitly marked **planned** describe later phase contracts and are not callable
today. In particular, futures, RAG, asynchronous reports, watchlists, alerts,
notifications, and most admin operations are not Phase 8 features.

## 1. Cross-cutting conventions

- Every response includes `X-Request-ID`; callers may supply a valid request ID.
- Provider-backed success responses use the data/freshness envelope defined in `requirements.md`.
- Errors use `application/problem+json` with `type`, `title`, `status`, `code`, `detail`, `request_id` and optional safe field errors.
- `POST /reports`, RAG ingestion and admin retry endpoints require `Idempotency-Key`.
- Cursor pagination is used for reports, events, jobs, agent runs and audit logs.
- Guest quotas are enforced by signed guest identity plus IP/network controls. Authenticated quotas are per user and operation class.
- Caddy exposes only public/user API routes. `/metrics` and detailed diagnostics remain private even if an application route exists.

## 2. Health and public system routes

| Method | Route | Access | Purpose |
|---|---|---|---|
| GET | `/livez` | Public monitor | Process is alive; no dependency fan-out |
| GET | `/readyz` | Public monitor, reduced detail | API can serve; returns only aggregate readiness publicly |
| GET | `/api/v1/health` | Internal | Database and Redis readiness detail; not routed publicly through Caddy |
| GET | `/metrics` | Internal collector only | Prometheus metrics; private network only |

## 3. Authentication and account

| Method | Route | Access | Purpose |
|---|---|---|---|
| POST | `/auth/register` | Public, strict limit | Create unverified user |
| POST | `/auth/login` | Public, strict limit | Verify credentials and create token family |
| POST | `/auth/refresh` | Refresh token | Rotate token; reuse revokes family |
| POST | `/auth/logout` | Authenticated/refresh | Revoke current session/family |
| POST | `/auth/logout-all` | User | Revoke all user sessions |
| POST | `/auth/verify-email` | Single-use token | Verify account email |
| POST | `/auth/verification/resend` | Public, non-enumerating | Queue another verification message if eligible |
| POST | `/auth/password-reset/request` | Public, non-enumerating | Queue reset instructions |
| POST | `/auth/password-reset/confirm` | Single-use token | Replace password and revoke sessions |
| GET | `/users/me` | User | Current profile/role/preferences summary |
| PATCH | `/users/me` | User | Update allowed profile/preferences fields |
| GET | `/users/me/sessions` | User | List sanitized active sessions |
| DELETE | `/users/me/sessions/{session_id}` | Owner | Revoke one session |

## 4. Stock and SEC research

| Method | Route | Access | Purpose |
|---|---|---|---|
| GET | `/stocks/search?q=&exchange=` | Guest limited | Exchange-qualified symbol/company search |
| GET | `/stocks/{symbol}` | Guest limited | Company/quote overview with unavailable fields when unlicensed |
| GET | `/stocks/{symbol}/candles` | Guest limited | Normalized OHLCV with interval/range validation |
| GET | `/stocks/{symbol}/technicals` | Guest limited | Deterministic indicator set |
| GET | `/stocks/{symbol}/financials` | Guest limited | SEC XBRL or human-approved official-report statements |
| GET | `/stocks/{symbol}/ratios` | Guest limited | Sector-aware deterministic financial ratios |
| GET | `/stocks/{symbol}/trend` | Guest limited | Rule/model class probabilities and version |
| GET | `/stocks/{symbol}/risk` | Guest limited | Explainable stock risk contract |
| GET | `/stocks/{symbol}/research` | Guest limited | Aggregated partial response for the UI |
| GET | `/stocks/{symbol}/filings` | Guest limited | 10-K/10-Q/8-K index |
| POST | `/stocks/{symbol}/price-uploads` | User | Validate and privately analyze OHLCV CSV text |
| GET | `/stocks/{symbol}/price-uploads` | Owner | List the current user's private uploads for the stock |
| GET | `/stocks/{symbol}/price-uploads/{upload_id}` | Owner | Resolve one private upload and its deterministic analytics |
| DELETE | `/stocks/{symbol}/price-uploads/{upload_id}` | Owner | Delete one private upload |

Phase 8 implements financials, ratios, filing links, official-report aggregation,
and authenticated private price uploads. Each accepts
`exchange=PSX|NASDAQ|NYSE`; PSX is the
product default, while canonical identity remains `exchange:symbol`. Until a
provider record proves external-display permission, price-dependent responses
remain HTTP 200 with null components, `freshness: unavailable`, `partial: true`,
and a stable license warning. A future provider disclosure identifies its
real-time/delayed/EOD/historical classes and written authorization scope.
Official fundamentals remain independent, but PSX manifest companies appear
only after a named human approval; valid candidates still return unavailable.
Private upload bodies are JSON containing bounded UTF-8 `csv_text`; accepted
columns are exactly `date,open,high,low,close,volume`, with 20–1,500 daily rows.

## 5. RAG (planned Phase 13)

| Method | Route | Access | Purpose |
|---|---|---|---|
| POST | `/rag/questions` | Guest limited/user | Evidence-first answer; optional Ollama summary |
| GET | `/rag/questions/{answer_id}` | Owner/admin | Fetch persisted answer/status when async |
| POST | `/rag/questions/{answer_id}/feedback` | Owner | Rating/reason/citation feedback |
| GET | `/rag/chunks/{chunk_id}` | User with source access | Resolve cited evidence and SEC source |

Question bodies allow ticker/CIK, form types, date bounds and comparison mode. They do not accept arbitrary system prompts or outbound URLs.

## 6. General crypto

Implemented in Phase 6. All routes are public, read-only, served below the
versioned `/api/v1` prefix, and retain CoinGecko provenance/freshness metadata.
Path identity is a lowercase CoinGecko provider ID; symbols and Binance pairs
are rejected as path identities.

| Method | Route | Access | Purpose |
|---|---|---|---|
| GET | `/crypto/search?q=` | Guest limited | Name/symbol/provider-ID search with ambiguity |
| GET | `/crypto/global` | Guest limited | Market cap/volume/dominance/risk summary |
| GET | `/crypto/trending` | Guest limited | Provider-supported trending assets |
| GET | `/crypto/markets` | Guest limited | Paged market list; optional gainers/losers |
| GET | `/crypto/{coin_id}` | Guest limited | Coin overview and supply/ATH metadata |
| GET | `/crypto/{coin_id}/history` | Guest limited | Price/market cap/volume history |
| GET | `/crypto/{coin_id}/technicals` | Guest limited | Deterministic indicators |
| GET | `/crypto/{coin_id}/trend` | Guest limited | Rule/model trend output |
| GET | `/crypto/{coin_id}/anomalies` | Guest limited | Layered anomaly output |
| GET | `/crypto/{coin_id}/risk` | Guest limited | Explainable crypto risk |
| GET | `/crypto/{coin_id}/research` | Guest limited | Aggregated partial response for UI |

History accepts only 1, 7, 30, 90, or 365 days. Market lists are bounded to
100 rows and ten pages. Search responses expose exact ID/name/symbol matches and
set an explicit ambiguity flag when a symbol maps to multiple provider IDs.
Every response carries `Powered by CoinGecko` through provenance; aggregate
research repeats it as a display field.

## 7. Binance Spot

Implemented in Phase 5. All routes are public, read-only, served below the
versioned `/api/v1` prefix, and retain Binance provenance/freshness metadata.
Symbols are checked against cached exchange metadata before a market request.

| Method | Route | Access | Purpose |
|---|---|---|---|
| GET | `/binance/spot/symbols` | Guest limited | Cached exchange info and valid pairs |
| GET | `/binance/spot/{symbol}/ticker` | Guest limited | 24-hour ticker |
| GET | `/binance/spot/{symbol}/candles` | Guest limited | Validated interval/limit candles |
| GET | `/binance/spot/{symbol}/order-book` | Guest limited | Bounded depth, spread, imbalance/slippage |
| GET | `/binance/spot/{symbol}/trades` | Guest limited | Bounded recent public trades |
| GET | `/binance/spot/{symbol}/technicals` | Guest limited | Deterministic technicals |
| GET | `/binance/spot/{symbol}/risk` | Guest limited | Liquidity/volatility/anomaly risk |
| GET | `/binance/spot/{symbol}/research` | Guest limited | Aggregated partial UI response |

No method under this namespace creates or signs an exchange order.

Product bounds are deliberately smaller than the upstream maxima:

- Candle interval: `1m`, `5m`, `15m`, `1h`, `4h`, `1d`, or `1w`; limit
  50–500.
- Order-book limit: 20, 50, or 100, keeping the upstream request weight at 5.
- Recent-trades limit: 1–200.
- Slippage notional: positive and no more than 1,000,000 quote-asset units.
- Aggregate research may be `partial: true`; unavailable components are `null`
  and named in stable warnings while successful components remain usable.

## 8. Binance Futures (implemented Phase 9)

| Method | Route | Access | Purpose |
|---|---|---|---|
| GET | `/binance/futures/symbols` | Guest limited | Public contract metadata |
| GET | `/binance/futures/status` | Guest limited | Feature flag and cached reachability state |
| GET | `/binance/futures/{symbol}/market` | Guest limited | Mark/index/funding snapshot |
| GET | `/binance/futures/{symbol}/funding` | Guest limited | Current and bounded funding history |
| GET | `/binance/futures/{symbol}/basis` | Guest limited | Bounded perpetual basis history |
| GET | `/binance/futures/{symbol}/open-interest` | Guest limited | Current/history/anomaly |
| GET | `/binance/futures/{symbol}/positioning` | Guest limited | Responsibly available ratios/taker flow |
| GET | `/binance/futures/{symbol}/risk` | Guest limited | Explainable futures risk |
| GET | `/binance/futures/{symbol}/research` | Guest limited | Aggregated partial UI response |

## 9. Reports and jobs (planned Phase 15)

| Method | Route | Access | Purpose |
|---|---|---|---|
| POST | `/reports` | Guest limited/user, idempotent | Queue a structured report |
| GET | `/reports/{report_id}` | Owner or guest capability token | Fetch status/result |
| GET | `/reports` | User | Cursor-paged personal history |
| DELETE | `/reports/{report_id}` | Owner | Delete/anonymize saved report |
| POST | `/reports/{report_id}/feedback` | Owner | Quality/citation feedback |
| GET | `/jobs/{job_id}` | Request owner/admin | Sanitized job state/progress |
| POST | `/jobs/{job_id}/cancel` | Request owner/admin | Best-effort cancellation if allowed |

`POST /reports` returns `202 Accepted`, job/report IDs, generation mode expectation and status URL. A duplicate idempotency key with the same body returns the original result; a different body returns `409 idempotency_conflict`.

## 10. Watchlists, alerts and notifications (planned Phase 16)

| Method | Route | Access | Purpose |
|---|---|---|---|
| POST | `/watchlists` | User | Create list |
| GET | `/watchlists` | User | List own lists |
| GET | `/watchlists/{watchlist_id}` | Owner | Get list and item summaries |
| PATCH | `/watchlists/{watchlist_id}` | Owner | Rename/update |
| DELETE | `/watchlists/{watchlist_id}` | Owner | Delete list/items |
| POST | `/watchlists/{watchlist_id}/items` | Owner | Add normalized unique asset |
| DELETE | `/watchlists/{watchlist_id}/items/{item_id}` | Owner | Remove item |
| POST | `/alerts` | User | Create validated rule |
| GET | `/alerts` | User | List own rules |
| GET | `/alerts/{alert_id}` | Owner | Rule detail |
| PATCH | `/alerts/{alert_id}` | Owner | Update/enable/disable |
| DELETE | `/alerts/{alert_id}` | Owner | Delete rule |
| GET | `/alerts/{alert_id}/events` | Owner | Trigger/delivery history |
| GET | `/notifications` | User | In-app notifications |
| POST | `/notifications/{notification_id}/read` | Owner | Mark read |

## 11. Admin

Only `GET /admin/users`, `PATCH /admin/users/{user_id}`, and
`GET /admin/audit-logs` are implemented through Phase 8. The remaining routes
in this section are planned contracts.

| Method | Route | Access | Purpose |
|---|---|---|---|
| GET | `/admin/overview` | Admin | Sanitized operational dashboard |
| GET | `/admin/providers` | Admin | Health, quota, latency, failures/429s |
| GET | `/admin/jobs` | Admin | Filtered job queue/failures |
| POST | `/admin/jobs/{job_id}/retry` | Admin + idempotency | Retry an eligible failed job |
| GET | `/admin/agent-runs` | Admin | Workflow/agent log catalog |
| GET | `/admin/models` | Admin | Model registry and drift |
| POST | `/admin/models/{model_id}/activate` | Admin + fresh auth | Audited active-model change |
| GET | `/admin/prompts` | Admin | Prompt versions/evaluation status |
| GET | `/admin/rag-quality` | Admin | Retrieval latency/no-result/citation coverage/feedback |
| GET | `/admin/users` | Admin | Paged sanitized users |
| PATCH | `/admin/users/{user_id}` | Admin + fresh auth | Role/status change with self-lockout guard |
| GET | `/admin/feature-flags` | Admin | Flag list |
| PATCH | `/admin/feature-flags/{key}` | Admin + fresh auth | Versioned audited flag update |
| GET | `/admin/audit-logs` | Admin | Filtered append-only audit view |

## 12. Rate limits

The implemented pilot has a Redis-first global API budget of 120 requests per
60 seconds per client address (configurable), plus the stricter authentication
attempt budget of 5 per 15 minutes. Provider-specific quota managers apply
separate ceilings. The classes below are later-phase targets, not all current
enforcement rules.

Exact values are configuration and load-test outputs, but the policy starts with:

| Class | Guest | Authenticated | Notes |
|---|---:|---:|---|
| Auth attempts | 5 / 15 min / IP+identity | Same | Progressive delay; non-enumerating errors |
| Cached research reads | 30 / min | 120 / min | Burst token bucket |
| Provider-refreshing reads | 10 / min | 30 / min | Shared provider quota also applies |
| RAG questions | 3 / day | 30 / day | Monthly provider/CPU budgets apply |
| Reports | 2 / day | 10 / day | Queue and concurrency caps apply |
| Admin mutations | N/A | 30 / hour | Admin only, audit logged |

Provider quota managers may impose stricter limits. A `429` response includes a safe `Retry-After` value.
