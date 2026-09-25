"""Market-data storage, backfill and gap-filling.

Driven against the Bitunix simulator so the whole path is exercised: real
HTTP, real parsing, real Timescale writes.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from decimal import Decimal
from itertools import pairwise

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from quanta.exchanges.base import Bar, Interval
from quanta.exchanges.bitunix import BitunixAdapter
from quanta.exchanges.sim.server import create_sim_app
from quanta.services import market_store
from quanta.services.market_data import MarketDataService, channel_for, ticker_channel

NOW = 1_700_000_000_000


def bar(open_time: int, close: str = "100", *, closed: bool = True) -> Bar:
    return Bar(
        open_time=open_time,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal(close),
        volume=Decimal("10"),
        closed=closed,
    )


@pytest.fixture
async def adapter() -> AsyncGenerator[BitunixAdapter, None]:
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_sim_app()), base_url="http://sim"
    )
    yield BitunixAdapter(client=client)
    await client.aclose()


@pytest.fixture
def session_factory(db: AsyncSession) -> async_sessionmaker[AsyncSession]:
    """A factory handing every caller the test's own transaction."""

    class _Factory:
        def __call__(self) -> AsyncSession:
            return self  # type: ignore[return-value]

        async def __aenter__(self) -> AsyncSession:
            return db

        async def __aexit__(self, *_: object) -> None:
            return None

    return _Factory()  # type: ignore[return-value]


class TestKlineStorage:
    async def test_round_trips_bars(self, db: AsyncSession) -> None:
        bars = [bar(NOW + i * 60_000, close=str(100 + i)) for i in range(5)]
        written = await market_store.upsert_bars(db, "BTCUSDT", Interval.M1, bars)
        assert written == 5

        stored = await market_store.read_bars(db, "BTCUSDT", Interval.M1)
        assert [b.open_time for b in stored] == [b.open_time for b in bars]
        assert stored[-1].close == Decimal("104")

    async def test_prices_keep_full_precision(self, db: AsyncSession) -> None:
        """A price rounded in storage is a backtest that lies."""
        precise = Bar(
            open_time=NOW,
            open=Decimal("64123.123456789012"),
            high=Decimal("64200.000000000001"),
            low=Decimal("64000.987654321098"),
            close=Decimal("64111.111111111111"),
            volume=Decimal("0.000000000001"),
        )
        await market_store.upsert_bars(db, "BTCUSDT", Interval.M1, [precise])
        stored = await market_store.read_bars(db, "BTCUSDT", Interval.M1)
        assert stored[0].open == Decimal("64123.123456789012")
        assert stored[0].close == Decimal("64111.111111111111")

    async def test_a_forming_bar_is_overwritten(self, db: AsyncSession) -> None:
        await market_store.upsert_bars(
            db, "BTCUSDT", Interval.M1, [bar(NOW, close="100", closed=False)]
        )
        await market_store.upsert_bars(
            db, "BTCUSDT", Interval.M1, [bar(NOW, close="105", closed=False)]
        )
        stored = await market_store.read_bars(db, "BTCUSDT", Interval.M1)
        assert len(stored) == 1
        assert stored[0].close == Decimal("105")

    async def test_a_closed_bar_is_never_reopened(self, db: AsyncSession) -> None:
        """A late frame after a reconnect must not rewrite settled history."""
        await market_store.upsert_bars(
            db, "BTCUSDT", Interval.M1, [bar(NOW, close="100", closed=True)]
        )
        await market_store.upsert_bars(
            db, "BTCUSDT", Interval.M1, [bar(NOW, close="999", closed=False)]
        )
        stored = await market_store.read_bars(db, "BTCUSDT", Interval.M1)
        assert stored[0].close == Decimal("100")
        assert stored[0].closed is True

    async def test_series_are_kept_apart(self, db: AsyncSession) -> None:
        await market_store.upsert_bars(db, "BTCUSDT", Interval.M1, [bar(NOW)])
        await market_store.upsert_bars(db, "BTCUSDT", Interval.M5, [bar(NOW)])
        await market_store.upsert_bars(db, "ETHUSDT", Interval.M1, [bar(NOW)])
        await market_store.upsert_bars(db, "BTCUSDT", Interval.M1, [bar(NOW)], price_type="MARK")

        assert len(await market_store.read_bars(db, "BTCUSDT", Interval.M1)) == 1
        assert len(await market_store.read_bars(db, "BTCUSDT", Interval.M5)) == 1
        assert len(await market_store.read_bars(db, "ETHUSDT", Interval.M1)) == 1
        assert len(await market_store.read_bars(db, "BTCUSDT", Interval.M1, price_type="MARK")) == 1

    async def test_reads_the_newest_bars_when_limited(self, db: AsyncSession) -> None:
        bars = [bar(NOW + i * 60_000, close=str(i)) for i in range(50)]
        await market_store.upsert_bars(db, "BTCUSDT", Interval.M1, bars)

        stored = await market_store.read_bars(db, "BTCUSDT", Interval.M1, limit=10)
        assert len(stored) == 10
        assert stored[-1].close == Decimal("49")
        # Still chronological, which is what the chart needs.
        assert [b.open_time for b in stored] == sorted(b.open_time for b in stored)

    async def test_filters_by_range(self, db: AsyncSession) -> None:
        bars = [bar(NOW + i * 60_000) for i in range(20)]
        await market_store.upsert_bars(db, "BTCUSDT", Interval.M1, bars)

        stored = await market_store.read_bars(
            db, "BTCUSDT", Interval.M1, start=NOW + 5 * 60_000, end=NOW + 10 * 60_000
        )
        assert len(stored) == 5
        assert stored[0].open_time == NOW + 5 * 60_000

    async def test_coverage_tracks_the_stored_window(self, db: AsyncSession) -> None:
        bars = [bar(NOW + i * 60_000) for i in range(30)]
        await market_store.upsert_bars(db, "BTCUSDT", Interval.M1, bars)

        state = await market_store.coverage(db, "BTCUSDT", Interval.M1)
        assert state is not None
        assert state.earliest_open_time == NOW
        assert state.latest_open_time == NOW + 29 * 60_000
        assert state.bar_count == 30


class TestGapDetection:
    def test_no_gaps_in_a_contiguous_run(self) -> None:
        bars = [bar(NOW + i * 60_000) for i in range(10)]
        assert market_store.find_gaps(bars, Interval.M1) == []

    def test_finds_a_single_hole(self) -> None:
        bars = [bar(NOW), bar(NOW + 60_000), bar(NOW + 5 * 60_000)]
        assert market_store.find_gaps(bars, Interval.M1) == [(NOW + 2 * 60_000, NOW + 5 * 60_000)]

    def test_finds_several_holes(self) -> None:
        bars = [bar(NOW), bar(NOW + 3 * 60_000), bar(NOW + 4 * 60_000), bar(NOW + 9 * 60_000)]
        assert market_store.find_gaps(bars, Interval.M1) == [
            (NOW + 60_000, NOW + 3 * 60_000),
            (NOW + 5 * 60_000, NOW + 9 * 60_000),
        ]

    def test_handles_an_empty_or_single_series(self) -> None:
        assert market_store.find_gaps([], Interval.M1) == []
        assert market_store.find_gaps([bar(NOW)], Interval.M1) == []


class TestFunding:
    async def test_round_trips_funding(self, db: AsyncSession) -> None:
        from quanta.exchanges.base import Funding

        eight_hours = 8 * 3_600_000
        entries = [
            Funding(NOW + i * eight_hours, Decimal("0.0001"), Decimal("64000")) for i in range(4)
        ]
        assert await market_store.upsert_funding(db, "BTCUSDT", entries) == 4

        stored = await market_store.read_funding(db, "BTCUSDT")
        assert len(stored) == 4
        assert stored[0].funding_rate == Decimal("0.0001")

    async def test_resubmitting_a_settlement_updates_it(self, db: AsyncSession) -> None:
        from quanta.exchanges.base import Funding

        await market_store.upsert_funding(db, "BTCUSDT", [Funding(NOW, Decimal("0.0001"))])
        await market_store.upsert_funding(db, "BTCUSDT", [Funding(NOW, Decimal("0.0002"))])
        stored = await market_store.read_funding(db, "BTCUSDT")
        assert len(stored) == 1
        assert stored[0].funding_rate == Decimal("0.0002")


class TestInstruments:
    async def test_caches_contract_metadata(
        self, db: AsyncSession, adapter: BitunixAdapter
    ) -> None:
        symbols = await adapter.symbols()
        assert await market_store.upsert_instruments(db, symbols) == len(symbols)

        stored = await market_store.read_instruments(db)
        btc = next(row for row in stored if row.symbol == "BTCUSDT")
        assert btc.max_leverage == 200

    async def test_refreshing_updates_rather_than_duplicates(
        self, db: AsyncSession, adapter: BitunixAdapter
    ) -> None:
        symbols = await adapter.symbols()
        await market_store.upsert_instruments(db, symbols)
        await market_store.upsert_instruments(db, symbols)
        assert len(await market_store.read_instruments(db)) == len(symbols)


class TestBackfill:
    async def test_downloads_and_stores_a_range(
        self, db: AsyncSession, adapter: BitunixAdapter, session_factory: object
    ) -> None:
        service = MarketDataService(adapter, session_factory, None)  # type: ignore[arg-type]
        step = Interval.M5.milliseconds
        end = (NOW // step) * step
        start = end - step * 400

        written = await service.backfill("BTCUSDT", Interval.M5, start=start, end=end)
        assert written >= 390

        stored = await market_store.read_bars(db, "BTCUSDT", Interval.M5, limit=1000)
        times = [b.open_time for b in stored]
        assert len(times) == len(set(times))
        assert {b - a for a, b in pairwise(times)} == {step}

    async def test_gapfill_repairs_a_hole(
        self, db: AsyncSession, adapter: BitunixAdapter, session_factory: object
    ) -> None:
        """A disconnect leaves a hole; SPEC §3.1 requires it to be filled."""
        service = MarketDataService(adapter, session_factory, None)  # type: ignore[arg-type]
        step = Interval.M1.milliseconds
        end = (NOW // step) * step
        start = end - step * 120

        await service.backfill("BTCUSDT", Interval.M1, start=start, end=start + step * 40)
        await service.backfill("BTCUSDT", Interval.M1, start=start + step * 80, end=end)

        before = await market_store.read_bars(db, "BTCUSDT", Interval.M1, limit=1000)
        assert market_store.find_gaps(before, Interval.M1), "test setup left no gap"

        await service.fill_gaps("BTCUSDT", Interval.M1)

        after = await market_store.read_bars(db, "BTCUSDT", Interval.M1, limit=1000)
        assert market_store.find_gaps(after, Interval.M1) == []

    async def test_ensure_history_only_fetches_what_is_missing(
        self, db: AsyncSession, adapter: BitunixAdapter, session_factory: object
    ) -> None:
        service = MarketDataService(adapter, session_factory, None)  # type: ignore[arg-type]
        step = Interval.M15.milliseconds
        now = (NOW // step) * step

        first = await service.ensure_history("BTCUSDT", Interval.M15, bars=200, now_ms=now)
        assert first >= 190

        second = await service.ensure_history("BTCUSDT", Interval.M15, bars=200, now_ms=now)
        # Only the tail is refreshed the second time round.
        assert second < first


class TestChannels:
    def test_kline_channels_are_distinct_per_series(self) -> None:
        assert channel_for("BTCUSDT", Interval.M1) != channel_for("BTCUSDT", Interval.M5)
        assert channel_for("BTCUSDT", Interval.M1) != channel_for("ETHUSDT", Interval.M1)
        assert channel_for("BTCUSDT", Interval.M1, "MARK") != channel_for(
            "BTCUSDT", Interval.M1, "LAST"
        )

    def test_ticker_channel_is_per_symbol(self) -> None:
        assert ticker_channel("BTCUSDT") == "md:ticker:BTCUSDT"


class TestSharedSubscriptions:
    async def test_watching_one_series_twice_shares_the_connection(
        self, adapter: BitunixAdapter, session_factory: object
    ) -> None:
        """SPEC §4: one upstream socket however many browsers are watching."""
        service = MarketDataService(adapter, session_factory, None)  # type: ignore[arg-type]
        service.subscribe("BTCUSDT", Interval.M1)
        service.subscribe("BTCUSDT", Interval.M1)
        service.subscribe("BTCUSDT", Interval.M5)

        subscriptions = service._current_subscriptions()
        kline_subs = [s for s in subscriptions if s.channel.value == "kline"]
        assert len(kline_subs) == 2

        # One ticker subscription per symbol, not per series.
        ticker_subs = [s for s in subscriptions if s.channel.value == "ticker"]
        assert len(ticker_subs) == 1

    async def test_unsubscribing_removes_the_series(
        self, adapter: BitunixAdapter, session_factory: object
    ) -> None:
        service = MarketDataService(adapter, session_factory, None)  # type: ignore[arg-type]
        service.subscribe("BTCUSDT", Interval.M1)
        service.unsubscribe("BTCUSDT", Interval.M1)
        assert service._current_subscriptions() == []


class TestNoFutureBars:
    """A bar that has not opened yet must never be stored or served.

    It would draw as a phantom candle ahead of the live one, and a backtest
    would treat it as settled history.
    """

    async def test_the_adapter_never_returns_an_unopened_bar(self, adapter: BitunixAdapter) -> None:
        import time

        now = int(time.time() * 1000)
        for interval in (Interval.M1, Interval.M15, Interval.H1):
            bars = await adapter.klines("BTCUSDT", interval, limit=10)
            current_open = (now // interval.milliseconds) * interval.milliseconds
            assert bars[-1].open_time <= current_open, (
                f"{interval.value}: newest bar opens at {bars[-1].open_time}, "
                f"after the current bar {current_open}"
            )

    async def test_only_the_current_bar_is_unclosed(self, adapter: BitunixAdapter) -> None:
        import time

        now = int(time.time() * 1000)
        bars = await adapter.klines("BTCUSDT", Interval.M1, limit=20)
        current_open = (now // Interval.M1.milliseconds) * Interval.M1.milliseconds

        for candle in bars:
            if candle.open_time == current_open:
                assert not candle.closed, "the forming bar is marked closed"
            else:
                assert candle.closed, f"a past bar at {candle.open_time} is marked open"

    async def test_ensure_history_stores_nothing_from_the_future(
        self, db: AsyncSession, adapter: BitunixAdapter, session_factory: object
    ) -> None:
        import time

        service = MarketDataService(adapter, session_factory, None)  # type: ignore[arg-type]
        await service.ensure_history("BTCUSDT", Interval.M1, bars=120)

        now = int(time.time() * 1000)
        current_open = (now // Interval.M1.milliseconds) * Interval.M1.milliseconds
        stored = await market_store.read_bars(db, "BTCUSDT", Interval.M1, limit=200)

        assert stored, "nothing was stored"
        assert stored[-1].open_time <= current_open
        assert all(b.closed for b in stored if b.open_time < current_open)
