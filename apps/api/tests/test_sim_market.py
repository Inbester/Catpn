"""The synthetic market has to behave like one.

The simulator stands in for the venue offline (SPEC §9 lists regions where
Bitunix is unreachable), so research run against it must not be measuring
the generator. An earlier version was a sum of sine waves: its returns
carried a lag-2 autocorrelation of -0.87, and a Discover search over it
reported that a bar turning up predicted the next bar 96% of the time.
That is a property of a sine wave, not of a market.
"""

from __future__ import annotations

import numpy as np
import pytest

from quanta.exchanges.base import Interval
from quanta.exchanges.sim.market import SyntheticMarket

T0 = 1_700_000_000_000
HOUR = 3_600_000


def closes(symbol: str, count: int = 6000, interval: Interval = Interval.H1) -> np.ndarray:
    market = SyntheticMarket(symbol)
    bars = market.bars(start=T0, end=T0 + count * interval.milliseconds, interval=interval)
    return np.array([float(bar.close) for bar in bars])


def returns(symbol: str, **kwargs: object) -> np.ndarray:
    close = closes(symbol, **kwargs)  # type: ignore[arg-type]
    return np.diff(close) / close[:-1]


class TestReturnsLookLikeAMarket:
    @pytest.mark.parametrize("symbol", ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    @pytest.mark.parametrize("lag", [1, 2, 3, 5, 8])
    def test_returns_are_near_uncorrelated(self, symbol: str, lag: int) -> None:
        series = returns(symbol)
        correlation = float(np.corrcoef(series[:-lag], series[lag:])[0, 1])
        # A real market sits near zero. The old sine path reached -0.87.
        assert abs(correlation) < 0.05, f"lag {lag} autocorrelation {correlation:+.3f}"

    @pytest.mark.parametrize("symbol", ["BTCUSDT", "ETHUSDT"])
    def test_a_turn_up_does_not_predict_the_next_bar(self, symbol: str) -> None:
        """The exact artefact that gave the search a 96% win rate."""
        close = closes(symbol)
        change = np.diff(close, prepend=close[0])
        turned_up = (change > 0) & np.roll(change < 0, 1)
        higher_next = np.roll(close, -1) > close

        hit_rate = float(np.mean(higher_next[turned_up][:-1]))
        assert 0.42 < hit_rate < 0.58, f"turn-up predicted the next bar {hit_rate:.1%} of the time"

    @pytest.mark.parametrize("symbol", ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    def test_volatility_is_in_the_right_order(self, symbol: str) -> None:
        daily = float(np.std(returns(symbol)) * np.sqrt(24) * 100.0)
        assert 1.5 < daily < 8.0, f"{daily:.2f}% daily is not a crypto-like move"

    def test_price_stays_near_its_anchor(self) -> None:
        close = closes("BTCUSDT", count=14_000)
        # Wandering, but not to zero or to the moon: a chart of it has to
        # be usable and a backtest over it has to mean something.
        assert close.min() > 10_000
        assert close.max() < 250_000


class TestDeterminism:
    def test_the_same_window_generates_identically(self) -> None:
        # What makes the simulator usable as test data rather than a demo.
        assert np.array_equal(closes("BTCUSDT", count=500), closes("BTCUSDT", count=500))

    def test_a_window_does_not_depend_on_where_generation_started(self) -> None:
        """O(1) addressing: asking for one week must not replay from an origin."""
        market = SyntheticMarket("BTCUSDT")
        start = T0 + 5_000 * HOUR
        end = start + 100 * HOUR
        direct = {
            b.open_time: b.close for b in market.bars(start=start, end=end, interval=Interval.H1)
        }
        replayed = {
            b.open_time: b.close
            for b in market.bars(start=T0, end=end, interval=Interval.H1)
            if b.open_time in direct
        }
        assert direct == replayed
        assert len(direct) >= 100

    def test_different_symbols_are_different_series(self) -> None:
        btc = returns("BTCUSDT", count=2000)
        eth = returns("ETHUSDT", count=2000)
        assert abs(float(np.corrcoef(btc, eth)[0, 1])) < 0.2


class TestBarShape:
    def test_high_and_low_contain_open_and_close(self) -> None:
        market = SyntheticMarket("BTCUSDT")
        for bar in market.bars(start=T0, end=T0 + 200 * HOUR, interval=Interval.H1):
            assert bar.low <= bar.open <= bar.high
            assert bar.low <= bar.close <= bar.high
            assert bar.volume > 0
