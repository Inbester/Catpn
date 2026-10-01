"""Choosing indicators for a search, and combining them (SPEC §3.2)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from quanta_engine.discover.catalog import (
    CATALOG,
    MAX_INDICATORS,
    CatalogError,
    Choice,
    build,
    cci,
    describe,
    roc,
    stochastic,
)
from quanta_engine.discover.primitives import PrimitiveKind, build_primitives
from quanta_engine.discover.rules import count_rules, enumerate_rules


@dataclass
class Bars:
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray


def make_bars(n: int = 400, seed: int = 3) -> Bars:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    spread = np.abs(rng.normal(0, 0.5, n)) + 0.1
    return Bars(
        high=close + spread,
        low=close - spread,
        close=close,
        volume=rng.uniform(10, 100, n),
    )


BARS = make_bars()


def scales(choices: list[Choice]) -> dict[str, str]:
    return {s.key: s.scale for s in build(choices, BARS).series}


class TestChoosing:
    def test_price_is_always_there_and_first(self) -> None:
        built = build([], BARS)
        assert [s.key for s in built.series] == ["close"]
        assert built.series[0].source.is_price

    def test_the_same_indicator_can_be_added_twice_with_different_settings(self) -> None:
        built = build(
            [Choice("i1", "ema", {"length": 9}), Choice("i2", "ema", {"length": 21})], BARS
        )
        assert built.labels == {"i1": "EMA 9", "i2": "EMA 21"}
        crosses = [
            p.label for p in build_primitives(built.series) if p.kind is PrimitiveKind.PAIR_CROSS
        ]
        assert "EMA 9 crosses above EMA 21" in crosses

    def test_defaults_fill_in_missing_settings(self) -> None:
        built = build([Choice("i1", "macd")], BARS)
        assert built.labels["i1"] == "MACD 12/26/9"
        assert {"i1.macd", "i1.signal"} <= set(built.data)

    def test_every_catalog_entry_builds_on_real_bars(self) -> None:
        # One of each, fed close or the bars: nothing in the catalog may be
        # all-NaN on 400 ordinary bars.
        ids = list(CATALOG)
        for start in range(0, len(ids), MAX_INDICATORS):
            batch = ids[start : start + MAX_INDICATORS]
            built = build([Choice(f"i{n}", key) for n, key in enumerate(batch)], BARS)
            for series in built.series:
                assert np.isfinite(built.data[series.key]).sum() > 100, series.key

    def test_the_catalog_describes_itself_for_the_picker(self) -> None:
        rows = {row["id"]: row for row in describe()}
        assert rows["rsi"]["params"] == [
            {
                "name": "length",
                "label": "Length",
                "default": 14,
                "min": 2,
                "max": 100,
                "integer": True,
            }
        ]
        assert rows["stoch"]["takes_input"] is False


class TestRefusals:
    @pytest.mark.parametrize(
        ("choice", "message"),
        [
            (Choice("i1", "nope"), "no indicator called"),
            (Choice("i1", "ema", {"length": 1}), "between 2 and 500"),
            (Choice("i1", "ema", {"length": 9.5}), "whole number"),
            (Choice("i1", "ema", {"speed": 3}), "no setting called"),
            (Choice("i1", "macd", {"fast": 30, "slow": 26}), "shorter than Slow"),
            (Choice("i1", "rsi", input="i9.rsi"), "not price or an indicator listed above"),
            (Choice("i1", "atr", input="close.x"), "takes no input"),
            (Choice("I-1", "ema"), "not a usable indicator key"),
        ],
    )
    def test_a_bad_choice_is_named(self, choice: Choice, message: str) -> None:
        with pytest.raises(CatalogError, match=message):
            build([choice], BARS)

    def test_an_input_must_come_from_an_indicator_listed_before_it(self) -> None:
        # Order is what rules out a loop: nothing can feed what fed it.
        with pytest.raises(CatalogError, match="listed above"):
            build([Choice("i1", "ema", input="i2.rsi"), Choice("i2", "rsi")], BARS)

    def test_a_key_may_be_used_once(self) -> None:
        with pytest.raises(CatalogError, match="used twice"):
            build([Choice("i1", "ema"), Choice("i1", "rsi")], BARS)

    def test_there_is_a_cap_on_how_many(self) -> None:
        choices = [Choice(f"i{n}", "ema", {"length": 5 + n}) for n in range(MAX_INDICATORS + 1)]
        with pytest.raises(CatalogError, match=f"at most {MAX_INDICATORS}"):
            build(choices, BARS)


class TestCombining:
    def test_an_ema_of_rsi_lives_on_the_rsi_scale(self) -> None:
        # So "RSI crosses its own EMA" is searched, and "EMA of RSI above
        # the price" — a comparison of different units — never is.
        choices = [Choice("i1", "rsi"), Choice("i2", "ema", {"length": 9}, input="i1.rsi")]
        built = build(choices, BARS)
        assert scales(choices)["i2.ema"] == "bounded_100"
        assert built.labels["i2"] == "EMA 9 of RSI 14"

        primitives = build_primitives(built.series)
        labels = {p.label for p in primitives}
        assert "RSI 14 crosses above EMA 9 of RSI 14" in labels
        assert not any(
            "Price" in p.label and "EMA 9 of RSI" in p.label
            for p in primitives
            if p.kind is PrimitiveKind.POSITION
        )

    def test_an_oscillator_keeps_its_own_scale_whatever_it_is_fed(self) -> None:
        choices = [Choice("i1", "volume"), Choice("i2", "rsi", input="i1.volume")]
        assert scales(choices)["i2.rsi"] == "bounded_100"

    def test_an_sma_of_volume_can_be_compared_with_volume(self) -> None:
        # The usual volume-spike rule, which needs both on one scale.
        choices = [Choice("i1", "volume"), Choice("i2", "sma", {"length": 20}, input="i1.volume")]
        labels = {p.label for p in build_primitives(build(choices, BARS).series)}
        assert "Volume crosses above SMA 20 of Volume" in labels

    def test_an_indicator_of_an_indicator_is_computed_after_its_warm_up(self) -> None:
        # The recursive averages seed from their first window; a leading NaN
        # there would make every later value NaN.
        built = build(
            [Choice("i1", "rsi"), Choice("i2", "ema", {"length": 9}, input="i1.rsi")], BARS
        )
        values = built.data["i2.ema"]
        assert np.isnan(values[:10]).all()
        assert np.isfinite(values[30:]).all()

    def test_divergence_is_offered_for_oscillators_only(self) -> None:
        built = build([Choice("i1", "rsi"), Choice("i2", "atr"), Choice("i3", "volume")], BARS)
        diverging = {
            p.series[1].key
            for p in build_primitives(built.series)
            if p.kind is PrimitiveKind.DIVERGENCE
        }
        assert diverging == {"i1.rsi"}

    def test_required_indicators_appear_in_every_rule(self) -> None:
        built = build([Choice("i1", "rsi"), Choice("i2", "macd"), Choice("i3", "ema")], BARS)
        primitives = build_primitives(built.series)
        required = frozenset({"i1", "i2"})
        rules = list(enumerate_rules(primitives, require=required))
        assert rules
        assert all(required <= rule.sources for rule in rules)
        assert len(rules) < count_rules(primitives)

    def test_fewer_conditions_per_rule_means_fewer_rules(self) -> None:
        primitives = build_primitives(build([Choice("i1", "rsi")], BARS).series)
        one = count_rules(primitives, max_filters=0)
        three = count_rules(primitives, max_filters=2)
        assert 0 < one < three
        assert one == sum(1 for p in primitives if p.is_trigger)

    def test_counting_can_stop_early(self) -> None:
        primitives = build_primitives(
            build([Choice("i1", "rsi"), Choice("i2", "macd")], BARS).series
        )
        assert count_rules(primitives, limit=10) == 11


class TestFormulas:
    def test_stochastic_stays_between_0_and_100(self) -> None:
        k, d = stochastic(BARS.high, BARS.low, BARS.close, 14, 3, 3)
        for line in (k, d):
            finite = line[np.isfinite(line)]
            assert finite.size and finite.min() >= 0 and finite.max() <= 100

    def test_stochastic_reads_100_at_the_top_of_the_range(self) -> None:
        high = np.array([1.0, 2.0, 3.0, 4.0])
        low = np.array([0.0, 1.0, 2.0, 3.0])
        close = high.copy()
        k, _ = stochastic(high, low, close, 2, 1, 1)
        assert k[-1] == pytest.approx(100.0)

    def test_cci_by_hand(self) -> None:
        high = np.array([3.0, 4.0, 5.0])
        low = np.array([1.0, 2.0, 3.0])
        close = np.array([2.0, 3.0, 4.0])
        # Typical prices 2, 3, 4: mean 3, mean deviation 2/3, last is 4.
        assert cci(high, low, close, 3)[-1] == pytest.approx((4 - 3) / (0.015 * (2 / 3)))

    def test_roc_is_percent_change(self) -> None:
        values = np.array([100.0, 101.0, 110.0])
        out = roc(values, 2)
        assert np.isnan(out[:2]).all()
        assert out[2] == pytest.approx(10.0)
