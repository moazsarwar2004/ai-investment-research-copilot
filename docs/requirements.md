# Final Requirements Baseline

Baseline ID: `REQ-2026-07-13-P0`  
Change rule: changes after approval require a documented decision, affected tests and an updated risk entry.

## 1. Product statement

AI Investment Research Co-Pilot is a source-backed research and education application for approximately 5–15 users. It combines deterministic market and financial analytics, SEC evidence retrieval, asynchronous reports and explainable risk outputs. It never executes trades and never promises or personalizes returns.

Every research view and generated report must show a financial disclaimer, source attribution, source timestamp, fetch timestamp, cache state, freshness state, staleness and missing-data limitations.

## 2. User roles

| Capability | Guest | Registered user | Admin |
|---|---:|---:|---:|
| Home and public service status | Yes | Yes | Yes |
| Limited stock/crypto/Binance research | Quota limited | Yes | Yes |
| Limited RAG questions/reports | Quota limited | Yes | Yes |
| Watchlists, alerts, saved reports | No | Own resources | Own resources |
| Personal alert/report history | No | Own resources | Own resources |
| Provider/job/model/agent monitoring | No | No | Yes |
| Retry jobs and manage users/flags | No | No | Yes, audited |

Backend dependencies enforce every role and ownership rule. Frontend visibility is only a usability aid.

## 3. Required product surfaces

### 3.1 Home

- Introduction, feature summary, research-only disclaimer and data-source/freshness explanation.
- Quick actions for Microsoft, Apple, Tesla, Bitcoin, Ethereum, BTC/USDT spot, BTCUSDT futures and SEC questions.
- Popular assets and public provider-degradation status without exposing internal topology.

### 3.2 Stock research

- Symbol/company search, company profile, exchange, sector and industry.
- Latest legally displayable quote, OHLC, previous close, high/low, 52-week range, change, volume and market cap when available.
- Historical line/candlestick/volume charts.
- SMA 20/50/200, EMA 12/26, RSI, MACD/signal/histogram, Bollinger Bands, ATR, ROC, momentum, historical volatility, maximum drawdown, support and resistance.
- SEC-derived statements for revenue, profits, income, EPS, assets, liabilities, equity, cash, debt, operating cash flow, capex and free cash flow.
- Deterministic margins, returns, liquidity, leverage, coverage, turnover and growth ratios.
- SEC filings, filing risks, trend, anomalies and explainable stock risk.
- If no display-licensed quote provider is configured, fundamentals and filing research still work while quote fields explicitly report unavailable.

### 3.3 SEC filing intelligence and RAG

- Discover, download, hash, deduplicate, parse, clean, section, chunk and embed 10-K, 10-Q and 8-K filings.
- Extract Risk Factors, MD&A, Liquidity, Legal Proceedings, Market Risk, Cybersecurity and Material Events.
- Compare the latest and previous filing; identify added, removed and materially changed evidence.
- Hybrid dense + BM25 retrieval, metadata filters, reranking, evidence-first answer, optional local summary.
- Every answer supplies filing type/date/section/source, retrieved excerpts, retrieval score/confidence and answer mode.
- Weak evidence returns an explicit insufficient-evidence result.
- Retrieved text is data, never an instruction. Citations must resolve to retrieved chunks.

### 3.4 General crypto

- Search by provider ID, name or symbol; resolve symbol ambiguity explicitly.
- Price, rank, market cap, FDV, volume, supply, 24-hour range, ATH/ATL and distance from ATH.
- History, technicals, volatility, drawdown, trend, anomalies, explainable crypto risk, source and freshness.
- Global market cap/volume, BTC and ETH dominance, trending assets and gainers/losers when the provider plan supplies them.

### 3.5 Binance Spot

- Validated symbols; public ticker, candles, trades and order book for 1m, 5m, 15m, 1h, 4h, 1d and 1w intervals.
- Price/OHLC/change/volumes/trade count, spread, depth, imbalance, estimated slippage, liquidity, pressure and large-trade anomalies.
- Binance/global-price comparison, deterministic technicals and spot risk.
- No authenticated trading endpoints or user exchange keys.

### 3.6 Binance Futures

- Public contract, mark/index/spot price, funding/history/next funding, open interest/history, basis, premium/discount, taker flow and responsibly available ratio data.
- Crowding and anomaly analysis plus deterministic futures risk and a prominent leverage warning.
- No order, account, position or leverage endpoint.

### 3.7 Reports

- Asynchronous generation with executive summary, market snapshot, technical/fundamental view, bull/bear cases, risks, anomalies, risk explanation, confidence, freshness, sources, missing inputs and disclaimer.
- Modes: `local_llm`, `template_fallback`, or `cached`.
- The local LLM receives only verified structured input and must pass schema/citation validation.
- Idempotency and report caching prevent duplicate expensive jobs.

### 3.8 Watchlists and alerts

- Multiple user-owned watchlists containing stocks, crypto assets, Binance spot pairs and futures contracts.
- Price/trend/risk/risk-change/anomaly/latest-filing summary.
- Alert rules for price, percentage change, RSI, risk, volume, volatility, filings, funding, open interest, spread, liquidity and order-book imbalance.
- In-app events are mandatory; email is optional and configuration-gated.
- Cooldown and a deterministic event fingerprint prevent duplicates.

### 3.9 Admin and agent logs

- Provider, database, Redis, worker, scheduler and Ollama health; freshness; cache ratio; requests/errors/p95; queue/failures; model/drift/RAG/LLM/fallback measurements.
- Job retry, user/feature-flag management and audit history.
- Agent run fields include workflow/agent/asset/status/times/duration/provider/cache/retries/model/prompt/error code and sanitized error text.
- Secrets, passwords, tokens, cookies and authorization headers are always redacted.

## 4. Deterministic analytics

### 4.1 Risk response contract

Every score returns:

```text
overall_score, risk_label, component_scores, component_weights,
methodology_version, data_confidence, missing_inputs, limitations
```

Scores are bounded 0–100, reproducible from stored inputs and independent of an LLM. Missing components are omitted, available weights are renormalized to 1.0, and confidence decreases according to data coverage and freshness.

Initial weights:

| Model | Components |
|---|---|
| Stock | volatility 25%, drawdown 20%, leverage/liquidity 20%, earnings stability 15%, filing risk 10%, technical trend risk 10% |
| Crypto | volatility 30%, drawdown 20%, liquidity 15%, market-size risk 15%, trend instability 10%, anomaly risk 10% |
| Futures | volatility 25%, funding extremity 20%, open-interest anomaly 20%, crowding 15%, basis 10%, liquidity 10% |

### 4.2 Trend and anomaly outputs

- Trend classes are `bullish`, `neutral`, `bearish`, with probabilities, confidence, prediction horizon and model/rule version.
- Time-series splits are oldest 70% training, next 15% validation and latest 15% testing; no random future leakage.
- Anomaly layers are deterministic rules, rolling z-score/baseline and optional Isolation Forest.
- Rule-based trend/anomaly fallbacks remain available whenever model artifacts are missing, stale or invalid.

## 5. Data and freshness contract

All provider-backed API payloads include:

```json
{
  "data": {},
  "meta": {
    "request_id": "uuid",
    "source": "provider_name",
    "source_timestamp": "UTC timestamp or null",
    "fetched_at": "UTC timestamp",
    "cache_status": "miss|hit|stale|bypass",
    "freshness": "live|delayed|cached|stale|unavailable",
    "staleness_seconds": 0,
    "partial": false,
    "warnings": []
  }
}
```

Soft TTL permits background refresh while serving a still-valid value. Hard TTL forbids a cache entry from being presented as current. Stale fallback is allowed only with a prominent stale badge and the original timestamps.

Planned TTL ranges:

| Data | Soft TTL | Hard TTL |
|---|---:|---:|
| Binance ticker | 15 s | 30 s |
| Binance order book | 5 s | 10 s |
| Binance candles | 1 min | 5 min |
| Crypto overview | 3 min | 5 min |
| Stock quote | 10 min | 15 min |
| Daily stock candles | 30 min | 60 min |
| Financial statements | 12 h | 24 h |
| SEC filing index | 2 h | 6 h |
| Parsed filing/embedding | Content-addressed permanent | Replaced only by a new content hash |
| Report | 1 h | 6 h |

## 6. Reliability and performance objectives

These are engineering targets, not a commercial SLA:

| Objective | Target |
|---|---|
| Intended availability | 24/7, 99.0% monthly internal target excluding upstream outages |
| Cached read latency | p95 under 750 ms at 10 concurrent users |
| Uncached provider request | p95 under 5 s or a bounded partial/stale response |
| Async job acceptance | p95 under 750 ms |
| Standard report completion | p95 under 120 s when Ollama is healthy; template fallback under 20 s |
| Error rate | Under 1% for first-party 5xx over 15 minutes |
| RPO / RTO | 24 hours / 4 hours |
| Backups | Daily; 7 daily, 4 weekly, 3 monthly; monthly restore test |
| Load target | 5–15 active users, approximately 10 concurrent, cache-heavy reads |

External calls have explicit connect/read/write/pool timeouts, bounded exponential backoff with jitter, `Retry-After` support, a circuit breaker and a total deadline. Heavy POST requests require `Idempotency-Key`.

## 7. Security requirements

- Argon2id password hashes with tunable parameters and automatic rehash.
- Short-lived access tokens and one-time rotating refresh tokens; only refresh-token hashes are stored. Reuse revokes the token family.
- Email verification and password-reset tokens are random, hashed, single-use and expiring.
- Resource ownership and role checks occur in services/dependencies before repository calls.
- HTTPS, HSTS after validation, secure headers, strict CORS allowlist, same-origin production routing and request body limits.
- Secure cookie attributes where cookies are used; Streamlit never stores tokens in browser local storage. Tokens held by the frontend remain in server-side session memory and are redacted from logs.
- Per-IP guest limits and per-user authenticated limits; stricter quotas for reports, RAG and authentication.
- Parameterized SQLAlchemy statements, Pydantic validation, HTML sanitization and controlled outbound hosts.
- CSRF protection for cookie-authenticated state changes; idempotency for heavy writes.
- Audit registration/login/logout/reset, role changes, admin actions, job retries, alert/report deletion and feature-flag changes.
- Database, Redis, Ollama, MLflow, telemetry and metrics are private-network only.
- GitHub push protection/secret scanning where available, Gitleaks, dependency audit and Trivy image scanning in CI.

## 8. MLOps and LLMOps requirements

- Version datasets, feature definitions, training configuration and evaluation output.
- Track model name/version, training date, period, features, hyperparameters, metrics, artifact, active state and drift.
- MLflow tracks experiments; the application database controls approved active-model selection.
- Inference logs model/rule version and confidence without raw sensitive user input.
- Drift jobs compare recent features with the training baseline and create admin-visible status.
- Version prompts, validate structured output and citations, cap context, detect prompt injection patterns and record latency/failure/fallback counts.
- Ollama unavailability must never make price, technical, risk, alert or template-report paths unavailable.

## 9. Operations and delivery

- Development and production Docker Compose files, health checks and `restart: unless-stopped` on production services.
- Caddy is the only public ingress on ports 80/443.
- PostgreSQL, Redis and Ollama data live on persistent volumes; generated artifacts have explicit retention.
- Prometheus-format metrics, JSON logs and OpenTelemetry traces flow through an internal collector/agent.
- External monitors cover frontend, liveness, readiness, worker, scheduler, backup, SEC sync and TLS expiry.
- CI runs formatting/lint/type/test/security/secret/image checks using mocked providers.
- Releases use immutable semantic or commit-SHA image tags, run migrations, health-check, and roll back application images on failure. Database migrations must be backward-compatible across one release.
- Daily `pg_dump` output is compressed, client-side encrypted and uploaded to remote object storage; restores are documented and exercised.

## 10. Definition of done

A feature is complete only when its schema/migration, provider/repository, service, thin route, validation, cache, timeout/retry, fallback, provenance/freshness metadata, tests, UI states, logs/metrics and documentation are implemented and verified. A production feature also requires a license/terms check for every displayed third-party dataset.

## 11. Acceptance caveat

The zero-cost requirement and a multi-user stock quote display are not currently proven compatible. Phase 7 may not be marked production-complete until a provider grants suitable display rights. This does not block SEC filing/fundamental research, the provider abstraction, or the rest of the platform.

