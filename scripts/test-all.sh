#!/usr/bin/env bash
#
# Every gate, all three packages. This is the command that decides whether
# a change is finished — not a subset of it, and not "the tests I thought
# were relevant".
#
#   ./scripts/test-all.sh          run everything
#   ./scripts/test-all.sh --quick  skip the slow database suite
#
# Exit code 0 means the change may ship. deploy.sh runs this and refuses
# to continue on anything else.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

QUICK=0
[[ "${1:-}" == "--quick" ]] && QUICK=1

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
fail() { printf '\033[31m✗ %s\033[0m\n' "$1"; exit 1; }
pass() { printf '\033[32m✓ %s\033[0m\n' "$1"; }

step() {
  local name="$1"; shift
  printf '  %-34s' "$name"
  if "$@" > /tmp/quanta-gate.log 2>&1; then
    printf '\033[32mok\033[0m\n'
  else
    printf '\033[31mFAILED\033[0m\n\n'
    tail -40 /tmp/quanta-gate.log
    fail "$name"
  fi
}

# --- Engine --------------------------------------------------------------
bold "engine"
cd "$ROOT/packages/engine"
[[ -x .venv/bin/python ]] || fail "packages/engine/.venv missing — run: uv venv .venv && uv pip install -e '.[dev]'"
step "lint"        .venv/bin/ruff check .
step "format"      .venv/bin/ruff format --check .
step "types"       .venv/bin/mypy quanta_engine
step "tests"       .venv/bin/pytest -q

# --- API -----------------------------------------------------------------
bold "api"
cd "$ROOT/apps/api"
[[ -x .venv/bin/python ]] || fail "apps/api/.venv missing — run: uv venv .venv && uv pip install -e '.[dev]'"
step "lint"        .venv/bin/ruff check .
step "format"      .venv/bin/ruff format --check .
step "types"       .venv/bin/mypy quanta tests
if [[ $QUICK -eq 0 ]]; then
  # These need Postgres and Redis. Say so plainly when they are not
  # there: the alternative is a forty-line asyncpg traceback whose actual
  # message is "connection refused" on the last line.
  if ! (exec 3<>/dev/tcp/127.0.0.1/5432) 2>/dev/null; then
    fail "Postgres is not running on :5432 — start it with:
      docker compose -f infra/docker-compose.yml up -d
    or skip the database suite with: ./scripts/test-all.sh --quick"
  fi
  if ! (exec 3<>/dev/tcp/127.0.0.1/6379) 2>/dev/null; then
    fail "Redis is not running on :6379 — start it with:
      docker compose -f infra/docker-compose.yml up -d"
  fi
  step "migrations" .venv/bin/alembic check
  step "tests"      .venv/bin/pytest -q
else
  printf '  %-34s\033[33mskipped (--quick)\033[0m\n' "migrations + tests"
fi

# --- Web -----------------------------------------------------------------
bold "web"
cd "$ROOT/apps/web"
[[ -d node_modules ]] || fail "apps/web/node_modules missing — run: npm install"
step "lint"        npm run lint
step "format"      npx prettier --check "src/**/*.{ts,tsx,css}"
step "types"       npm run typecheck
step "tests"       npm test
step "build"       npm run build

echo
pass "every gate passed"
