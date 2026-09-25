# Quanta — Crypto Charting, Research & Trading Platform
### Project Specification v1.0 · 2026-09-26

> **برای گفتگوی بعدی:** این فایل و `quanta-design.zip` را بدهید و بگویید «فاز ۰ و ۱ را بساز».
> این سند مرجع اصلی است. تصاویر داخل zip طراحی تأییدشده‌اند. هر جا بین متن و تصویر اختلاف بود، متن این سند معتبر است.
>
> **For the implementing agent:** Read this whole file first. Mockup PNGs are in `quanta-design.zip → images/`. The HTML/JS mockup sources are in `mockups/`. They are visual references only, use fake data, and are **not** production code. Build the real app from this spec.

---

## 0. Product summary

This is a multi-user web platform for crypto perpetual futures. It has seven parts:

1. **Chart:** a TradingView-like live chart with indicators and drawing tools.
2. **Research:** build strategies, auto-discover indicator relationships, and study leverage, costs and risk as a professional trader or CFO would.
3. **Test:** backtest, forward test (period vs period, walk-forward) and paper trading.
4. **Alerts:** strategy, price, indicator and risk signals sent to browser push and Telegram.
5. **Trading bot:** executes a validated setup on the exchange. Its design is **not done yet**.
6. **Resources:** choose server or local compute, and set up WireGuard network routing per feature.
7. **AI:** placeholder. Scope **not defined yet**.

**The core principle:** a strategy is defined once, in a safe formula DSL. The *same engine code* runs it everywhere: chart, backtest, forward test, paper, alerts and bot. There is no duplicate logic.

**The core object is the Setup.** A Setup is a named, colored bundle:

- a locked strategy version (content hash)
- symbol and timeframe
- parameters and exit rules
- position: margin % × leverage, margin mode
- fee tier
- risk budget
- the research run it came from

Every menu (Test, Alerts, Bot) has a Setup picker in its header.

---

## 1. Decisions log

| # | Decision | Status |
|---|---|---|
| D1 | Menu order: Chart · Research · Test · Alerts · Trading bot · Resources · AI | ✅ approved |
| D2 | Visual theme A "Graphite" (dark) is the default. Theme B "Paper" (light) is the alternative. | ✅ approved |
| D3 | Chart view (menu 1) | ✅ approved |
| D4 | Research (Builder, Discover, multi-indicator, leverage/costs, trade risk, robustness, range controls, Setups) | ✅ approved |
| D5 | Test (period vs period, walk-forward, paper trading, drawdown charts everywhere) | ✅ approved |
| D6 | Alerts and Telegram | ✅ approved |
| D7 | Resources (Compute, Network/WireGuard) | ✅ approved |
| D8 | Global Jobs ring and active-alerts bell in the rail. Autosave and History. | ✅ approved |
| D9 | Trading bot menu design | ⏳ **pending** (design in the next session, before phase 6) |
| D10 | AI menu scope | ⏳ **pending** |
| D11 | UI language | ⏳ Default: **English UI with an i18n-ready frontend**. Persian (RTL chrome, LTR charts and numbers) comes later. Jalali calendar support is required from day one. |
| D12 | Exchange | ⏳ Default: an **exchange adapter layer**. Bitunix is adapter #1. See §9 (legal). |
| D13 | Formula authoring | ⏳ Default: a **safe DSL plus a visual builder**. Never `eval` user code. |
| D14 | Local compute agent (Python app on the user's PC) | ⏳ Default: **deferred**. Browser and server compute first. |
| D15 | Backend language | ✅ Python |

---

## 2. Design system (strict)

### Grid and layout

- **Spacing:** 8 px base grid with a 4 px sub-step. Every spacing value is a multiple of 4.
- **Layout skeleton:**
  - App rail: 56 px
  - Drawing toolbar (chart only): 48 px
  - Main area: fluid
  - Right panel: 320 px
  - Header bars: 56 px
  - Tab strips: 44 px

### Typography

- **UI text:** Inter 400/500/600, 13/16 base.
- **Numbers:** JetBrains Mono with tabular figures. Every price and value is monospaced so digits do not shift on live updates.

### Colour tokens

| Token | Theme A (dark) | Theme B (light) |
|---|---|---|
| bg | `#0B0C0E` | `#F7F7F5` |
| surface | `#0F1113` | `#FFFFFF` |
| line | `#1C1F23` | `#E6E5E1` |
| line2 | `#15171A` | `#EFEEEB` |
| text | `#E7E9EC` | `#16181B` |
| muted | `#7D848E` | `#6F737A` |
| dim | `#4A5059` | `#A3A6AB` |
| up | `#2EBD85` | `#0E9F6E` |
| down | `#F0506E` | `#D83A4A` |
| accent-bg | `#1A1D21` | `#F0EFEC` |
| drawing | `#6EA8FE` | `#2563EB` |
| amber (liq/warn) | `#F59E0B` | `#B7791F` |

### Rules

- **Colour carries meaning only.** Green and red mean up and down, amber means warning or liquidation, blue means drawings. Everything else is neutral.
- **No flashing prices.** A price change gets at most a subtle 300 ms tint.
- **Paper vs LIVE** is always shown with a persistent badge.
- **Live actions need confirmation.** Starting a live bot or using the kill switch requires 2FA confirmation.
- **Fixed page pattern:** settings panel on the left, results in the middle, detail or summary on the right.
- **Icons:** 1.5 px stroke line icons, 20 px in the rail, 16–18 px elsewhere.

### Global chrome (every page)

**App rail, top to bottom:**
1. Logo
2. The 7 menus
3. Spacer
4. **Jobs ring:** % progress plus a queued-count badge. Click opens the **Jobs tray** (Running / Queued / Paused with checkpoint / Finished).
5. **Active-alerts bell:** green count badge. Click opens active alerts grouped by Setup, with the next check times.
6. Settings
7. Account

**Other global chrome:**
- **Top-bar save status:** "Saved", "Saving…" or "Offline". The **History** tab lives in the chart's right panel.
- **Completion toast:** shown when a job finishes. A browser notification is also sent if the tab is hidden. The tab title shows `(61%) Quanta`.

### Mockups (images in the zip)

| Area | Files |
|---|---|
| Design direction | `design-A-graphite`, `design-B-paper` |
| Chart | `chart-1` … `chart-6` |
| Strategy / Research | `strategy-1` … `strategy-7` |
| Jobs and autosave | `jobs-1`, `jobs-2`, `autosave-history` |
| Forward test | `forward-1` … `forward-3` |
| Research | `research-1` … `research-5` |
| Alerts | `alerts-1` … `alerts-3`, `rail-active-alerts` |
| Setups | `setups-1` … `setups-3` |
| Resources | `resources-1`, `resources-2` |

---

## 3. Menus: functional spec

### 3.1 Chart ✅

**Chart engine**
- TradingView **Lightweight Charts** (open source; attribution required). Custom plugins are needed for the candle countdown, drawings and position lines.
- **Data:** a live kline stream over one shared server-side WebSocket, fanned out to clients via Redis pub/sub. Missing bars are gap-filled on reconnect.
- **Candle source:** Last or Mark price, selectable.

**Top bar**
- Symbol search (⌘K; searches instantly in-memory on the client)
- Compare (later)
- Timeframes 1m / 5m / 15m / 1h / 4h / 1D plus custom
- Chart type: candles, hollow, Heikin-Ashi, bars, line, area
- Indicators
- Templates
- Create alert
- Replay (later)
- Undo / Redo
- Layout (later)
- Settings
- Screenshot
- Fullscreen / focus mode (hides the side panels)

**Left drawing toolbar** (TradingView grouping; flyouts; favourites with a star)
- **Cursors:** cross, dot, arrow, eraser
- **Lines:** trend (Alt+T), ray, info, extended, horizontal (Alt+H), horizontal ray (Alt+J), vertical (Alt+V), cross line (Alt+C), channels
- **Other groups:** Fibonacci, patterns, long/short position tool, shapes, brush, text
- **Utilities:** ruler, zoom
- **Magnet:** weak or strong, snapping to OHLC
- **Drawing state:** stay-in-drawing mode, lock all, hide all (drawings / indicators / all), remove all
- **Object tree** (right panel)

**Selected drawing**
- A floating toolbar with: colour, width, style, text, **add alert**, lock, delete, settings, more.
- Keys: ⌫ deletes, ⌘Z undoes.

**Legend**
- OHLC with change, a live dot, and the value of every indicator.
- Hovering an indicator shows eye / gear / × / more.

**Panes**
- Move up/down, collapse, maximize, remove.
- Hiding Volume or collapsing a pane gives the space back to the price chart.

**Price scale**
- Last price with the **candle countdown underneath**. The countdown uses exchange server time and UTC bar boundaries; its format depends on the timeframe (mm:ss / hh:mm:ss / 2d 04h).
- High and low of the visible range; mark price line.
- Modes: %, log, auto, invert.

**Trading lines**
- Position entry with live PnL, TP, SL, **liquidation price**, alert lines, execution arrows.
- Dragging TP/SL comes with the bot phase.

**Time scale**
- Day and session breaks.
- Range buttons 1D / 5D / 1M / 3M / 6M / YTD / 1Y / All.
- Go to date; clock with timezone (Tehran UTC+3:30); jump back to the live bar.

**Right panel** (tabs Watchlist / Objects / History)
- **Watchlist:** symbol, last, 24h %.
- **Detail card:** mark, index, funding/8h, next funding countdown, 24h high/low.

**Settings dialog** (6 tabs): Symbol, Status line, Scales & lines, Canvas, Trading, Alerts. Settings can be saved as a template.

**Persistence**
- Drawings are saved per symbol and timeframe. Indicators, panes, zoom and layouts are saved too.

### 3.2 Research ✅

**Strategy list and Builder** (tabs: Builder / Formula / Discover)

*Builder*
- **Inputs:** each parameter can be marked as optimizable.
- **Long entry and short entry:** condition rows combined with ALL or ANY, plus OR groups. Conditions are evaluated **on bar close** by default.
- **Exit and risk:** ATR stop loss, R-multiple take profit, break-even, trailing stop, opposite signal, time exit. The first rule hit closes the position.

*Formula view*
- Shows the same rules as DSL text and stays in sync with the builder.

*Discover (auto-relationship engine)*
1. Sources are the indicators the user adds, any number of them.
2. The engine auto-detects each series' **scale group**: unbounded price-like, bounded 0–100 (thresholds 30/50/70), centered at 0, or centered at 1.
3. It then generates **primitives**:
   - **Per series:** slope rising/falling (filter), turn up/down (trigger), N-bar high/low (trigger), neutral level above/below (filter), level cross (trigger).
   - **Per same-scale pair:** position above/below (filter), cross (trigger), spread converging/diverging (filter).
   - **Three or more on one scale:** stack order (filter).
   - **Price vs each non-price series:** divergence, regular and hidden, bullish and bearish (trigger).
4. **Rule** = 1 trigger plus up to 2 filters. Contradictions and redundancies are pruned (for example, "crosses above" already implies "above").
5. Each rule is tested long and short over 4 horizons. Options: max conditions per rule; "mix ≥ 2 indicators" only.
6. **Statistics:**
   - Benjamini–Hochberg FDR at 5%.
   - A 70/30 in-sample / out-of-sample split.
   - Returns shown before and after Bitunix costs.
   - The "expected false hits" count is displayed.
   - The **Add** button pushes a rule into the Builder.

*Reference counts, used for testing the enumerator*

| Case | Primitives | Raw combos ≤3 | Valid rules | Tests |
|---|---|---|---|---|
| Price + 3-line indicator (L1, L2 around 0; L3 around 1) | 54 (18 filters / 36 triggers) | 26,289 | 5,324 | 42,592 |
| Price + EMA20/50 + RSI14 + 3-line indicator | 112 (48 / 64) | 234,248 | 69,828 | 558,624 |

In the second case, cross-indicator-only rules number 59,348.

**Research study tabs:** Leverage & costs · Trade risk · Robustness · Relationships (Discover results) · Risk report (CFO PDF)

*Setup panel* (all values are ranges, pulled **live from Bitunix**)
- **Market:** the leverage limits come from `maxLeverage` and the position tiers.
- **Margin per trade:** dual range slider 0–100% with a step.
- **Leverage:** dual range slider from 1× to the exchange max, on a log scale. BTCUSDT on Bitunix allows 200×.
- **Margin mode:** isolated, cross or both.
- **Fee tier:** dropdown listing VIP 0–8 with maker/taker rates and requirements. The account's tier is auto-detected. Multiple tiers can be selected for comparison.
- **Max drawdown budget:** dual range, e.g. −10% to −25%.
- **Risk of ruin:** slider, e.g. ≤1% chance of losing 50%.

*Leverage & costs*
- A **margin × leverage heatmap** showing net per year and max drawdown. In-budget cells are outlined, out-of-budget cells dimmed, and liquidations badged.
- **Recommendation:** the best net inside the budget, at the **lowest leverage for equal exposure**. Key insight to show: exposure = margin × leverage, and lower leverage means a farther liquidation price.
- An isolated vs cross table covering: exposure, liquidation distance, net per year, max DD, worst trade, number of liquidations, costs ÷ gross, risk of ruin.
- A return vs drawdown chart.

*Trade risk*
- MAE scatter (worst point vs final result) with liquidation lines per leverage.
- KPIs: winners that were red first, median dip, 95th-percentile dip, deepest dip ("survives up to N×"), worst closed trade, average hold and funding events.
- The deepest trades listed.
- Holding-time histogram with net funding.

*Robustness*
- Parameter heatmap to judge plateau vs peak.
- 1,000 reshuffled years (Monte Carlo).
- Daily VaR and CVaR.
- Kelly and half-Kelly risk per trade.
- Stress tests: VIP3 fees, fees ×2, slippage ×3, funding +0.03% per 8h, removing the best 5 trades.

*Save as setup*
- Name, colour, and a summary of everything in the bundle.
- Checkboxes for where to use it: Backtest / Forward / Paper / Alerts / Bot. The Bot option is locked until paper trading passes.

*Setups overview*
- A pipeline table per setup: Research → Backtest → Forward → Paper → Alerts → Bot, each stage with a status chip.
- Exposure KPIs.
- Conflict checks: the same symbol on one account in one-way mode must use **hedge mode or sub-accounts**.
- A combined-drawdown simulation against the user's budget.

**Compute**
- Heavy research runs on **Server** or **This computer** (see Resources).
- The footer widget shows the source and device (CPU/GPU/RAM bars). Clicking it opens a popover with the detected hardware, allocation sliders, live usage and progress.

### 3.3 Test ✅

**Backtest**

*Execution model*
- Fill at the next bar's open.
- 1m bar magnifier to resolve intrabar TP/SL.
- Commissions, slippage, **historical funding** every 8h, **mark-price liquidation** with tiered maintenance margin (MMR).
- No lookahead, no repaint.

*Result tabs*
- **Overview:** KPI strip (net, max DD, PF, win rate, avg win/loss, Sharpe/Sortino, costs, buy & hold), equity **with a drawdown pane**, cost breakdown, long vs short, P&L distribution, P&L by weekday, leverage sensitivity.
- Performance, Trades analysis.
- **List of trades:** click a trade to see it on the chart. Columns: run-up, drawdown, fees, funding, cumulative P&L. CSV export.
- Costs & liquidation, Properties.

**Forward test** (the strategy version is frozen and hash-locked)

*Period vs period* (the user's own idea)
- Reference period vs test period, with **Jalali month presets**: same month this year, same month every year, next month, custom.
- A **Monte Carlo 90% band** built from the reference trades.
- Verdict chip, e.g. HOLDS UP · WEAKER, plus checks.
- Side-by-side table including **longest drawdown (days)**.
- Equity and drawdown by trade number, with a worst-case line.
- A market regime panel (BTC return, volatility, trend efficiency, candle range, long vs short net) and a written explanation.

*Walk-forward*
- 12 windows, 3 months optimise → 1 month test.
- Gantt timeline, chosen parameters, max DD per window, WFE.
- Chained out-of-sample equity with an underwater chart.

*Paper trading*
- Live feed. KPI strip showing next bar close.
- Live vs expected **cone** and **drawdown vs band and user limit**.
- Execution quality: latency, real slippage, funding, missed signals, fills from the live order book.
- **Promotion checklist:**
  - ≥14 days running
  - ≥30 trades
  - Inside the cone
  - DD under the limit
  - Drift ≤0.025%

  "Promote to bot" unlocks when all pass, or via a 2FA override.

**Rule:** every equity chart in the product has a drawdown pane under it.

### 3.4 Alerts ✅

**Alert types**
- **Strategy (via Setup):** long/short entry, exit, TP/SL hit.
- **Price:** including lines drawn on the chart.
- **Indicator.**
- **Risk:** drawdown, liquidation distance.
- **Market:** funding.
- **System:** bot errors, disconnects.

**Evaluation**
- Runs **server-side, 24/7**, so alerts fire with the browser closed.
- Default is on bar close (no repaint). Every tick is optional.

**Options**
- Repeat: every signal, once, or once per bar. Expiry.
- **Burst merge:** signals within 10 s become one message.
- **Quiet hours:** Telegram sends silently.

**Message template**
- Variables: `{{side_icon}} {{SIDE}} {{symbol}} {{tf}} {{strategy}} {{version}} {{price}} {{sl}} {{sl_pct}} {{tp}} {{tp_pct}} {{size}} {{leverage}} {{pnl}} {{rsi}} {{time_tehran}} {{chart_link}}`
- Optional chart snapshot. English or Persian.
- Every message ends with "Not financial advice".

**Destinations**
- Browser push per device
- Telegram DM, group, channel
- Webhook (HMAC-signed JSON)
- Email

**Activity view**
- Each event with per-destination status and latency, and retry notes such as `429 → retried`.
- A preview of the Telegram message with inline buttons "Open chart" and "Mute 1 h".

**Channels page:** see §7 for Telegram setup details.

### 3.5 Trading bot ⏳ (design pending; requirements so far)

- A bot = one Setup + an exchange API key + risk limits. It is only available after the Setup passes paper trading.
- **API keys:**
  - Keys with withdrawal permission are rejected.
  - The key must be IP-whitelisted to the server's static IP (Bitunix allows up to 20 IPs per key).
  - Keys are envelope-encrypted with KMS or Vault and never returned to the client.
- **Risk limits:** max position, max daily loss, max DD with auto-stop, max leverage, max orders per minute, and a **kill switch** (2FA).
- Idempotent orders via `clientId`. Reconciles with exchange positions on restart. Hedge-mode awareness.
- Every order goes to an audit log.
- **Order traffic always leaves from the server's static IP and is never routed through user VPNs** (see §9).

### 3.6 Resources ✅

**Compute tab**
- Two cards, **Server** and **This computer**, each showing the user's share or detected hardware, the queue or allocation, and speed on the last run.
- Live server specs: CPU, memory, GPU and storage, each with a utilisation bar.
- **Per-feature choice:**

| Feature | Options |
|---|---|
| Research / Discover | Server / This computer / Auto |
| Backtest & forward | Server / This computer / Auto |
| Alerts & bots | Server (locked) |

- **Browser compute, what can be detected:**
  - `navigator.hardwareConcurrency`
  - WebGPU `adapter.info`: vendor and architecture only, never the exact model
  - `navigator.deviceMemory`: coarse, power-of-two values
  - COOP/COEP headers are required for SharedArrayBuffer and WASM threads
  - OPFS for the data cache
- **Browser compute, allocation and limits:**
  - Allocation sliders: CPU workers %, GPU duty cycle %, RAM budget. One core is reserved for the chart; work throttles on battery.
  - Live usage shows **this app only**; the browser cannot see whole-system load.
- Jobs run in workers outside page components, so switching menus never stops them. They checkpoint to IndexedDB. Closing the tab pauses browser jobs; server jobs continue.

**Network tab (WireGuard)**
- **Add configs:** upload several `.conf` files or paste one. The expected format is displayed:
```
[Interface]
PrivateKey = <44-char base64>
Address    = 10.8.0.2/32
DNS        = 1.1.1.1            # optional
[Peer]
PublicKey  = <44-char base64>
PresharedKey = <base64>         # optional
Endpoint   = host.example.net:51820
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
```
- **Validation before saving:** both sections exist, keys are valid 32-byte base64, Endpoint is host:port, Address is an IP/CIDR.
- **Live test every 30 s:** handshake age, 20 pings (average), jitter, packet loss, throughput, exit IP (masked), quality bars (Excellent / Good / Fair / Poor).
- **Per-feature routing with ordered failover:** Chart live data, Research history download, Alerts/Telegram, AI. The **Trading bot uses the server's static IP, locked**.
- Private keys are encrypted at rest and never shown again.
- *Implementation note:* tunnels live in the server's network namespace, one per user config (or a per-tenant egress service). Rate-limit the tests.

### 3.7 AI ⏳ — scope to be defined.

---

## 4. Architecture

```
[Browser SPA: React + TS + Vite · Lightweight Charts · Web Workers + WASM/WebGPU compute · Service Worker (push, cache)]
        │  HTTPS + WSS (JWT access 15 min / refresh HttpOnly cookie)
[API Gateway: FastAPI (async) · rate limit · WAF/CDN in front]
        ├─ auth-service (Argon2id, TOTP 2FA, sessions)
        ├─ market-data-service ── 1 shared WS to exchange ──► Redis pub/sub ──► client WS fan-out
        │                          + REST backfill → TimescaleDB (klines, mark klines, funding history)
        ├─ strategy-engine (pure Python + NumPy/Numba; same core compiled to WASM later via Pyodide/Rust port if needed)
        ├─ job-runner (Arq/Celery + Redis): backtests, discovery, walk-forward, Monte Carlo — checkpointed
        ├─ alert-evaluator (bar-close scheduler per symbol/TF) ──► notifier (Telegram, Web Push/VAPID, webhook, email) with queue + retries
        ├─ execution-service (ISOLATED process/host, static egress IP, no inbound internet) — bots only
        ├─ network-service (WireGuard tunnels, health checks, per-feature egress routing)
        └─ persistence: PostgreSQL 16 + TimescaleDB · Redis · object storage (reports, snapshots)
```

**Monorepo layout**
- `apps/web`, `apps/api`
- `packages/engine` (the strategy DSL and core)
- `services/*`
- `infra/` (Docker Compose for dev, then Kubernetes or Nomad)

**Exchange adapter interface**

```python
class ExchangeAdapter(Protocol):
    async def symbols() -> list[Symbol]            # min/max leverage, precision, status
    async def position_tiers(symbol) -> list[Tier]
    async def fee_tiers() -> list[FeeTier]; async def account_fee_tier(key) -> str
    async def klines(symbol, tf, start, end, price_type="LAST"|"MARK") -> list[Bar]
    async def funding_history(symbol, start, end) -> list[Funding]
    def stream(channels) -> AsyncIterator[Event]   # kline, ticker, mark, depth
    # private (execution-service only)
    async def place_order(...); cancel; positions; balance; set_leverage; set_margin_mode
```

**Strategy DSL**
- Expression grammar parsed to an AST with a whitelist of functions: `ema, sma, rsi, atr, macd, crossover, crossunder, rising, falling, highest, lowest, …`
- Sandbox limits: no attribute access, no imports, a step limit, CPU and memory time limits.
- Series are evaluated vectorised.
- A strategy version is identified by a content hash of its AST plus parameters.

---

## 5. Security checklist (OWASP ASVS L2 target)

- **Authentication:**
  - Argon2id password hashing.
  - TOTP 2FA, **required** for bots, API keys, kill switch and changes to withdrawal-adjacent settings.
  - Short-lived JWTs plus refresh tokens in HttpOnly, SameSite=strict cookies. CSRF tokens on cookie-auth routes.
- **Isolation:** tenant isolation enforced at the query layer (row-level security in Postgres).
- **Secrets:** exchange keys, Telegram bot tokens and WireGuard private keys are envelope-encrypted (KMS/Vault), write-only from the UI and never logged.
- **User code:** never executed; only the DSL runs.
- **Abuse limits:** rate limits per user and per IP. Job quotas. Caps on Discover test counts. Upload validation for `.conf` files.
- **Headers:** CSP (strict, nonce-based), COOP/COEP (needed for compute), HSTS. Dependency pinning plus SCA scanning.
- **Audit:** every order, key change, bot start/stop and alert destination change goes to an append-only audit log.
- **Execution service:** separate network segment; outbound to the exchange only; static IP; idempotency keys; startup reconciliation.
- **Backups:** encrypted, with a tested restore procedure.

---

## 6. Bitunix API reference (verified 2026-09)

**Endpoints**
- **Base REST:** `https://fapi.bitunix.com`.
- **Auth headers:** `api-key`, `nonce` (32 chars), `timestamp` (ms), `sign` (built with the SecretKey), `Content-Type: application/json`.
- **Klines:** `GET /api/v1/futures/market/kline`
  - Params: `symbol, interval (1m 5m 15m 30m 1h 2h 4h 6h 8h 12h 1d 3d 1w 1M), startTime, endTime, limit ≤200, type=LAST_PRICE|MARK_PRICE`
  - **10 req/s per IP.**
  - Backfill history once and store it; never query history live per user.
- **Funding history:** `GET /api/v1/futures/market/get_funding_rate_history` (`symbol, startTime, endTime, limit ≤200`) → `markPrice, fundingRate, fundingTime`. 10 req/s per IP.
- **Trading pairs:** returns `maxLeverage, minLeverage, defaultLeverage, basePrecision, quotePrecision, minTradeVolume, maxMarketOrderVolume, symbolStatus, maxFundingRate, minFundingRate, isApiSupported`. 10 req/s per IP.
- **Position tiers (public):** `GET /api/v1/futures/position/get_position_tiers?symbol=` → `level, startValue, endValue, leverage, maintenanceMarginRate`.
- **Place order:** 10 req/s per UID.
  - Fields: `symbol, qty, price, side BUY|SELL, tradeSide OPEN|CLOSE (hedge), orderType LIMIT|MARKET, effect IOC|FOK|GTC|POST_ONLY, positionId, clientId, reduceOnly, tpPrice, tpStopType MARK_PRICE|LAST_PRICE, tpOrderType, tpOrderPrice, slPrice, slStopType, slOrderType, slOrderPrice`.

**WebSocket**
- Public `wss://fapi.bitunix.com/public/`, private `wss://fapi.bitunix.com/private/`.
- **Max 5 messages per second including ping/pong**; exceeding it disconnects, and repeat offenders get IP bans.
- Up to 300 subscriptions per connection.
- Public channels: kline, depth, ticker, trade, market price. Private channels: order, position, balance, TP/SL.

**Fees (futures maker / taker)**

| Tier | Maker / taker | Requirement (any one: 30-day futures volume · or balance) |
|---|---|---|
| VIP0 | 0.020 / 0.060% | below VIP1 |
| VIP1 | 0.020 / 0.050% | 1M · or 1K |
| VIP2 | 0.016 / 0.050% | 5M · or 10K |
| VIP3 | 0.014 / 0.040% | 8M · or 50K |
| VIP4 | 0.012 / 0.0375% | 20M · or 200K |
| VIP5 | 0.010 / 0.035% | 50M · or 1M |
| VIP6 | 0.008 / 0.0315% | 100M · or 2M |
| VIP7 | 0.006 / 0.030% | 200M · or 3M |
| VIP8 | 0.000 / 0.026% | 500M |

Fetch these from the exchange when possible; this table is the fallback.

**Funding**
- Every 8 h at 00:00, 08:00, 16:00 UTC (can vary per pair).
- Fee = position value × rate. A positive rate means longs pay shorts.
- The rate is fixed at the start of each period.

**Liquidation**
- Uses mark price and tiered MMR.
- Isolated long: `liq ≈ entry × (1 − (margin − maint) / (margin × lev))`.
- Cross mode uses the whole account balance in place of margin.
- **Max leverage:** BTC/ETH USDT perpetuals go up to **200×**, but read it per symbol from the API.

**API keys:** permissions read / trade / withdraw (reject withdraw); up to 20 whitelisted IPs per key.

**Sources:**
- openapidoc.bitunix.com (also bitunix.com/api-docs/futures/…)
- bitunix.com/service/handling-fee
- Bitunix help center articles on funding (id 79), forced liquidation (id 151), tiered MMR (id 78) and restricted regions (id 146)

---

## 7. Telegram and Web Push

**Telegram**
- **One platform bot**, e.g. `@QuantaAlertsBot`. The user can optionally paste their own BotFather token, stored encrypted.
- **Linking:**
  - DM: `https://t.me/<bot>?start=<code>`
  - Group: `?startgroup=<code>` (the group admin confirms)
  - Channel: add the bot as admin with only **Post messages**, paste @username, and the platform posts a verification message.
  - Codes: `[A-Za-z0-9_-]`, ≤64 chars, **single-use, 10 min TTL**. Store only `chat_id`; `/stop` unlinks.
- **Limits:** about 1 message/s per chat, **20 messages/min per group**, about 30 messages/s bulk. Queue per chat with token buckets, merge bursts, retry on 429 honouring `retry_after`.
- **Message features:** inline keyboard "Open chart" and "Mute 1 h"; `disable_notification` during quiet hours; chart snapshot via `sendPhoto`.

**Web Push**
- VAPID with a Service Worker. Permission is requested only from a user click.
- **iOS 16.4+:** works only if the site is installed to the Home Screen (manifest with `display: standalone`). Show a guide in Alerts → Channels → Browser.

---

## 8. Build phases

Each phase ends runnable and tested.

| Phase | Scope | Done when |
|---|---|---|
| **0** | Monorepo, Docker Compose (Postgres + Timescale, Redis), FastAPI skeleton, auth (Argon2 + TOTP), React/Vite/TS app shell, **design tokens A and B**, rail with 7 menus, Jobs ring and bell (stub), autosave framework (IndexedDB + server sync), i18n and Jalali utilities, CI, security headers | Log in, see the shell in both themes, CI green |
| **1** | Exchange adapter (Bitunix public), market-data service (one shared WebSocket, Redis fan-out, backfill to Timescale), **Chart**: live candles, countdown, timeframes, watchlist with instant search, symbol detail card, indicators (EMA, SMA, RSI, MACD, Volume, ATR, BB) with legend and pane controls, drawing toolbar (lines group, magnet, lock, hide, remove, object tree), selected-drawing toolbar, settings dialog, History tab, persistence | Live BTCUSDT chart with drawings that survive a refresh |
| **2** | DSL and engine (AST, sandbox, hash versioning), Builder and Formula views, **Backtest** (next-open fills, 1m magnifier, fees, historical funding, mark-price liquidation with tiers), result tabs, list of trades, trade view on the chart, CSV export | Backtest reproduces hand-checked fixtures |
| **3** | **Test**: period vs period (Jalali presets, Monte Carlo band, regime panel), walk-forward, drawdown panes everywhere, **Setups** (save, picker in all headers, overview) | Farvardin 1404 vs 1405 report runs |
| **4** | **Research**: range controls with live Bitunix limits and fee tiers, margin × leverage heatmap, trade risk (MAE), robustness (Monte Carlo, VaR, Kelly, stress), **Discover** (enumerator matching the §3.2 counts, FDR, out-of-sample), Resources/Compute (server job runner plus browser workers/WASM/WebGPU, allocation sliders, progress, checkpoint/resume) | Enumerator unit tests match 5,324 and 69,828 |
| **5** | **Alerts**: server evaluator on bar close, notifier (Telegram DM/group/channel, Web Push, webhook, email), templates EN/FA, burst merge, quiet hours, delivery log, active-alerts bell; **paper trading** (live, execution-quality metrics, promotion checklist); Resources/Network (WireGuard import/validate/test/route) | Signal reaches a Telegram group within 2 s of bar close |
| **6** | Finish the Trading bot design, then build: execution service, key vault, risk limits, kill switch, reconciliation, audit log, hedge-mode checks | Testnet or small live dry run passes a checklist |
| **7** | AI menu (after its scope is defined), Persian UI, Local agent (optional), hardening, load tests, pen test | — |

---

## 9. Legal and compliance (must read)

- **Bitunix restricted regions** include Iran, the UAE, Iraq, the US, Canada, France, mainland China, Hong Kong, Singapore, Malaysia and others (help center id 146; the list can change).
  - Users in restricted regions must not trade on Bitunix. Accounts can be frozen.
  - The platform **must not** provide features intended to evade exchange geo-restrictions or sanctions. This is why bot order traffic is locked to the server's static IP and is never routed through user VPN tunnels.
  - Keep the exchange layer pluggable so a compliant venue can be added.
- **Multi-user signals and bots** can count as investment advice or portfolio management in many jurisdictions. Recommended model:
  - Users connect **their own** API keys and trade their own accounts.
  - The platform never holds funds.
  - Clear Terms of Service and a risk disclosure.
  - "Not financial advice" on every signal.
  - Get local legal advice before a public launch.
- **Telegram channels:** the user is responsible for local rules on publishing trading signals.

---

## 10. Open items for the next session

1. Design the **Trading bot** menu (D9).
2. Define the **AI** menu (D10).
3. Confirm the defaults for D11–D14.
4. Choose where the code lives: connect a local folder in the Claude desktop app, or build in the cloud workspace and download.
5. Pick hosting (region with access to the Bitunix and Telegram APIs), a domain, and whether to create the Telegram bot now via @BotFather (the token is entered later, encrypted).
6. The **user** provides Bitunix API keys only in phase 6, and only if legally permitted in their jurisdiction.
