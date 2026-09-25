"""Client-side rate limiting for exchange calls.

SPEC §6 is strict about this: REST is 10 req/s per IP, and the public
WebSocket allows 5 messages/s *including ping/pong* — exceeding it
disconnects, and repeat offenders get IP-banned. So the limit is enforced
before a request goes out rather than reacted to afterwards.
"""

from __future__ import annotations

import asyncio
import time
from types import TracebackType


class AsyncRateLimiter:
    """A token bucket that paces calls to at most ``rate`` per ``period``.

    Deliberately conservative: tokens refill continuously, and a caller with
    no token available waits rather than being rejected, so a burst of chart
    subscriptions queues instead of tripping a ban.
    """

    def __init__(self, rate: int, period: float = 1.0, *, burst: int | None = None) -> None:
        if rate <= 0:
            raise ValueError("rate must be positive")
        self._rate = rate
        self._period = period
        self._capacity = burst if burst is not None else rate
        self._tokens = float(self._capacity)
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    @property
    def capacity(self) -> int:
        return self._capacity

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._updated
        if elapsed <= 0:
            return
        self._tokens = min(
            float(self._capacity), self._tokens + elapsed * (self._rate / self._period)
        )
        self._updated = now

    async def acquire(self, tokens: int = 1) -> None:
        """Wait until ``tokens`` are available, then spend them."""
        if tokens > self._capacity:
            raise ValueError(f"cannot acquire {tokens} tokens from a bucket of {self._capacity}")

        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                deficit = tokens - self._tokens
                wait = deficit * self._period / self._rate

            # Sleep outside the lock so other callers can refill-check too.
            await asyncio.sleep(wait)

    async def __aenter__(self) -> AsyncRateLimiter:
        await self.acquire()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None
