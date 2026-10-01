# Running Quanta on your own server

The loop this is built for:

```
   laptop  ──edit──▶  ./scripts/test-all.sh  ──▶  ./scripts/deploy.sh  ──▶  server
                            every gate              refuses to ship
                                                    a failing suite
```

## Before anything: do not put this on the public internet

One user does not need a public port. Put the server behind **WireGuard**
or **Tailscale**, bind the app to the VPN address, and publish nothing.

That single decision removes almost the entire attack surface — no scanner
finds you, no one brute-forces the login, a zero-day in the reverse proxy
cannot be reached. Everything else in this document is smaller than that
one choice.

The alternative is a public port plus TLS, a firewall, fail2ban, and
keeping all of it patched — ongoing work that the VPN simply deletes.

---

## Part 1 — the laptop

Clone wherever you keep projects. On macOS, for the layout you asked for:

```bash
mkdir -p ~/Documents/Cloude
cd ~/Documents/Cloude
git clone https://github.com/Inbester/Catpn.git BioChart
cd BioChart
```

Install the three toolchains:

```bash
# Database and cache for local work
cp infra/.env.example infra/.env     # then fill in the two passwords
docker compose -f infra/docker-compose.yml up -d

# API
cd apps/api
uv venv .venv && uv pip install -e ".[dev]"
cp .env.example .env                 # then fill in SECRET_KEY and VAULT_MASTER_KEY
.venv/bin/alembic upgrade head
cd ../..

# Engine
cd packages/engine && uv venv .venv && uv pip install -e ".[dev]" && cd ../..

# Web
cd apps/web && npm install && cd ../..
```

Generate each secret separately:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Run it:

```bash
cd apps/api && .venv/bin/uvicorn quanta.main:app --reload    # :8000
cd apps/web && npm run dev                                   # :5173
```

If the exchange is unreachable, run the simulator and point `.env` at it —
see the README.

### The one command that decides a change is done

```bash
./scripts/test-all.sh
```

Lint, format, types and tests across the engine, the API and the web app,
plus `alembic check` and a production build. `--quick` skips the database
suite when you are iterating; never deploy on `--quick`.

---

## Part 2 — the server, once

**Install:** Docker with the compose plugin, `git`, `age`, and your VPN.

**Get the code:**

```bash
sudo mkdir -p /opt/quanta && sudo chown "$USER" /opt/quanta
git clone https://github.com/Inbester/Catpn.git /opt/quanta
cd /opt/quanta
```

**Configure.** Copy `infra/.env.example` to `infra/.env` and set:

| Setting | What it is |
|---|---|
| `POSTGRES_PASSWORD`, `REDIS_PASSWORD` | Generate both. Compose refuses to start without them. |
| `SECRET_KEY` | Signs sessions. |
| `VAULT_MASTER_KEY` | Unwraps exchange keys. **Must differ from `SECRET_KEY`** — production refuses to boot otherwise. |
| `SITE_ADDRESS` | `quanta.internal` for Caddy's own certificate, or a real domain. |
| `SITE_ORIGIN` | The same address with its scheme, e.g. `https://quanta.internal`. |
| `BIND_ADDRESS` | The server's **VPN** address. Leave at `127.0.0.1` if you tunnel. |
| `EXCHANGE_STATIC_IP` | The address orders leave from. Without it no exchange key can be added at all. |
| `BACKUP_RECIPIENT` | Your `age` public key. |
| `TELEGRAM_BOT_TOKEN` | From @BotFather. Without it Telegram alerts are recorded as failed, with that reason. |
| `WIREPROXY_AWG_COMMAND` | Optional. Path to an AmneziaWG build of wireproxy; only needed for AmneziaWG configs. |

WireGuard tunnels need nothing on the host: wireproxy is built into the API
image and runs as the app's own user. The server only has to be able to
reach each tunnel's endpoint over **UDP** — if a firewall blocks outbound
UDP, every tunnel will fail its Test with a timeout.

**Backup keys:**

```bash
age-keygen -o quanta-backup.key          # run this on your LAPTOP
grep 'public key' quanta-backup.key      # → BACKUP_RECIPIENT on the server
```

Keep the private key off the server. A backup you can decrypt with a file
sitting next to it is a copy, not a backup.

**Bring it up:**

```bash
cd /opt/quanta
docker compose -f infra/docker-compose.prod.yml up -d --build
docker compose -f infra/docker-compose.prod.yml run --rm api alembic upgrade head
```

**Trust Caddy's certificate** (only for `tls internal`). Caddy prints the
root's location; copy it to each device and trust it once:

```bash
docker compose -f infra/docker-compose.prod.yml exec web \
  cat /data/caddy/pki/authorities/local/root.crt
```

**Point your VPN's DNS** at the server for `SITE_ADDRESS`, or add a hosts
entry on each device.

---

## Part 3 — deploying a change

On the laptop, once:

```bash
cp scripts/deploy.env.example scripts/deploy.env   # then fill it in
```

Then, every time:

```bash
./scripts/deploy.sh
```

What it does, in order:

1. **Refuses a dirty tree.** Commit or stash first.
2. **Pushes** the branch if the server would not otherwise see it.
3. **Runs every gate.** A failure stops the deploy here.
4. **Checks for live bots.** If any is armed or running it stops and says
   so — restarting the API under a live position is your call, not a
   script's. `ALLOW_LIVE=1` overrides once you have decided.
5. **Backs the database up**, labelled `pre-deploy`.
6. **Ships**: fetch, reset to your commit, rebuild, migrate, restart.
7. **Waits for health.** Up to a minute.
8. **Rolls the code back** if it never became healthy.

Step 8 restores the code, not the schema: a migration that ran is still
applied, and reversing one automatically is how data gets lost. If the new
schema is incompatible with the old code, restore:

```bash
AGE_IDENTITY=~/quanta-backup.key ./scripts/restore.sh --latest
```

---

## Part 4 — backups

Run one nightly. On the server:

```bash
crontab -e
# 03:17 rather than 03:00 — nothing else on the machine wakes at :17.
17 3 * * * cd /opt/quanta && ./scripts/backup.sh >> /var/log/quanta-backup.log 2>&1
```

Routine backups are kept 30 days, pre-deploy ones 90 — those are the ones
you reach for when a deploy went wrong weeks ago.

**Prove they work.** Monthly, with the private key to hand:

```bash
AGE_IDENTITY=/media/usb/quanta-backup.key ./scripts/restore.sh --verify-latest
```

This restores into a scratch database, counts the tables, the users and the
exchange keys, then drops it. The live database is never touched. A backup
nobody has ever restored is a file with a hopeful name.

**Copy them off the machine.** A backup on the same disk as the database
survives a bad migration but not a dead disk.

---

## Part 5 — before real money

1. **Turn on 2FA.** Nothing can arm a bot without it.
2. **Add the exchange key** with trading permission only, whitelisted to
   `EXCHANGE_STATIC_IP`. A key that can withdraw is refused outright.
3. **Paper trade first.** A Setup cannot become a bot until it passes.
4. **Press the kill switch on purpose.** Once, with a real position open,
   before you are relying on it. A kill switch nobody has tested is a
   button, not a guarantee.
5. **Start small.** Testnet, then an amount you would not mind losing,
   then normal size.

Read [`architecture/SECURITY.md`](architecture/SECURITY.md) for the
invariants — including the honest list of what is *not* yet proven, such as
the Bitunix order signing, which has never run against the live venue.

---

## Troubleshooting

**The API will not start.** It refuses unsafe production configuration on
purpose. The error names every problem at once:

```bash
docker compose -f infra/docker-compose.prod.yml logs api | tail -20
```

**Compose will not start.** It has no default passwords. Set
`POSTGRES_PASSWORD` and `REDIS_PASSWORD` in `infra/.env`.

**No exchange key can be added.** `EXCHANGE_STATIC_IP` is unset. That is
deliberate: a key admitted without a whitelist is worse than no key.

**The browser will not trust the site.** Caddy's local CA has not been
trusted on that device — see Part 2.

**A tunnel says "Failed".** The reason under it is wireproxy's own. A
timeout usually means outbound UDP to the endpoint is blocked; "no such
host" means the endpoint name does not resolve from the server. Tunnels
only ever carry alert delivery (and AI later); if they are all down,
alerts go from the server and each delivery says so.
