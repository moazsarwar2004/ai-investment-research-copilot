# Operations and recovery runbook

## Daily checks

- Frontend and `/livez` are reachable through HTTPS.
- `/readyz` reports ready without exposing dependency details publicly.
- Error rate and provider-unavailable logs have not materially increased.
- Disk and PostgreSQL volume usage remain below 80 percent.
- The encrypted backup job produced an archive and checksum.
- SEC, Binance and CoinGecko quota/failure events remain within policy.

Logs are structured JSON and include request IDs. Do not log bearer/refresh
tokens, CSV content, passwords, database URLs, provider keys, or raw client IPs.

## Backup

Run `ENV_FILE=.env.production sh infrastructure/backup/backup.sh`. Set an
`BACKUP_AGE_RECIPIENT` so the durable copy is encrypted before it leaves the
host. The script creates a PostgreSQL custom-format archive and SHA-256 file.
Redis contains disposable cache/coordination state and is not the source of
truth for accounts or private uploads.

Keep at least seven daily copies and one separately controlled off-host copy.
The encryption private key must not exist only on the application host.

## Restore exercise

Use a disposable environment whenever possible. Verify the archive checksum,
then run:

```sh
RESTORE_CONFIRM=I_UNDERSTAND_THIS_REPLACES_DATABASE_CONTENTS \
  ENV_FILE=.env.production \
  sh infrastructure/backup/restore.sh /absolute/path/to/archive.dump.age
```

After restoration, apply migrations, start services, run `scripts/smoke.py`, and
verify login plus a private upload using a dedicated test account. Record the
actual recovery time and recovered backup timestamp. Never test a destructive
restore against the only production database.

## Incident priorities

1. Disable affected routes or providers without inventing fallback data.
2. Preserve request IDs, audit records and relevant redacted logs.
3. Revoke compromised sessions/secrets and rotate independent keys.
4. Restore the last known image for application regressions.
5. Restore PostgreSQL only when data integrity requires it.
6. Tell users what data and time range were affected.

Horizontal scaling is deferred. Before adding API replicas, move provider
quotas/circuit state to Redis, define trusted proxy handling, recalculate the
database connection budget, coordinate background jobs, and load-test the
deployment.

The Phase 8 `/metrics` registry is process-local and resets on restart. Scrape
`http://api:8000/metrics` from the private network and add an external metrics
backend plus alert rules before calling observability complete.
