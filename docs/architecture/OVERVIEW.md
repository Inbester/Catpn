# How the system fits together

Four processes, one database, one cache. Nothing clever.

```
                    ┌──────────────┐
   browser ────────▶│   web (Vite) │  React 18 + TypeScript
                    │   static     │  served as static files
                    └──────┬───────┘
                           │  /api/* proxied
                           ▼
                    ┌──────────────┐        ┌───────────────┐
                    │   API        │───────▶│  PostgreSQL   │  + TimescaleDB
                    │   FastAPI    │        │  (hypertables │    for bars
                    │              │        │   for klines) │
                    │  ┌────────┐  │        └───────────────┘
                    │  │ engine │  │        ┌───────────────┐
                    │  └────────┘  │───────▶│     Redis     │  pub/sub + rate
                    └──┬────────┬──┘        └───────────────┘    limits
                       │        │
          market data  │        │  orders (server's static IP only)
                       ▼        ▼
                  ┌─────────────────┐
                  │ exchange adapter│  Bitunix, or the simulator
                  └─────────────────┘
```

## The four processes

**web** — a Vite build. In development `npm run dev` proxies `/api` to the
API; in production it is static files behind Caddy. It holds no secrets and
makes no exchange calls.

**API** — FastAPI. Everything server-side lives here: auth, the market-data
pipeline, backtests, research jobs, alerts, and the trading bot. The
strategy engine is imported as a library, not run as a service.

**PostgreSQL + TimescaleDB** — bars and funding rates are hypertables
because they are time-series and large; everything else is ordinary tables.

**Redis** — pub/sub for the live market fan-out, and fixed-window counters
for rate limiting. Losing it degrades the app (no live chart, no rate
limiting) but does not lose data.

## Where the layers are

```
api/api/routes/     HTTP: parse, authorise, call a service, shape a response.
                    No business logic.
api/services/       The work. One module per area. These are what tests
                    exercise; most take plain arguments and return plain
                    results so they can be tested without a database.
api/models/         SQLAlchemy tables. One file per area.
api/schemas/        Pydantic request shapes.
api/core/           Config, security primitives, middleware, logging.
api/exchanges/      The venue. `base.py` is public market data and is
                    imported everywhere; `trading.py` is private and is
                    imported only by the execution service.
engine/             Pure maths and parsing. No database, no network, no
                    FastAPI. Importable and testable on its own.
```

The division that matters: **`engine/` knows nothing about the web app,
and `api/exchanges/trading.py` is imported by exactly one module.** The
second one is a security boundary, not a style preference — it is how
"can this code place an order?" is answered by reading imports.

## How data flows

**A bar reaching the chart.** The market-data service holds one WebSocket
to the venue per symbol, writes closed bars to Timescale, and publishes
every update to Redis. Each browser gets its own stream from the API, fed
from Redis. One upstream connection serves every user — SPEC §6 requires
history to be stored once, server-side, rather than refetched per user.

**A backtest.** The route loads bars from Timescale, hands them and a
parsed strategy to `engine/backtest/`, and stores the result. The engine
never touches the database.

**An alert firing.** `alert_runner` ticks on bar close, asks
`alert_service` which rules now hold, renders through `alert_templates`,
and hands the message to `notifier`. Evaluation is server-side so an alert
fires whether or not a browser is open.

**An order.** Only `execution.py` can place one. It opens the user's key
from the vault for the length of the call, asks `risk.py` whether the order
may go, derives a `client_id` from the bot, the bar and the purpose, and
sends it. The key is dropped; the order is written to `bot_orders`.

## What runs in the background

Three loops, all inside the API process, all switchable off by config:

| Loop | Module | Off switch |
|---|---|---|
| Market data (WS + backfill) | `services/market_data.py` | `MARKET_DATA_ENABLED` |
| Alert evaluation | `services/alert_runner.py` | `ALERTS_ENABLED` |
| Research jobs | `services/jobs.py` | — |

Tests drive each of them directly rather than waiting on a tick, which is
why they are off in the test environment.

## Working without the exchange

`fapi.bitunix.com` is unreachable from some networks, and SPEC §9 lists
regions where the venue is restricted. `api/exchanges/sim/` speaks the same
wire format:

```bash
cd apps/api && .venv/bin/python -m quanta.exchanges.sim   # :8100
```

Its bars come from a seed, so the same symbol and timeframe give identical
output on every run. `sim/trading.py` is the matching order book, so the
whole trading path can be exercised with no live account.
