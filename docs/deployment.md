# Production pilot deployment

Phase 8 is designed for a small, invite-only pilot of roughly 5–15 users on one
Linux host. The production topology deliberately uses one API worker, one
Streamlit process, PostgreSQL, Redis, and Caddy. It does not require Kubernetes,
Celery, or an LLM.

## Prerequisites

- A Linux host with Docker Engine and Compose v2.
- A DNS name pointing to the host and inbound ports 80/443.
- A monitored email address for the SEC User-Agent if SEC support is enabled.
- Independent random database, JWT, and token-digest secrets.
- A remote destination for encrypted database backups before real user data is
  accepted.

No deployment host or credentials are committed to this repository. Creating a
configuration does not prove that a live deployment succeeded.

## First deployment

1. Copy `.env.production.example` to `.env.production` outside version control.
2. Replace every `CHANGE_ME` value and set the real `APP_DOMAIN`.
   If PSX company-report fundamentals will be advertised, complete the human
   process in `psx_manifest_review.md`, commit the approved manifest under
   `data/psx/`, and set `STOCK_FUNDAMENTALS_MANIFEST_PATH` to its image path
   (for example `data/psx/psx_fundamentals.approved.json`). The Docker image
   includes `data/`; candidate/rejected entries still remain unavailable.
3. Validate with `docker compose --env-file .env.production -f
   compose.production.yaml config --quiet`.
4. Build with `docker compose --env-file .env.production -f
   compose.production.yaml build`.
5. Start with `docker compose --env-file .env.production -f
   compose.production.yaml up -d --wait`.
6. Set `SMOKE_BASE_URL=https://your-domain` and run `python scripts/smoke.py`.
7. Check API, frontend and Caddy logs before inviting users.

Only Caddy publishes host ports. PostgreSQL and Redis remain on a private Docker
network. The API intentionally runs one worker because provider quotas and
circuit breakers are process-local in this release.

Prometheus-compatible metrics are available only on the private Docker network
at `http://api:8000/metrics`. Phase 8 does not ship an external metrics backend
or alert receiver; configure those before describing monitoring as complete.

## Release and rollback

Build and deploy an immutable commit-SHA or version tag. Before an upgrade:

1. Run the backup script and copy the encrypted archive off-host.
2. Pull/build the exact target image.
3. Run the one-shot migration service.
4. Wait for readiness and run the smoke check.

If application health fails, restore the previous image tag and restart. Do not
describe `alembic downgrade` as a general rollback strategy. Phase 8's migration
is additive, but future destructive migrations require expand/migrate/contract.
Database restoration is an incident action using the tested restore procedure.

## Unresolved launch gates

- Configure and test real email delivery for verification and password reset.
  No production mail sender or invite-provisioning command exists in Phase 8;
  test tokens are correctly rejected in production, so user onboarding remains
  blocked until one of those paths is implemented.
- Review current Binance, CoinGecko, SEC, PSX, SECP, and company-report terms.
- Configure external uptime checks for `/livez` and `/readyz`.
- Schedule daily encrypted backups and record a successful restore exercise.
- Deploy `data/psx/psx_fundamentals.approved.json` before advertising SYS/MEBL coverage.
- All external PSX price classes remain unavailable until written display and
  derived-data rights are documented; see `psx_integration.md`.
