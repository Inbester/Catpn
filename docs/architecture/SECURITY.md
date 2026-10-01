# What must never break

The invariants. Each one has a reason and a place in the code where it is
enforced. Changing any of them is a spec change, not a refactor.

## The exchange key

**It never leaves the server.** Not in a response, a log, an audit row, an
error message or a `__repr__`. What may be shown is a label the user
chose, the last four characters, and a fingerprint.

- Sealed: `services/keyvault.py`
- Shown: `services/bot_service.py::key_summary`
- Proven: `tests/test_bot_routes.py::TestKeySecrecy`

**A key that can withdraw is refused**, and so is one not pinned to the
server's static IP. The platform never holds funds, so it never needs
withdrawal permission; an unrestricted key works from anywhere, which is
what the whitelist exists to prevent.

- Enforced: `services/keyvault.py::verify_admissible`
- Proven: `tests/test_keyvault.py::TestAdmission`

**Envelope encryption.** Each secret gets its own random data key; the data
key is sealed under a master key that never reaches the database. Every
ciphertext is bound to its owning user and key id, so a row copied into
another account fails to open rather than quietly decrypting.

**The vault's master key is not the session key.** `VAULT_MASTER_KEY` is
its own setting and production refuses to start if it is missing or equal
to `SECRET_KEY` — one leak must not cost both.

- Enforced: `core/config.py::_reject_insecure_production_config`

## Order traffic

**It leaves from the server's static IP and is never routed through a user
VPN** (SPEC §9). Nothing in the execution path takes a proxy argument,
which is the cheapest way to keep that true. WireGuard routing in
Resources/Network covers alert delivery and AI only — exchange traffic is
deliberately excluded.

Tunnels are SOCKS5 proxies on loopback, one wireproxy process each, never
routes in the host's table — so a tunnel can only carry what is explicitly
handed to it. The exchange clients set `trust_env=False` (and the
websocket `proxy=None`), because both libraries otherwise follow
`HTTPS_PROXY` from the environment and one stray variable would move order
traffic off the static IP. Details: [`NETWORK.md`](NETWORK.md).

- Enforced: `tests/test_network_isolation.py` fails the build if a module
  on the exchange path imports the tunnel code, passes a proxy, or builds a
  client that trusts the environment.

## Tunnel configs

**A WireGuard private key is a credential.** Sealed at rest with a key
derived from `VAULT_MASTER_KEY`, never returned by the API. When a tunnel
starts, the rendered config is written `0600`, read once by wireproxy, and
deleted as soon as the proxy listens. Host commands in an imported file
(`PostUp`, `PreDown`, …) are stripped before anything is written; nothing
in a config can make the server run a command.

**No feature may exist to evade geo-restrictions.** Bitunix restricts Iran
among other regions. The adapter layer stays pluggable so a compliant
venue can replace it.

## The bot

**A risk limit never blocks an exit.** Every check lets a reduce-only order
through. A daily-loss limit that trips while a position is open and then
refuses the closing order has taken a bad day and made it unbounded.

- Enforced: `services/risk.py::RiskGuard.check_order`, first branch
- Proven: `tests/test_risk.py::TestExitsAreNeverBlocked`

**`client_id`s are derived, never random.** The same signal computes the
same id on every run, so a crash between "order sent" and "order recorded"
cannot become a second position. The database has a unique
`(bot_id, client_id)` as the second half of the same guarantee.

- `services/execution.py::client_id_for`, `models/bot.py`

**An uncertain order is resolved, never resent.** A timeout does not mean
the order failed; it means nobody knows.

**Halted is not stopped.** A halt carries its reason and only a person
clears it. Clearing returns a bot to `stopped`, never to `armed`.

**Anything that can move money verifies 2FA server-side.** Arming, going
live, the kill switch, and raising a risk limit. Lowering a limit does
not — making yourself safer should not be gated behind a phone.

- `api/routes/bots.py::_require_2fa`

## The web layer

**No user code is ever `eval`'d.** Strategies go through the DSL in
`engine/dsl/`.

**Security headers on every response**: CSP with per-request nonces, HSTS,
`X-Frame-Options: DENY`, `nosniff`, COOP/COEP/CORP, Referrer-Policy.

- `core/middleware.py::SecurityHeadersMiddleware`

**Sessions**: Argon2 passwords, TOTP with replay protection (a used
counter is refused), refresh-token rotation, CSRF token, HttpOnly cookies.

## Deployment

**Postgres and Redis bind loopback**, never `0.0.0.0`. This database holds
the sealed exchange keys.

**Compose refuses to start without passwords.** A default that works
everywhere is a password that works everywhere.

**Production refuses to boot unsafely**: a placeholder `SECRET_KEY`, a
missing or shared `VAULT_MASTER_KEY`, `COOKIE_SECURE=false` or
`DEBUG=true` each stop the process rather than running.

**Recommended exposure: none.** One user does not need a public port. Put
the server behind WireGuard or Tailscale and bind everything to loopback;
that removes almost the whole attack surface at no maintenance cost.

## Known gaps

Honest list, so nobody assumes otherwise:

| Gap | Impact |
|---|---|
| Bitunix order signing unverified against the live venue | Orders may be rejected until the concatenation is corrected. Isolated in one tested function. |
| `LocalMasterKey` is not a KMS | Key material lives in the API process, so a process compromise reaches it. The `MasterKeyProvider` protocol exists so KMS/Vault is two methods. |
| Rate limiting degrades open | If Redis is down, brute-force protection stops. Acceptable behind a VPN; not on a public port. |
| No load test, no pen test | SPEC §8 phase 7. |
