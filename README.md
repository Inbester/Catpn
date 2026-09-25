# Quanta

Crypto charting, research and trading platform for perpetual futures.

The full product specification is in [`docs/SPEC.md`](docs/SPEC.md); the design
decision log is in [`docs/DECISIONS.md`](docs/DECISIONS.md) and the approved
mockups are in [`docs/design/`](docs/design/).

> **Status:** phase 0 (see SPEC §8). Auth, workspace autosave and the app shell.

## Layout

```
apps/api/        FastAPI backend (Python 3.11)
apps/web/        React + TypeScript frontend (Vite)
packages/engine/ Strategy DSL and backtest core (phase 2)
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

## Tests

```bash
cd apps/api && .venv/bin/pytest          # needs the quanta_test database
cd apps/web && npm test
```

`quanta_test` is created once with:

```bash
docker exec quanta-postgres psql -U quanta -d quanta -c "CREATE DATABASE quanta_test OWNER quanta;"
```

## Notes

Charting uses TradingView Lightweight Charts, which requires attribution.
Order traffic is locked to the server's static egress IP and is never routed
through user VPN tunnels — see SPEC §9 for the compliance rules this follows.
