# Which files do I need?

A task-to-files index. Find the row that matches the prompt, open those
files, and stop. Reading the whole tree to answer a narrow question is the
expensive mistake this page exists to prevent.

Paths are from the repository root. `api/` means `apps/api/quanta/`,
`web/` means `apps/web/src/`, `engine/` means
`packages/engine/quanta_engine/`.

---

## By task

### "The chart does X wrong"
| | |
|---|---|
| Page and panes | `web/features/chart/ChartPage.tsx` |
| Series, scales, theme | `web/features/chart/lib/chartTheme.ts` |
| Indicators and drawings | `web/features/chart/components/` |
| Where bars come from | `api/services/market_data.py`, `api/services/market_store.py` |
| Bar storage | `api/models/market.py` (Timescale hypertables) |
| Live stream | `api/services/market_data.py` → Redis pub/sub → `web/lib/api/` |

### "A strategy or backtest is wrong"
| | |
|---|---|
| Language: lexer, parser, AST | `engine/dsl/` |
| Evaluating a rule over bars | `engine/dsl/evaluator.py` |
| The backtest loop | `engine/backtest/engine.py` |
| Fees, funding, liquidation | `engine/backtest/liquidation.py` |
| Result metrics | `engine/backtest/stats.py` |
| Running one from the API | `api/services/backtest_service.py`, `api/api/routes/strategies.py` |
| UI | `web/features/test/` |

### "Forward test / walk-forward / Monte Carlo"
| | |
|---|---|
| Period vs period | `engine/forward/compare.py` |
| Walk-forward windows | `engine/forward/walkforward.py` |
| Monte Carlo band | `engine/forward/montecarlo.py` |
| Market regime panel | `engine/forward/regime.py` |
| Month presets (Gregorian, UTC) | `web/features/forward/lib/presets.ts` |
| API | `api/services/forward_service.py`, `api/api/routes/forward.py` |

### "Discover / research"
| | |
|---|---|
| Primitive enumeration | `engine/discover/primitives.py`, `rules.py` |
| Signal evaluation | `engine/discover/signals.py` |
| FDR and significance | `engine/discover/stats.py` |
| The search driver | `engine/discover/search.py` |
| Leverage, trade risk, robustness | `engine/research/` |
| Jobs and progress | `api/services/jobs.py`, `api/models/job.py` |
| UI | `web/features/research/` |

### "Alerts or notifications"
| | |
|---|---|
| Rule evaluation on bar close | `api/services/alert_service.py` |
| The background loop | `api/services/alert_runner.py` |
| Message rendering, disclaimer | `api/services/alert_templates.py` |
| Telegram, web push, webhook, email | `api/services/notifier.py` |
| Models | `api/models/alert.py` |
| UI | `web/features/alerts/` |

### "Paper trading"
| | |
|---|---|
| Sessions, fills, promotion checklist | `api/services/paper_service.py` |
| Models | `api/models/paper.py` |
| UI | `web/features/alerts/components/PaperPanel.tsx` |

### "The trading bot" (SPEC §3.5)
| | |
|---|---|
| **Start here** | [`TRADING.md`](TRADING.md) |
| Protocol and types | `api/exchanges/trading.py` |
| Bitunix implementation | `api/exchanges/bitunix_trading.py` |
| Offline venue for tests | `api/exchanges/sim/trading.py` |
| Risk limits | `api/services/risk.py` |
| Placing, reconciling, killing | `api/services/execution.py` |
| Key sealing | `api/services/keyvault.py` |
| DB joining-up, pre-flight | `api/services/bot_service.py` |
| Routes | `api/api/routes/bots.py` |
| Models | `api/models/bot.py` |

### "Auth, 2FA, sessions"
| | |
|---|---|
| Passwords, TOTP, tokens | `api/services/auth_service.py` |
| Hashing, JWT, TOTP primitives | `api/core/security.py` |
| Routes | `api/api/routes/auth.py` |
| Current-user dependency | `api/api/deps.py` |
| UI | `web/features/auth/LoginPage.tsx`, `web/lib/auth/store.ts` |

### "Something about configuration or startup"
| | |
|---|---|
| Every setting, production guards | `api/core/config.py` |
| App assembly, exception handlers | `api/main.py` |
| Security headers, request ids | `api/core/middleware.py` |
| Rate limiting | `api/core/rate_limit.py` |
| Readable validation errors | `api/core/validation.py` |

### "The database"
| | |
|---|---|
| Every table | `api/models/` (one file per area) |
| Base classes, mixins | `api/db/base.py` |
| Session factory | `api/db/session.py` |
| Migrations | `apps/api/alembic/versions/` |
| Schema drift check | `alembic check` — CI runs it |

### "The app shell, routing, theme"
| | |
|---|---|
| Rail, top bar, trays | `web/components/shell/` |
| Routes | `web/app/routes.tsx` |
| Design tokens | `web/styles/tokens.css` |
| Theme switching | `web/lib/theme.ts` |
| Autosave | `web/lib/autosave/` |

### "Persian hover help"
| | |
|---|---|
| Terms and lookup | `web/features/glossary/lib/terms.ts` |
| Word under the pointer | `web/features/glossary/lib/wordAt.ts` |
| The tip itself | `web/features/glossary/GlossaryTip.tsx` |
| Try it in a browser | `apps/web/glossary.html` + `web/dev/glossary-harness.tsx` |

### "Deployment, backups, the server"
| | |
|---|---|
| **Start here** | [`../DEPLOY.md`](../DEPLOY.md) |
| Local database and cache | `infra/docker-compose.yml` |
| Server stack | `infra/docker-compose.prod.yml` |
| Images | `infra/Dockerfile.api`, `infra/Dockerfile.web` |
| Run every gate | `scripts/test-all.sh` |
| Ship to the server | `scripts/deploy.sh` |
| Backups | `scripts/backup.sh`, `scripts/restore.sh` |

---

## By question

**"Why is it like this?"** → `docs/DECISIONS.md`, newest entries last. Every
non-obvious choice is there with its reason.

**"What is it supposed to do?"** → `docs/SPEC.md`. Section numbers are
referenced from docstrings throughout the code, so `SPEC §3.5` in a
comment means that section.

**"How do I write code here?"** → [`CONVENTIONS.md`](CONVENTIONS.md).

**"What talks to what?"** → [`OVERVIEW.md`](OVERVIEW.md).

**"What must never break?"** → [`SECURITY.md`](SECURITY.md), and the rules
list in `CLAUDE.md`.

---

## Reading order for a newcomer

1. `docs/SPEC.md` §1–§3 — what the product is
2. [`OVERVIEW.md`](OVERVIEW.md) — the shape of the system
3. The one row above that matches what you are about to change
