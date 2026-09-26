"""Signal compilation, multiplicity correction and the held-out split."""

from __future__ import annotations

import numpy as np
import pytest

from quanta_engine.discover.primitives import Series, Source, build_primitives
from quanta_engine.discover.signals import compile_all, compile_primitive, series_values
from quanta_engine.discover.stats import (
    benjamini_hochberg,
    expected_false_hits,
    forward_returns,
    score,
    split_index,
)

PRICE = Source(key="price", label="Price", is_price=True)
OSC = Source(key="osc", label="Oscillator")


def line(key: str, scale: str, source: Source = OSC) -> Series:
    return Series(key, key.upper(), source, scale)


class TestForwardReturns:
    def test_measures_the_move_after_the_signal(self) -> None:
        close = np.array([100.0, 110.0, 121.0, 121.0])
        assert forward_returns(close, 1)[0] == pytest.approx(10.0)
        assert forward_returns(close, 2)[0] == pytest.approx(21.0)

    def test_leaves_the_unmeasurable_tail_as_nan(self) -> None:
        # A signal on the last bar has no future. Counting it as flat would
        # pull every mean toward zero and flatter a rule that fires late.
        out = forward_returns(np.array([100.0, 101.0, 102.0]), 2)
        assert np.isnan(out[-1]) and np.isnan(out[-2])
        assert np.isfinite(out[0])


class TestSignals:
    def test_warm_up_bars_are_never_true(self) -> None:
        # A primitive satisfied while its indicator is warming hands every
        # rule free signals in the first bars — exactly what a search over
        # hundreds of thousands of rules would seize on.
        values = np.arange(60, dtype=float)
        series = [line("a", "centered_0")]
        data = {"a": values}
        for primitive in build_primitives(series):
            mask = compile_primitive(primitive, data)
            assert not bool(mask[0]), primitive.key

    def test_a_level_cross_fires_once_not_continuously(self) -> None:
        values = np.array([-2.0, -1.0, 1.0, 2.0, 3.0])
        series = [line("a", "centered_0")]
        primitives = {p.key: p for p in build_primitives(series)}
        cross = compile_primitive(primitives["level_cross:a:0.0:above"], {"a": values})
        above = compile_primitive(primitives["level:a:0.0:above"], {"a": values})

        assert int(cross.sum()) == 1
        assert int(above.sum()) == 3
        # The cross is a subset of being above: that is exactly why the
        # enumerator refuses to combine them into one rule.
        assert bool((cross <= above).all())

    def test_position_needs_both_series_finite(self) -> None:
        a = np.array([np.nan, 2.0, 3.0])
        b = np.array([1.0, np.nan, 1.0])
        series = [line("a", "centered_0"), line("b", "centered_0")]
        primitives = {p.key: p for p in build_primitives(series)}
        mask = compile_primitive(primitives["position:a|b:above"], {"a": a, "b": b})
        assert list(mask) == [False, False, True]

    def test_every_primitive_compiles(self) -> None:
        rng = np.random.default_rng(7)
        series = [
            Series("close", "Price", PRICE, "price"),
            Series("ema20", "EMA 20", Source("ema", "EMA"), "price"),
            Series("ema50", "EMA 50", Source("ema", "EMA"), "price"),
            Series("rsi14", "RSI 14", Source("rsi", "RSI"), "bounded_100"),
            line("l1", "centered_0"),
            line("l2", "centered_0"),
            line("l3", "centered_1"),
        ]
        n = 400
        data = {
            "close": 100 + np.cumsum(rng.normal(0, 1, n)),
            "ema20": 100 + np.cumsum(rng.normal(0, 1, n)),
            "ema50": 100 + np.cumsum(rng.normal(0, 1, n)),
            "rsi14": rng.uniform(10, 90, n),
            "l1": rng.normal(0, 1, n),
            "l2": rng.normal(0, 1, n),
            "l3": rng.normal(1, 0.2, n),
        }
        primitives = build_primitives(series)
        masks = compile_all(primitives, series_values(series, data))
        assert len(masks) == len(primitives) == 112
        for key, mask in masks.items():
            assert mask.dtype == np.bool_, key
            assert mask.shape == (n,), key


class TestScore:
    def test_refuses_to_judge_too_few_signals(self) -> None:
        mask = np.zeros(100, dtype=bool)
        mask[:5] = True
        n, _, _, _, p, _ = score(mask, np.full(100, 1.0), side="long", cost_percent=0.0)
        assert n == 5
        assert p == 1.0

    def test_a_short_earns_the_opposite_of_the_move(self) -> None:
        mask = np.ones(50, dtype=bool)
        returns = np.full(50, -2.0)
        _, gross, _, _, _, _ = score(mask, returns, side="short", cost_percent=0.0)
        assert gross == pytest.approx(2.0)

    def test_costs_move_the_mean_and_not_the_test(self) -> None:
        # Whether an edge is distinguishable from noise is a fact about the
        # signal; whether it survives fees is a separate question.
        mask = np.ones(60, dtype=bool)
        returns = np.linspace(0.5, 1.5, 60)
        free = score(mask, returns, side="long", cost_percent=0.0)
        charged = score(mask, returns, side="long", cost_percent=0.13)
        assert charged[1] == pytest.approx(free[1])
        assert charged[2] == pytest.approx(free[2] - 0.13)
        assert charged[4] == pytest.approx(free[4])


class TestBenjaminiHochberg:
    def test_nothing_passes_when_everything_is_noise(self) -> None:
        rng = np.random.default_rng(3)
        passed, _ = benjamini_hochberg(list(rng.uniform(0, 1, 5000)))
        assert sum(passed) == 0

    def test_a_clear_signal_survives_a_crowd_of_noise(self) -> None:
        p_values = [1e-9] + [0.5] * 999
        passed, _ = benjamini_hochberg(p_values)
        assert passed[0] is True
        assert sum(passed) == 1

    def test_is_less_strict_than_bonferroni(self) -> None:
        # Twenty borderline results: Bonferroni at 0.05/20 = 0.0025 would
        # reject all of them; BH is meant to keep the run of small ones.
        p_values = [0.001 * (i + 1) for i in range(20)]
        passed, _ = benjamini_hochberg(p_values)
        assert sum(passed) > 0
        assert sum(passed) >= sum(p <= 0.05 / 20 for p in p_values)

    def test_keeps_the_caller_s_order(self) -> None:
        passed, _ = benjamini_hochberg([0.9, 1e-12, 0.8])
        assert passed == [False, True, False]

    def test_passes_a_contiguous_block_from_the_smallest(self) -> None:
        # BH rejects everything up to the largest qualifying rank, so a
        # bigger p-value can pass on the back of smaller ones.
        p_values = [0.001, 0.002, 0.03, 0.9]
        passed, _ = benjamini_hochberg(p_values)
        assert passed[:3] == [True, True, True]
        assert passed[3] is False

    def test_an_empty_search_passes_nothing(self) -> None:
        assert benjamini_hochberg([]) == ([], 0.0)


class TestExpectedFalseHits:
    def test_is_a_share_of_the_hits_not_of_everything_tested(self) -> None:
        # BH controls the rate among discoveries. Multiplying alpha by the
        # whole search would describe a different procedure and overstate
        # the expected noise by orders of magnitude.
        assert expected_false_hits(tested=500_000, hits=40) == pytest.approx(2.0)

    def test_is_zero_when_nothing_was_found(self) -> None:
        assert expected_false_hits(tested=500_000, hits=0) == 0.0


class TestSplit:
    def test_holds_back_the_last_thirty_percent(self) -> None:
        assert split_index(1000) == 700

    def test_always_leaves_a_bar_on_each_side(self) -> None:
        assert split_index(2) == 1
        assert split_index(3, share=0.99) == 2


class TestOverlappingWindows:
    """A 24-bar return from every bar is not 2,000 independent readings."""

    def test_a_long_horizon_is_judged_on_fewer_effective_signals(self) -> None:
        rng = np.random.default_rng(4)
        mask = np.ones(2400, dtype=bool)
        returns = rng.normal(0.05, 1.0, 2400)

        naive = score(mask, returns, side="long", cost_percent=0.0, horizon=1)
        overlapping = score(mask, returns, side="long", cost_percent=0.0, horizon=24)

        # Same data, same mean — but a 24-bar window shares 23 of its 24
        # bars with its neighbour, so the evidence is far thinner.
        assert overlapping[1] == pytest.approx(naive[1])
        assert abs(overlapping[3]) < abs(naive[3])
        assert overlapping[4] > naive[4]

    def test_the_inflation_is_about_the_square_root_of_the_horizon(self) -> None:
        rng = np.random.default_rng(5)
        mask = np.ones(2400, dtype=bool)
        returns = rng.normal(0.05, 1.0, 2400)

        naive = score(mask, returns, side="long", cost_percent=0.0, horizon=1)
        overlapping = score(mask, returns, side="long", cost_percent=0.0, horizon=16)
        assert abs(naive[3]) / abs(overlapping[3]) == pytest.approx(4.0, rel=0.02)

    def test_a_horizon_that_leaves_too_few_effective_signals_is_refused(self) -> None:
        mask = np.ones(100, dtype=bool)
        returns = np.full(100, 1.0)
        # 100 bars at a 24-bar horizon is four independent readings.
        assert score(mask, returns, side="long", cost_percent=0.0, horizon=24)[4] == 1.0
