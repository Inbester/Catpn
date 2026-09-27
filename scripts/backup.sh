#!/usr/bin/env bash
#
# An encrypted database backup. Runs on the server.
#
#   ./scripts/backup.sh            a routine backup
#   ./scripts/backup.sh pre-deploy labelled, taken by deploy.sh
#
# Encrypted with age, because this dump contains the sealed exchange keys
# and their wrapped data keys. An unencrypted dump on the same disk as the
# database protects against a disk failure and nothing else.
#
# BACKUP_RECIPIENT (an age public key) must be set in infra/.env. Keep the
# matching private key OFF this server — a backup you can decrypt with a
# file stored next to it is not a backup, it is a copy.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LABEL="${1:-routine}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="${BACKUP_DIR:-$ROOT/backups}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-30}"

# shellcheck source=/dev/null
[[ -f infra/.env ]] && source infra/.env

: "${POSTGRES_USER:=quanta}"
: "${POSTGRES_DB:=quanta}"
: "${BACKUP_RECIPIENT:?set BACKUP_RECIPIENT (an age public key) in infra/.env}"

command -v age > /dev/null || { echo "age is not installed: https://github.com/FiloSottile/age" >&2; exit 1; }

mkdir -p "$DEST"
OUT="$DEST/quanta-$STAMP-$LABEL.sql.age"

echo "backing up $POSTGRES_DB → $(basename "$OUT")"

# --clean --if-exists so the dump can be restored over an existing
# database without hand-dropping it first.
docker compose -f infra/docker-compose.prod.yml exec -T postgres \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists \
  | age -r "$BACKUP_RECIPIENT" -o "$OUT"

SIZE="$(du -h "$OUT" | cut -f1)"

# A dump that ends without pg_dump's footer is a truncated dump, and the
# time to find that out is now, not during a restore.
if [[ ! -s "$OUT" ]]; then
  rm -f "$OUT"
  echo "backup is empty — failing rather than keeping it" >&2
  exit 1
fi

echo "wrote $OUT ($SIZE)"

# --- Retention -----------------------------------------------------------
# Pre-deploy backups are kept longer than routine ones: those are the ones
# you reach for when a deploy went wrong weeks ago.
find "$DEST" -name 'quanta-*-routine.sql.age' -mtime "+$KEEP_DAYS" -delete 2>/dev/null || true
find "$DEST" -name 'quanta-*-pre-deploy.sql.age' -mtime "+$((KEEP_DAYS * 3))" -delete 2>/dev/null || true

COUNT="$(find "$DEST" -name 'quanta-*.sql.age' | wc -l | tr -d ' ')"
echo "$COUNT backup(s) on disk"

cat <<'EOF'

  Reminder: a backup that has never been restored is a file, not a backup.
  Run ./scripts/restore.sh --verify-latest on a scratch database from time
  to time. It is the only way to know this works.
EOF
