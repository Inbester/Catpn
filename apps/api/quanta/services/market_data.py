"""The market-data service (SPEC §4).

Two jobs:

* **Backfill.** Pull history over REST once and store it in Timescale.
  SPEC §6 allows 10 requests a second per IP, so history is never fetched
  live per user; the chart reads the database.
* **Fan-out.** Hold *one* WebSocket to the exchange for the whole process
  and publish normalised events to Redis, which the client WebSocket
  endpoints subscribe to. One shared upstream connection regardless of how
  many browsers are watching is the only way to stay inside the venue's
  5 messages/second budget.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from quanta.exchanges.base import (
    EventType,
    ExchangeError,
    Interval,
    PriceType,
    StreamEvent,
    Subscription,
)
from quanta.services import market_store

logger = structlog.get_logger(__name__)

# How many bars a fresh chart wants before the user sees anything.
INITIAL_BACKFILL_BARS = 1500
# Cap on a single gap-fill so a long disconnect cannot stall startup.
MAX_GAPFILL_BARS = 5000


def channel_for(symbol: str, interval: Interval, price_type: PriceType = "LAST") -> str:
    """Redis channel for one kline series."""
    return f"md:kline:{price_type}:{symbol}:{interval.value}"


def ticker_channel(symbol: str) -> str:
    return f"md:ticker:{symbol}"


def _encode(event: StreamEvent) -> str:
    """Serialise an event for Redis.

    Decimals become strings, never floats: a price that round-trips through
    binary floating point is no longer the price the exchange sent.
    """
    payload: dict[str, Any] = {
        "type": event.type.value,
        "symbol": event.symbol,
        "ts": event.received_at,
    }
    if event.interval is not None:
        payload["interval"] = event.interval.value
    if event.bar is not None:
        payload["bar"] = {
            "t": event.bar.open_time,
            "o": str(event.bar.open),
            "h": str(event.bar.high),
            "l": str(event.bar.low),
            "c": str(event.bar.close),
            "v": str(event.bar.volume),
            "closed": event.bar.closed,
        }
    if event.ticker is not None:
        ticker = event.ticker
        payload["ticker"] = {
            "symbol": ticker.symbol,
            "last": str(ticker.last),
            "change24h": str(ticker.change_percent_24h),
            "mark": str(ticker.mark_price) if ticker.mark_price is not None else None,
            "index": str(ticker.index_price) if ticker.index_price is not None else None,
            "fundingRate": str(ticker.funding_rate) if ticker.funding_rate is not None else None,
            "nextFundingTime": ticker.next_funding_time,
            "high24h": str(ticker.high_24h) if ticker.high_24h is not None else None,
            "low24h": str(ticker.low_24h) if ticker.low_24h is not None else None,
            "openInterest": str(ticker.open_interest) if ticker.open_interest is not None else None,
        }
    if event.price is not None:
        payload["price"] = str(event.price)
    return json.dumps(payload, separators=(",", ":"))


@dataclass(slots=True)
class SeriesKey:
    symbol: str
    interval: Interval
    price_type: PriceType = "LAST"

    def as_tuple(self) -> tuple[str, str, str]:
        return (self.symbol, self.interval.value, self.price_type)


class MarketDataService:
    """Owns the shared exchange connection and the backfill."""

    def __init__(
        self,
        adapter: Any,
        session_factory: async_sessionmaker[AsyncSession],
        redis: Redis | None,
    ) -> None:
        self._adapter = adapter
        self._sessions = session_factory
        self._redis = redis
        self._stream_task: asyncio.Task[None] | None = None
        self._subscriptions: set[tuple[str, str, str]] = set()
        self._restart = asyncio.Event()

    @property
    def adapter(self) -> Any:
        """The exchange adapter, for routes that pass metadata straight through."""
        return self._adapter

    # --- Backfill -------------------------------------------------------

    async def backfill(
        self,
        symbol: str,
        interval: Interval,
        *,
        start: int,
        end: int,
        price_type: PriceType = "LAST",
    ) -> int:
        """Download and store a range. Returns the number of bars written."""
        written = 0
        async with self._sessions() as db:
            async for page in self._adapter.iter_klines(
                symbol, interval, start=start, end=end, price_type=price_type
            ):
                written += await market_store.upsert_bars(
                    db, symbol, interval, page, price_type=price_type
                )
                await db.commit()

        logger.info(
            "backfill_complete",
            symbol=symbol,
            interval=interval.value,
            bars=written,
        )
        return written

    async def ensure_history(
        self,
        symbol: str,
        interval: Interval,
        *,
        bars: int = INITIAL_BACKFILL_BARS,
        price_type: PriceType = "LAST",
        now_ms: int | None = None,
    ) -> int:
        """Make sure at least ``bars`` recent bars are stored.

        Only the missing tail is fetched, so switching back to a symbol is
        nearly free rather than re-downloading everything.
        """
        now = now_ms if now_ms is not None else _now_ms()
        step = interval.milliseconds
        wanted_start = ((now // step) * step) - step * bars

        async with self._sessions() as db:
            state = await market_store.coverage(db, symbol, interval, price_type=price_type)

        # +1 so the window includes the bar that is currently forming, but
        # not the next one, which has not opened yet.
        wanted_end = ((now // step) * step) + 1

        if state is None or state.latest_open_time is None:
            return await self.backfill(
                symbol, interval, start=wanted_start, end=wanted_end, price_type=price_type
            )

        written = 0
        # Extend backwards if the stored window starts too late.
        if state.earliest_open_time is not None and state.earliest_open_time > wanted_start:
            written += await self.backfill(
                symbol,
                interval,
                start=wanted_start,
                end=state.earliest_open_time,
                price_type=price_type,
            )

        # Always refresh the tail: the last stored bar may have been forming.
        written += await self.backfill(
            symbol,
            interval,
            start=state.latest_open_time,
            end=wanted_end,
            price_type=price_type,
        )
        return written

    async def fill_gaps(
        self,
        symbol: str,
        interval: Interval,
        *,
        price_type: PriceType = "LAST",
        limit: int = MAX_GAPFILL_BARS,
    ) -> int:
        """Refetch any holes in the stored series.

        SPEC §3.1 requires gap-filling on reconnect; this finds the holes so
        only what is missing is requested.
        """
        async with self._sessions() as db:
            stored = await market_store.read_bars(
                db, symbol, interval, limit=limit, price_type=price_type
            )

        gaps = market_store.find_gaps(stored, interval)
        if not gaps:
            return 0

        logger.info("gapfill_started", symbol=symbol, interval=interval.value, gaps=len(gaps))
        filled = 0
        for start, end in gaps:
            filled += await self.backfill(
                symbol, interval, start=start, end=end, price_type=price_type
            )
        return filled

    async def refresh_instruments(self) -> int:
        """Cache contract metadata (leverage limits, precision, status)."""
        symbols = await self._adapter.symbols()
        async with self._sessions() as db:
            count = await market_store.upsert_instruments(db, symbols)
            await db.commit()
        return count

    async def refresh_funding(
        self, symbol: str, *, start: int | None = None, end: int | None = None
    ) -> int:
        entries = await self._adapter.funding_history(symbol, start=start, end=end)
        async with self._sessions() as db:
            count = await market_store.upsert_funding(db, symbol, entries)
            await db.commit()
        return count

    # --- Shared stream --------------------------------------------------

    def subscribe(self, symbol: str, interval: Interval, price_type: PriceType = "LAST") -> None:
        """Add a series to the shared upstream connection."""
        key = SeriesKey(symbol, interval, price_type).as_tuple()
        if key in self._subscriptions:
            return
        self._subscriptions.add(key)
        # Wake the stream loop so it reconnects with the new subscription set.
        self._restart.set()

    def unsubscribe(self, symbol: str, interval: Interval, price_type: PriceType = "LAST") -> None:
        self._subscriptions.discard(SeriesKey(symbol, interval, price_type).as_tuple())

    def _current_subscriptions(self) -> list[Subscription]:
        subscriptions: list[Subscription] = []
        seen_tickers: set[str] = set()

        for symbol, interval, price_type in sorted(self._subscriptions):
            subscriptions.append(
                Subscription(
                    EventType.KLINE,
                    symbol,
                    Interval(interval),
                    price_type,  # type: ignore[arg-type]
                )
            )
            if symbol not in seen_tickers:
                subscriptions.append(Subscription(EventType.TICKER, symbol))
                seen_tickers.add(symbol)
        return subscriptions

    async def run_stream(self) -> None:
        """Hold the one upstream connection and publish to Redis.

        Restarts whenever the subscription set changes, because the venue's
        subscribe message is sent once per connection.
        """
        while True:
            self._restart.clear()
            subscriptions = self._current_subscriptions()

            if not subscriptions:
                await self._restart.wait()
                continue

            consumer = asyncio.create_task(self._consume(subscriptions))
            waiter = asyncio.create_task(self._restart.wait())

            done, pending = await asyncio.wait(
                {consumer, waiter}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            for task in done:
                # Surface a crash in the consumer rather than silently looping.
                with contextlib.suppress(asyncio.CancelledError):
                    exc = task.exception()
                    if exc is not None and not isinstance(exc, ExchangeError):
                        logger.error("market_stream_error", error=str(exc))

    async def _consume(self, subscriptions: list[Subscription]) -> None:
        """Read the upstream socket, persist bars and publish events."""
        async for event in self._adapter.stream(subscriptions):
            await self._handle_event(event)

    async def _handle_event(self, event: StreamEvent) -> None:
        if event.type is EventType.KLINE and event.bar is not None and event.interval:
            # Persist first: a browser that reloads mid-tick must see the
            # same forming bar the stream just produced.
            try:
                async with self._sessions() as db:
                    await market_store.upsert_bars(db, event.symbol, event.interval, [event.bar])
                    await db.commit()
            except Exception as exc:  # a bad write must not kill the shared stream
                logger.warning("kline_persist_failed", symbol=event.symbol, error=str(exc))

            await self._publish(channel_for(event.symbol, event.interval), event)

        elif event.type is EventType.TICKER and event.ticker is not None:
            await self._publish(ticker_channel(event.symbol), event)

    async def _publish(self, channel: str, event: StreamEvent) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.publish(channel, _encode(event))
        except RedisError as exc:
            logger.warning("market_publish_failed", channel=channel, error=str(exc))

    async def start(self) -> None:
        if self._stream_task is None:
            self._stream_task = asyncio.create_task(self.run_stream())

    async def stop(self) -> None:
        if self._stream_task is not None:
            self._stream_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._stream_task
            self._stream_task = None
        await self._adapter.close()


async def subscribe_channel(redis: Redis, channels: list[str]) -> AsyncIterator[dict[str, Any]]:
    """Yield decoded messages from a set of Redis channels."""
    pubsub = redis.pubsub()
    await pubsub.subscribe(*channels)
    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            raw = message.get("data")
            if not raw:
                continue
            try:
                yield json.loads(raw)
            except ValueError:
                continue
    finally:
        with contextlib.suppress(RedisError):
            await pubsub.unsubscribe(*channels)
        await pubsub.aclose()


def _now_ms() -> int:
    import time

    return int(time.time() * 1000)


__all__ = [
    "MarketDataService",
    "SeriesKey",
    "channel_for",
    "subscribe_channel",
    "ticker_channel",
]
