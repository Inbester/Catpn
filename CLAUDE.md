# Quanta — working notes for Claude

Read this first. It exists so a prompt about one part of the system does
not cost a read of the whole system.

**Before touching code, open [`docs/architecture/MAP.md`](docs/architecture/MAP.md).**
It answers "which files do I need for this task?" in one page. Go to the
files it names; do not sweep the tree.

## What this is

A multi-user crypto perpetual-futures charting, research and trading
platform. The product specification is [`docs/SPEC.md`](docs/SPEC.md); every
design decision and its reason is logged in
[`docs/DECISIONS.md`](docs/DECISIONS.md). When the two disagree, DECISIONS
is newer — it records amendments to the spec.

## Layout

```
apps/api/          FastAPI backend, Python 3.11
apps/web/          React 18 + TypeScript, Vite
packages/engine/   Strategy DSL, backtest and research maths (pure Python)
infra/             Docker Compose, deployment
docs/              Spec, decisions, architecture
scripts/           Test and deploy commands
```

## The rules that are not negotiable

These come from SPEC §5 and §9. Breaking one is a bug however well the
code reads.

1. **The exchange API key never leaves the server.** Not to the client,
   not to a log, not into an audit row. Only a label, the last four
   characters and a fingerprint are shown.
2. **A key that can withdraw is refused**, and a key not pinned to the
   server's static IP is refused. The platform never holds funds.
3. **Bot order traffic leaves from the server's static IP** and is never
   routed through a user's VPN. Nothing in the execution path takes a
   proxy argument, which is how that stays true.
4. **No feature may exist to evade an exchange's geo-restrictions.**
   Bitunix restricts Iran among others; the adapter layer stays pluggable
   so a compliant venue can replace it.
5. **A risk limit never blocks an exit.** Every check lets a reduce-only
   order through. See `apps/api/quanta/services/risk.py`.
6. **Order `client_id`s are derived, never random**, so a retry cannot
   become a second position.
7. **User code is never `eval`'d.** Strategies go through the DSL in
   `packages/engine/quanta_engine/dsl/`.

## House style

Full details in [`docs/architecture/CONVENTIONS.md`](docs/architecture/CONVENTIONS.md).
The short version:

- **Comments say why, not what.** A comment that restates the code is
  noise; a comment that records the reason a non-obvious choice was made
  is the most valuable line in the file.
- **Tests assert behaviour, not implementation**, and each test's name is
  the claim it makes.
- Python: `ruff` for lint and format, `mypy --strict`, no `Any` where a
  type is knowable. TypeScript: `eslint`, `tsc --noEmit`, `prettier`.
- Money and quantities are `Decimal` in Python, never `float`.
- Every user-facing string in the web app goes through i18n
  (`apps/web/src/i18n/en.json`). The interface is **English only** and the
  calendar **Gregorian**; Persian appears solely as hover help
  (`apps/web/src/features/glossary/`).

## Before you say a change is done

```bash
./scripts/test-all.sh        # every gate, all three packages
```

Never report work as finished on the strength of a subset.

## Deploying

Laptop → tests → server. `./scripts/deploy.sh` refuses to ship a dirty
tree or a failing suite. See [`docs/DEPLOY.md`](docs/DEPLOY.md).
