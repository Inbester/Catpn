"""The search against noise and against a planted edge.

A rule search over a price history will always turn up rules that look
profitable. The question this file settles is whether the multiplicity
correction stops them being reported, and whether a real relationship
still gets through it.
"""

from __future__ import annotations

import numpy as np
import pytest

from quanta_engine.discover.primitives import Series, Source
from quanta_engine.discover.search import SearchConfig, run_search

PRICE = Source(key="price", label="Price", is_price=True)
OSC = Source(key="osc", label="Oscillator")


def small_series() -> list[Series]:
    """Price plus a two-line oscillator: enough rules to need correcting."""
    return [
        Series("close", "Price", PRICE, "price"),
        Series("o1", "O1", OSC, "centered_0"),
        Series("o2", "O2", OSC, "centered_0"),
    ]


def random_walk(n: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return 100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))


class TestNoise:
    def test_a_search_over_noise_reports_almost_nothing(self) -> None:
        """The whole point of the correction.

        Price and the oscillators are independent random walks, so every
        rule here is worthless. Thousands of tests at an uncorrected 5%
        would hand back hundreds of "findings".
        """
        rng = np.random.default_rng(11)
        n = 1500
        close = random_walk(n, seed=5)
        data = {
            "close": close,
            "o1": rng.normal(0, 1, n),
            "o2": rng.normal(0, 1, n),
        }

        result = run_search(small_series(), data, close, config=SearchConfig(cost_percent=0.0))

        assert result.tested > 5_000
        # A few can still slip through — that is what "5% of findings"
        # means — but not the hundreds an uncorrected search would give.
        assert len(result.hits) <= result.tested * 0.002, (
            f"{len(result.hits)} hits out of {result.tested} tests looks like noise leaking through"
        )

    def test_the_uncorrected_search_would_have_reported_many(self) -> None:
        """Shows the correction is doing work, not that the data is easy."""
        rng = np.random.default_rng(11)
        n = 1500
        close = random_walk(n, seed=5)
        data = {"close": close, "o1": rng.normal(0, 1, n), "o2": rng.normal(0, 1, n)}

        result = run_search(small_series(), data, close, config=SearchConfig(cost_percent=0.0))

        # Taking p <= 0.05 at face value over this many tests hands back
        # hundreds of findings from data with nothing in it.
        assert result.significant_uncorrected > 100
        assert len(result.hits) < result.significant_uncorrected / 10


class TestPlantedEdge:
    def test_finds_a_relationship_that_is_really_there(self) -> None:
        """o1 crossing zero genuinely precedes a rise, by construction."""
        rng = np.random.default_rng(23)
        n = 3000
        o1 = rng.normal(0, 1, n)

        steps = rng.normal(0, 0.004, n)
        crossed = np.zeros(n, dtype=bool)
        crossed[1:] = (o1[:-1] <= 0) & (o1[1:] > 0)
        # Every cross is followed by four bars of drift the noise cannot
        # explain away.
        for index in np.flatnonzero(crossed):
            steps[index + 1 : index + 5] += 0.010

        close = 100.0 * np.exp(np.cumsum(steps))
        data = {"close": close, "o1": o1, "o2": rng.normal(0, 1, n)}

        result = run_search(small_series(), data, close, config=SearchConfig(cost_percent=0.0))

        assert result.hits, "the planted edge was corrected away"
        keys = {hit.rule_key for hit in result.hits}
        assert any("level_cross:o1:0.0:above" in key for key in keys)

        best = result.hits[0]
        assert best.side == "long"
        assert best.mean_return_percent > 0

    def test_the_held_out_stretch_is_scored_separately(self) -> None:
        rng = np.random.default_rng(23)
        n = 3000
        o1 = rng.normal(0, 1, n)
        steps = rng.normal(0, 0.004, n)
        crossed = np.zeros(n, dtype=bool)
        crossed[1:] = (o1[:-1] <= 0) & (o1[1:] > 0)
        for index in np.flatnonzero(crossed):
            steps[index + 1 : index + 5] += 0.010
        close = 100.0 * np.exp(np.cumsum(steps))
        data = {"close": close, "o1": o1, "o2": rng.normal(0, 1, n)}

        result = run_search(small_series(), data, close, config=SearchConfig(cost_percent=0.0))

        assert result.in_sample_bars == 2100
        assert result.out_of_sample_bars == 900
        # A planted edge is in the held-out stretch too, so it should show
        # there as well — and the count of signals must be its own.
        best = result.hits[0]
        assert best.out_of_sample_signals > 0
        assert best.out_of_sample_mean_percent > 0


class TestCosts:
    def test_costs_are_charged_to_the_reported_net(self) -> None:
        rng = np.random.default_rng(23)
        n = 3000
        o1 = rng.normal(0, 1, n)
        steps = rng.normal(0, 0.004, n)
        crossed = np.zeros(n, dtype=bool)
        crossed[1:] = (o1[:-1] <= 0) & (o1[1:] > 0)
        for index in np.flatnonzero(crossed):
            steps[index + 1 : index + 5] += 0.010
        close = 100.0 * np.exp(np.cumsum(steps))
        data = {"close": close, "o1": o1, "o2": rng.normal(0, 1, n)}

        free = run_search(small_series(), data, close, config=SearchConfig(cost_percent=0.0))
        charged = run_search(small_series(), data, close, config=SearchConfig(cost_percent=0.13))

        # The same rules are found either way — costs do not change whether
        # a signal is distinguishable from noise — but the net is lower.
        assert len(free.hits) == len(charged.hits)
        assert charged.hits[0].mean_net_percent == pytest.approx(
            free.hits[0].mean_net_percent - 0.13
        )


class TestReporting:
    def test_expected_false_hits_is_reported_with_the_count(self) -> None:
        rng = np.random.default_rng(11)
        n = 1500
        close = random_walk(n, seed=5)
        data = {"close": close, "o1": rng.normal(0, 1, n), "o2": rng.normal(0, 1, n)}
        result = run_search(small_series(), data, close)
        assert result.expected_false_hits == pytest.approx(0.05 * len(result.hits))
