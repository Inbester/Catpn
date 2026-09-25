"""The Bitunix adapter, driven against the simulator.

The simulator speaks the wire format from SPEC §6, so these exercise the
real parsing, pagination and error handling rather than mocks.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from decimal import Decimal
from itertools import pairwise

import httpx
import pytest

from quanta.exchanges.base import (
    Bar,
    EventType,
    ExchangeError,
    Interval,
    RateLimitError,
    Subscription,
)
from quanta.exchanges.bitunix import (
    FALLBACK_FEE_TIERS,
    BitunixAdapter,
    _parse_bar,
    _parse_stream_message,
    _parse_ticker,
    _subscribe_payload,
)
from quanta.exchanges.sim.server import create_sim_app


@pytest.fixture
async def adapter() -> AsyncGenerator[BitunixAdapter, None]:
    """An adapter wired to the simulator over an in-process transport."""
    app = create_sim_app()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://sim")
    exchange = BitunixAdapter(client=client)
    yield exchange
    await client.aclose()


class TestSymbols:
    async def test_lists_tradable_symbols(self, adapter: BitunixAdapter) -> None:
        symbols = await adapter.symbols()
        assert len(symbols) >= 10
        names = {s.symbol for s in symbols}
        assert {"BTCUSDT", "ETHUSDT"} <= names

    async def test_btc_allows_200x(self, adapter: BitunixAdapter) -> None:
        """SPEC §6: BTC and ETH perpetuals go to 200x. Read per symbol."""
        symbols = {s.symbol: s for s in await adapter.symbols()}
        assert symbols["BTCUSDT"].max_leverage == 200
        assert symbols["SOLUSDT"].max_leverage < 200

    async def test_is_tradable_reflects_status_and_api_support(
        self, adapter: BitunixAdapter
    ) -> None:
        symbols = await adapter.symbols()
        assert all(s.is_tradable for s in symbols)


class TestPositionTiers:
    async def test_tiers_are_ordered_and_complete(self, adapter: BitunixAdapter) -> None:
        tiers = await adapter.position_tiers("BTCUSDT")
        assert [t.level for t in tiers] == sorted(t.level for t in tiers)
        assert len(tiers) >= 3

    async def test_maintenance_margin_rises_with_notional(self, adapter: BitunixAdapter) -> None:
        """Liquidation maths depends on this ladder being monotonic."""
        tiers = await adapter.position_tiers("BTCUSDT")
        rates = [t.maintenance_margin_rate for t in tiers]
        leverages = [t.leverage for t in tiers]
        assert rates == sorted(rates)
        assert leverages == sorted(leverages, reverse=True)

    async def test_tier_bands_are_contiguous(self, adapter: BitunixAdapter) -> None:
        tiers = await adapter.position_tiers("BTCUSDT")
        for lower, upper in pairwise(tiers):
            assert lower.end_value == upper.start_value

    async def test_unknown_symbol_raises(self, adapter: BitunixAdapter) -> None:
        with pytest.raises(ExchangeError):
            await adapter.position_tiers("NOTREAL")


class TestFeeTiers:
    async def test_returns_all_vip_levels(self, adapter: BitunixAdapter) -> None:
        tiers = await adapter.fee_tiers()
        assert len(tiers) == 9
        assert tiers[0].tier == "VIP0"

    async def test_rates_are_fractions_not_percentages(self, adapter: BitunixAdapter) -> None:
        """VIP0 taker is 0.060%, i.e. 0.0006 — a costing error here would
        skew every research number by two orders of magnitude."""
        tiers = {t.tier: t for t in await adapter.fee_tiers()}
        assert tiers["VIP0"].taker == Decimal("0.0006")
        assert tiers["VIP0"].maker == Decimal("0.0002")
        assert tiers["VIP3"].taker == Decimal("0.0004")

    async def test_fees_fall_as_the_tier_rises(self, adapter: BitunixAdapter) -> None:
        tiers = await adapter.fee_tiers()
        takers = [t.taker for t in tiers]
        assert takers == sorted(takers, reverse=True)

    async def test_falls_back_to_the_published_table(self) -> None:
        """A missing endpoint must not silently make trading look free."""

        async def failing(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="unavailable")

        client = httpx.AsyncClient(transport=httpx.MockTransport(failing), base_url="http://sim")
        exchange = BitunixAdapter(client=client)
        tiers = await exchange.fee_tiers()
        assert tiers == list(FALLBACK_FEE_TIERS)
        assert all(t.taker > 0 for t in tiers)
        await client.aclose()


class TestKlines:
    async def test_returns_bars_oldest_first(self, adapter: BitunixAdapter) -> None:
        bars = await adapter.klines("BTCUSDT", Interval.M15, limit=50)
        assert len(bars) == 50
        assert [b.open_time for b in bars] == sorted(b.open_time for b in bars)

    async def test_bars_are_contiguous_on_the_interval(self, adapter: BitunixAdapter) -> None:
        bars = await adapter.klines("BTCUSDT", Interval.M15, limit=40)
        gaps = {b.open_time - a.open_time for a, b in pairwise(bars)}
        assert gaps == {Interval.M15.milliseconds}

    async def test_open_times_sit_on_utc_boundaries(self, adapter: BitunixAdapter) -> None:
        """SPEC §3.1: the candle countdown uses UTC bar boundaries."""
        bars = await adapter.klines("BTCUSDT", Interval.H1, limit=10)
        assert all(b.open_time % Interval.H1.milliseconds == 0 for b in bars)

    async def test_ohlc_is_internally_consistent(self, adapter: BitunixAdapter) -> None:
        bars = await adapter.klines("BTCUSDT", Interval.M5, limit=60)
        for bar in bars:
            assert bar.low <= bar.open <= bar.high
            assert bar.low <= bar.close <= bar.high
            assert bar.volume >= 0

    async def test_only_the_newest_bar_is_still_forming(self, adapter: BitunixAdapter) -> None:
        bars = await adapter.klines("BTCUSDT", Interval.M1, limit=30)
        assert all(b.closed for b in bars[:-1])

    async def test_limit_is_capped_at_the_venue_maximum(self, adapter: BitunixAdapter) -> None:
        """Asking for more than 200 must not error; it clamps."""
        bars = await adapter.klines("BTCUSDT", Interval.M1, limit=500)
        assert len(bars) <= 200

    async def test_mark_price_series_differs_from_last(self, adapter: BitunixAdapter) -> None:
        last = await adapter.klines("BTCUSDT", Interval.M15, limit=5, price_type="LAST")
        mark = await adapter.klines("BTCUSDT", Interval.M15, limit=5, price_type="MARK")
        assert [b.open_time for b in last] == [b.open_time for b in mark]
        assert last[0].close != mark[0].close

    async def test_unsupported_interval_is_rejected(self, adapter: BitunixAdapter) -> None:
        with pytest.raises(KeyError):
            await adapter.klines("BTCUSDT", "7m", limit=5)  # type: ignore[arg-type]

    async def test_unknown_symbol_raises(self, adapter: BitunixAdapter) -> None:
        with pytest.raises(ExchangeError, match="unknown symbol"):
            await adapter.klines("NOTREAL", Interval.M1, limit=5)


class TestKlinePagination:
    async def test_walks_a_long_range_in_pages(self, adapter: BitunixAdapter) -> None:
        """SPEC §6: history is backfilled once, 200 bars at a time."""
        step = Interval.M1.milliseconds
        end = (1_700_000_000_000 // step) * step
        start = end - step * 650

        pages = [
            page async for page in adapter.iter_klines("BTCUSDT", Interval.M1, start=start, end=end)
        ]
        assert len(pages) >= 4
        assert all(len(page) <= 200 for page in pages)

        flat = [bar for page in pages for bar in page]
        assert len(flat) >= 600

    async def test_pagination_produces_no_gaps_or_duplicates(self, adapter: BitunixAdapter) -> None:
        step = Interval.M5.milliseconds
        end = (1_700_000_000_000 // step) * step
        start = end - step * 500

        flat = [
            bar
            async for page in adapter.iter_klines("BTCUSDT", Interval.M5, start=start, end=end)
            for bar in page
        ]
        times = [b.open_time for b in flat]
        assert len(times) == len(set(times)), "pagination repeated a bar"
        gaps = {b - a for a, b in pairwise(times)}
        assert gaps == {step}, f"pagination left a gap: {gaps}"


class TestFunding:
    async def test_settlements_are_eight_hours_apart(self, adapter: BitunixAdapter) -> None:
        """SPEC §6: funding settles at 00:00, 08:00 and 16:00 UTC."""
        entries = await adapter.funding_history("BTCUSDT", limit=12)
        assert len(entries) >= 3
        eight_hours = 8 * 3_600_000
        gaps = {b.funding_time - a.funding_time for a, b in pairwise(entries)}
        assert gaps == {eight_hours}
        assert all(e.funding_time % eight_hours == 0 for e in entries)

    async def test_rates_are_within_the_venue_cap(self, adapter: BitunixAdapter) -> None:
        entries = await adapter.funding_history("BTCUSDT", limit=20)
        assert all(abs(e.funding_rate) <= Decimal("0.00375") for e in entries)


class TestTickers:
    async def test_covers_every_symbol(self, adapter: BitunixAdapter) -> None:
        tickers = await adapter.tickers()
        symbols = await adapter.symbols()
        assert {t.symbol for t in tickers} == {s.symbol for s in symbols}

    async def test_carries_what_the_detail_card_needs(self, adapter: BitunixAdapter) -> None:
        """SPEC §3.1: mark, index, funding, next funding, 24h high/low."""
        ticker = next(t for t in await adapter.tickers() if t.symbol == "BTCUSDT")
        assert ticker.mark_price is not None
        assert ticker.index_price is not None
        assert ticker.funding_rate is not None
        assert ticker.next_funding_time is not None
        assert ticker.high_24h is not None and ticker.low_24h is not None
        assert ticker.low_24h <= ticker.last <= ticker.high_24h


class TestErrorHandling:
    async def _adapter_returning(self, response: httpx.Response) -> BitunixAdapter:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _request: response),
            base_url="http://sim",
        )
        return BitunixAdapter(client=client)

    async def test_429_becomes_a_rate_limit_error(self) -> None:
        adapter = await self._adapter_returning(httpx.Response(429, headers={"Retry-After": "3"}))
        with pytest.raises(RateLimitError) as caught:
            await adapter.symbols()
        assert caught.value.retry_after == 3.0
        assert caught.value.retryable

    async def test_server_errors_are_marked_retryable(self) -> None:
        adapter = await self._adapter_returning(httpx.Response(503))
        with pytest.raises(ExchangeError) as caught:
            await adapter.symbols()
        assert caught.value.retryable

    async def test_client_errors_are_not_retryable(self) -> None:
        adapter = await self._adapter_returning(httpx.Response(400, text="bad request"))
        with pytest.raises(ExchangeError) as caught:
            await adapter.symbols()
        assert not caught.value.retryable

    async def test_venue_error_code_is_surfaced(self) -> None:
        adapter = await self._adapter_returning(
            httpx.Response(200, json={"code": "10001", "msg": "symbol not found", "data": None})
        )
        with pytest.raises(ExchangeError, match="symbol not found") as caught:
            await adapter.symbols()
        assert caught.value.code == "10001"

    async def test_non_json_body_is_reported_clearly(self) -> None:
        adapter = await self._adapter_returning(
            httpx.Response(200, text="<html>maintenance</html>")
        )
        with pytest.raises(ExchangeError, match="non-JSON"):
            await adapter.symbols()

    async def test_a_timeout_is_retryable(self) -> None:
        def timeout(_request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("too slow")

        client = httpx.AsyncClient(transport=httpx.MockTransport(timeout), base_url="http://sim")
        adapter = BitunixAdapter(client=client)
        with pytest.raises(ExchangeError) as caught:
            await adapter.symbols()
        assert caught.value.retryable


class TestParsing:
    def test_parses_the_object_kline_shape(self) -> None:
        bar = _parse_bar(
            {
                "time": 1_700_000_000_000,
                "open": "64000.1",
                "high": "64200.0",
                "low": "63900.5",
                "close": "64100.2",
                "baseVol": "123.45",
            }
        )
        assert bar == Bar(
            open_time=1_700_000_000_000,
            open=Decimal("64000.1"),
            high=Decimal("64200.0"),
            low=Decimal("63900.5"),
            close=Decimal("64100.2"),
            volume=Decimal("123.45"),
        )

    def test_parses_the_array_kline_shape(self) -> None:
        bar = _parse_bar([1_700_000_000_000, "1", "2", "0.5", "1.5", "10"])
        assert bar is not None
        assert bar.high == Decimal("2")

    def test_rejects_a_kline_without_a_timestamp(self) -> None:
        assert _parse_bar({"open": "1", "high": "2", "low": "1", "close": "2"}) is None

    def test_rejects_a_kline_with_an_unparsable_price(self) -> None:
        assert _parse_bar({"time": 1, "open": "n/a", "high": "2", "low": "1", "close": "2"}) is None

    def test_a_ratio_change_is_normalised_to_percent(self) -> None:
        ticker = _parse_ticker(
            {"symbol": "BTCUSDT", "lastPrice": "64000", "priceChangePercent": "0.0214"}
        )
        assert ticker is not None
        assert ticker.change_percent_24h == Decimal("2.14")

    def test_kline_subscription_needs_an_interval(self) -> None:
        with pytest.raises(ExchangeError, match="needs an interval"):
            _subscribe_payload([Subscription(EventType.KLINE, "BTCUSDT")])

    def test_subscription_payload_uses_the_venue_channel_names(self) -> None:
        payload = _subscribe_payload(
            [
                Subscription(EventType.KLINE, "BTCUSDT", Interval.M15),
                Subscription(EventType.TICKER, "ETHUSDT"),
            ]
        )
        assert payload["op"] == "subscribe"
        assert payload["args"] == [
            {"symbol": "BTCUSDT", "ch": "market_kline_15m"},
            {"symbol": "ETHUSDT", "ch": "ticker"},
        ]

    def test_parses_a_kline_frame(self) -> None:
        events = _parse_stream_message(
            json.dumps(
                {
                    "ch": "market_kline_1m",
                    "symbol": "BTCUSDT",
                    "ts": 1_700_000_000_000,
                    "data": {
                        "time": 1_700_000_000_000,
                        "open": "1",
                        "high": "2",
                        "low": "1",
                        "close": "2",
                        "closed": False,
                    },
                }
            )
        )
        assert len(events) == 1
        assert events[0].type is EventType.KLINE
        assert events[0].interval is Interval.M1
        assert events[0].bar is not None and not events[0].bar.closed

    def test_ignores_control_frames(self) -> None:
        """Pongs and subscribe acks carry no market data."""
        assert _parse_stream_message(json.dumps({"op": "pong", "ts": 1})) == []
        assert _parse_stream_message(json.dumps({"op": "subscribe", "success": True})) == []

    def test_ignores_malformed_frames(self) -> None:
        assert _parse_stream_message("not json") == []
        assert _parse_stream_message(json.dumps([1, 2, 3])) == []

    def test_parses_a_mark_price_frame(self) -> None:
        events = _parse_stream_message(
            json.dumps(
                {"ch": "mark_price", "symbol": "BTCUSDT", "ts": 1, "data": {"markPrice": "64001.5"}}
            )
        )
        assert len(events) == 1
        assert events[0].price == Decimal("64001.5")


class TestSubscriptionLimits:
    async def test_rejects_more_than_the_venue_allows(self, adapter: BitunixAdapter) -> None:
        """SPEC §6: 300 subscriptions per connection."""
        too_many = [Subscription(EventType.TICKER, f"SYM{i}USDT") for i in range(301)]
        with pytest.raises(ExchangeError, match="exceeds"):
            async for _ in adapter.stream(too_many):
                break
