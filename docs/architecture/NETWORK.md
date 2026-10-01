# Networks: tunnels, routes, and what stays on the server

Read this before touching anything under Resources → Network, alert
delivery's transport, or an exchange client's HTTP setup.

## The one-paragraph version

A user imports WireGuard configs. Each one runs on the server as its own
**wireproxy** process — a userspace WireGuard client that exposes the
tunnel as a SOCKS5 proxy on a loopback port. A feature that may use a
tunnel (alert delivery, later AI) asks `routing.resolve` which proxy to use
for this user right now and builds its HTTP client with it. Exchange
traffic never asks, never imports the tunnel code, and is pinned to ignore
proxy variables, so it always leaves from the server's static IP.

## Why a proxy per tunnel and not kernel WireGuard

| | Kernel WireGuard + policy routing | wireproxy (chosen) |
|---|---|---|
| Needs | root / `NET_ADMIN`, `wg-quick`, `ip rule` per tunnel | nothing — a static binary as the app's user |
| How traffic picks a tunnel | routing table, by source address or fwmark | the HTTP client is handed a proxy URL |
| Failure mode | one wrong rule silently moves **all** traffic, orders included | a proxy can only carry what is handed to it |
| Several tunnels at once | a table and rule set each | a port each |
| Imported `PostUp` lines | executed as root by `wg-quick` | stripped before the config is written |

The second column is SPEC §9 enforced by construction: exchange traffic
cannot end up in a tunnel by accident, because nothing routes it there.

## Files

| Piece | File |
|---|---|
| Config parsing and validation (the import form) | `api/services/wireguard.py` |
| Rendering, sealing at rest, running, measuring | `api/services/tunnels.py` |
| Choosing a route for one send | `api/services/routing.py` |
| Process-wide manager + live notifier | `api/api/network_runtime.py`, started in `api/main.py` |
| HTTP API | `api/api/routes/network.py` |
| Alert delivery using the route | `api/services/alert_runner.py::_deliver`, `api/api/routes/alerts.py` (test send) |
| Transport per route | `api/services/notifier.py::_client_for` |
| Models | `api/models/network.py` (`Tunnel`, `FeatureRoute`, `ROUTABLE_FEATURES`, `UNROUTABLE`) |
| UI | `web/features/resources/NetworkTab.tsx`, `web/features/resources/lib/network.ts` |
| The binary in production | `infra/Dockerfile.api` (`wireproxy` stage, pinned v1.1.3) |
| The guard | `apps/api/tests/test_network_isolation.py` |

## Lifecycle of a tunnel

1. **Import.** `wireguard.parse` names every mistake; the config is sealed
   with Fernet keyed from `VAULT_MASTER_KEY` (not `SECRET_KEY`) and only a
   summary — endpoint, addresses, public key — is ever returned.
2. **Start, lazily.** Nothing runs at boot. The first Test, or the first
   alert routed through it, calls `TunnelManager.ensure`, which renders the
   config (whitelisted keys only, `[Socks5]` on `127.0.0.1:<free port>`,
   `[Resolve] ResolveStrategy = ipv4`, DNS added if missing), writes it
   `0600`, starts wireproxy, waits for the port, and **deletes the file**.
3. **Use.** `routing.resolve` walks the user's ordered list for the feature:
   switched off → skipped; fails to start → skipped with wireproxy's own
   reason; recently carried nothing → skipped; first that comes up wins.
   None → the server's own route. The skips are written into the delivery
   record, so the activity feed says which way a message actually went.
4. **Fail over on send.** The usual real failure is a wireproxy that
   starts and listens but never completes a handshake — invisible until
   something is sent. `routing.deliver` watches each send: a failure in
   the path (connection error, or the malformed SOCKS reply wireproxy
   gives with no handshake) marks the tunnel unreachable for 60 s and
   re-sends only those destinations by the next route. A refusal from the
   destination itself (a 404 webhook) is not retried — every route would
   get the same answer. A Test that succeeds clears the mark.
5. **Stop.** Switching a tunnel off or removing it stops the process and
   drops the pooled HTTP client that pointed at it. Shutdown stops all.

## What was verified against the real binary (v1.1.3)

These are not guesses; each one changed the code.

- **`ResolveStrategy` must be set.** The default `auto` is not handled by
  the resolver, so every hostname lookup fails.
- **A config without `DNS` cannot resolve through the tunnel.** Public
  resolvers are added and the import form says so.
- **AmneziaWG configs pass `--configtest` and then never connect.** Plain
  wireproxy ignores `Jc`, `S1`, `H1`… and speaks ordinary WireGuard to an
  Amnezia server. Such configs are refused unless `WIREPROXY_AWG_COMMAND`
  names an AmneziaWG build.
- **wg-quick keys (`PostUp`, `Table`, `SaveConfig`) are ignored**, not
  executed. They are stripped anyway, so that stays true whatever a future
  version does.
- **httpx and websockets follow `HTTPS_PROXY` by default.** Every client
  that must take a specific route sets `trust_env=False` (websockets:
  `proxy=None`).
- End to end: two wireproxy peers, a real handshake, an HTTP request
  through the SOCKS5 side — `tests/test_tunnels.py::TestRealWireproxy`,
  run when `WIREPROXY_TEST_BINARY` points at the binary.

## What may be routed

| Feature | Routable | Why |
|---|---|---|
| Alert delivery (Telegram, webhooks) | yes | reachability: Telegram is blocked on some networks |
| AI | yes (no AI traffic yet) | reachability |
| Chart live data | **no** | exchange traffic from a personal exit is the circumvention SPEC §9 rules out |
| Research history download | **no** | same |
| Trading bot orders | **no** | the key is pinned to the server's static IP |

The refusal is in three places: the routes API (`UNROUTABLE`), the
resolver (`routing.resolve` raises), and the isolation test, which fails
the build if any module on the exchange path imports the tunnel code or
passes a proxy.

## Measuring

Test sends up to three real GETs to `TUNNEL_PROBE_URL` (Cloudflare's
trace by default, which also reports the exit IP) and reports median
latency, mean successive difference as jitter, loss, and a one-word band.
If the first one gets nothing back it stops there: through a dead tunnel
the rest would fail the same way. Every request through a tunnel — probe
or alert — has a hard 8 s deadline via `asyncio.timeout`, because httpx's
own timeouts do not cover the SOCKS exchange and wireproxy holds that open
for about 35 s while it waits on a peer that never answers. No handshake
age: wireproxy does not expose it, and an invented number would be
believed. Tests are limited to one per tunnel per 25 seconds.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `WIREPROXY_COMMAND` | `wireproxy` | the binary (in the production image) |
| `WIREPROXY_AWG_COMMAND` | empty | an AmneziaWG build; empty refuses Amnezia configs |
| `TUNNEL_RUNTIME_DIR` | system temp | where the short-lived rendered configs go |
| `TUNNEL_PROBE_URL` | Cloudflare trace | what Test measures against |

## Not built, on purpose

- **Kernel WireGuard / network namespaces.** Unneeded for HTTP-level
  routing, and they bring back the "one rule moves everything" failure.
- **A tunnel for the whole server.** That would be a host change, outside
  the app, and would put order traffic in it.
- **Routing exchange traffic.** See the table above; this is SPEC §9.
