# AI Investment Research Co-Pilot

Phase 1 provides the production-oriented FastAPI foundation for the source-backed
investment research system described in `docs/`. It intentionally contains no
database, cache, authentication, market-data, ML, RAG, or deployment integration.

The service is research and educational software, not personalized financial
advice.

## Prerequisites

- Windows PowerShell
- Python 3.12 (`py -3.12 --version`)
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

The application has safe defaults, so `.env` is optional for Phase 1. Copying the
example makes local choices explicit. `.env.example` contains only non-secret
documentation; a real `.env` is ignored because later phases will put credentials
there.

If activation is blocked, use this process-scoped policy (it changes only the
current PowerShell process), then activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

You can also avoid activation entirely and run
`.\.venv\Scripts\python.exe -m ...`.

## Run the API

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn backend.app.main:app --reload
```

Open:

- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/docs`
- `http://127.0.0.1:8000/livez`
- `http://127.0.0.1:8000/readyz`
- `http://127.0.0.1:8000/api/v1/health`

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

For the rationale, endpoint examples, failure guide, and Phase 1 boundary, see
[`docs/phase_1_foundation.md`](docs/phase_1_foundation.md).

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_NAME` | `AI Investment Research Co-Pilot` | Public service name |
| `APP_VERSION` | `0.1.0` | API/log build identity |
| `ENVIRONMENT` | `development` | `development`, `testing`, `staging`, or `production` |
| `DEBUG` | `false` in code | Local behavior flag; forbidden in production |
| `API_V1_PREFIX` | `/api/v1` | Versioned route prefix |
| `LOG_LEVEL` | `INFO` | Standard logging threshold |
| `LOG_FORMAT` | `json` | `json` or local `console` output |
| `ALLOWED_ORIGINS` | `http://localhost:8501` | Strict comma-separated CORS allowlist |
| `DOCS_ENABLED` | `true` | Enables `/docs`, `/redoc`, and `/openapi.json` |
| `ENABLE_HSTS` | `false` | Production-only HSTS switch |

Configuration is validated before the server accepts traffic. Invalid enum
values, unsafe origins, local HSTS, and production debug mode fail startup.
