"""Running WireGuard tunnels as local proxies (SPEC §3.6).

Each config a user imports runs as its own **wireproxy**: a userspace
WireGuard client that exposes the tunnel as a SOCKS5 proxy on a loopback
port. A feature that should go through a tunnel builds its HTTP client with
that proxy; a feature that should not simply doesn't.

Why this and not kernel WireGuard with policy routing: a tunnel here never
touches the server's routing table. A wrong `ip rule` can silently move
*every* connection onto a tunnel — order traffic included — and nothing in
the application would notice. A proxy can only carry what is explicitly
handed to it, so exchange traffic cannot end up in a tunnel by accident.
That is the property SPEC §9 needs, enforced by construction rather than
by configuration.

Three things learned from running the real binary, each handled below:

- **AmneziaWG configs pass wireproxy's config test and are then silently
  wrong.** Plain wireproxy ignores the obfuscation keys (Jc, S1, H1, …),
  connects as ordinary WireGuard, and never completes a handshake with an
  Amnezia server. They are refused unless the AWG build is configured.
- **wireproxy v1.1.3 cannot resolve hostnames by default.** Its default
  ResolveStrategy is "auto", but the resolver only handles "ipv4" and
  "ipv6", so every lookup fails. Every rendered config sets it explicitly.
- **A tunnel with no DNS server cannot resolve anything through itself.**
  If the config names none, public resolvers are added — reached through
  the tunnel, so local DNS filtering does not apply — and the tunnel's
  summary says so.

The rendered file holds a private key. It is written with 0600, read once
by wireproxy at start, and deleted as soon as the proxy is listening.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import itertools
import os
import shlex
import shutil
import socket
import statistics
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import socksio
import structlog
from cryptography.fernet import Fernet, InvalidToken

from quanta.core.config import Settings, get_settings

logger = structlog.get_logger(__name__)

# What reaches wireproxy. Everything else — PostUp, PreDown, Table,
# SaveConfig, FwMark — is a wg-quick instruction for the host, and none of
# it belongs in a process that should only ever proxy. wireproxy ignores
# them today; stripping them means that stays true whatever it does next.
INTERFACE_KEYS = {"privatekey": "PrivateKey", "address": "Address", "dns": "DNS", "mtu": "MTU"}
PEER_KEYS = {
    "publickey": "PublicKey",
    "presharedkey": "PresharedKey",
    "endpoint": "Endpoint",
    "allowedips": "AllowedIPs",
    "persistentkeepalive": "PersistentKeepalive",
}
# AmneziaWG's obfuscation parameters, kept only for the AWG build.
AMNEZIA_KEYS = {
    "jc": "Jc",
    "jmin": "Jmin",
    "jmax": "Jmax",
    "s1": "S1",
    "s2": "S2",
    "h1": "H1",
    "h2": "H2",
    "h3": "H3",
    "h4": "H4",
}
DEFAULT_DNS = "1.1.1.1, 8.8.8.8"

STARTUP_TIMEOUT_SECONDS = 8.0
# How long a tunnel that carried nothing is passed over before it is tried
# again. Long enough that one dead peer does not cost every alert in a
# burst a timeout; short enough that a recovered one is back within a bar.
UNREACHABLE_SECONDS = 60.0
PROBE_ATTEMPTS = 3
PROBE_TIMEOUT_SECONDS = 8.0


class TunnelError(Exception):
    """A tunnel that would not start or would not carry traffic.

    The message is shown to the user, so it says what to do, not only what
    broke.
    """


# --- Configs at rest -----------------------------------------------------


def _fernet(secret: str, label: bytes) -> Fernet:
    digest = hashlib.blake2b(secret.encode(), digest_size=32, person=label).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _legacy_fernet(settings: Settings) -> Fernet:
    """How phase 5 sealed configs: SHA-256 of the session secret."""
    digest = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def seal_config(text: str, settings: Settings | None = None) -> str:
    """Encrypt a config for storage.

    Keyed from the vault's master secret, not the session one: a WireGuard
    private key is a credential, and one leaked session secret should not
    hand it over (the same reasoning as keyvault.py).
    """
    resolved = settings or get_settings()
    master = resolved.vault_master_key or resolved.secret_key
    return _fernet(master, b"quanta-tunnels").encrypt(text.encode()).decode("ascii")


def open_config(token: str, settings: Settings | None = None) -> str:
    """Decrypt a stored config, including ones sealed before the change of key."""
    resolved = settings or get_settings()
    master = resolved.vault_master_key or resolved.secret_key
    for cipher in (_fernet(master, b"quanta-tunnels"), _legacy_fernet(resolved)):
        with contextlib.suppress(InvalidToken):
            return cipher.decrypt(token.encode("ascii")).decode()
    raise TunnelError("This tunnel's config could not be decrypted. Remove it and import it again.")


# --- Rendering -----------------------------------------------------------


def _sections(text: str) -> dict[str, dict[str, str]]:
    sections: dict[str, dict[str, str]] = {}
    current: str | None = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip().lower()
            sections.setdefault(current, {})
            continue
        if "=" in line and current is not None:
            key, _, value = line.partition("=")
            sections[current][key.strip().lower()] = value.strip()
    return sections


def is_amnezia(text: str) -> bool:
    interface = _sections(text).get("interface", {})
    return any(key in interface for key in AMNEZIA_KEYS)


def has_dns(text: str) -> bool:
    return bool(_sections(text).get("interface", {}).get("dns"))


def render(text: str, *, port: int, amnezia: bool = False) -> str:
    """The wireproxy config for one tunnel: its WireGuard sections, a SOCKS5
    listener on a loopback port, and the resolver settings it needs."""
    sections = _sections(text)
    interface = sections.get("interface", {})
    peer = sections.get("peer", {})

    allowed_interface = dict(INTERFACE_KEYS)
    if amnezia:
        allowed_interface.update(AMNEZIA_KEYS)

    lines = ["[Interface]"]
    for key, canonical in allowed_interface.items():
        if key in interface:
            lines.append(f"{canonical} = {interface[key]}")
    if "dns" not in interface:
        lines.append(f"DNS = {DEFAULT_DNS}")

    lines += ["", "[Peer]"]
    for key, canonical in PEER_KEYS.items():
        if key in peer:
            lines.append(f"{canonical} = {peer[key]}")

    lines += [
        "",
        "[Socks5]",
        # Loopback only: the proxy is for this process, never the network.
        f"BindAddress = 127.0.0.1:{port}",
        "",
        "[Resolve]",
        # Without this, wireproxy v1.1.3 fails every hostname lookup.
        "ResolveStrategy = ipv4",
        "",
    ]
    return "\n".join(lines)


# --- Measuring -----------------------------------------------------------


def _exit_ip(body: str) -> str | None:
    for line in body.splitlines():
        if line.startswith("ip="):
            return line[3:].strip() or None
    stripped = body.strip()
    return stripped if stripped and len(stripped) <= 45 and " " not in stripped else None


def _no_response(errors: list[str]) -> str:
    # The process can be up while the handshake never completes; from here
    # that looks like requests that never come back, so say what to check.
    last = errors[-1] if errors else "no response"
    return (
        f"Nothing came back through the tunnel ({last}). "
        "Check the endpoint, the keys, and that the server can reach it over UDP."
    )


def band(latency_ms: float | None, loss_percent: float) -> str:
    """One word for the page. Thresholds are for message delivery, not games."""
    if latency_ms is None or loss_percent >= 100:
        return "down"
    if latency_ms >= 400:
        return "poor"
    if loss_percent > 0 or latency_ms >= 150:
        return "fair"
    return "good"


async def probe(
    proxy: str | None,
    *,
    url: str,
    attempts: int = PROBE_ATTEMPTS,
    request_timeout: float = PROBE_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Send real requests down a route and report what came back.

    `trust_env=False`: what is measured must be exactly the route asked
    for, not whatever proxy variables the server happens to have set.
    """
    latencies: list[float] = []
    exit_ip: str | None = None
    errors: list[str] = []

    async with httpx.AsyncClient(proxy=proxy, trust_env=False, timeout=request_timeout) as client:
        tried = 0
        for _ in range(attempts):
            tried += 1
            started = time.perf_counter()
            try:
                # A hard deadline as well as httpx's own: httpx's timeouts do
                # not cover the SOCKS exchange, and wireproxy holds that open
                # for ~35s while it waits on a peer that never answers.
                async with asyncio.timeout(request_timeout):
                    response = await client.get(url)
                response.raise_for_status()
            except (httpx.HTTPError, socksio.ProtocolError, TimeoutError) as exc:
                # socksio's error is what wireproxy's reply turns into when
                # the peer never completed a handshake. Not an httpx error,
                # so it is named here or it escapes as a 500.
                if isinstance(exc, socksio.ProtocolError):
                    errors.append("no WireGuard handshake with the peer")
                elif isinstance(exc, TimeoutError):
                    errors.append(f"no answer within {request_timeout:.0f}s")
                else:
                    errors.append(str(exc) or exc.__class__.__name__)
                if not latencies:
                    # Nothing has got through yet, so the rest would fail
                    # the same way — each after wireproxy's own handshake
                    # wait. One answer beats the same one three times over.
                    break
                continue
            latencies.append((time.perf_counter() - started) * 1000)
            exit_ip = exit_ip or _exit_ip(response.text)

    loss = round(100 * (tried - len(latencies)) / tried, 1)
    latency = round(statistics.median(latencies), 1) if latencies else None
    jitter = (
        round(statistics.fmean(abs(a - b) for a, b in itertools.pairwise(latencies)), 1)
        if len(latencies) > 1
        else None
    )
    return {
        "state": "ok" if latencies else "failed",
        "detail": "" if latencies else _no_response(errors),
        "latency_ms": latency,
        "jitter_ms": jitter,
        "loss_percent": loss,
        "exit_ip": exit_ip,
        "quality": band(latency, loss),
        # wireproxy does not expose it, and an invented number would be
        # believed; it stays empty rather than guessed.
        "handshake_age_s": None,
    }


# --- Running -------------------------------------------------------------


@dataclass
class _Running:
    port: int
    process: asyncio.subprocess.Process
    started_at: float = field(default_factory=time.monotonic)

    @property
    def alive(self) -> bool:
        return self.process.returncode is None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _listening(port: int) -> bool:
    try:
        _, writer = await asyncio.open_connection("127.0.0.1", port)
    except OSError:
        return False
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()
    return True


class TunnelManager:
    """Starts, tracks and stops one wireproxy per tunnel."""

    def __init__(
        self,
        *,
        command: list[str],
        awg_command: list[str] | None = None,
        runtime_dir: Path | None = None,
        startup_timeout: float = STARTUP_TIMEOUT_SECONDS,
    ) -> None:
        self._command = command
        self._awg_command = awg_command or []
        self._runtime_dir = runtime_dir or Path(tempfile.gettempdir()) / "quanta-tunnels"
        self._startup_timeout = startup_timeout
        self._running: dict[str, _Running] = {}
        self._errors: dict[str, str] = {}
        self._unreachable: dict[str, tuple[float, str]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> TunnelManager:
        resolved = settings or get_settings()
        return cls(
            command=shlex.split(resolved.wireproxy_command),
            awg_command=shlex.split(resolved.wireproxy_awg_command),
            runtime_dir=Path(resolved.tunnel_runtime_dir) if resolved.tunnel_runtime_dir else None,
        )

    # --- What the page shows ------------------------------------------

    @staticmethod
    def _installed(command: list[str]) -> bool:
        return bool(command) and shutil.which(command[0]) is not None

    @property
    def available(self) -> bool:
        return self._installed(self._command)

    @property
    def amnezia_available(self) -> bool:
        return self._installed(self._awg_command)

    def engine(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "amnezia": self.amnezia_available,
            "detail": (
                ""
                if self.available
                else "wireproxy is not installed on this server, so tunnels cannot run. "
                "The production image includes it; set WIREPROXY_COMMAND if it lives elsewhere."
            ),
        }

    def state(self, tunnel_id: str) -> str:
        running = self._running.get(tunnel_id)
        if tunnel_id in self._errors or self.unreachable(tunnel_id) is not None:
            # A process that is up but carries nothing has failed, as far
            # as anyone using it can tell.
            return "failed"
        if running is not None and running.alive:
            return "running"
        return "stopped" if self.available else "unavailable"

    def last_error(self, tunnel_id: str) -> str | None:
        return self._errors.get(tunnel_id) or self.unreachable(tunnel_id)

    # --- Whether it carries traffic -----------------------------------

    def mark_unreachable(self, tunnel_id: str, reason: str) -> None:
        """Nothing got through it; pass it over for a while."""
        self._unreachable[tunnel_id] = (time.monotonic() + UNREACHABLE_SECONDS, reason)
        logger.info("tunnel.unreachable", tunnel_id=tunnel_id, reason=reason)

    def mark_reachable(self, tunnel_id: str) -> None:
        self._unreachable.pop(tunnel_id, None)

    def unreachable(self, tunnel_id: str) -> str | None:
        """Why the tunnel is being passed over, or None if it is not."""
        entry = self._unreachable.get(tunnel_id)
        if entry is None:
            return None
        until, reason = entry
        if time.monotonic() >= until:
            del self._unreachable[tunnel_id]
            return None
        return reason

    def proxy_for(self, tunnel_id: str) -> str | None:
        running = self._running.get(tunnel_id)
        if running is None or not running.alive:
            return None
        return f"socks5h://127.0.0.1:{running.port}"

    # --- Lifecycle -----------------------------------------------------

    async def ensure(self, tunnel_id: str, config_text: str) -> str:
        """Start the tunnel if it is not running, and return its proxy URL."""
        lock = self._locks.setdefault(tunnel_id, asyncio.Lock())
        async with lock:
            existing = self.proxy_for(tunnel_id)
            if existing is not None:
                return existing
            try:
                proxy = await self._start(tunnel_id, config_text)
            except TunnelError as exc:
                self._errors[tunnel_id] = str(exc)
                raise
            self._errors.pop(tunnel_id, None)
            return proxy

    async def _start(self, tunnel_id: str, config_text: str) -> str:
        amnezia = is_amnezia(config_text)
        if amnezia and not self.amnezia_available:
            raise TunnelError(
                "This is an AmneziaWG config. Plain WireGuard would accept it and then never "
                "connect, so it is not started. Set WIREPROXY_AWG_COMMAND to the AmneziaWG "
                "build of wireproxy on the server."
            )
        command = self._awg_command if amnezia else self._command
        if not self._installed(command):
            raise TunnelError("wireproxy is not installed on this server.")

        self._runtime_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        port = _free_port()
        path = self._runtime_dir / f"{tunnel_id}.conf"
        # Created 0600 from the start, never briefly world-readable.
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            handle.write(render(config_text, port=port, amnezia=amnezia))

        process = await asyncio.create_subprocess_exec(
            *command,
            "-s",
            "-c",
            str(path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            deadline = time.monotonic() + self._startup_timeout
            while time.monotonic() < deadline:
                if process.returncode is not None:
                    raise TunnelError(await self._why(process))
                if await _listening(port):
                    self._running[tunnel_id] = _Running(port=port, process=process)
                    logger.info("tunnel.started", tunnel_id=tunnel_id, port=port)
                    return f"socks5h://127.0.0.1:{port}"
                await asyncio.sleep(0.1)
            await self._kill(process)
            raise TunnelError(
                f"The tunnel did not start within {self._startup_timeout:.0f}s. "
                "Check the endpoint and that the server can reach it over UDP."
            )
        finally:
            # The private key is on disk only for as long as wireproxy needs
            # to read it once.
            with contextlib.suppress(FileNotFoundError):
                path.unlink()

    @staticmethod
    async def _why(process: asyncio.subprocess.Process) -> str:
        stderr = b""
        if process.stderr is not None:
            with contextlib.suppress(Exception):
                stderr = await asyncio.wait_for(process.stderr.read(), 1.0)
        lines = [line for line in stderr.decode(errors="replace").splitlines() if line.strip()]
        reason = lines[-1] if lines else f"exited with code {process.returncode}"
        # wireproxy prefixes log lines with a timestamp; the user needs the rest.
        reason = reason.split(" ", 2)[-1] if reason[:4].isdigit() else reason
        return f"The tunnel would not start: {reason}"

    @staticmethod
    async def _kill(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), 3.0)
        except TimeoutError:
            process.kill()
            await process.wait()

    async def stop(self, tunnel_id: str) -> None:
        running = self._running.pop(tunnel_id, None)
        self._errors.pop(tunnel_id, None)
        self._unreachable.pop(tunnel_id, None)
        if running is not None:
            await self._kill(running.process)
            logger.info("tunnel.stopped", tunnel_id=tunnel_id)

    async def stop_all(self) -> None:
        for tunnel_id in list(self._running):
            await self.stop(tunnel_id)
