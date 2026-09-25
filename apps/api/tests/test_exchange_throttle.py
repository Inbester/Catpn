"""The client-side rate limiter (SPEC §6 limits)."""

from __future__ import annotations

import asyncio
import time

import pytest

from quanta.exchanges.throttle import AsyncRateLimiter


async def test_burst_up_to_capacity_is_immediate() -> None:
    limiter = AsyncRateLimiter(rate=5)
    started = time.monotonic()
    for _ in range(5):
        await limiter.acquire()
    assert time.monotonic() - started < 0.05


async def test_exceeding_capacity_waits() -> None:
    """The 6th call in a 5/s bucket must wait for a refill."""
    limiter = AsyncRateLimiter(rate=5)
    for _ in range(5):
        await limiter.acquire()

    started = time.monotonic()
    await limiter.acquire()
    elapsed = time.monotonic() - started
    assert elapsed >= 0.15, f"expected a wait of ~0.2s, got {elapsed:.3f}s"


async def test_tokens_refill_over_time() -> None:
    limiter = AsyncRateLimiter(rate=10)
    for _ in range(10):
        await limiter.acquire()

    await asyncio.sleep(0.25)
    started = time.monotonic()
    await limiter.acquire()
    assert time.monotonic() - started < 0.05


async def test_concurrent_callers_are_all_paced() -> None:
    """Ten concurrent callers through a 5/s bucket take about a second."""
    limiter = AsyncRateLimiter(rate=5)
    started = time.monotonic()
    await asyncio.gather(*(limiter.acquire() for _ in range(10)))
    elapsed = time.monotonic() - started
    assert 0.7 <= elapsed <= 2.5, f"expected ~1s of pacing, got {elapsed:.3f}s"


async def test_rejects_an_impossible_request() -> None:
    limiter = AsyncRateLimiter(rate=5)
    with pytest.raises(ValueError, match="cannot acquire"):
        await limiter.acquire(6)


def test_rejects_a_non_positive_rate() -> None:
    with pytest.raises(ValueError, match="rate must be positive"):
        AsyncRateLimiter(rate=0)


async def test_works_as_a_context_manager() -> None:
    limiter = AsyncRateLimiter(rate=2)
    async with limiter:
        pass
    async with limiter:
        pass
