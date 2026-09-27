#!/usr/bin/env bash
#
# Restore a backup, or prove one can be restored.
#
#   ./scripts/restore.sh --verify-latest      restore into a scratch database
#                                             and check it, changing nothing
#   ./scripts/restore.sh --latest             restore over the real database
#   ./scripts/restore.sh <file.sql.age>       restore a specific backup
#
# --verify-latest is the one to run regularly. A backup nobody has ever
# restored is a file with a hopeful name.
#
# Needs the age PRIVATE key, which should not live on this server: pass it
# as AGE_IDENTITY=/path/to/key, from a USB stick or your laptop over ssh.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck source=/dev/null
[[ -f infra/.env ]] && source infra/.env
: "${POSTGRES_USER:=quanta}"
: "${POSTGRES_DB:=quanta}"
DEST="${BACKUP_DIR:-$ROOT/backups}"
COMPOSE="docker compose -f infra/docker-compose.prod.yml"

fail() { printf '\033[31m%s\033[0m\n' "$1" >&2; exit 1; }

: "${AGE_IDENTITY:?set AGE_IDENTITY=/path/to/age-private-key (keep it off this server)}"
[[ -f "$AGE_IDENTITY" ]] || fail "no such identity file: $AGE_IDENTITY"

MODE="${1:---verify-latest}"
case "$MODE" in
  --verify-latest|--latest)
    FILE="$(find "$DEST" -name 'quanta-*.sql.age' -print0 | xargs -0 ls -t 2>/dev/null | head -1)"
    [[ -n "$FILE" ]] || fail "no backups in $DEST"
    ;;
  *)
    FILE="$MODE"
    MODE="--file"
    [[ -f "$FILE" ]] || fail "no such backup: $FILE"
    ;;
esac

echo "backup: $(basename "$FILE")"

if [[ "$MODE" == "--verify-latest" ]]; then
  # A scratch database, so a verification can never damage the real one.
  SCRATCH="quanta_restore_check_$(date -u +%s)"
  echo "restoring into $SCRATCH (the live database is not touched)"

  $COMPOSE exec -T postgres createdb -U "$POSTGRES_USER" "$SCRATCH"
  trap '$COMPOSE exec -T postgres dropdb -U "$POSTGRES_USER" --if-exists "$SCRATCH" > /dev/null 2>&1 || true' EXIT

  age -d -i "$AGE_IDENTITY" "$FILE" \
    | $COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d "$SCRATCH" -q > /dev/null

  # Checking it restored *something real*, not merely that psql exited 0.
  TABLES="$($COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d "$SCRATCH" -tAc \
    "select count(*) from information_schema.tables where table_schema='public'")"
  USERS="$($COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d "$SCRATCH" -tAc \
    "select count(*) from users" 2>/dev/null || echo 0)"
  KEYS="$($COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d "$SCRATCH" -tAc \
    "select count(*) from exchange_keys" 2>/dev/null || echo 0)"

  echo "  tables:        $TABLES"
  echo "  users:         $USERS"
  echo "  exchange keys: $KEYS"

  [[ "$TABLES" -gt 10 ]] || fail "only $TABLES tables — this backup is not whole"
  printf '\033[32m✓ this backup restores\033[0m\n'
  exit 0
fi

# --- A real restore ------------------------------------------------------
cat <<EOF

  This replaces the contents of "$POSTGRES_DB" with the backup.
  Anything written since $(basename "$FILE") is lost.

EOF
read -r -p "  Type the database name to confirm: " CONFIRM
[[ "$CONFIRM" == "$POSTGRES_DB" ]] || fail "not confirmed"

echo "stopping the API so nothing writes mid-restore"
$COMPOSE stop api > /dev/null

age -d -i "$AGE_IDENTITY" "$FILE" \
  | $COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -q

echo "starting the API"
$COMPOSE start api > /dev/null

printf '\033[32m✓ restored from %s\033[0m\n' "$(basename "$FILE")"
echo
echo "  Check the app, and check your bots: their state came from the"
echo "  backup, so anything armed at backup time is armed again now."
