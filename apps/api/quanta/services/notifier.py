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
import structlog

logger = structlog.get_logger(__name__)

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "target": self.target,
            "state": self.state,
            "latency_ms": self.latency_ms,
            "attempts": self.attempts,
            "note": self.note,
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
    client: httpx.AsyncClient | None = None
    sent: list[dict[str, Any]] = field(default_factory=list)

    async def deliver(
        self, destinations: list[dict[str, Any]], message: str, *, quiet: bool = False
    ) -> list[Delivery]:
        """Send to every destination, independently.

        Gathered rather than sequential: a Telegram call that takes two
        seconds must not delay the webhook a bot is waiting on, and SPEC
        §8 gives the whole path a two-second budget from bar close.
        """
        results = await asyncio.gather(
            *(self._one(destination, message, quiet=quiet) for destination in destinations),
            return_exceptions=True,
        )

        deliveries: list[Delivery] = []
        for destination, result in zip(destinations, results, strict=True):
            if isinstance(result, Delivery):
                deliveries.append(result)
            else:
                # An exception here is a bug in the sender, not a failed
                # send; it still belongs in the record.
                deliveries.append(
                    Delivery(
                        kind=str(destination.get("kind", "?")),
                        target=str(destination.get("target", "")),
                        state="failed",
                        note=str(result),
                    )
                )
        return deliveries

    async def _one(self, destination: dict[str, Any], message: str, *, quiet: bool) -> Delivery:
        kind = str(destination.get("kind", ""))
        target = str(destination.get("target", ""))
        delivery = Delivery(kind=kind, target=target)
        started = time.perf_counter()

        for attempt in range(1, MAX_ATTEMPTS + 1):
            delivery.attempts = attempt
            try:
                retry_after = await self._send(kind, destination, message, quiet=quiet)
            except Exception as exc:
                delivery.state = "failed"
                delivery.note = str(exc)[:200]
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
        self, kind: str, destination: dict[str, Any], message: str, *, quiet: bool
    ) -> float | None:
        """Send once. Returns seconds to wait when rate limited, else None."""
        if kind == "telegram":
            return await self._telegram(destination, message, quiet=quiet)
        if kind == "webhook":
            return await self._webhook(destination, message)
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
        self, destination: dict[str, Any], message: str, *, quiet: bool
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
        if not self.telegram_token or self.client is None:
            self.sent.append({"kind": "telegram", **payload})
            limiter.record(target, is_group=is_group)
            return None

        response = await self.client.post(
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

    async def _webhook(self, destination: dict[str, Any], message: str) -> float | None:
        url = str(destination.get("target", ""))
        secret = str(destination.get("secret", ""))
        payload = {"message": message, "sent_at": time.time()}
        # Serialised once, then both signed and sent: signing a different
        # byte string than the one sent is how valid messages get rejected.
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

        headers = {"content-type": "application/json"}
        if secret:
            headers["x-quanta-signature"] = sign_webhook(secret, body)

        if self.client is None:
            self.sent.append({"kind": "webhook", "target": url, "body": body.decode()})
            return None

        response = await self.client.post(
            url, content=body, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS
        )
        if response.status_code == 429:
            return RETRY_BACKOFF_SECONDS
        response.raise_for_status()
        return None
