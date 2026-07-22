# Phase 3 Identity and Authorization

## 1. Outcome

Phase 3 adds the durable multi-user security boundary required by every later
user-owned feature. The API now supports registration, email verification,
login, refresh rotation, logout, password reset, current-user/session views,
owner-scoped session revocation, administrator user management, and audit-log
inspection.

The implementation follows the modular-monolith boundaries established in
Phase 0:

- routes parse HTTP and select status codes;
- schemas reject undocumented fields and normalize email/password inputs;
- services own state transitions, RBAC, fresh-auth, and ownership decisions;
- repositories contain SQLAlchemy queries only; and
- PostgreSQL remains the source of truth while Redis only accelerates rate
  limits.

## 2. Durable schema

Migration `20260721_0002` creates `citext` email support and three tables:

| Table | Security purpose |
| --- | --- |
| `users` | Case-insensitive unique email, Argon2id hash, user/admin role, lifecycle status, single-use verification/reset digests and expiries |
| `user_sessions` | One row per refresh generation, unique keyed digest, family ID, parent/replacement links, absolute family expiry, revocation reason, pseudonymized IP and bounded user agent |
| `audit_logs` | Sanitized actor/action/resource/request evidence with BRIN/time and lookup indexes |

Only one unrevoked refresh generation may exist in a token family. The database
enforces this with a partial unique index. A trigger rejects `UPDATE` or
`DELETE` attempts on audit rows from the runtime application role; only the
table owner used for migrations and controlled maintenance can mutate them.

## 3. Security invariants

### 3.1 Passwords and recovery tokens

- Passwords are hashed with tunable Argon2id parameters. Staging/production
  validation rejects parameters below the configured safety floor.
- Login performs a dummy Argon2id verification when an email does not exist to
  reduce timing-based account discovery.
- Successful login automatically rehashes passwords when the configured cost
  policy changes.
- Verification, reset, and refresh tokens use 48 bytes of URL-safe randomness.
  PostgreSQL stores only an HMAC-SHA-256 digest keyed separately from the JWT
  signing secret.
- Verification and reset material is single-use and expiring. A password reset
  revokes every active session for that user.

### 3.2 Access and refresh tokens

- Access tokens use HS256 with required issuer, audience, subject, session,
  type, ID, issue, not-before, expiry, role, and primary-authentication claims.
- The default access lifetime is 15 minutes. The refresh generation lifetime is
  seven days and the absolute family lifetime is 30 days.
- Every protected request validates the JWT and rechecks the user, role,
  account status, session, revocation state, and family expiry in PostgreSQL.
- Refresh creates a new random token, revokes the previous generation, and
  preserves the original primary-authentication time.
- Reusing any rotated refresh token records a replay audit event and revokes
  the currently active generation in that family.
- Role or status changes revoke the affected user's sessions. Sensitive admin
  mutations also require a primary login within the fresh-auth window.

### 3.3 Authorization, ownership, and throttling

- User-owned repository reads include both the resource ID and authenticated
  user ID. A cross-user session ID returns the same `404` as a missing ID.
- Administrator access is based on the current database role, not a frontend
  flag or a stale token claim.
- Authentication attempts use an IP-plus-identity keyed digest. Redis performs
  the atomic fixed-window count; a bounded process-local limiter takes over
  when Redis is unavailable.
- The initial policy is five attempts per 15 minutes. A rejected request returns
  `429` and a safe `Retry-After` header.
- Responses containing credentials or account/session metadata set
  `Cache-Control: no-store`.

## 4. Implemented API

| Method | Route | Access |
| --- | --- | --- |
| `POST` | `/api/v1/auth/register` | Strict public limit |
| `POST` | `/api/v1/auth/verify-email` | Single-use token |
| `POST` | `/api/v1/auth/verification/resend` | Non-enumerating public result |
| `POST` | `/api/v1/auth/login` | Strict public limit |
| `POST` | `/api/v1/auth/refresh` | Rotating refresh token |
| `POST` | `/api/v1/auth/logout` | Refresh-token family |
| `POST` | `/api/v1/auth/logout-all` | Authenticated user |
| `POST` | `/api/v1/auth/password-reset/request` | Non-enumerating public result |
| `POST` | `/api/v1/auth/password-reset/confirm` | Single-use token |
| `GET/PATCH` | `/api/v1/users/me` | Authenticated user |
| `GET` | `/api/v1/users/me/sessions` | Owner |
| `DELETE` | `/api/v1/users/me/sessions/{session_id}` | Owner predicate |
| `GET/PATCH` | `/api/v1/admin/users[/{user_id}]` | Admin; mutation requires fresh auth |
| `GET` | `/api/v1/admin/audit-logs` | Admin |

Development and test environments may explicitly set
`AUTH_EXPOSE_TEST_TOKENS=true`, which places verification/reset tokens in the
corresponding response for a local demo. Configuration validation forbids this
setting in staging and production. A later delivery phase must connect the same
service boundary to the selected outbound email mechanism before internet
exposure; raw tokens must never be logged.

## 5. Local demo

Start the healthy services, apply migrations, and run the API:

```powershell
docker compose up -d --wait
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

With the local-only `.env.example` setting
`AUTH_EXPOSE_TEST_TOKENS=true`, use a second PowerShell window:

```powershell
$registration = Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/auth/register `
  -ContentType application/json `
  -Body (@{
    email = 'phase3@example.com'
    password = 'Local-Demo-Pass-42!'
    display_name = 'Phase 3 Demo'
  } | ConvertTo-Json)

Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/auth/verify-email `
  -ContentType application/json `
  -Body (@{ token = $registration.test_token } | ConvertTo-Json)

$tokens = Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/auth/login `
  -ContentType application/json `
  -Body (@{
    email = 'phase3@example.com'
    password = 'Local-Demo-Pass-42!'
  } | ConvertTo-Json)

Invoke-RestMethod `
  -Uri http://127.0.0.1:8000/api/v1/users/me `
  -Headers @{ Authorization = "Bearer $($tokens.access_token)" }
```

Expected results are `201` registration, `200` verification/login, and a
sanitized current-user object. Password hashes, raw persisted tokens, raw IP
addresses, and authorization headers never appear in responses or audits.

## 6. Validation evidence

Fast quality and unit/API gates:

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m black --check .
.\.venv\Scripts\python.exe -m mypy backend
.\.venv\Scripts\python.exe -m pytest -m "not integration"
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m alembic upgrade head --sql
docker compose config --quiet
```

Real PostgreSQL/Redis gate:

```powershell
docker compose up -d --wait
.\.venv\Scripts\python.exe -m alembic upgrade head
$env:RUN_INFRASTRUCTURE_TESTS = '1'
.\.venv\Scripts\python.exe -m pytest -m integration
Remove-Item Env:RUN_INFRASTRUCTURE_TESTS
```

The integration suite uses real PostgreSQL and Redis to prove the current
migration revision, registration/verification/login, refresh rotation, replay
family revocation, the sixth-attempt limit, admin denial, cross-user denial, and
database-level audit immutability. Generated accounts and audits are removed
through the migration owner in test cleanup.

## 7. Common errors

| Symptom | Cause and action |
| --- | --- |
| `JWT_SIGNING_KEY must be replaced before deployment` | Staging/production is using a documented local key. Generate independent high-entropy JWT and digest keys. |
| `AUTH_EXPOSE_TEST_TOKENS must be false` | Disable local token exposure outside development/testing. |
| Login returns `401` after registration | Verify the email first; unverified and disabled accounts cannot log in. |
| A refresh token works once and then returns `401` | This is expected rotation. Persist only the newly returned refresh token in server-side session memory. |
| A newly rotated token also returns `401` after retrying the old token | Replay protection revoked the family. Log in again. |
| Auth requests return `429` | Wait for `Retry-After`; do not retry in a tight loop. |
| Migration fails creating `citext` | Run Alembic with the migration role, not the least-privilege runtime role. |

## 8. Exit checklist

- [x] User, rotating-session, and audit schemas plus Alembic migration.
- [x] Argon2id hashing, verification, dummy verification, and rehash support.
- [x] Registration, verification/resend, login, refresh, logout/all, and reset.
- [x] Short-lived access JWTs and hashed one-time refresh tokens.
- [x] Refresh replay detection with family-wide revocation and audit evidence.
- [x] Current-user/session APIs with repository-level owner predicates.
- [x] Database-backed RBAC, fresh-auth admin mutations, and self-lockout guard.
- [x] Redis-first auth limit with process-local fallback and `Retry-After`.
- [x] Append-only sanitized audit records and runtime-role mutation denial.
- [x] Unit, API, and real PostgreSQL/Redis gate coverage.

Recommended phase completion commit:

```text
feat: complete phase 3 identity and authorization
```
