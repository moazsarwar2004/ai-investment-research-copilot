# Phase 8 — Official fundamentals and private stock data

## 1. Outcome

Phase 8 makes stock research useful without bypassing market-data display rights.
It keeps regulatory/company-report data independent from price data and exposes
four explicit source modes:

| Mode | Meaning |
| --- | --- |
| `licensed_provider` | Current or delayed market research under reviewed display rights |
| `user_supplied` | Owner-private analysis of a legally obtained OHLCV CSV |
| `official_reports` | SEC or operator-verified PSX/SECP/company-report fundamentals |
| `offline_demo` | Dated demonstration fixtures, never represented as current |

The stock aggregate can be partial. Missing quotes never suppress available
company profiles, financial periods, ratios, reports, or fundamental risk.

## 2. Official fundamentals

One normalized contract covers SEC and Pakistani official-report sources:

- Company identity, exchange, currency, country, sector/industry and source ID.
- Annual/quarterly period, currency, revenue, cost/gross/operating profit, net
  income, EPS, assets, liabilities, equity, debt, cash and cash flows.
- Annual, quarterly, announcement, 10-K, 10-Q and 8-K report links.
- Source URL and source label on every financial period.
- Null values for missing facts; zero is never substituted.

Ratios are deterministic and versioned. Growth compares like fiscal periods
(FY-to-FY, Q1-to-Q1), not adjacent mixed periods. Corporate risk uses
leverage/liquidity, earnings stability and source warnings. Bank mode disables
corporate current-ratio/debt-to-equity logic and uses bank-specific income,
deposit, financing, equity/assets, ROA/ROE, and capital inputs where available.
Both remain transparent historical heuristics, not forecasts or recommendations.

SEC periods are built from one coherent accession and duration context. Q2/Q3
quarter-only facts are not mixed with six- or nine-month facts, and every
normalized field retains concept, unit, accession, form, filed date, period and
frame evidence. ROA/ROE use comparable average positive balances; non-positive
equity is treated explicitly instead of producing a reassuring negative ratio.

## 3. SEC adapter

SEC support uses only official endpoints:

- `www.sec.gov/files/company_tickers.json`
- `data.sec.gov/submissions/CIK##########.json`
- `data.sec.gov/api/xbrl/companyfacts/CIK##########.json`

It is disabled by default. Activation requires `SEC_ENABLED=true` and an
identifying `SEC_USER_AGENT` containing an application name and monitored email.
The initial local ceilings are 5 requests/second and 300 requests/minute, below
the SEC published maximum. Phase 8 production runs one API worker; quota/circuit
state must move to Redis before horizontal scaling. Provider caching, allowlisted hosts, response-size bounds,
timeouts, retry/backoff, circuit breaking and stale fallback remain active.

Company Facts normalization retains only supported 10-K/10-Q facts, resolves
duplicates deterministically by filing date/amendment, and filters comparative
facts repeated years later. Every period links back to its EDGAR accession.

## 4. Pakistan official-report manifest

No stable, reviewed PSX/SECP financial-statements API was enabled. The runtime
therefore never scrapes websites. An operator can configure
`STOCK_FUNDAMENTALS_MANIFEST_PATH` with a version-2 JSON manifest containing
official company investor-relations report links and normalized facts. The
complete file is schema-validated, limited to 8 MiB, hashed, and loaded
fail-closed. Only entries approved by a named human reviewer are published;
candidate and rejected companies remain unavailable. Validation covers allowed
HTTPS hosts, document hashes/pages, statement basis, per-fact reported
value/unit/scale, duplicate periods, unit conversion, and accounting
consistency. An illustrative schema is in
[`examples/stock_fundamentals_manifest.example.json`](examples/stock_fundamentals_manifest.example.json).

Real SYS and MEBL records were human-approved on 2026-09-27 and the approved
manifest passes the fail-closed production publication gate. See
[`psx_integration.md`](psx_integration.md) and
[`psx_manifest_review.md`](psx_manifest_review.md). Coverage is explicit per
company; an absent or unapproved company returns a typed unavailable result.

## 5. Private price CSV

Authenticated users can upload UTF-8 CSV content with exactly:

```csv
date,open,high,low,close,volume
2026-01-01,100,105,98,103,500000
```

Controls:

- 1 MiB maximum; 20–1,500 rows; at most 1,825 days.
- ISO `YYYY-MM-DD`, finite positive OHLC, non-negative volume, unique dates and
  internally consistent highs/lows.
- A source label and aware source timestamp; no future source or candle date.
- Bearer authentication and an `owner_user_id` predicate on every read/delete.
- Database cascade on account deletion and unique owner+asset+content hash.
- Per-user, per-asset and total-row budgets; owner-serialized quota checks.
- Retention cleanup and append-only create/delete audit events.
- Daily or near-daily cadence plus bounded magnitude and decimal precision.
- Original bytes are not retained; validated normalized candles are stored.
- Response and UI always say `user_supplied`, `owner_private` and unverified.

The existing Phase 7 SMA/EMA, RSI, MACD, Bollinger, ATR, momentum, volatility,
drawdown, support/resistance, trend and risk engine is reused unchanged.

## 6. API and UI

Public official-data routes:

- `GET /api/v1/stocks/{symbol}/financials`
- `GET /api/v1/stocks/{symbol}/ratios`
- `GET /api/v1/stocks/{symbol}/filings`
- `GET /api/v1/stocks/{symbol}/research`

Authenticated upload routes:

- `POST/GET /api/v1/stocks/{symbol}/price-uploads`
- `GET/DELETE /api/v1/stocks/{symbol}/price-uploads/{upload_id}`

The Streamlit page prioritizes Company, Financial performance, Ratios, Reports
and announcements, and Fundamental risk. One banner explains unavailable
market prices. The private upload control signs in through the existing identity
API, rotates refresh tokens, revokes logout server-side, and keeps tokens only in
Streamlit session memory. Users can reopen or delete their saved private uploads.

A deterministic evidence assistant answers four bounded questions from the
loaded structured response and downloads a cited Markdown brief. It is not
presented as free-form RAG or LLM output; filing RAG remains Phase 13.

## 7. Exit evidence

- Official fundamentals remain available while quote/candle fields are null.
- SEC ticker, submissions and Company Facts recorded-shape tests make no network
  calls and validate report links and repeated comparative facts.
- Ratio/risk golden tests verify like-period growth and reproducibility.
- CSV tests cover exact schema, minimum rows, invalid OHLC, idempotency, Phase 7
  technical reuse and cross-owner denial.
- API documentation includes official and private routes.
- UI fixture test verifies the fundamentals-first unavailable mode.

Focused verification:

```powershell
python -m pytest -q `
  backend/app/tests/test_stock_fundamentals.py `
  backend/app/tests/test_sec_provider.py `
  backend/app/tests/test_stock_uploads.py `
  backend/app/tests/test_stock_analytics.py `
  backend/app/tests/test_stock_service.py `
  backend/app/tests/test_stock_api.py `
  backend/app/tests/test_research_brief.py `
  backend/app/tests/test_frontend_state.py
```

## 8. Deferred boundaries

- Automatic Pakistani report discovery waits for a documented official API or
  explicit permission; the reviewed manifest remains the safe fallback.
- Arbitrary PDF/Excel user uploads remain deferred.
- Filing section extraction, embeddings, BM25/vector retrieval and cited Q&A
  remain Phase 13.
- External real-time, delayed, EOD, and historical stock data remain disabled
  until the exact data class and written display/derived-data rights are
  recorded by the license gate.

## 9. Production-pilot boundary

The repository includes a non-root image, private-network production Compose,
Caddy HTTPS ingress, immutable image workflow, smoke check and backup/restore
runbook. These are reproducible delivery preparation, not proof of a live
deployment. Real user onboarding/email, a deployment host, external monitoring,
off-host encrypted backups and a restore exercise remain launch gates documented
in `deployment.md` and `operations.md`.
