# How code is written here

The rules an AI or a new contributor should follow so that what they add
reads like what is already there.

## Comments

**A comment says why, not what.** The code already says what it does; a
comment that repeats it is noise that goes stale. The valuable comment is
the one that records a reason you could not recover by reading:

```python
# Idempotency first, before anything can have an effect. A retry after a
# timeout must be indistinguishable from the first call.
existing_id = account.by_client_id.get(request.client_id)
```

```python
# Not noise: the phase 4 migrations created these columns without the
# server defaults their models declare, so every autogenerate since has
# re-reported the difference.
```

Bad:

```python
# Get the account
account = self._account(credentials)
```

**Module docstrings carry the design.** Every module that makes a
non-obvious choice opens with a docstring explaining the shape of the
problem and why it was solved this way. Read `services/risk.py` or
`services/execution.py` for the register.

**Cite the spec.** `SPEC §3.5` in a docstring means that section of
`docs/SPEC.md`. Keep doing it: it is how a reader finds the requirement
behind the code.

## Tests

**Test names are claims.** `test_a_reduce_only_order_passes_a_breached_daily_loss`
says what must be true. `test_risk_2` says nothing.

**Assert behaviour, not implementation.** A test that breaks when a
private method is renamed was testing the wrong thing.

**The important test goes first in the file.** In `test_risk.py` the first
class is `TestExitsAreNeverBlocked`, because that is the rule that matters
most; a reader who stops after one class has still read the right one.

**A test for a bug records the bug.** When something real was found, the
test says so:

```python
# Not "1E-8": scientific notation is not a quantity any venue reads
# back as one satoshi.
assert body["qty"] == "0.00000001"
```

## Python

- `ruff` for lint and format, `mypy` in strict mode. Both run in CI and
  must be clean.
- **`Decimal` for money and quantities, never `float`.** A float position
  size is a wrong position size.
- `from __future__ import annotations` at the top of every module.
- Dataclasses are `frozen=True, slots=True` unless they are mutable state.
- Services take plain arguments and return plain results where they can,
  so they are testable without a database. `risk.py` and `execution.py`
  hold no ORM models on purpose.
- Errors carry a machine-readable code *and* a human sentence. "Invalid
  key" tells a user nothing about which of three settings to change.

## TypeScript

- `eslint`, `tsc --noEmit`, `prettier`. All three run in CI.
- Feature folders: `features/<area>/` holds the page, its components, its
  `lib/`, and its tests. Shared things go in `lib/` or `components/`.
- **Every user-facing string goes through i18n** (`i18n/en.json`). The
  interface is English only; do not add a second bundle.
- CSS modules, and colours come from `styles/tokens.css` — never a literal
  hex in a component.

## Database

- One model file per area, mirroring `services/`.
- Migrations are generated (`alembic revision --autogenerate`) and then
  **read and edited**: autogenerate produces noise and occasionally misses
  intent. `alembic check` must be clean, and CI enforces it.
- A foreign key's `ondelete` is a decision. `RESTRICT` on
  `bots.exchange_key_id` exists because a bot without its key cannot close
  what it holds.

## Security

Never weaken these without changing `docs/SPEC.md` first:

- No secret in a log, an audit row, an error message, or a `__repr__`.
  `Credentials` overrides `__repr__` for exactly this reason.
- No `eval` of user input, ever. The DSL exists so it is not needed.
- Anything that can move money verifies 2FA server-side, not from a
  client-supplied flag.
- New settings that must differ in production belong in the guard in
  `core/config.py`, which refuses to boot rather than run unsafely.

## Commits

One change per commit, with a message that says what and **why**. The body
is prose, not a bullet list of files — the diff already lists the files.
A commit that fixes something found by testing says how it was found.

## When you disagree with a convention

Change it here first, then in the code. A convention that half the tree
follows is worse than either choice.
