# Phase 2: Durable Infrastructure

**Implemented:** July 15, 2026  
**Runtime validated:** July 17, 2026  
**Status:** Complete  
**Scope:** PostgreSQL/pgvector, Redis, async persistence plumbing, migrations,
cache primitives, and readiness  
**Python:** 3.12

## Purpose and boundary

This phase gives the Phase 1 API a real durable system of record and disposable
acceleration layer without implementing later domain schemas. PostgreSQL is
required for traffic readiness. Redis may disappear without losing user-owned
state or breaking the primary source/database path.

The first Alembic revision enables pgvector and creates Alembic's version table.
Identity tables begin in Phase 3; provider and market schemas begin in their
own phases. This preserves the sequential phase contract and avoids speculative
tables.

## Runtime design

```text
FastAPI lifespan
  -> validated secret-aware settings
  -> async SQLAlchemy engine -> PostgreSQL 17 + pgvector (durable, required)
  -> redis-py async client   -> Redis (disposable, degradable)

GET /livez
  -> process/configuration only; no dependency calls

GET /readyz
  -> database SELECT 1 + Redis PING concurrently
  -> database down: 503 not_ready
  -> Redis down: 200 ready, redis=degraded
```

The local Compose network is a project-scoped bridge, and host ports bind only to
`127.0.0.1`. The bridge is required so the host-run FastAPI development process
can reach the services; neither port listens on a LAN interface. PostgreSQL and
Redis use named volumes. The PostgreSQL initialization hook creates a runtime role
that can use future migrated objects but cannot issue migrations. Alembic uses the
separate migration role.

## Implementation map

| Area | Location | Contract |
| --- | --- | --- |
| Compose | `compose.yaml` | Pinned pgvector/PostgreSQL and Redis images, health checks, loopback ports, named volumes |
| Role bootstrap | `infrastructure/postgres/init/001-create-app-role.sh` | Creates/grants the runtime role only on a fresh volume |
| Configuration | `backend/app/core/config.py` | Secret-aware URLs, strict schemes, bounded pools/timeouts, versioned Redis prefix |
| Database | `backend/app/database/` | Pooled async application engine, no-pool readiness engine, request-scoped sessions, bounded probe, disposal |
| Migrations | `alembic.ini`, `alembic/` | Async Alembic environment and pgvector baseline revision |
| Cache | `backend/app/cache/redis_cache.py` | Canonical keys, JSON envelopes, soft/hard TTL, corrupt-entry eviction, outage bypass |
| Lifecycle | `backend/app/core/resources.py`, `backend/app/main.py` | Injectable resources and shutdown cleanup |
| Readiness | `backend/app/api/health_routes.py` | Concurrent dependency probes and required/degraded policy |
| Evidence | `backend/app/tests/` | Unit/API tests plus opt-in real-service integration test |

## Cache contract

Cache keys contain provider, operation, normalized asset, interval, and a digest
of canonical parameters under the configured `copilot:v1` namespace. Values are
JSON envelopes with:

```text
schema_version, value, created_at, soft_expires_at, hard_expires_at
```

- Before soft expiry: `hit`.
- Between soft and hard expiry: `stale`, with an explicit warning.
- At or after hard expiry: `miss`; the value is not returned.
- Redis connection/read/write failure: `bypass`; provider/database work continues.
- Malformed envelope: delete best-effort and return `miss`.

Redis's key expiry is the hard safety boundary. The timestamps remain in the
envelope so API metadata can later report source/cache freshness precisely.

## Fresh setup and migration

From the repository root:

```powershell
Copy-Item .env.example .env
docker compose up -d
docker compose ps
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Expected Compose state:

```text
postgres   ...   Up ... (healthy)   127.0.0.1:5432->5432/tcp
redis      ...   Up ... (healthy)   127.0.0.1:6379->6379/tcp
```

Expected migration tail:

```text
INFO  [alembic.runtime.migration] Running upgrade  -> 20260715_0001, Enable the pgvector extension.
```

Verify the revision and extension using the documented default role/database:

```powershell
docker compose exec -T postgres psql -U copilot_migrator -d copilot -Atc "SELECT version_num FROM alembic_version"
docker compose exec -T postgres psql -U copilot_migrator -d copilot -Atc "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
```

The first command must print `20260715_0001`; the second prints the installed
pgvector version.

## Persistence exit test

This verifies that `down`/`up` preserves the migrated database volume:

```powershell
$before = docker compose exec -T postgres psql -U copilot_migrator -d copilot -Atc "SELECT version_num FROM alembic_version"
docker compose down
docker compose up -d

do {
    Start-Sleep -Seconds 2
    $health = docker inspect --format '{{.State.Health.Status}}' ai-investment-research-copilot-postgres-1 2>$null
} until ($health -eq 'healthy')

$after = docker compose exec -T postgres psql -U copilot_migrator -d copilot -Atc "SELECT version_num FROM alembic_version"
if ($before -ne '20260715_0001' -or $after -ne $before) {
    throw "PostgreSQL migration state did not survive Compose restart"
}
'PASS: PostgreSQL migration state survived Compose down/up'
```

Expected output:

```text
PASS: PostgreSQL migration state survived Compose down/up
```

`docker compose down -v` intentionally deletes the volumes and is not part of
this test.

## Redis loss and fallback exit test

The deterministic test uses a failing Redis double and requires no service:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/app/tests/test_cache.py -q
```

Expected result: `5 passed`.

For a running API with PostgreSQL healthy:

```powershell
docker compose stop redis
Invoke-RestMethod http://127.0.0.1:8000/readyz | ConvertTo-Json -Depth 4
docker compose start redis
```

The probe remains HTTP 200 and includes:

```json
{
  "status": "ready",
  "checks": {
    "application": "ok",
    "configuration": "ok",
    "database": "ok",
    "redis": "degraded"
  }
}
```

Stopping PostgreSQL instead must produce HTTP 503 with `database: error` and
`status: not_ready`. `/livez` remains 200 in both cases.

## Real-service integration test

After Compose is healthy and `alembic upgrade head` has completed:

```powershell
$env:RUN_INFRASTRUCTURE_TESTS = '1'
.\.venv\Scripts\python.exe -m pytest -m integration
Remove-Item Env:RUN_INFRASTRUCTURE_TESTS
```

The test verifies database/Redis pings, the pgvector extension, the Alembic
revision, and a namespaced Redis write/read/delete round trip. It skips during
ordinary unit-test runs so CI or developer machines without services do not
produce false failures.

## Quality gates

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m black --check .
.\.venv\Scripts\python.exe -m mypy backend
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m alembic upgrade head --sql
```

## Common failures

| Symptom | Cause and safe resolution |
| --- | --- |
| `docker` is not recognized | Install/start Docker Desktop with Compose v2, reopen PowerShell, and verify `docker compose version`. |
| Port 5432 or 6379 is in use | Set `POSTGRES_PORT` or `REDIS_PORT` in `.env` and update the matching connection URL. Do not stop an unrelated database blindly. |
| Runtime role/password changes do not apply | PostgreSQL init hooks run only on an empty volume. Keep the existing credentials or intentionally recreate the local volume after confirming no data is needed. |
| Alembic reports authentication failure | `MIGRATION_DATABASE_URL` must use the migration role; `DATABASE_URL` uses the runtime role. Keep URL-escaped passwords. |
| `/readyz` returns 503 | Inspect PostgreSQL health and migration/configuration first. A Redis-only failure reports degraded but remains ready. |
| Cache calls are slow during an outage | Keep the one-second Redis connect/socket defaults or another explicitly bounded value. Do not add unbounded retries. |
| Database readiness is slow during an outage | Keep `DATABASE_PROBE_TIMEOUT_SECONDS` bounded. One shared no-pool probe may finish asynchronously after the response deadline; repeated probes reuse it instead of spawning more work or blocking liveness with driver cancellation cleanup. |
| Integration test is skipped | Start Compose, migrate, then set `RUN_INFRASTRUCTURE_TESTS=1` for that test invocation. |
| Black stalls in a restricted shell | Set `BLACK_CACHE_DIR=.black_cache` for that process; the repository ignores this local cache directory. |
| `docker compose down` appears to lose cache data | Redis is disposable by design; correctness may not depend on cached values. PostgreSQL migration state must persist. |

## Version verification

Versions were checked against primary project registries on July 15, 2026:

- SQLAlchemy `2.0.51`, asyncpg `0.31.0`, Alembic `1.18.5`, and redis-py
  `8.0.1` are pinned in the Python dependency files.
- `pgvector/pgvector:0.8.5-pg17-bookworm` pins pgvector and the PostgreSQL major
  line; `redis:8.4.4-alpine` pins Redis and its base variant.
- Recheck security advisories and supported tags during each dependency update;
  never replace these with floating `latest` tags.

Primary references: [SQLAlchemy on PyPI](https://pypi.org/project/SQLAlchemy/),
[asyncpg on PyPI](https://pypi.org/project/asyncpg/),
[Alembic on PyPI](https://pypi.org/project/alembic/),
[redis-py on PyPI](https://pypi.org/project/redis/),
[pgvector releases](https://github.com/pgvector/pgvector/releases), and the
[Redis official image](https://hub.docker.com/_/redis).

## Validation record on July 17, 2026

Executed on the supplied Windows/Python 3.12 workspace:

```text
Ruff:           All checks passed
Black:          34 Python files unchanged
MyPy:           Success, 32 source files
Pytest:         41 passed, including the real infrastructure integration test
Alembic offline revision: 20260715_0001 rendered successfully
Compose:        PostgreSQL/pgvector and Redis healthy on loopback-only ports
Persistence:    revision 20260715_0001 survived Compose down/up
PostgreSQL:     pgvector 0.8.5 and copilot_app runtime role verified
Redis failure:  readiness 200/degraded in about 1.03 s; liveness stayed 200
Database failure: readiness 503 in about 2.21 s; liveness answered in about 7 ms
Recovery:       both dependencies returned to ready without restarting the API
```

The fresh migration, real-service integration, Compose persistence, Redis-loss,
PostgreSQL-loss, liveness independence, and recovery exit gates all passed on
Docker Desktop. Phase 2 is fully runtime-validated.

## Recommended Git commit

```text
feat: add phase 2 durable infrastructure
```
