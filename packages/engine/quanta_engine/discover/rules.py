"""Rule enumeration and pruning (SPEC §3.2, steps 4 and 5).

A rule is one trigger plus up to two filters. The raw count — every subset
of at most three primitives — is what the user is told the search space
*would* be; the valid count is what is actually tested after contradictions
and redundancies are removed. Both are reported because the gap between
them is the honest measure of how much the pruner is doing.

Pruning uses one idea rather than a table of special cases. Every primitive
carries a *subject*: the thing it makes a claim about. Two primitives over
the same subject cannot both be asserted, because they are competing
answers to one question — a series is rising or falling, not both. That
covers contradiction ("above 70" with "below 70") and redundancy ("crosses
above 70" with "above 70") in the same step, since a cross shares its
level's subject.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from dataclasses import dataclass

from quanta_engine.discover.primitives import Primitive

# SPEC §3.2 step 5: every rule is tried long and short over four horizons.
SIDES = 2
HORIZONS = 4

MAX_FILTERS = 2


@dataclass(frozen=True, slots=True)
class Rule:
    """One trigger with the filters that must also hold."""

    trigger: Primitive
    filters: tuple[Primitive, ...] = ()

    @property
    def key(self) -> str:
        # Filters are unordered, so sort them: "A and B" and "B and A" are
        # one rule and must not be tested twice.
        return "+".join([self.trigger.key, *sorted(f.key for f in self.filters)])

    @property
    def label(self) -> str:
        if not self.filters:
            return self.trigger.label
        return f"{self.trigger.label} while {' and '.join(f.label for f in self.filters)}"

    @property
    def sources(self) -> frozenset[str]:
        found = set(self.trigger.sources)
        for item in self.filters:
            found |= item.sources
        return frozenset(found)

    @property
    def indicator_sources(self) -> frozenset[str]:
        """The indicators this rule draws on, price excluded.

        Price is a source but not an indicator: "price above EMA 20 while
        EMA 20 is rising" is one indicator's evidence, read twice.
        """
        found = set(self.trigger.indicator_sources)
        for item in self.filters:
            found |= item.indicator_sources
        return frozenset(found)

    @property
    def size(self) -> int:
        return 1 + len(self.filters)


def count_raw_combinations(primitives: list[Primitive], max_size: int = 3) -> int:
    """Every subset of at most ``max_size`` primitives, pruned or not.

    This is the number the search space would have if nothing were ruled
    out — the figure SPEC §3.2 tabulates as "raw combos".
    """
    total = 0
    n = len(primitives)
    for size in range(1, max_size + 1):
        if size > n:
            break
        combinations = 1
        for i in range(size):
            combinations = combinations * (n - i) // (i + 1)
        total += combinations
    return total


def _compatible(items: tuple[Primitive, ...]) -> bool:
    """False when any two of these compete over the same subject."""
    subjects = [item.subject for item in items]
    return len(set(subjects)) == len(subjects)


def enumerate_rules(
    primitives: list[Primitive],
    *,
    max_filters: int = MAX_FILTERS,
    mix_indicators: bool = False,
) -> Iterator[Rule]:
    """Every valid rule, in a stable order.

    ``mix_indicators`` is SPEC §3.2's "mix at least two indicators": keep
    only rules whose primitives, taken together, draw on more than one
    indicator. Two lines of the same indicator are not a mix however many
    series they are, and neither is price plus a single indicator — the
    option exists to find rules that corroborate one source with another.
    """
    triggers = [item for item in primitives if item.is_trigger]
    filters = [item for item in primitives if not item.is_trigger]

    for trigger in triggers:
        # A filter over the trigger's own subject is either implied by it
        # or contradicts it; either way the rule says nothing new.
        usable = [item for item in filters if item.subject != trigger.subject]

        for count in range(max_filters + 1):
            for chosen in itertools.combinations(usable, count):
                if not _compatible(chosen):
                    continue
                rule = Rule(trigger=trigger, filters=chosen)
                if mix_indicators and len(rule.indicator_sources) < 2:
                    continue
                yield rule


def count_rules(primitives: list[Primitive], *, mix_indicators: bool = False) -> int:
    """How many valid rules there are, without keeping them all."""
    return sum(1 for _ in enumerate_rules(primitives, mix_indicators=mix_indicators))


def count_tests(rule_count: int) -> int:
    """Each rule is tested long and short over four horizons."""
    return rule_count * SIDES * HORIZONS
