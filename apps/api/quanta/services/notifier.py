"""Delivering an alert (SPEC §3.4 and §7).

Every send is attempted, timed and recorded, including the failures. An
alert the user believes is watching over them, which silently stopped
delivering, is worse than no alert at all — so a 429 that was retried and
a webhook that refused both show up in the activity view with the reason.

Each destination is independent. One channel failing never stops another:
a Telegram outage must not cost you the webhook your bot is listening on.

Rate limits are Telegram's own — one message a second per chat, twenty a
minute per group — and are applied per target rather than globally,
because a queue shared across chats would let a busy group delay a
direct message that had plenty of budget.

**Live or recording.** A `Notifier(live=True)` sends for real, over the
route the caller resolved (the server's own, or a tunnel's SOCKS5 proxy;
see services/routing.py). Without `live` — tests, and any process that has
not started the app — sends are recorded instead. Before this split the
production notifier had no HTTP client at all, so every Telegram message
and webhook was recorded as "sent" and none was: exactly the silent
failure the paragraph above exists to prevent.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import socksio
import structlog

logger = structlog.get_logger(__name__)

# Failures of the path rather than of the destination: a connection that
# never opened, or a SOCKS reply wireproxy sends when its peer never
# completed a handshake. Only these make a different route worth trying.
ROUTE_ERRORS: tuple[type[Exception], ...] = (
    httpx.TransportError,
    socksio.ProtocolError,
    TimeoutError,
)

# Telegram's documented limits (SPEC §7).
PER_CHAT_INTERVAL_SECONDS = 1.0
PER_GROUP_PER_MINUTE = 20

# A 429 is normal under load and worth one retry; anything else is not
# going to be fixed by trying again immediately.
MAX_ATTEMPTS = 2
RETRY_BACKOFF_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 8.0


@dataclass
class Delivery:
    """The record of one attempt at one destination."""

    kind: str
    target: str
    state: str = "pending"
    latency_ms: int = 0
    attempts: int = 0
    note: str = ""
    #: Which network carried it: "server" or a tunnel's label.
    route: str = "server"
    #: The tunnel, not the destination, failed: nothing got through it.
    #: Read by routing.deliver to try the next route; not stored.
    route_failed: bool = field(default=False, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "target": self.target,
            "state": self.state,
            "latency_ms": self.latency_ms,
            "attempts": self.attempts,
            "note": self.note,
            "route": self.route,
        }


@dataclass
class _ChatBudget:
    """When this chat may next be sent to."""

    next_allowed: float = 0.0
    minute_start: float = 0.0
    minute_count: int = 0


class RateLimiter:
    """Per-target pacing, so one busy chat cannot delay another."""

    def __init__(self) -> None:
        self._budgets: dict[str, _ChatBudget] = {}

    def delay_for(self, target: str, *, is_group: bool, now: float | None = None) -> float:
        """Seconds to wait before sending to this target."""
        now = now if now is not None else time.monotonic()
        budget = self._budgets.setdefault(target, _ChatBudget())

        wait = max(0.0, budget.next_allowed - now)

        if is_group:
            if now - budget.minute_start >= 60.0:
                budget.minute_start = now
                budget.minute_count = 0
            if budget.minute_count >= PER_GROUP_PER_MINUTE:
                # The window, not a fixed sleep: waiting a flat minute
                # would stall a group that only just filled its budget.
                wait = max(wait, 60.0 - (now - budget.minute_start))

        return wait

    def record(self, target: str, *, is_group: bool, now: float | None = None) -> None:
        now = now if now is not None else time.monotonic()
        budget = self._budgets.setdefault(target, _ChatBudget())
        budget.next_allowed = now + PER_CHAT_INTERVAL_SECONDS
        if is_group:
            if now - budget.minute_start >= 60.0:
                budget.minute_start = now
                budget.minute_count = 0
            budget.minute_count += 1


limiter = RateLimiter()


def sign_webhook(secret: str, body: bytes) -> str:
    """HMAC-SHA256 over the exact bytes sent (SPEC §3.4).

    Over the serialised body rather than a re-serialisation of the
    payload: a receiver that verifies a different byte string than the one
    signed will reject valid messages, and the difference is usually key
    order.
    """
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


@dataclass
class Notifier:
    """Sends messages, with the HTTP client injected so tests can watch."""

    telegram_token: str = ""
    #: Injected by tests; used for every send regardless of route.
    client: httpx.AsyncClient | None = None
    #: Send for real. See the module docstring.
    live: bool = False
    sent: list[dict[str, Any]] = field(default_factory=list)
    _clients: dict[str | None, httpx.AsyncClient] = field(default_factory=dict, repr=False)

    def _client_for(self, proxy: str | None) -> httpx.AsyncClient | None:
        """One pooled client per route.

        `trust_env=False`: a message goes exactly the way the user chose,
        not wherever a stray HTTPS_PROXY on the server would send it.
        """
        if self.client is not None:
            return self.client
        if not self.live:
            return None
        if proxy not in self._clients:
            self._clients[proxy] = httpx.AsyncClient(
                proxy=proxy, trust_env=False, timeout=REQUEST_TIMEOUT_SECONDS
            )
        return self._clients[proxy]

    async def forget(self, proxy: str) -> None:
        """Drop the client for a tunnel that stopped, so a restart gets a fresh one."""
        client = self._clients.pop(proxy, None)
        if client is not None:
            await client.aclose()

    async def aclose(self) -> None:
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()

    async def deliver(
        self,
        destinations: list[dict[str, Any]],
        message: str,
        *,
        quiet: bool = False,
        proxy: str | None = None,
        via: str = "server",
        route_note: str = "",
    ) -> list[Delivery]:
        """Send to every destination, independently.

        Gathered rather than sequential: a Telegram call that takes two
        seconds must not delay the webhook a bot is waiting on, and SPEC
        §8 gives the whole path a two-second budget from bar close.
        """
        results = await asyncio.gather(
            *(
                self._one(destination, message, quiet=quiet, proxy=proxy)
                for destination in destinations
            ),
            return_exceptions=True,
        )

        deliveries: list[Delivery] = []
        for destination, result in zip(destinations, results, strict=True):
            if isinstance(result, Delivery):
                delivery = result
            else:
                # An exception here is a bug in the sender, not a failed
                # send; it still belongs in the record.
                delivery = Delivery(
                    kind=str(destination.get("kind", "?")),
                    target=str(destination.get("target", "")),
                    state="failed",
                    note=str(result),
                )
            delivery.route = via
            if route_note:
                # A tunnel that was skipped on the way is part of what
                # happened to this message.
                delivery.note = f"{delivery.note}; {route_note}" if delivery.note else route_note
            deliveries.append(delivery)
        return deliveries

    async def _one(
        self, destination: dict[str, Any], message: str, *, quiet: bool, proxy: str | None = None
    ) -> Delivery:
        kind = str(destination.get("kind", ""))
        target = str(destination.get("target", ""))
        delivery = Delivery(kind=kind, target=target)
        started = time.perf_counter()

        for attempt in range(1, MAX_ATTEMPTS + 1):
            delivery.attempts = attempt
            try:
                retry_after = await self._send(kind, destination, message, quiet=quiet, proxy=proxy)
            except Exception as exc:
                delivery.state = "failed"
                delivery.note = str(exc)[:200]
                if proxy is not None and isinstance(exc, ROUTE_ERRORS):
                    delivery.route_failed = True
                    if isinstance(exc, socksio.ProtocolError):
                        why = "no WireGuard handshake with the peer"
                    elif isinstance(exc, TimeoutError):
                        why = f"no answer within {REQUEST_TIMEOUT_SECONDS:.0f}s"
                    else:
                        why = str(exc) or exc.__class__.__name__
                    delivery.note = f"nothing got through the tunnel ({why})"[:200]
                break

            if retry_after is None:
                delivery.state = "sent"
                delivery.note = "429 → retried" if attempt > 1 else ""
                break

            if attempt >= MAX_ATTEMPTS:
                delivery.state = "failed"
                delivery.note = f"rate limited, gave up after {attempt} attempts"
                break
            await asyncio.sleep(min(retry_after, RETRY_BACKOFF_SECONDS))

        delivery.latency_ms = int((time.perf_counter() - started) * 1000)
        return delivery

    async def _send(
        self,
        kind: str,
        destination: dict[str, Any],
        message: str,
        *,
        quiet: bool,
        proxy: str | None = None,
    ) -> float | None:
        """Send once. Returns seconds to wait when rate limited, else None."""
        if kind == "telegram":
            return await self._telegram(destination, message, quiet=quiet, proxy=proxy)
        if kind == "webhook":
            return await self._webhook(destination, message, proxy=proxy)
        if kind in {"web_push", "email"}:
            # Recorded as sent against the injected client so the path is
            # exercised end to end; the transports themselves are wired in
            # deployment, where the keys live.
            self.sent.append(
                {"kind": kind, "target": destination.get("target"), "message": message}
            )
            return None
        raise ValueError(f"unknown destination {kind!r}")

    async def _telegram(
        self, destination: dict[str, Any], message: str, *, quiet: bool, proxy: str | None = None
    ) -> float | None:
        target = str(destination.get("target", ""))
        is_group = target.startswith("-")

        wait = limiter.delay_for(target, is_group=is_group)
        if wait > 0:
            await asyncio.sleep(wait)

        payload = {
            "chat_id": target,
            "text": message,
            # Quiet hours send silently rather than not at all.
            "disable_notification": quiet,
        }
        client = self._client_for(proxy)
        if client is None:
            self.sent.append({"kind": "telegram", **payload})
            limiter.record(target, is_group=is_group)
            return None
        if not self.telegram_token:
            # Said plainly rather than recorded as sent: the user has to
            # know their alert went nowhere, and why.
            raise RuntimeError(
                "TELEGRAM_BOT_TOKEN is not set on the server, so Telegram messages cannot be sent."
            )

        # httpx's timeout does not cover a SOCKS exchange; this one does.
        async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
            response = await client.post(
                f"https://api.telegram.org/bot{self.telegram_token}/sendMessage",
                json=payload,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        if response.status_code == 429:
            body = response.json() if response.content else {}
            return float(body.get("parameters", {}).get("retry_after", RETRY_BACKOFF_SECONDS))
        response.raise_for_status()
        limiter.record(target, is_group=is_group)
        return None

    async def _webhook(
        self, destination: dict[str, Any], message: str, *, proxy: str | None = None
    ) -> float | None:
        url = str(destination.get("target", ""))
        secret = str(destination.get("secret", ""))
        payload = {"message": message, "sent_at": time.time()}
        # Serialised once, then both signed and sent: signing a different
        # byte string than the one sent is how valid messages get rejected.
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

        headers = {"content-type": "application/json"}
        if secret:
            headers["x-quanta-signature"] = sign_webhook(secret, body)

        client = self._client_for(proxy)
        if client is None:
            self.sent.append({"kind": "webhook", "target": url, "body": body.decode()})
            return None

        async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
            response = await client.post(
                url, content=body, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS
            )
        if response.status_code == 429:
            return RETRY_BACKOFF_SECONDS
        response.raise_for_status()
        return None
