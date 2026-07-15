# Phase 1: Production Application Foundation

**Implemented:** July 13, 2026  
**Scope:** FastAPI foundation only  
**Python:** 3.12

## Purpose and boundary

This phase turns the Phase 0 architecture into an executable HTTP service with a
stable operational contract. It deliberately stops before persistence, Redis,
workers, authentication, market-data providers, ML, RAG, observability
infrastructure, and cloud deployment. Readiness therefore checks only startup and
configuration; fake dependency checks would create false confidence.

## Architecture at a glance

```text
HTTP client
  -> RequestIDMiddleware (validate/generate correlation ID)
  -> RequestLoggingMiddleware (safe start/completion events and duration)
  -> SecurityHeadersMiddleware (browser defenses)
  -> CORSMiddleware (origin policy)
  -> FastAPI exception layer
  -> APIRouter endpoint
  -> Pydantic response validation
  -> response + X-Request-ID + security headers
```

Starlette executes the last-added user middleware first. Request-ID middleware is
registered last so the correlation context exists for every inner log and error.
Routes live outside `main.py`; the factory composes them with policy components.

## Component teaching guide

### 1. Central settings

1. **Problem solved:** deployment values change by environment and unsafe values
   must not silently reach runtime.
2. **Choice:** `pydantic-settings` provides typed environment loading, coercion,
   validation, and clear startup errors with little custom code.
3. **Location:** `backend/app/core/config.py`, below the delivery layer and shared
   by application composition and policy components.
4. **Flow:** process environment overrides `.env`, values become a validated
   `Settings`, `get_settings()` caches one instance, and the factory stores it on
   `app.state`.
5. **Failure:** malformed API prefixes/origins, production debug, or non-production
   HSTS prevent application creation instead of running insecurely.
6. **Test:** configuration tests cover parsing, deduplication, and invalid modes.
7. **Security:** no secret is hardcoded; wildcard origins and URL credentials are
   rejected. `.env` is ignored while `.env.example` is safe documentation.
8. **Monitoring later:** startup failures appear in process/container logs; a
   deployment platform will alert on failed readiness and restart loops.
9. **Scaling later:** the same environment contract works for local processes,
   containers, and secret-injected cloud workloads.
10. **Interview explanation:** “I use a typed, fail-fast configuration boundary so
    deploy-time inputs are validated once before requests execute.”

### 2. Application factory, lifespan, routers, and health

1. **Problem solved:** a global, tightly coupled app is hard to test and configure.
2. **Choice:** FastAPI's factory and modern lifespan APIs allow deterministic app
   instances and explicit startup/shutdown state.
3. **Location:** `backend/app/main.py` composes the application;
   `backend/app/api/health_routes.py` owns HTTP schemas and routes.
4. **Flow:** the factory resolves settings, configures logs, registers policies,
   and mounts routers. Lifespan marks startup complete before readiness succeeds.
5. **Failure:** configuration failures stop startup; `/readyz` returns the standard
   503 error if startup is incomplete. `/livez` deliberately avoids dependencies.
6. **Test:** a fresh factory instance runs under `TestClient`, which enters and
   exits lifespan. Tests validate all metadata and the UTC timestamp.
7. **Security:** strict response models block accidental extra fields; probes return
   no paths, secrets, host information, or dependency details.
8. **Monitoring later:** orchestrators use `/livez` for restart decisions and
   `/readyz` to remove an instance from traffic. Metrics can measure probe status.
9. **Scaling later:** routers and dependency checks can be extended independently;
   identical stateless instances can run behind a load balancer.
10. **Interview explanation:** “The factory is the composition root, while lifespan
    owns process state and health endpoints separate aliveness from traffic safety.”

### 3. Structured logs, request ID, and request timing

1. **Problem solved:** plain text and `print` are difficult to query, correlate,
   filter, or aggregate during an incident.
2. **Choice:** Python standard logging with a JSON formatter is sufficient for this
   phase and avoids a dependency. A `ContextVar` safely follows each async request.
3. **Location:** format/configuration in `core/logger.py`; request behavior in the
   request-ID and logging middleware modules.
4. **Flow:** a caller UUID is canonicalized or replaced, bound to request/context,
   logged on start and completion, then returned in `X-Request-ID`. Duration uses
   `perf_counter()`, which is monotonic and unaffected by wall-clock adjustment.
5. **Failure:** invalid/oversized IDs are replaced. Unexpected exceptions carry the
   same ID into the internal event and safe response.
6. **Test:** tests cover generated, preserved, replaced, and error-response IDs;
   the formatter test proves allowlisted fields and JSON structure.
7. **Security:** logs omit query strings, bodies, cookies, client headers, and
   arbitrary extras. Exception output records only the exception type, not its
   message or traceback text.
8. **Monitoring later:** JSON fields map cleanly into Loki/Grafana or OpenTelemetry;
   latency and status can feed dashboards and alerts.
9. **Scaling later:** the same ID can be forwarded to providers, jobs, agents, and
   trace baggage so work across many services remains searchable.
10. **Interview explanation:** “A correlation ID and structured, bounded fields let
    me reconstruct a request without collecting sensitive payloads.”

Example request event (duration varies):

```json
{"timestamp":"2026-07-13T12:00:00.000Z","level":"info","service":"AI Investment Research Co-Pilot","environment":"development","event":"http_request_completed","request_id":"1c35a02e-5261-4e8c-a50e-32b6b47fd167","method":"GET","path":"/livez","status_code":200,"duration_ms":1.234}
```

### 4. Exception contract

1. **Problem solved:** framework and application failures otherwise expose varying
   schemas, making clients brittle and risking leaked internals.
2. **Choice:** typed application exceptions plus global translators preserve useful
   status codes while producing one envelope.
3. **Location:** domain-safe error types in `core/exceptions.py`; HTTP translation
   and unexpected-error logging in `core/error_handlers.py`.
4. **Flow:** expected exceptions carry safe code/message/status. Validation and
   framework 404s are normalized. Unknown failures are logged internally and become
   a generic 500 with the same request ID.
5. **Failure:** even the unexpected path returns only `INTERNAL_SERVER_ERROR`; the
   FastAPI app is always created with `debug=False`, regardless of `DEBUG`.
6. **Test:** test-only routes raise expected and secret-bearing unexpected errors;
   assertions prove the secret, stack, path, and exception type are absent.
7. **Security:** no traceback, filesystem path, exception text, or environment data
   is sent. Security and correlation headers are also applied to error responses.
8. **Monitoring later:** 5xx structured events will feed error-rate alerts and can
   be grouped by exception type and request ID.
9. **Scaling later:** domain modules can add safe subclasses without changing the
   client envelope; inter-service errors can retain correlation.
10. **Interview explanation:** “Exceptions are translated at the API boundary:
    expected failures remain meaningful, unexpected ones remain observable but
    opaque to the caller.”

Error example:

```json
{
  "success": false,
  "data": null,
  "errors": [{"code": "RESOURCE_NOT_FOUND", "message": "The requested resource was not found."}],
  "meta": {"request_id": "1c35a02e-5261-4e8c-a50e-32b6b47fd167"}
}
```

### 5. Security headers and CORS

1. **Problem solved:** browsers need explicit content, embedding, feature, referrer,
   and cross-origin policy.
2. **Choice:** small middleware applies `nosniff`, `DENY`, a conservative referrer
   rule, and disables camera/microphone/geolocation. Starlette's maintained CORS
   middleware handles preflight behavior.
3. **Location:** shared header policy in `core/security.py`, middleware wrapper in
   `middleware/security_headers_middleware.py`, and composition in `main.py`.
4. **Flow:** the Streamlit browser origin sends a preflight/request; CORS compares
   the exact configured origin and exposes `X-Request-ID` to accepted clients.
5. **Failure:** malformed origins stop startup. An unlisted origin receives no
   allow-origin header, so the browser blocks script access.
6. **Test:** tests cover every header, local HSTS absence, allowed preflight, and a
   rejected origin.
7. **Security:** credentialed wildcard CORS is impossible. HSTS is only allowed in
   production because enabling it on local HTTP can create confusing browser state.
8. **Monitoring later:** rejected origins and CSP reports can become bounded
   security telemetry at the edge without logging private headers.
9. **Scaling later:** production will add TLS/edge HSTS, CSP, trusted hosts, proxy
   rules, rate limits, authentication, and a secret manager.
10. **Interview explanation:** “CORS is a browser read policy, not authentication;
    I use exact origins and independent server-side authorization later.”

Header intent:

| Header | Initial protection |
| --- | --- |
| `X-Content-Type-Options: nosniff` | Stops MIME-type guessing |
| `X-Frame-Options: DENY` | Blocks clickjacking through framing |
| `Referrer-Policy: strict-origin-when-cross-origin` | Limits cross-site URL detail |
| `Permissions-Policy` | Disables unused powerful browser features |
| `Strict-Transport-Security` | Production-only HTTPS enforcement when enabled |

## Endpoint contracts

### `GET /livez`

```json
{"status":"alive","service":"AI Investment Research Co-Pilot","version":"0.1.0"}
```

### `GET /readyz`

```json
{"status":"ready","checks":{"application":"ok","configuration":"ok"}}
```

### `GET /api/v1/health`

```json
{"service":"AI Investment Research Co-Pilot","version":"0.1.0","environment":"development","status":"healthy","timestamp":"2026-07-13T12:00:00Z"}
```

These are expected examples. The validation handoff records actual command results.

## Verification commands

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m black --check .
.\.venv\Scripts\python.exe -m mypy backend
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

## Common failures and safe fixes

| Failure | Diagnosis and fix |
| --- | --- |
| Python 3.12 not installed | Verify `py -0p`; install Python 3.12 from python.org or an approved package manager, then rerun `py -3.12 --version`. |
| Wrong VS Code interpreter | Run **Python: Select Interpreter** and choose `.venv\Scripts\python.exe`. |
| PowerShell blocks activation | Use `Set-ExecutionPolicy -Scope Process Bypass`; never weaken the machine-wide policy for this. |
| `uvicorn` not recognized | Activate `.venv`, install dependencies, or use `python -m uvicorn`. |
| Import path error | Run from the repository root with `backend.app.main:app`; do not run `main.py` directly. |
| Missing `.env` | Phase 1 defaults work without it. Copy `.env.example` to `.env` only when overrides are needed. |
| Invalid environment value | Use exactly `development`, `testing`, `staging`, or `production`; read the Pydantic startup message. |
| CORS error | Supply complete origins such as `https://app.example.com`, comma separated, with no path, credentials, or wildcard. |
| Tests are not discovered | Run from the root using `python -m pytest`; `pyproject.toml` points at `backend/app/tests`. |
| Ruff and Black conflict | Run `python -m black .`, then `python -m ruff check . --fix`, inspect changes, and rerun both checks. |
| MyPy reports missing stubs | Prefer typed libraries; add a targeted stub package only when the dependency genuinely requires it. Do not silence the whole module. |
| Port 8000 in use | Inspect `Get-NetTCPConnection -LocalPort 8000`, stop the intended stale process, or temporarily choose another port. |
| Git repository already initialized | Do not run `git init`; inspect `git status` and create/switch only the Phase 1 branch. |

## Exit-gate interpretation

Passing unit/API tests proves deterministic in-process behavior. A separate Uvicorn
smoke test proves the ASGI import, lifespan, network listener, JSON logs, docs, and
headers work together. Ruff, Black, and strict MyPy guard style and type regressions.
These checks do not claim production deployment readiness; TLS, external dependency
health, authentication, persistence, distributed tracing, and SLOs arrive later.

## Actual validation on July 13, 2026

The final workspace was exercised with the local Python 3.12 virtual environment:

```text
Python:     3.12.2
Pip check: No broken requirements found.
Ruff:      All checks passed!
Black:     23 files would be left unchanged.
MyPy:      Success: no issues found in 23 source files
Pytest:    24 passed in 0.88s
Compile:   backend compileall succeeded
```

The Uvicorn network smoke test started on `127.0.0.1:8000`. `/`, `/docs`,
`/livez`, `/readyz`, and `/api/v1/health` each returned HTTP 200. A caller-supplied
UUID returned unchanged in `X-Request-ID`; the response also included `nosniff`,
`DENY`, the configured referrer policy, and the exact Streamlit CORS origin. The
captured request-completion log included method, path, status 200, request ID, and
`duration_ms`.

Git validation could not be completed in this generated workspace. Its `.git`
path is protected by a host ACL and was empty rather than an initialized repository;
`git init -b main` failed while writing `.git/description` with “Permission denied.”
The implementation, review, and technical gates are complete, but branch creation,
diff review through Git, staging inspection, and the requested local commit must be
performed after the workspace owner restores Git metadata write access.
