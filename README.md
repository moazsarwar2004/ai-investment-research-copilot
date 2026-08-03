# AI Investment Research Co-Pilot

[![CI](https://github.com/moazsarwar2004/ai-investment-research-copilot/actions/workflows/ci.yml/badge.svg)](https://github.com/moazsarwar2004/ai-investment-research-copilot/actions/workflows/ci.yml)

AI Investment Research Co-Pilot is a source-backed research and education
platform for stocks, cryptocurrency, Binance markets, and SEC filings. It is
being developed as a production-oriented modular monolith for a small multi-user
pilot, with deterministic analytics, evidence retrieval, explainable risk,
asynchronous reports, alerts, and operational monitoring designed to evolve
through explicit release gates.

> **Current release:** `0.5.0` — Binance Spot research MVP. Phases 0–5 are
> complete, and Phase 6 (general crypto) is next. Public Spot market data,
> deterministic analytics, and the first Streamlit research page are available.

This software is for research and education only. It does not execute trades,
store exchange trading keys, provide personalized financial advice, or promise
returns.

## Project goals

The completed product is intended to provide:

- Stock research with price history, technical indicators, SEC-derived
  fundamentals, filing comparisons, and explainable risk.
- SEC filing intelligence with evidence-first retrieval, hybrid vector/BM25
  search, resolvable citations, and explicit insufficient-evidence responses.
- General cryptocurrency research plus Binance Spot and Futures market
  analytics using public, read-only endpoints.
- Deterministic trend, anomaly, volatility, drawdown, liquidity, and risk
  calculations that remain usable without an LLM.
- Source-aware reports showing provider, timestamps, cache/freshness state,
  missing inputs, limitations, and a financial disclaimer.
- User-owned watchlists, alerts, saved reports, in-app notifications, and
  role-protected administration.
- Measured ML, local Ollama assistance, monitoring, backups, and portable
  production deployment only after their documented phase gates pass.

The project deliberately excludes automated trading, real-money order
execution, personalized recommendations, guaranteed signals, and unofficial
scraped finance endpoints.

## Current progress

| Workstream | Status | Result |
| --- | --- | --- |
| Phase 0 - Production plan | Complete | Requirements, architecture, data model, APIs, provider constraints, risks, and 21-phase delivery plan |
| Phase 1 - API foundation | Complete | FastAPI application factory, validated settings, structured logging, request IDs, security middleware, errors, health endpoints, and tests |
| Phase 2 - Durable infrastructure | Complete | PostgreSQL/pgvector, Redis, async SQLAlchemy, Alembic, cache primitives, lifecycle management, readiness policy, and real-service tests |
| Continuous integration | Complete | Automated quality and PostgreSQL/Redis integration jobs on pushes and pull requests |
| Phase 3 - Identity and authorization | Complete | Users, sessions, Argon2id, JWT access, rotating refresh tokens, replay revocation, RBAC, ownership, rate limits, and append-only audits |
| Phase 4 - Provider framework | Complete | Async HTTP, strict adapters, normalization/provenance, quotas, retry/backoff, circuits, locks, and stale fallback |
| Phase 5 - Binance Spot MVP | Complete | Public symbols, ticker, candles, depth, trades, deterministic analytics/risk, and first Streamlit research page |
| Phases 6-20 | Planned | Remaining research modules, ML, RAG, reports, alerts, full frontend, observability, hardening, and deployment |

Six of the 21 planned delivery phases are complete. Detailed exit gates are in
[`docs/milestones.md`](docs/milestones.md).

## Architecture

The target is a modular monolith: one Python codebase with clear internal
boundaries, deployed as separate API, worker, and scheduler processes when those
phases are implemented.

```mermaid
flowchart LR
    Client["API clients + first<br/>Streamlit research page"] --> API["FastAPI backend<br/>implemented"]
    API --> PostgreSQL[("PostgreSQL 17 + pgvector<br/>implemented")]
    API --> Redis[("Redis cache<br/>implemented")]
    API --> ProviderFramework["Provider resilience framework<br/>implemented"]
    ProviderFramework --> Binance["Binance Spot public API<br/>implemented"]
    ProviderFramework -. "later adapters" .-> Providers["Crypto + stock + SEC providers"]
    Workers["Celery workers + scheduler<br/>planned"] -.-> PostgreSQL
    Workers -.-> Redis
    Workers -. "planned" .-> Ollama["Local embeddings + Ollama"]
    API -. "planned" .-> Observability["Metrics, traces, dashboards"]
```

PostgreSQL is the durable system of record. Redis is disposable acceleration;
losing Redis must not lose user-owned data. Deterministic analytics remain the
correctness layer, while ML and local LLM features must degrade to documented
fallbacks.

## Technology stack

| Area | Technology | Status |
| --- | --- | --- |
| Language and API | Python 3.12, FastAPI, Uvicorn | Implemented |
| Validation and settings | Pydantic, pydantic-settings | Implemented |
| Database | PostgreSQL 17, pgvector, async SQLAlchemy, asyncpg | Implemented |
| Migrations | Alembic | Implemented |
| Cache | Redis with versioned JSON envelopes and soft/hard TTL | Implemented |
| Local infrastructure | Docker Desktop and Docker Compose | Implemented |
| Testing and quality | pytest, pytest-asyncio, Ruff, Black, MyPy | Implemented |
| Automation | GitHub Actions | Implemented |
| Frontend | Streamlit | First Binance Spot research page implemented |
| Background work | Celery workers and scheduler | Planned |
| Provider resilience | HTTPX, strict Pydantic adapters, quotas, retries, circuits, cache locks | Implemented |
| Research and AI | Binance Spot adapters and deterministic analytics implemented; remaining providers, ML, RAG, and Ollama planned | In progress |
| Production operations | Caddy, OpenTelemetry, Grafana Cloud, uptime checks, encrypted backups | Planned by phase |

## Implemented through v0.5.0

- Strict FastAPI application configuration with development, testing, staging,
  and production modes.
- Structured JSON logging, request correlation IDs, bounded public error
  responses, CORS validation, and browser security headers.
- Liveness and dependency-aware readiness endpoints.
- PostgreSQL/pgvector and Redis with pinned container images, loopback-only host
  ports, health checks, and persistent named volumes.
- Separate migration and runtime database roles for local development.
- Async database sessions, bounded connection pools, independent readiness
  probes, and clean shutdown handling.
- Redis cache keys, schema-versioned values, freshness metadata, soft/hard TTL,
  corrupt-entry eviction, and safe cache bypass during Redis outages.
- Alembic migrations for pgvector plus users, rotating sessions, and
  append-only audit records.
- Argon2id password hashing, short-lived signed access tokens, one-time refresh
  rotation, family-wide replay revocation, email verification, password reset,
  logout, and session management.
- Database-backed user/admin authorization, fresh-auth admin mutations,
  owner-scoped session queries, and Redis-first authentication throttling with
  a bounded in-process fallback.
- Lifecycle-owned async provider HTTP client with exact HTTPS host allowlists,
  bounded deadlines/retries, `Retry-After`, response-size limits, and safe URL
  provenance.
- Provider-neutral adapter, normalization, freshness, warning, quota, circuit
  breaker, token-lock, single-flight, and stale-cache fallback contracts.
- Public, market-data-only Binance Spot adapters for exchange metadata, 24-hour
  ticker, UTC candles, bounded order-book depth, and bounded recent trades.
- Pair validation from cached exchange metadata, exact endpoint weights,
  authoritative usage-header reconciliation, and a conservative local
  per-minute weight budget with interactive reserve.
- Deterministic SMA/EMA/RSI/ATR/volatility/trend analytics, spread/depth/
  imbalance/slippage analytics, trade pressure/large-trade anomalies, and an
  explainable Spot risk score with missing-input weight renormalization.
- Eight read-only Binance Spot API routes, including partial-tolerant aggregate
  research with freshness, provenance, limitations, and a research disclaimer.
- First Streamlit research page with loading, empty, error, partial, and stale
  states plus price, technical, liquidity, trade, and risk views.
- Unit, API, failure-mode, and real infrastructure integration tests.
- GitHub CI for formatting, linting, types, tests, Compose validation, migrations,
  and real PostgreSQL/Redis verification.

General crypto, stock/SEC research, Futures, later analytics, ML, RAG, reports,
alerts, the complete frontend, and deployment remain gated to later phases.

## Repository structure

```text
.
|-- .github/workflows/       GitHub Actions CI
|-- alembic/                 Database migration environment and revisions
|-- backend/app/
|   |-- analytics/           Deterministic indicators, liquidity, anomaly, and risk calculations
|   |-- api/                 HTTP routes
|   |-- cache/               Redis cache contracts
|   |-- core/                Configuration, logging, errors, security, lifecycle
|   |-- database/            Async SQLAlchemy engine and sessions
|   |-- models/              Durable identity and audit ORM models
|   |-- repositories/        Persistence-only query boundaries
|   |-- schemas/             Strict HTTP identity contracts
|   |-- services/            Identity use cases and authorization decisions
|   |-- providers/           HTTP, adapters, provenance, quotas, circuits, fallback
|   |-- middleware/          Request ID, logging, and security headers
|   `-- tests/               Unit, API, and infrastructure tests
|-- frontend/                Streamlit Binance Spot research page and API client
|-- docs/                    Requirements, architecture, roadmap, and phase evidence
|-- infrastructure/          Container initialization scripts
|-- compose.yaml             Local PostgreSQL/pgvector and Redis services
|-- pyproject.toml           Package and tool configuration
`-- requirements*.txt        Runtime and development dependencies
```

## Quick start

### Prerequisites

- Windows PowerShell
- Python 3.12
- Docker Desktop with Linux containers and Compose v2
- Git

### 1. Create the Python environment

Run from the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

If activation is blocked, allow it only for the current PowerShell process:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

The committed `.env.example` contains documented local-only defaults. A real
`.env` is ignored by Git. Replace every credential before any shared or
internet-facing deployment.

### 2. Start and migrate the infrastructure

```powershell
docker compose up -d --wait
docker compose ps
python -m alembic upgrade head
```

`docker compose down` stops the services without deleting their named volumes.
Do not add `-v` unless you intentionally want to erase the local database and
cache volumes.

### 3. Run the API

```powershell
python -m uvicorn backend.app.main:app --reload
```

Open:

- API information: `http://127.0.0.1:8000/`
- Swagger UI: `http://127.0.0.1:8000/docs`
- Liveness: `http://127.0.0.1:8000/livez`
- Readiness: `http://127.0.0.1:8000/readyz`
- Versioned health: `http://127.0.0.1:8000/api/v1/health`

### 4. Run the Binance Spot research page

Keep the API running, then open a second PowerShell terminal:

```powershell
.\.venv\Scripts\Activate.ps1
python -m streamlit run frontend/app.py
```

Open `http://127.0.0.1:8501`. The page calls only the local API; the API uses
Binance's public market-data-only host and never accepts an exchange key.

`/livez` never calls external dependencies. `/readyz` returns HTTP 503 when
PostgreSQL is unavailable, while a Redis-only failure remains HTTP 200 with
`redis: degraded` because cache acceleration is disposable.

## Testing

The default test suite is deterministic and does not call live market-data
providers. Run the fast local quality gates:

```powershell
python -m ruff check .
python -m black --check .
python -m mypy backend
python -m pytest -m "not integration"
python -m pip check
python -m alembic upgrade head --sql
docker compose config --quiet
```

Run the focused Phase 4 provider-resilience tests:

```powershell
python -m pytest -q `
  backend/app/tests/test_provider_http.py `
  backend/app/tests/test_provider_controls.py `
  backend/app/tests/test_provider_manager.py
```

These tests cover timeouts, `429` and `Retry-After`, schema drift, stale cache
fallback, circuit breaking, quota reservation, provenance, outbound host
controls, and single-flight refreshes without requiring a live provider.

Run the focused Phase 5 Binance Spot tests:

```powershell
python -m pytest -q `
  backend/app/tests/test_binance_spot_provider.py `
  backend/app/tests/test_binance_spot_analytics.py `
  backend/app/tests/test_binance_spot_service.py `
  backend/app/tests/test_binance_spot_api.py `
  backend/app/tests/test_frontend_state.py
```

All provider responses are recorded-shape fixtures. Normal tests never call
Binance or require an API key. The frontend test also renders the initial
Streamlit page and asserts that it contains no script exception.

After Compose is healthy and the migration is applied, run the real
PostgreSQL/Redis tests:

```powershell
$env:RUN_INFRASTRUCTURE_TESTS = '1'
python -m pytest -m integration
Remove-Item Env:RUN_INFRASTRUCTURE_TESTS
```

The two integration tests verify PostgreSQL and Redis connectivity, pgvector,
the current Alembic revision, Redis round trips, token rotation and replay
revocation, rate limiting, RBAC, resource ownership, and append-only audit
enforcement.

## Continuous integration

The [`CI` workflow](.github/workflows/ci.yml) runs for pull requests to `main`,
pushes to `main`, and manual dispatches. It contains two sequential jobs:

1. `Quality` checks dependencies, Compose, Ruff, Black, MyPy, unit/API tests, and
   offline Alembic SQL.
2. `Infrastructure integration` starts PostgreSQL/pgvector and Redis, applies the
   migration, runs the real integration test, and removes its temporary volumes.

The workflow has read-only repository permissions, uses immutable action SHAs,
requires no GitHub secrets, and does not deploy the application.

## Configuration

The full local configuration template is [`.env.example`](.env.example). Main
groups include:

| Group | Purpose |
| --- | --- |
| `APP_*`, `ENVIRONMENT`, `DEBUG` | Service identity and runtime mode |
| `LOG_*` | Logging level and JSON/console format |
| `ALLOWED_ORIGINS`, `ENABLE_HSTS` | Browser and transport security policy |
| `DATABASE_URL`, `MIGRATION_DATABASE_URL` | Separate runtime and migration connections |
| `DATABASE_*` | Connection, command, probe, pool, and recycle limits |
| `REDIS_URL`, `REDIS_KEY_PREFIX`, `REDIS_*` | Cache connection, namespace, and bounded timeouts |
| `JWT_*`, `TOKEN_DIGEST_KEY`, token TTLs | Signed access and keyed opaque-token security |
| `ARGON2_*`, `AUTH_RATE_LIMIT_*` | Password cost policy and authentication throttling |
| `PROVIDER_*` | Outbound timeouts/deadline, retry, response, circuit, and lock limits |
| `BINANCE_SPOT_*` | Feature flag, pinned public host, local weight budget, and interactive reserve |

Infrastructure URLs use secret-aware settings fields so normal settings
representations do not expose their credentials.

## Documentation

| Document | Purpose |
| --- | --- |
| [`requirements.md`](docs/requirements.md) | Product scope, roles, features, safety, reliability, and acceptance requirements |
| [`architecture.md`](docs/architecture.md) | Runtime design, trust boundaries, deployment topology, and fallbacks |
| [`database_design.md`](docs/database_design.md) | Target data model, constraints, ownership, and retention |
| [`api_docs.md`](docs/api_docs.md) | Planned versioned API surface and response contracts |
| [`data_sources.md`](docs/data_sources.md) | Provider purpose, caching, attribution, licensing, and failure policy |
| [`risk_register.md`](docs/risk_register.md) | Technical, security, legal, and operational risks |
| [`milestones.md`](docs/milestones.md) | All 21 phases and their exit gates |
| [`phase_0_plan.md`](docs/phase_0_plan.md) | Approved planning baseline |
| [`phase_1_foundation.md`](docs/phase_1_foundation.md) | FastAPI foundation implementation and validation |
| [`phase_2_infrastructure.md`](docs/phase_2_infrastructure.md) | Durable infrastructure design, commands, failure tests, and evidence |
| [`phase_3_identity.md`](docs/phase_3_identity.md) | Identity design, security invariants, API demo, and exit evidence |
| [`phase_4_provider_framework.md`](docs/phase_4_provider_framework.md) | Provider contracts, resilience controls, mock-only tests, and exit evidence |
| [`phase_5_binance_spot.md`](docs/phase_5_binance_spot.md) | Spot adapters, analytics methodology, UI states, controls, demos, and exit evidence |

## Roadmap overview

| Milestone | Phases | Outcome |
| --- | ---: | --- |
| Approved design | 0 | Buildable requirements and architecture |
| Secure platform core | 1-4 | API, infrastructure, identity, authorization, and provider resilience |
| Deterministic research MVP | 5-10 | Binance, crypto, stocks/SEC, and reproducible analytics |
| ML, RAG, and reports | 11-15 | Measured models, evidence-first retrieval, guarded local LLM, and reports |
| Multi-user product and operations | 16-19 | Watchlists, alerts, frontend, observability, security, and recovery |
| Production pilot | 20 | Portable HTTPS deployment, immutable delivery, monitoring, and rollback |

Later phases do not begin until the current phase's tests and documented exit
evidence pass.

## Responsible-use boundary

- Research and educational use only; not personalized financial advice.
- No order placement, withdrawals, exchange-secret storage, or automated trading.
- No claim of guaranteed accuracy, performance, availability, or returns.
- Provider data must retain source attribution, timestamps, freshness, cache
  state, missing-data warnings, and licensing constraints.
- LLM output can summarize verified inputs but cannot calculate authoritative
  risk or invent evidence.
- Internet-facing deployment requires replacing local credentials and completing
  the later security, backup, observability, and production gates.
