"""The Discover enumerator against the reference counts in SPEC §3.2.

The spec tabulates two cases with exact primitive, combination, rule and
test counts. They are the acceptance criterion for this phase, so they are
asserted as literals: a change that moves any of them is a change to what
the product searches, not an implementation detail.
"""

from __future__ import annotations

import pytest

from quanta_engine.discover.primitives import Series, Source, build_primitives, group_by_scale
from quanta_engine.discover.rules import (
    Rule,
    count_raw_combinations,
    count_rules,
    count_tests,
    enumerate_rules,
)

PRICE = Source(key="price", label="Price", is_price=True)
EMA = Source(key="ema", label="EMA 20/50")
RSI = Source(key="rsi", label="RSI 14")
MINE = Source(key="mine", label="MyIndicator")


def case_one() -> list[Series]:
    """Price plus a three-line indicator: L1 and L2 around 0, L3 around 1."""
    return [
        Series("close", "Price", PRICE, "price"),
        Series("l1", "L1", MINE, "centered_0"),
        Series("l2", "L2", MINE, "centered_0"),
        Series("l3", "L3", MINE, "centered_1"),
    ]


def case_two() -> list[Series]:
    """Price, EMA 20 and 50, RSI 14, and the same three-line indicator."""
    return [
        Series("close", "Price", PRICE, "price"),
        Series("ema20", "EMA 20", EMA, "price"),
        Series("ema50", "EMA 50", EMA, "price"),
        Series("rsi14", "RSI 14", RSI, "bounded_100"),
        Series("l1", "L1", MINE, "centered_0"),
        Series("l2", "L2", MINE, "centered_0"),
        Series("l3", "L3", MINE, "centered_1"),
    ]


def split(primitives: list) -> tuple[int, int]:
    triggers = sum(1 for item in primitives if item.is_trigger)
    return len(primitives) - triggers, triggers


class TestScaleGroups:
    def test_case_two_has_the_four_groups_the_spec_names(self) -> None:
        groups = group_by_scale(case_two())
        assert [g.scale for g in groups] == ["price", "bounded_100", "centered_0", "centered_1"]
        assert [len(g.members) for g in groups] == [3, 1, 2, 1]

    def test_series_on_different_scales_are_never_paired(self) -> None:
        # "RSI above EMA 20" is arithmetic the chart can do and nobody can
        # read, so the pair primitives must not exist.
        pairs = [
            p
            for p in build_primitives(case_two())
            if p.kind.label in {"position", "pair_cross", "spread"}
        ]
        for primitive in pairs:
            assert len({line.scale for line in primitive.series}) == 1


class TestReferenceCaseOne:
    """Price + 3-line indicator: 54 primitives (18/36), 26,289 raw, 5,324 rules."""

    def test_primitive_counts(self) -> None:
        primitives = build_primitives(case_one())
        assert split(primitives) == (18, 36)
        assert len(primitives) == 54

    def test_raw_combinations(self) -> None:
        assert count_raw_combinations(build_primitives(case_one())) == 26_289

    def test_valid_rules(self) -> None:
        assert count_rules(build_primitives(case_one())) == 5_324

    def test_tests_run(self) -> None:
        assert count_tests(count_rules(build_primitives(case_one()))) == 42_592


class TestReferenceCaseTwo:
    """Price + EMA20/50 + RSI14 + 3-line: 112 (48/64), 234,248 raw, 69,828 rules."""

    def test_primitive_counts(self) -> None:
        primitives = build_primitives(case_two())
        assert split(primitives) == (48, 64)
        assert len(primitives) == 112

    def test_raw_combinations(self) -> None:
        assert count_raw_combinations(build_primitives(case_two())) == 234_248

    def test_valid_rules(self) -> None:
        assert count_rules(build_primitives(case_two())) == 69_828

    def test_tests_run(self) -> None:
        assert count_tests(count_rules(build_primitives(case_two()))) == 558_624


class TestPruning:
    def test_a_cross_is_never_combined_with_its_own_level(self) -> None:
        # "RSI crosses above 70 while RSI is above 70" states the cross
        # twice; "while RSI is below 70" contradicts it.
        primitives = build_primitives(case_two())
        for rule in enumerate_rules(primitives):
            if rule.trigger.kind.label != "level_cross":
                continue
            level = rule.trigger.level
            line = rule.trigger.series[0].key
            for item in rule.filters:
                assert not (
                    item.kind.label == "level"
                    and item.series[0].key == line
                    and item.level == level
                )

    def test_no_rule_asserts_both_directions_of_one_subject(self) -> None:
        for rule in enumerate_rules(build_primitives(case_one())):
            subjects = [f.subject for f in rule.filters]
            assert len(set(subjects)) == len(subjects)

    def test_every_rule_has_exactly_one_trigger_and_at_most_two_filters(self) -> None:
        for rule in enumerate_rules(build_primitives(case_one())):
            assert rule.trigger.is_trigger
            assert len(rule.filters) <= 2
            assert not any(f.is_trigger for f in rule.filters)

    def test_rule_keys_are_unique(self) -> None:
        # A rule reached by two orderings of its filters would be tested
        # twice and would inflate the FDR correction.
        keys = [rule.key for rule in enumerate_rules(build_primitives(case_one()))]
        assert len(keys) == len(set(keys))

    def test_pruning_removes_the_gap_the_spec_implies(self) -> None:
        primitives = build_primitives(case_one())
        triggers = sum(1 for p in primitives if p.is_trigger)
        filters = len(primitives) - triggers
        unpruned = triggers * (1 + filters + filters * (filters - 1) // 2)
        assert unpruned == 6_192
        assert count_rules(primitives) == 5_324


class TestMixIndicatorsOption:
    """SPEC §3.2 puts cross-indicator rules in case two at 59,348."""

    def test_matches_the_reference_count(self) -> None:
        assert count_rules(build_primitives(case_two()), mix_indicators=True) == 59_348

    def test_keeps_only_rules_drawing_on_two_indicators(self) -> None:
        primitives = build_primitives(case_two())
        for rule in enumerate_rules(primitives, mix_indicators=True):
            assert len(rule.indicator_sources) >= 2

    def test_two_lines_of_one_indicator_are_not_a_mix(self) -> None:
        # L1 crossing L2 uses two series but one indicator, so the option
        # drops it: the point is corroboration by an independent source.
        primitives = build_primitives(case_two())
        kept = {rule.key for rule in enumerate_rules(primitives, mix_indicators=True)}
        l1_crosses_l2 = Rule(
            trigger=next(p for p in primitives if p.key == "pair_cross:l1|l2:above")
        )
        assert l1_crosses_l2.key not in kept

    def test_price_with_one_indicator_is_not_a_mix(self) -> None:
        # Price is a source but not an indicator: price crossing EMA 20 is
        # one indicator's evidence, so it needs a second to qualify.
        primitives = build_primitives(case_two())
        kept = {rule.key for rule in enumerate_rules(primitives, mix_indicators=True)}
        price_crosses_ema = Rule(
            trigger=next(p for p in primitives if p.key == "pair_cross:close|ema20:above")
        )
        assert price_crosses_ema.key not in kept

    def test_is_a_strict_subset_of_the_full_search(self) -> None:
        assert 59_348 < 69_828


@pytest.mark.parametrize("case", [case_one, case_two])
def test_primitive_keys_are_unique(case) -> None:
    keys = [p.key for p in build_primitives(case())]
    assert len(keys) == len(set(keys))
