# AI Investment Research Co-Pilot

Phase 2 adds durable local infrastructure to the production-oriented FastAPI
foundation: PostgreSQL 17 with pgvector, Redis, async SQLAlchemy sessions,
Alembic migrations, cache freshness primitives, and dependency-aware readiness.
Authentication, providers, workers, market data, ML, RAG, and deployment remain
outside this phase.

The service is research and educational software, not personalized financial
advice.

## Prerequisites

- Windows PowerShell
- Python 3.12 (`py -3.12 --version`)
- Docker Desktop with Compose v2
- Git (for the project workflow)

## Local setup

Run from the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

The values committed in `.env.example` are documented local-only defaults, not
production secrets. A real `.env` is ignored. Replace every credential before a
shared or internet-facing deployment.

If activation is blocked, set a process-only policy and activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

You can also avoid activation and use `.\.venv\Scripts\python.exe -m ...`.

## Start and migrate the infrastructure

```powershell
docker compose up -d
docker compose ps
python -m alembic upgrade head
```

Compose places both services on a project-scoped bridge, binds their host ports
only to `127.0.0.1`, and stores their data in named volumes. `docker compose down`
preserves those volumes; do not add `-v` unless you intentionally want to erase
local data.

## Run the API

```powershell
python -m uvicorn backend.app.main:app --reload
```

Open:

- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/docs`
- `http://127.0.0.1:8000/livez`
- `http://127.0.0.1:8000/readyz`
- `http://127.0.0.1:8000/api/v1/health`

`/livez` never calls dependencies. `/readyz` returns 503 when PostgreSQL is
unavailable, but remains 200 with `redis: degraded` when Redis is unavailable;
the application can bypass disposable cache acceleration safely.

The default CORS allowlist permits the planned Streamlit development client at
`http://localhost:8501`. Add production origins to `ALLOWED_ORIGINS` as a
comma-separated list; wildcards are deliberately rejected.

## Quality gates

```powershell
python -m ruff check .
python -m black --check .
python -m mypy backend
python -m pytest
```

After Compose is healthy and Alembic is at `head`, run the real infrastructure
test explicitly:

```powershell
$env:RUN_INFRASTRUCTURE_TESTS = '1'
python -m pytest -m integration
Remove-Item Env:RUN_INFRASTRUCTURE_TESTS
```

For architecture, persistence and Redis-loss validation, expected output, and
common failures, see
[`docs/phase_2_infrastructure.md`](docs/phase_2_infrastructure.md).

## Configuration

| Variable group | Defaults | Purpose |
| --- | --- | --- |
| `APP_NAME`, `APP_VERSION`, `ENVIRONMENT` | service name, `0.2.0`, `development` | Public identity and runtime mode |
| `DEBUG`, `DOCS_ENABLED`, `ENABLE_HSTS` | `false`, `true`, `false` in code | Runtime and browser-security switches |
| `LOG_LEVEL`, `LOG_FORMAT` | `INFO`, `json` | Structured logging policy |
| `ALLOWED_ORIGINS` | `http://localhost:8501` | Strict CORS allowlist |
| `DATABASE_URL` | local `copilot_app` URL | Least-privilege application connection |
| `MIGRATION_DATABASE_URL` | falls back to `DATABASE_URL` | Alembic connection; separate locally by default |
| `DATABASE_*TIMEOUT*`, `DATABASE_POOL_*` | bounded values in `.env.example` | Async connection and pool limits |
| `REDIS_URL`, `REDIS_KEY_PREFIX` | local DB 0, `copilot:v1` | Cache connection and version namespace |
| `REDIS_*TIMEOUT*`, `REDIS_HEALTH_CHECK_INTERVAL_SECONDS` | bounded values in `.env.example` | Fast cache failure and connection health |

Configuration is validated before the server accepts traffic. Invalid URL
schemes, missing database names, unsafe origins, local HSTS, and production debug
mode fail startup. Connection URLs use secret-aware fields so settings
representations do not expose credentials.
