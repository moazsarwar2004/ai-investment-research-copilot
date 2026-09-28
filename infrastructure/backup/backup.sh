#!/bin/sh
set -eu

ENV_FILE="${ENV_FILE:-.env.production}"
if [ ! -f "$ENV_FILE" ]; then
  echo "Missing production environment file: $ENV_FILE" >&2
  exit 1
fi

set -a
. "$ENV_FILE"
set +a

: "${BACKUP_DIRECTORY:?Set BACKUP_DIRECTORY}"
: "${POSTGRES_DB:?Set POSTGRES_DB}"
: "${POSTGRES_MIGRATION_USER:?Set POSTGRES_MIGRATION_USER}"
: "${POSTGRES_MIGRATION_PASSWORD:?Set POSTGRES_MIGRATION_PASSWORD}"

case "$BACKUP_DIRECTORY" in
  /|""|.)
    echo "BACKUP_DIRECTORY must be a dedicated absolute directory" >&2
    exit 1
    ;;
esac

mkdir -p "$BACKUP_DIRECTORY"
umask 077
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
archive="$BACKUP_DIRECTORY/copilot-$timestamp.dump"

docker compose --env-file "$ENV_FILE" -f compose.production.yaml exec -T \
  -e "PGPASSWORD=$POSTGRES_MIGRATION_PASSWORD" postgres \
  pg_dump --format=custom --no-owner --no-privileges \
  --username "$POSTGRES_MIGRATION_USER" --dbname "$POSTGRES_DB" > "$archive"

if [ -n "${BACKUP_AGE_RECIPIENT:-}" ]; then
  age --recipient "$BACKUP_AGE_RECIPIENT" --output "$archive.age" "$archive"
  rm -f -- "$archive"
  archive="$archive.age"
fi

sha256sum "$archive" > "$archive.sha256"

retention_days="${BACKUP_RETENTION_DAYS:-7}"
find "$BACKUP_DIRECTORY" -type f -name 'copilot-*' \
  -mtime "+$retention_days" -delete

echo "Backup created: $archive"
