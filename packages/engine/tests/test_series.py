"""Series primitives.

These must match the chart's TypeScript versions exactly, so the assertions
here mirror the ones in apps/web/src/features/chart/lib/indicators.test.ts.
"""

from __future__ import annotations

import numpy as np
import pytest

from quanta_engine.series import (
    atr,
    bollinger,
    crossover,
    crossunder,
    ema,
    falling,
    highest,
    lowest,
    macd_lines,
    rising,
    rsi,
    shift,
    sma,
    stdev,
    true_range,
)


def arr(*values: float) -> np.ndarray:
    return np.array(values, dtype=np.float64)


class TestSma:
    def test_is_nan_until_the_window_fills(self) -> None:
        result = sma(arr(1, 2, 3, 4), 3)
        assert np.isnan(result[:2]).all()
        assert result[2] == pytest.approx(2.0)
        assert result[3] == pytest.approx(3.0)

    def test_matches_a_hand_computed_average(self) -> None:
        assert sma(arr(2, 4, 6, 8, 10), 5)[4] == pytest.approx(6.0)

    def test_all_nan_without_enough_data(self) -> None:
        assert np.isnan(sma(arr(1, 2), 5)).all()

    def test_rejects_a_zero_length(self) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            sma(arr(1, 2, 3), 0)


class TestEma:
    def test_seeds_from_the_sma_of_the_first_window(self) -> None:
        # SMA(1..5) = 3, so the first EMA value is 3.
        result = ema(arr(1, 2, 3, 4, 5), 5)
        assert np.isnan(result[:4]).all()
        assert result[4] == pytest.approx(3.0)

    def test_applies_the_standard_smoothing_factor(self) -> None:
        # k = 2/(3+1) = 0.5, seed = SMA(1,2,3) = 2.
        # then 4*0.5 + 2*0.5 = 3; 5*0.5 + 3*0.5 = 4.
        result = ema(arr(1, 2, 3, 4, 5), 3)
        assert result[2] == pytest.approx(2.0)
        assert result[3] == pytest.approx(3.0)
        assert result[4] == pytest.approx(4.0)

    def test_tracks_a_constant_exactly(self) -> None:
        assert ema(np.full(20, 42.0), 10)[-1] == pytest.approx(42.0)

    def test_the_seed_does_not_depend_on_extra_history(self) -> None:
        """Loading more bars must not change a signal on the same bar.

        Seeding from the first value instead of the SMA would make the
        result drift with however much history happened to be loaded.
        """
        values = np.linspace(100, 200, 400)
        full = ema(values, 20)
        tail = ema(values[100:], 20)
        assert full[-1] == pytest.approx(tail[-1], rel=1e-9)


class TestRsi:
    def test_is_100_when_every_change_is_a_gain(self) -> None:
        assert rsi(np.arange(1.0, 31.0), 14)[-1] == pytest.approx(100.0)

    def test_is_0_when_every_change_is_a_loss(self) -> None:
        assert rsi(np.arange(100.0, 70.0, -1.0), 14)[-1] == pytest.approx(0.0)

    def test_stays_within_bounds_on_noisy_data(self) -> None:
        noisy = 100 + np.sin(np.arange(200) / 3) * 12 + (np.arange(200) % 7)
        values = rsi(noisy, 14)
        finite = values[~np.isnan(values)]
        assert (finite >= 0).all()
        assert (finite <= 100).all()

    def test_has_no_value_before_warm_up(self) -> None:
        assert np.isnan(rsi(arr(1, 2, 3, 4, 5), 14)).all()


class TestAtr:
    def test_true_range_uses_the_previous_close(self) -> None:
        high = arr(10, 12, 11)
        low = arr(9, 11, 9)
        close = arr(9.5, 11.5, 10)
        # Bar 1: max(12-11, |12-9.5|, |11-9.5|) = 2.5
        assert true_range(high, low, close)[1] == pytest.approx(2.5)

    def test_first_bar_is_just_the_range(self) -> None:
        assert true_range(arr(10, 12), arr(9, 11), arr(9.5, 11.5))[0] == pytest.approx(1.0)

    def test_grows_with_volatility(self) -> None:
        n = 40
        close = np.full(n, 100.0)
        calm = atr(close + 1, close - 1, close, 14)[-1]
        wild_high = np.where(np.arange(n) > 20, close + 10, close + 1)
        wild_low = np.where(np.arange(n) > 20, close - 10, close - 1)
        assert atr(wild_high, wild_low, close, 14)[-1] > calm

    def test_is_never_negative(self) -> None:
        close = 100 + np.sin(np.arange(100)) * 5
        values = atr(close + 1, close - 1, close, 14)
        assert (values[~np.isnan(values)] >= 0).all()


class TestMacd:
    def test_is_zero_on_a_flat_series(self) -> None:
        line, signal, hist = macd_lines(np.full(100, 50.0))
        assert line[-1] == pytest.approx(0.0)
        assert signal[-1] == pytest.approx(0.0)
        assert hist[-1] == pytest.approx(0.0)

    def test_is_positive_in_an_uptrend(self) -> None:
        assert macd_lines(np.arange(100.0, 220.0))[0][-1] > 0

    def test_histogram_is_line_minus_signal(self) -> None:
        values = 100 + np.sin(np.arange(150) / 8) * 20
        line, signal, hist = macd_lines(values)
        warm = ~np.isnan(hist)
        assert np.allclose(hist[warm], line[warm] - signal[warm])


class TestBollinger:
    def test_collapses_on_a_flat_series(self) -> None:
        middle, upper, lower = bollinger(np.full(40, 100.0), 20)
        assert middle[-1] == pytest.approx(100.0)
        assert upper[-1] == pytest.approx(100.0)
        assert lower[-1] == pytest.approx(100.0)

    def test_bands_are_symmetric(self) -> None:
        values = 100 + np.sin(np.arange(60) / 4) * 10
        middle, upper, lower = bollinger(values, 20)
        warm = ~np.isnan(middle)
        assert np.allclose(upper[warm] - middle[warm], middle[warm] - lower[warm])

    def test_uses_population_standard_deviation(self) -> None:
        values = arr(1, 2, 3, 4, 5)
        assert stdev(values, 5)[-1] == pytest.approx(float(np.std(values)))


class TestCrosses:
    def test_crossover_fires_on_the_crossing_bar_only(self) -> None:
        a = arr(1, 2, 3, 4)
        b = arr(2, 2, 2, 2)
        assert crossover(a, b).tolist() == [False, False, True, False]

    def test_crossunder_is_the_mirror(self) -> None:
        a = arr(4, 3, 2, 1)
        b = arr(2, 2, 2, 2)
        assert crossunder(a, b).tolist() == [False, False, False, True]

    def test_touching_without_crossing_is_not_a_cross(self) -> None:
        a = arr(1, 2, 2, 1)
        b = arr(2, 2, 2, 2)
        assert not crossover(a, b).any()

    def test_a_nan_warm_up_is_never_a_signal(self) -> None:
        a = np.array([np.nan, np.nan, 3.0, 4.0])
        b = arr(2, 2, 2, 2)
        assert crossover(a, b).tolist() == [False, False, False, False]


class TestMonotonic:
    def test_rising_over_one_bar(self) -> None:
        assert rising(arr(1, 2, 3, 3, 4), 1).tolist() == [False, True, True, False, True]

    def test_rising_over_two_bars(self) -> None:
        assert rising(arr(1, 2, 3, 3, 4), 2).tolist() == [False, False, True, False, False]

    def test_falling_mirrors_rising(self) -> None:
        assert falling(arr(5, 4, 3, 2, 1), 2).tolist() == [False, False, True, True, True]

    def test_rejects_a_zero_length(self) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            rising(arr(1, 2), 0)


class TestWindows:
    def test_highest_and_lowest_include_the_current_bar(self) -> None:
        values = arr(1, 5, 3, 2, 8)
        assert highest(values, 3)[4] == pytest.approx(8.0)
        assert lowest(values, 3)[4] == pytest.approx(2.0)

    def test_shift_moves_values_forward_in_time(self) -> None:
        result = shift(arr(1, 2, 3), 1)
        assert np.isnan(result[0])
        assert result[1] == pytest.approx(1.0)

    def test_shift_cannot_look_into_the_future(self) -> None:
        with pytest.raises(ValueError, match="future"):
            shift(arr(1, 2, 3), -1)

    def test_shift_by_zero_is_the_identity(self) -> None:
        assert np.array_equal(shift(arr(1, 2, 3), 0), arr(1, 2, 3))


class TestAlignment:
    def test_every_primitive_returns_the_input_length(self) -> None:
        values = np.linspace(100, 200, 80)
        for result in (
            sma(values, 20),
            ema(values, 20),
            rsi(values, 14),
            atr(values + 1, values - 1, values, 14),
            stdev(values, 20),
            highest(values, 10),
            lowest(values, 10),
            macd_lines(values)[0],
            bollinger(values, 20)[0],
        ):
            assert result.shape == values.shape
