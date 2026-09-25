"""Reading and writing market data in Timescale."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from quanta.exchanges.base import Bar, Funding, Interval, PriceType, Symbol
from quanta.models.market import BackfillState, FundingRate, InstrumentMeta, Kline

# Postgres allows at most 32,767 bind parameters in one statement. A kline
# row carries 11 of them, so a single INSERT tops out just under 3,000 rows.
# Chunking well below that keeps bulk writes working whatever the caller
# hands us — the backfill pages in 200s, but an import does not.
MAX_BIND_PARAMETERS = 32_000


def _chunk_size(columns: int) -> int:
    return max(1, MAX_BIND_PARAMETERS // max(1, columns))


def _chunks(rows: list[dict[str, Any]], columns: int) -> Iterator[list[dict[str, Any]]]:
    size = _chunk_size(columns)
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def to_datetime(epoch_ms: int) -> datetime:
    return datetime.fromtimestamp(epoch_ms / 1000, tz=UTC)


def to_epoch_ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


async def upsert_bars(
    db: AsyncSession,
    symbol: str,
    interval: Interval,
    bars: list[Bar],
    *,
    price_type: PriceType = "LAST",
) -> int:
    """Insert or update bars, returning how many rows were written.

    An upsert rather than an insert because the newest bar is still forming:
    it is rewritten on every tick until the exchange marks it closed. A
    closed bar is never overwritten by an unclosed one — a late frame from a
    reconnect must not reopen settled history.
    """
    if not bars:
        return 0

    rows = [
        {
            "symbol": symbol,
            "interval": interval.value,
            "price_type": price_type,
            "open_time": to_datetime(bar.open_time),
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
            "quote_volume": bar.quote_volume,
            "closed": bar.closed,
        }
        for bar in bars
    ]

    for chunk in _chunks(rows, columns=11):
        statement = insert(Kline).values(chunk)
        statement = statement.on_conflict_do_update(
            constraint="pk_klines",
            set_={
                "open": statement.excluded.open,
                "high": statement.excluded.high,
                "low": statement.excluded.low,
                "close": statement.excluded.close,
                "volume": statement.excluded.volume,
                "quote_volume": statement.excluded.quote_volume,
                "closed": statement.excluded.closed,
                "updated_at": func.now(),
            },
            where=Kline.closed.is_(False),
        )
        await db.execute(statement)

    await _touch_backfill_state(db, symbol, interval, price_type)
    return len(rows)


async def _touch_backfill_state(
    db: AsyncSession, symbol: str, interval: Interval, price_type: PriceType
) -> None:
    """Recompute the stored coverage window for a series."""
    result = await db.execute(
        select(
            func.min(Kline.open_time),
            func.max(Kline.open_time),
            func.count(),
        ).where(
            Kline.symbol == symbol,
            Kline.interval == interval.value,
            Kline.price_type == price_type,
        )
    )
    earliest, latest, count = result.one()

    statement = insert(BackfillState).values(
        symbol=symbol,
        interval=interval.value,
        price_type=price_type,
        earliest_open_time=to_epoch_ms(earliest) if earliest else None,
        latest_open_time=to_epoch_ms(latest) if latest else None,
        bar_count=count or 0,
    )
    await db.execute(
        statement.on_conflict_do_update(
            constraint="pk_backfill_state",
            set_={
                "earliest_open_time": statement.excluded.earliest_open_time,
                "latest_open_time": statement.excluded.latest_open_time,
                "bar_count": statement.excluded.bar_count,
                "updated_at": func.now(),
            },
        )
    )


async def read_bars(
    db: AsyncSession,
    symbol: str,
    interval: Interval,
    *,
    start: int | None = None,
    end: int | None = None,
    limit: int = 1000,
    price_type: PriceType = "LAST",
) -> list[Bar]:
    """Read stored bars, oldest first.

    With no ``start``, the most recent ``limit`` bars are returned — which
    is what a chart opening on a symbol asks for.
    """
    query = select(Kline).where(
        Kline.symbol == symbol,
        Kline.interval == interval.value,
        Kline.price_type == price_type,
    )
    if start is not None:
        query = query.where(Kline.open_time >= to_datetime(start))
    if end is not None:
        query = query.where(Kline.open_time < to_datetime(end))

    # Take the newest `limit`, then flip to chronological order.
    query = query.order_by(Kline.open_time.desc()).limit(limit)
    result = await db.execute(query)
    rows = list(result.scalars().all())
    rows.reverse()

    return [
        Bar(
            open_time=to_epoch_ms(row.open_time),
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            volume=row.volume,
            quote_volume=row.quote_volume,
            closed=row.closed,
        )
        for row in rows
    ]


async def coverage(
    db: AsyncSession, symbol: str, interval: Interval, *, price_type: PriceType = "LAST"
) -> BackfillState | None:
    result = await db.execute(
        select(BackfillState).where(
            BackfillState.symbol == symbol,
            BackfillState.interval == interval.value,
            BackfillState.price_type == price_type,
        )
    )
    return result.scalar_one_or_none()


def find_gaps(bars: list[Bar], interval: Interval) -> list[tuple[int, int]]:
    """Missing ``[start, end)`` windows inside a run of bars.

    SPEC §3.1 requires missing bars to be gap-filled on reconnect. Finding
    the holes here means the backfill refetches only what is absent instead
    of the whole range.
    """
    step = interval.milliseconds
    gaps: list[tuple[int, int]] = []

    for previous, current in pairwise(bars):
        expected = previous.open_time + step
        if current.open_time > expected:
            gaps.append((expected, current.open_time))
    return gaps


async def upsert_funding(db: AsyncSession, symbol: str, entries: list[Funding]) -> int:
    if not entries:
        return 0

    rows = [
        {
            "symbol": symbol,
            "funding_time": to_datetime(entry.funding_time),
            "funding_rate": entry.funding_rate,
            "mark_price": entry.mark_price,
        }
        for entry in entries
    ]
    for chunk in _chunks(rows, columns=4):
        statement = insert(FundingRate).values(chunk)
        await db.execute(
            statement.on_conflict_do_update(
                constraint="pk_funding_rates",
                set_={
                    "funding_rate": statement.excluded.funding_rate,
                    "mark_price": statement.excluded.mark_price,
                },
            )
        )
    return len(rows)


async def read_funding(
    db: AsyncSession, symbol: str, *, start: int | None = None, end: int | None = None
) -> list[Funding]:
    query = select(FundingRate).where(FundingRate.symbol == symbol)
    if start is not None:
        query = query.where(FundingRate.funding_time >= to_datetime(start))
    if end is not None:
        query = query.where(FundingRate.funding_time < to_datetime(end))

    result = await db.execute(query.order_by(FundingRate.funding_time))
    return [
        Funding(
            funding_time=to_epoch_ms(row.funding_time),
            funding_rate=row.funding_rate,
            mark_price=row.mark_price,
        )
        for row in result.scalars().all()
    ]


async def upsert_instruments(db: AsyncSession, symbols: list[Symbol]) -> int:
    if not symbols:
        return 0

    rows = [
        {
            "symbol": symbol.symbol,
            "exchange": "bitunix",
            "base": symbol.base,
            "quote": symbol.quote,
            "min_leverage": symbol.min_leverage,
            "max_leverage": symbol.max_leverage,
            "default_leverage": symbol.default_leverage,
            "base_precision": symbol.base_precision,
            "quote_precision": symbol.quote_precision,
            "min_trade_volume": symbol.min_trade_volume,
            "status": symbol.status,
            "api_supported": symbol.api_supported,
        }
        for symbol in symbols
    ]
    for chunk in _chunks(rows, columns=12):
        statement = insert(InstrumentMeta).values(chunk)
        await db.execute(
            statement.on_conflict_do_update(
                index_elements=[InstrumentMeta.symbol],
                set_={
                    "base": statement.excluded.base,
                    "quote": statement.excluded.quote,
                    "min_leverage": statement.excluded.min_leverage,
                    "max_leverage": statement.excluded.max_leverage,
                    "default_leverage": statement.excluded.default_leverage,
                    "base_precision": statement.excluded.base_precision,
                    "quote_precision": statement.excluded.quote_precision,
                    "min_trade_volume": statement.excluded.min_trade_volume,
                    "status": statement.excluded.status,
                    "api_supported": statement.excluded.api_supported,
                    "refreshed_at": func.now(),
                },
            )
        )
    return len(rows)


async def read_instruments(db: AsyncSession) -> list[InstrumentMeta]:
    result = await db.execute(select(InstrumentMeta).order_by(InstrumentMeta.symbol))
    return list(result.scalars().all())


async def read_instrument(db: AsyncSession, symbol: str) -> InstrumentMeta | None:
    return await db.get(InstrumentMeta, symbol)


__all__ = [
    "coverage",
    "find_gaps",
    "read_bars",
    "read_funding",
    "read_instrument",
    "read_instruments",
    "to_datetime",
    "to_epoch_ms",
    "upsert_bars",
    "upsert_funding",
    "upsert_instruments",
]
