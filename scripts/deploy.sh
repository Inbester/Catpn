#!/usr/bin/env bash
#
# Laptop → tests → server.
#
#   ./scripts/deploy.sh
#
# It refuses to ship a dirty tree or a failing suite, backs the database
# up before it migrates, and rolls back to the previous commit if the new
# version does not come up healthy.
#
# Configure it once in scripts/deploy.env (copy deploy.env.example).
#
# The one thing it will not decide for you: a bot that is armed or running
# is holding real money, and restarting the API under it is your call. The
# script stops and says so.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

bold() { printf '\n\033[1m%s\033[0m\n' "$1"; }
info() { printf '  %s\n' "$1"; }
fail() { printf '\033[31m✗ %s\033[0m\n' "$1"; exit 1; }
pass() { printf '\033[32m✓ %s\033[0m\n' "$1"; }

# --- Configuration -------------------------------------------------------
CONFIG="$ROOT/scripts/deploy.env"
[[ -f "$CONFIG" ]] || fail "no scripts/deploy.env — copy scripts/deploy.env.example and fill it in"
# shellcheck source=/dev/null
source "$CONFIG"

: "${DEPLOY_HOST:?set DEPLOY_HOST in scripts/deploy.env}"
: "${DEPLOY_PATH:?set DEPLOY_PATH in scripts/deploy.env}"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-$(git rev-parse --abbrev-ref HEAD)}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/api/v1/health/ready}"
SKIP_TESTS="${SKIP_TESTS:-0}"

remote() { ssh "$DEPLOY_HOST" "cd '$DEPLOY_PATH' && $*"; }

# --- 1. The tree must be clean -------------------------------------------
bold "1. local state"
[[ -z "$(git status --porcelain)" ]] || fail "working tree is dirty — commit or stash first"
info "tree clean, branch $DEPLOY_BRANCH"

LOCAL_SHA="$(git rev-parse HEAD)"
git fetch --quiet origin "$DEPLOY_BRANCH"
if [[ "$(git rev-parse "origin/$DEPLOY_BRANCH")" != "$LOCAL_SHA" ]]; then
  info "pushing $LOCAL_SHA to origin/$DEPLOY_BRANCH"
  git push origin "$DEPLOY_BRANCH"
fi

# --- 2. Tests ------------------------------------------------------------
bold "2. tests"
if [[ "$SKIP_TESTS" == "1" ]]; then
  # Deliberately loud: this is the guard that makes the whole script worth
  # having, and skipping it should never feel routine.
  printf '\033[33m  SKIPPED — you set SKIP_TESTS=1\033[0m\n'
else
  "$ROOT/scripts/test-all.sh"
fi

# --- 3. Is anything live? ------------------------------------------------
bold "3. live bots"
RUNNING="$(remote "docker compose -f infra/docker-compose.prod.yml exec -T postgres \
  psql -U \${POSTGRES_USER:-quanta} -d \${POSTGRES_DB:-quanta} -tAc \
  \"select count(*) from bots where state in ('armed','running')\"" 2>/dev/null || echo "?")"

if [[ "$RUNNING" == "?" ]]; then
  info "could not ask the server (first deploy, or the stack is down) — continuing"
elif [[ "$RUNNING" != "0" ]]; then
  printf '\033[33m  %s bot(s) are armed or running.\033[0m\n' "$RUNNING"
  info "Restarting the API under a live bot is your call, not this script's."
  info "Stop them in the app, or re-run with ALLOW_LIVE=1 if you know what"
  info "this deploy changes."
  [[ "${ALLOW_LIVE:-0}" == "1" ]] || fail "refusing to deploy over live bots"
  printf '\033[33m  ALLOW_LIVE=1 — continuing anyway\033[0m\n'
else
  info "no bots armed or running"
fi

# --- 4. Back up before migrating -----------------------------------------
bold "4. backup"
remote "./scripts/backup.sh pre-deploy" || fail "backup failed — not deploying"
pass "database backed up"

# --- 5. Ship -------------------------------------------------------------
bold "5. deploy"
PREVIOUS="$(remote "git rev-parse HEAD")"
info "server is at ${PREVIOUS:0:8}, moving to ${LOCAL_SHA:0:8}"

remote "git fetch --quiet origin '$DEPLOY_BRANCH' && git checkout --quiet '$DEPLOY_BRANCH' && git reset --hard --quiet '$LOCAL_SHA'"
remote "docker compose -f infra/docker-compose.prod.yml build --quiet"
remote "docker compose -f infra/docker-compose.prod.yml run --rm api alembic upgrade head"
remote "docker compose -f infra/docker-compose.prod.yml up -d"

# --- 6. Prove it came up -------------------------------------------------
bold "6. health"
HEALTHY=0
for attempt in $(seq 1 30); do
  if remote "curl -fsS '$HEALTH_URL' > /dev/null 2>&1"; then
    HEALTHY=1
    break
  fi
  sleep 2
done

if [[ $HEALTHY -eq 1 ]]; then
  pass "healthy at ${LOCAL_SHA:0:8}"
  remote "docker image prune -f > /dev/null 2>&1 || true"
  exit 0
fi

# --- 7. Roll back --------------------------------------------------------
printf '\033[31m  did not come up healthy — rolling back to %s\033[0m\n' "${PREVIOUS:0:8}"
remote "git reset --hard --quiet '$PREVIOUS'"
remote "docker compose -f infra/docker-compose.prod.yml build --quiet"
remote "docker compose -f infra/docker-compose.prod.yml up -d"

# The code is back; the schema is not. A migration that ran is still
# applied, and undoing it automatically is how data gets lost.
cat <<'EOF'

  The code rolled back. The database did NOT: any migration that ran is
  still applied, and reversing one automatically is how data is lost.

  If the new schema is not compatible with the old code, restore from the
  backup taken in step 4:

      ./scripts/restore.sh --latest

EOF
exit 1
