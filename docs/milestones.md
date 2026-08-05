# Milestone and Phase Plan

## 1. Delivery rule

Phases remain sequential as requested. A later phase may be discussed, but implementation does not begin until the current phase's exit evidence passes. Each phase ends with code/docs/tests, a demo command, expected output, common-error notes, a checklist and a recommended commit message.

## 2. Phase gates

| Phase | Objective | Required implementation/evidence | Exit gate |
|---:|---|---|---|
| 0 | Freeze a feasible production plan | Requirements, diagrams, ERD, routes, provider/free-tier matrix, risks, milestones and validation | All Phase 0 document checks pass; stock/hosting constraints accepted as explicit gates |
| 1 | Establish local foundation | Repository structure, Python 3.12 environment, dependencies, FastAPI config/logging/errors, `/livez`, initial tests and lint/type config | App starts on Windows; health API and unit tests pass; no secrets committed |
| 2 | Add durable infrastructure | Compose, pgvector Postgres, Redis, async SQLAlchemy, Alembic, cache primitives, readiness detail | Fresh Compose up/migrate/down/up preserves DB; Redis loss/fallback test passes |
| 3 | Secure identity and authorization | User/session/audit schemas; registration/login/refresh/logout/reset/verification; Argon2id; RBAC/ownership | Token rotation/replay, rate-limit, admin and cross-user denial tests pass |
| 4 | Build provider framework | Async HTTP client, adapters, normalization, provenance, quota, retry/backoff, circuit breaker, cache/locks | Mocked timeout/429/schema-change/stale-cache tests pass with no live provider dependency |
| 5 | Deliver Binance Spot MVP | Public ticker/candles/book/trades, analytics/liquidity/risk, first Streamlit research page | Mock/API contract tests, symbol/weight controls and UI loading/error/stale states pass |
| 6 | Add general crypto | Coin search/global/overview/history, analytics/anomalies/risk and quota budget | Terms recheck, call-budget test, symbol ambiguity test and cached UI demo pass |
| 7 | Add stocks | Exchange-neutral provider abstraction; PSX-default search/profile/quote/candles when licensed; technicals, risk and UI | External-display license recorded or quote stays unavailable; exchange-identity and SEC-independent tests pass |
| 8 | Add SEC and fundamentals | Ticker/CIK, submissions, filing download/parse/sections, XBRL statements/ratios/comparison/risk | User-Agent/rate controls, representative filings, amended facts and source-link tests pass |
| 9 | Add Binance Futures | Public mark/index/funding/OI/basis/positioning, anomalies/risk and disclaimer | Jurisdiction/reachability gate, mocked provider tests and no-trading surface audit pass |
| 10 | Complete deterministic analytics | Indicators, ratios, volatility/drawdown, trend/risk/anomaly rules, validation/source verification | Golden datasets, edge cases, missing-input renormalization and reproducibility tests pass |
| 11 | Add measured ML | Features, temporal splits, trend classifier, optional Isolation Forest, artifacts/inference/fallback | No-leakage test and baseline comparison; activate only if it beats documented rules |
| 12 | Operationalize ML | Dataset/feature versions, MLflow, registry metadata, active selection, drift/evaluation/retraining job | Reproduce an experiment, checksum artifact, switch/rollback model and raise drift alert |
| 13 | Build SEC RAG | Content hashes, chunks, local embeddings, pgvector, BM25, merge/rerank/citations and retrieval-only answers | Labeled retrieval evaluation, metadata isolation, weak-evidence and citation-integrity tests pass |
| 14 | Add Ollama and LLMOps | Benchmarked small model, prompt registry, structured schemas, injection/citation guards, monitoring/fallback | Target hardware benchmark and adversarial/evaluation dataset pass; fallback demonstrated |
| 15 | Add reports and agents | Agent state/workflow, logged stages, async idempotent reports, template/local modes | Retry/idempotency/partial-agent failure tests and source-complete report demo pass |
| 16 | Add watchlists and alerts | CRUD/ownership, scheduler evaluation, fingerprints/cooldowns, events/in-app notifications, optional email | Cross-user denial, duplicate-worker, cooldown and missed-worker recovery tests pass |
| 17 | Complete frontend | All requested screens, responsive source/freshness cards, role protection and UI states | Guest/user/admin end-to-end journeys and accessibility/basic responsive checks pass |
| 18 | Add observability | Metrics/logs/traces, dashboards, provider/model/RAG/LLM views, external monitors/heartbeats | Synthetic failure appears in dashboard/alert without leaking secrets; cardinality budget passes |
| 19 | Harden security/reliability | Headers/CORS/body/rates, audit/redaction, secrets, backup/restore, failure simulations and runbooks | Security scan, provider/Redis/DB/Ollama/worker failures, backup restore and incident drill pass |
| 20 | Automate production delivery | Multi-arch images, production Compose/Caddy/DNS/HTTPS, GitHub Actions deploy, migrations, health/rollback/smoke | Live HTTPS pilot, persistent data, external checks, immutable release and rollback exercise pass |

## 3. Milestone grouping

### M0 — Approved design (Phase 0)

Outcome: no application code, but a complete implementation contract and known external gates.

### M1 — Secure platform core (Phases 1–4)

Outcome: locally runnable, tested API with persistent storage, queue/cache, authentication, authorization and resilient provider plumbing.

### M2 — Deterministic research MVP (Phases 5–10)

Outcome: Binance Spot/Futures, crypto, conditionally licensed stock pricing, SEC/fundamentals and complete non-LLM analytics. This is the first meaningful research product and must remain functional without ML/Ollama.

### M3 — ML, RAG and reports (Phases 11–15)

Outcome: only models that improve measured baselines, evidence-first SEC Q&A and guarded asynchronous reports with deterministic fallbacks.

### M4 — Multi-user product and operations (Phases 16–19)

Outcome: complete user workflows, alerts, admin UI, observability, security controls, backups and failure recovery.

### M5 — Live production pilot (Phase 20)

Outcome: portable, HTTPS, monitored, persistent, automatically deployable and recoverable system on a verified free host or approved fallback.

## 4. Test evidence required at every phase

- Unit tests for domain functions and validation.
- Integration tests for database/Redis boundaries added in that phase.
- API tests for success, authorization, invalid input, rate limits and dependency failures.
- Provider tests use recorded/synthetic fixtures, never required live calls in normal CI.
- Structured log/metric assertions for new operational paths.
- Swagger or scripted smoke command and expected response.
- Frontend loading/empty/error/stale states for every new UI surface.
- Documentation and migration review.

## 5. Release branches and commits

Use small reviewable commits within a phase, then one phase-completion commit. Suggested Phase 0 commit:

```text
docs: establish phase 0 production planning baseline
```

Never tag a phase complete solely because code exists; the exit-gate evidence is part of the deliverable.
