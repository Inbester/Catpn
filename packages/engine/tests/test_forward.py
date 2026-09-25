"""Forward testing: Monte Carlo bands, regime metrics, comparison, walk-forward."""

from __future__ import annotations

from itertools import pairwise

import numpy as np
import pytest

from quanta_engine.backtest.engine import run_backtest
from quanta_engine.backtest.types import BacktestConfig, Bars
from quanta_engine.forward.compare import Verdict, compare_periods
from quanta_engine.forward.montecarlo import simulate, trade_returns_on_equity
from quanta_engine.forward.regime import describe, realised_volatility, trend_efficiency
from quanta_engine.forward.walkforward import (
    MAX_COMBINATIONS,
    build_windows,
    expand_grid,
    run_walk_forward,
)
from quanta_engine.strategy import ExitRules, Strategy

HOUR = 3_600_000
DAY = 86_400_000
T0 = 1_700_000_000_000


def series(seed: int, n: int = 700, drift: float = 0.0, scale: float = 1.0) -> Bars:
    rng = np.random.default_rng(seed)
    prices = 100 + rng.normal(drift, scale, n).cumsum()
    prices = np.maximum(prices, 1.0)
    times = np.arange(n, dtype=np.int64) * HOUR + T0
    return Bars(
        time=times,
        open=prices,
        high=prices + 0.5,
        low=prices - 0.5,
        close=prices,
        volume=np.full(n, 100.0),
    )


def crossover_strategy(**params: float) -> Strategy:
    return Strategy(
        name="Cross",
        long_entry="crossover(close, ema(close, fast))",
        short_entry="crossunder(close, ema(close, fast))",
        exits=ExitRules(exit_on_opposite=True),
        params={"fast": 20.0, **params},
    )


class TestMonteCarlo:
    def test_the_band_widens_with_volatility(self) -> None:
        calm = simulate(np.full(100, 0.001), trade_count=50)
        noisy = simulate(np.random.default_rng(0).normal(0.001, 0.05, 100), trade_count=50)
        calm_width = calm.net_percent.high - calm.net_percent.low
        noisy_width = noisy.net_percent.high - noisy.net_percent.low
        assert noisy_width > calm_width

    def test_a_constant_winner_has_a_narrow_band(self) -> None:
        """Every resample is identical, so there is nothing to spread."""
        result = simulate(np.full(50, 0.01), trade_count=20)
        assert result.net_percent.high == pytest.approx(result.net_percent.low)

    def test_the_band_is_deterministic(self) -> None:
        """A verdict must not change on a re-run for no visible reason."""
        returns = np.random.default_rng(3).normal(0.002, 0.02, 80)
        first = simulate(returns, trade_count=60)
        second = simulate(returns, trade_count=60)
        assert first.net_percent.low == second.net_percent.low
        assert first.net_percent.high == second.net_percent.high

    def test_more_trades_compound_further(self) -> None:
        returns = np.full(100, 0.01)
        short = simulate(returns, trade_count=10)
        long = simulate(returns, trade_count=100)
        assert long.net_percent.median > short.net_percent.median

    def test_drawdown_band_is_negative(self) -> None:
        result = simulate(np.random.default_rng(1).normal(0.0, 0.03, 100), trade_count=50)
        assert result.max_drawdown_percent.low <= 0
        assert result.max_drawdown_percent.low <= result.max_drawdown_percent.high

    def test_an_empty_history_yields_an_empty_band(self) -> None:
        result = simulate(np.array([]), trade_count=50)
        assert result.net_percent.runs == 0
        assert result.net_percent.low == 0.0

    def test_band_membership_and_position(self) -> None:
        result = simulate(np.random.default_rng(5).normal(0.005, 0.02, 100), trade_count=50)
        band = result.net_percent
        assert band.contains(band.median)
        assert band.position(band.low) == pytest.approx(0.0)
        assert band.position(band.high) == pytest.approx(1.0)
        # Outside the band, the position clamps rather than running off.
        assert band.position(band.high + 1000) == pytest.approx(1.0)

    def test_returns_are_relative_to_the_equity_each_trade_started_with(self) -> None:
        returns = trade_returns_on_equity([100.0, 200.0], [10_000.0, 20_000.0])
        assert returns.tolist() == pytest.approx([0.01, 0.01])

    def test_a_zero_equity_does_not_divide_by_zero(self) -> None:
        assert trade_returns_on_equity([100.0], [0.0]).tolist() == [0.0]


class TestRegime:
    def test_a_straight_line_is_perfectly_efficient(self) -> None:
        assert trend_efficiency(np.array([1.0, 2.0, 3.0, 4.0])) == pytest.approx(1.0)

    def test_a_round_trip_is_perfectly_inefficient(self) -> None:
        assert trend_efficiency(np.array([1.0, 2.0, 1.0])) == pytest.approx(0.0)

    def test_a_trend_is_more_efficient_than_chop(self) -> None:
        trend = np.linspace(100, 130, 300)
        chop = 100 + np.sin(np.arange(300) / 2) * 5
        assert trend_efficiency(trend) > trend_efficiency(chop)

    def test_volatility_rises_with_noise(self) -> None:
        rng = np.random.default_rng(2)
        calm = 100 + rng.normal(0, 0.05, 300).cumsum()
        wild = 100 + rng.normal(0, 1.0, 300).cumsum()
        assert realised_volatility(wild, HOUR) > realised_volatility(calm, HOUR)

    def test_describe_reports_the_period_return(self) -> None:
        bars = Bars(
            time=np.arange(100, dtype=np.int64) * HOUR + T0,
            open=np.linspace(100, 110, 100),
            high=np.linspace(100, 110, 100) + 1,
            low=np.linspace(100, 110, 100) - 1,
            close=np.linspace(100, 110, 100),
            volume=np.full(100, 1.0),
        )
        regime = describe(bars.time, bars.high, bars.low, bars.close)
        assert regime.return_percent == pytest.approx(10.0)
        assert regime.bars == 100
        assert regime.trend_efficiency == pytest.approx(1.0)

    def test_a_single_bar_is_handled(self) -> None:
        one = np.array([100.0])
        regime = describe(np.array([T0], dtype=np.int64), one, one, one)
        assert regime.return_percent == 0.0


class TestCompare:
    def _run(self, bars: Bars) -> tuple:
        config = BacktestConfig(initial_capital=10_000, leverage=2, margin_percent=10)
        return run_backtest(crossover_strategy(), bars, config), bars

    def test_refuses_to_compare_different_versions(self) -> None:
        """A period comparison isolates the data; two versions isolate nothing."""
        bars = series(1)
        config = BacktestConfig(initial_capital=10_000)
        first = run_backtest(crossover_strategy(fast=20), bars, config)
        second = run_backtest(crossover_strategy(fast=30), bars, config)

        with pytest.raises(ValueError, match="one frozen strategy version"):
            compare_periods(
                reference=first,
                reference_bars=bars,
                reference_label="A",
                test=second,
                test_bars=bars,
                test_label="B",
                initial_capital=10_000,
            )

    def test_the_same_data_holds_up(self) -> None:
        """Compared with itself, a strategy must land inside its own band."""
        reference, bars = self._run(series(4, drift=0.05))
        comparison = compare_periods(
            reference=reference,
            reference_bars=bars,
            reference_label="Ref",
            test=reference,
            test_bars=bars,
            test_label="Same",
            initial_capital=10_000,
            runs=500,
        )
        assert comparison.verdict in (Verdict.HOLDS_UP, Verdict.HOLDS_UP_WEAKER)
        by_key = {check.key: check for check in comparison.checks}
        assert by_key["net_in_band"].passed

    def test_a_collapse_lands_outside_the_range(self) -> None:
        reference, reference_bars = self._run(series(11, drift=0.09, scale=0.6))
        test, test_bars = self._run(series(12, drift=-0.09, scale=1.6))

        comparison = compare_periods(
            reference=reference,
            reference_bars=reference_bars,
            reference_label="Farvardin 1404",
            test=test,
            test_bars=test_bars,
            test_label="Farvardin 1405",
            initial_capital=10_000,
            runs=800,
        )
        assert comparison.verdict is Verdict.OUTSIDE_RANGE
        assert "outside the expected range" in comparison.headline

    def test_too_few_trades_is_its_own_verdict(self) -> None:
        """Silence is not evidence; say so rather than pass or fail."""
        quiet = Bars(
            time=np.arange(50, dtype=np.int64) * HOUR + T0,
            open=np.full(50, 100.0),
            high=np.full(50, 100.5),
            low=np.full(50, 99.5),
            close=np.full(50, 100.0),
            volume=np.full(50, 1.0),
        )
        result = run_backtest(crossover_strategy(), quiet, BacktestConfig())
        comparison = compare_periods(
            reference=result,
            reference_bars=quiet,
            reference_label="A",
            test=result,
            test_bars=quiet,
            test_label="B",
            initial_capital=10_000,
            runs=200,
        )
        assert comparison.verdict is Verdict.TOO_FEW_TRADES

    def test_every_check_is_named_and_explained(self) -> None:
        reference, reference_bars = self._run(series(21, drift=0.05))
        test, test_bars = self._run(series(22, drift=0.02))
        comparison = compare_periods(
            reference=reference,
            reference_bars=reference_bars,
            reference_label="A",
            test=test,
            test_bars=test_bars,
            initial_capital=10_000,
            test_label="B",
            runs=400,
        )
        keys = {check.key for check in comparison.checks}
        assert keys == {"net_in_band", "drawdown_in_band", "trade_count", "profit_factor"}
        for check in comparison.checks:
            assert check.detail, f"{check.key} has no explanation"
            assert check.severity in ("ok", "warn", "fail")

    def test_the_reading_names_real_numbers(self) -> None:
        reference, reference_bars = self._run(series(31, drift=0.08))
        test, test_bars = self._run(series(32, drift=-0.08))
        comparison = compare_periods(
            reference=reference,
            reference_bars=reference_bars,
            reference_label="Farvardin 1404",
            test=test,
            test_bars=test_bars,
            test_label="Farvardin 1405",
            initial_capital=10_000,
            runs=400,
        )
        assert "Farvardin 1405" in comparison.reading
        assert "trend efficiency" in comparison.reading
        # It must always end by saying one period is not proof.
        assert "cannot prove" in comparison.reading

    def test_longest_drawdown_is_reported_in_days(self) -> None:
        reference, reference_bars = self._run(series(41, drift=0.03))
        test, test_bars = self._run(series(42, drift=0.03))
        comparison = compare_periods(
            reference=reference,
            reference_bars=reference_bars,
            reference_label="A",
            test=test,
            test_bars=test_bars,
            test_label="B",
            initial_capital=10_000,
            runs=300,
        )
        row = next(m for m in comparison.metrics if m.key == "longest_drawdown")
        assert row.unit == "d"
        # 700 hourly bars is about 29 days, so a drawdown cannot exceed that.
        assert 0 <= row.test <= 30

    def test_serialises_for_the_api(self) -> None:
        reference, reference_bars = self._run(series(51, drift=0.04))
        test, test_bars = self._run(series(52, drift=0.01))
        payload = compare_periods(
            reference=reference,
            reference_bars=reference_bars,
            reference_label="A",
            test=test,
            test_bars=test_bars,
            test_label="B",
            initial_capital=10_000,
            runs=300,
        ).to_dict()

        assert payload["verdict"]
        assert payload["monte_carlo"]["runs"] == 300
        assert len(payload["metrics"]) == 9
        assert payload["reference"]["regime"]["trend_efficiency"] is not None


class TestWalkForwardWindows:
    def test_windows_roll_by_the_out_of_sample_length(self) -> None:
        windows = build_windows(0, 400 * DAY, in_sample_days=90, out_of_sample_days=30)
        assert len(windows) > 1
        for earlier, later in pairwise(windows):
            assert later.in_sample_start - earlier.in_sample_start == 30 * DAY

    def test_out_of_sample_stretches_never_overlap(self) -> None:
        """Every bar is tested once; testing one twice would double-count it."""
        windows = build_windows(0, 400 * DAY)
        for earlier, later in pairwise(windows):
            assert earlier.out_of_sample_end <= later.out_of_sample_start

    def test_out_of_sample_always_follows_in_sample(self) -> None:
        for window in build_windows(0, 400 * DAY):
            assert window.out_of_sample_start == window.in_sample_end

    def test_a_short_range_yields_no_windows(self) -> None:
        assert build_windows(0, 30 * DAY) == []

    def test_the_window_count_is_capped(self) -> None:
        assert len(build_windows(0, 2000 * DAY, max_windows=12)) == 12

    def test_rejects_a_zero_length_window(self) -> None:
        with pytest.raises(ValueError, match="at least one day"):
            build_windows(0, 400 * DAY, in_sample_days=0)


class TestWalkForwardGrid:
    def test_expands_every_combination(self) -> None:
        grid = expand_grid({"fast": [10, 20], "slow": [50, 100]})
        assert len(grid) == 4
        assert {"fast": 10, "slow": 50} in grid

    def test_an_empty_grid_is_one_run(self) -> None:
        assert expand_grid({}) == [{}]

    def test_refuses_an_unreasonable_grid(self) -> None:
        with pytest.raises(ValueError, match=str(MAX_COMBINATIONS)):
            expand_grid({"a": list(range(30)), "b": list(range(30))})


class TestWalkForwardRun:
    def test_produces_one_result_per_window(self) -> None:
        bars = series(61, n=24 * 300, drift=0.01, scale=0.4)
        result = run_walk_forward(
            crossover_strategy(),
            bars,
            grid={"fast": [10, 30]},
            config=BacktestConfig(initial_capital=10_000, leverage=2),
        )
        assert len(result.windows) >= 3
        for window in result.windows:
            assert "fast" in window.chosen_params

    def test_the_chained_curve_is_out_of_sample_only(self) -> None:
        """Every chained point must fall inside some out-of-sample window."""
        bars = series(62, n=24 * 300, drift=0.01, scale=0.4)
        result = run_walk_forward(
            crossover_strategy(),
            bars,
            grid={"fast": [20]},
            config=BacktestConfig(initial_capital=10_000),
        )
        spans = [
            (window.window.out_of_sample_start, window.window.out_of_sample_end)
            for window in result.windows
        ]
        for moment in result.chained_time:
            assert any(start <= moment < end for start, end in spans), moment

    def test_drawdown_aligns_with_the_chained_curve(self) -> None:
        bars = series(63, n=24 * 300, drift=0.01, scale=0.4)
        result = run_walk_forward(
            crossover_strategy(), bars, grid={"fast": [20]}, config=BacktestConfig()
        )
        assert len(result.chained_drawdown) == len(result.chained_equity)
        assert max(result.chained_drawdown) <= 0.0

    def test_efficiency_is_undefined_when_in_sample_lost(self) -> None:
        """Dividing by a loss produces a number that looks like a score."""
        bars = series(64, n=24 * 300, drift=-0.05, scale=1.2)
        result = run_walk_forward(
            crossover_strategy(), bars, grid={"fast": [20]}, config=BacktestConfig()
        )
        for window in result.windows:
            if window.in_sample_net_percent <= 0:
                assert window.efficiency is None

    def test_a_range_too_short_says_so(self) -> None:
        with pytest.raises(ValueError, match="too short"):
            run_walk_forward(crossover_strategy(), series(65, n=100), grid={"fast": [20]})

    def test_serialises_for_the_api(self) -> None:
        bars = series(66, n=24 * 300, drift=0.01, scale=0.4)
        payload = run_walk_forward(
            crossover_strategy(), bars, grid={"fast": [20]}, config=BacktestConfig()
        ).to_dict()
        assert "windows" in payload
        assert "chained" in payload
        assert len(payload["chained"]["time"]) == len(payload["chained"]["value"])
