# Quanta

Crypto charting, research and trading platform for perpetual futures.

The full product specification is in [`docs/SPEC.md`](docs/SPEC.md); the design
decision log is in [`docs/DECISIONS.md`](docs/DECISIONS.md) and the approved
mockups are in [`docs/design/`](docs/design/).

> **Status:** phase 2 (see SPEC §8). Auth, workspace autosave, the app shell,
> the Bitunix market-data pipeline, the Chart menu, and the strategy DSL,
> backtest engine and Test menu.

## Layout

```
apps/api/        FastAPI backend (Python 3.11)
apps/web/        React + TypeScript frontend (Vite)
packages/engine/ Strategy DSL and backtest core
infra/           Docker Compose for local development
docs/            Specification, decisions and design references
```

## Running it locally

Start Postgres (with TimescaleDB) and Redis:

```bash
docker compose -f infra/docker-compose.yml up -d
```

### API

```bash
cd apps/api
uv venv .venv && uv pip install -e ".[dev]"
cp .env.example .env
.venv/bin/alembic upgrade head
.venv/bin/uvicorn quanta.main:app --reload
```

The API serves on <http://localhost:8000>, with docs at `/docs` outside
production.

### Web

```bash
cd apps/web
npm install
npm run dev
```

The app serves on <http://localhost:5173>.

### Market data without the exchange

`fapi.bitunix.com` is unreachable from some networks, and SPEC §9 lists
regions where the venue is restricted. A simulator speaks the same wire
format so the chart, backfill and fan-out all work offline:

```bash
cd apps/api
.venv/bin/python -m quanta.exchanges.sim     # serves on :8100
```

Then point the API at it in `apps/api/.env`:

```
EXCHANGE_REST_URL=http://127.0.0.1:8100
EXCHANGE_WS_URL=ws://127.0.0.1:8100/public/
```

Its bars are generated from a seed, so the same symbol and timeframe give
identical output on every run.

### Loading deep history

Boot only warms a recent window, because SPEC §6 stores history once,
server-side, rather than fetching it live for each user. A forward test or
a walk-forward over a year needs more than that, so load it explicitly:

```bash
cd apps/api
.venv/bin/python -m quanta.tools.backfill BTCUSDT 1h \
  --start 2025-03-01 --end 2026-05-01 --funding
```

Dates are UTC and `--end` is exclusive. `--funding` also stores the
8-hourly settlements, without which a backtest over that range charges no
funding and quietly understates its own costs.

## Tests

```bash
cd packages/engine && .venv/bin/pytest
cd apps/api && .venv/bin/pytest          # needs the quanta_test database
cd apps/web && npm test
```

The chart's TypeScript indicators are pinned to the Python engine by a
generated fixture (`apps/web/src/features/chart/lib/__fixtures__`). If the
two ever disagree a user would see one number on screen and another in
their backtest, with no way to tell which is right, so the parity test
fails instead.

`quanta_test` is created once with:

```bash
docker exec quanta-postgres psql -U quanta -d quanta -c "CREATE DATABASE quanta_test OWNER quanta;"
```

## Notes

Charting uses TradingView Lightweight Charts, which requires attribution.
Order traffic is locked to the server's static egress IP and is never routed
through user VPN tunnels — see SPEC §9 for the compliance rules this follows.
