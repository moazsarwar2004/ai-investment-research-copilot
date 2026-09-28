#!/bin/sh
set -eu

if [ "${RESTORE_CONFIRM:-}" != "I_UNDERSTAND_THIS_REPLACES_DATABASE_CONTENTS" ]; then
  echo "Set RESTORE_CONFIRM=I_UNDERSTAND_THIS_REPLACES_DATABASE_CONTENTS" >&2
  exit 1
fi

ENV_FILE="${ENV_FILE:-.env.production}"
archive="${1:-}"
if [ ! -f "$ENV_FILE" ] || [ ! -f "$archive" ]; then
  echo "Usage: restore.sh /absolute/path/to/copilot-TIMESTAMP.dump[.age]" >&2
  exit 1
fi

set -a
. "$ENV_FILE"
set +a

: "${POSTGRES_DB:?Set POSTGRES_DB}"
: "${POSTGRES_MIGRATION_USER:?Set POSTGRES_MIGRATION_USER}"
: "${POSTGRES_MIGRATION_PASSWORD:?Set POSTGRES_MIGRATION_PASSWORD}"

restore_file="$archive"
temporary_file=""
case "$archive" in
  *.age)
    temporary_file="$(mktemp)"
    trap 'rm -f -- "$temporary_file"' EXIT INT TERM
    age --decrypt --output "$temporary_file" "$archive"
    restore_file="$temporary_file"
    ;;
esac

docker compose --env-file "$ENV_FILE" -f compose.production.yaml exec -T \
  -e "PGPASSWORD=$POSTGRES_MIGRATION_PASSWORD" postgres \
  pg_restore --clean --if-exists --exit-on-error --no-owner --no-privileges \
  --username "$POSTGRES_MIGRATION_USER" --dbname "$POSTGRES_DB" < "$restore_file"

echo "Restore completed. Run migrations and the smoke check before reopening traffic."
