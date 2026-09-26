"""Scale detection and primitive generation (SPEC §3.2, step 2 and 3).

A primitive is one testable statement about the series on the chart —
"RSI crossed above 70", "EMA20 is above EMA50", "L1 is rising". Rules are
built from these, so the set of primitives fixes everything downstream:
the reference counts in SPEC §3.2 are counts of this function's output.

Two kinds exist and the distinction matters for every later step:

*Triggers* say something happened on this bar. They can open a trade.
*Filters* say something is true on this bar. They can only permit one.

A rule is exactly one trigger plus up to two filters, because a rule with
no trigger has no entry moment and a rule with two triggers is really two
rules that happened to fire together.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

# The scales a series can live on. Detection picks one of these, and only
# series on the same scale may be compared to each other: "RSI above EMA20"
# is a number the chart can compute and nobody can interpret.
ScaleName = Literal["price", "bounded_100", "centered_0", "centered_1"]

# The levels that mean something on each scale. A price-like series has
# none: there is no number that is "high" for BTC the way 70 is high for
# RSI. SPEC §3.2 fixes 30/50/70 for the bounded scale.
SCALE_LEVELS: dict[ScaleName, tuple[float, ...]] = {
    "price": (),
    "bounded_100": (30.0, 50.0, 70.0),
    "centered_0": (0.0,),
    "centered_1": (1.0,),
}


class PrimitiveKind(Enum):
    """What a primitive says, and whether it can open a trade."""

    SLOPE = ("slope", False)
    TURN = ("turn", True)
    EXTREME = ("extreme", True)
    LEVEL = ("level", False)
    LEVEL_CROSS = ("level_cross", True)
    POSITION = ("position", False)
    PAIR_CROSS = ("pair_cross", True)
    SPREAD = ("spread", False)
    STACK = ("stack", False)
    DIVERGENCE = ("divergence", True)

    def __init__(self, label: str, is_trigger: bool) -> None:
        self.label = label
        self.is_trigger = is_trigger


@dataclass(frozen=True, slots=True)
class Source:
    """One chip the user added: a price source or an indicator.

    A source can publish several series — an indicator with three lines is
    one source. The "mix at least two indicators" option counts sources,
    not series, so a rule relating two lines of the same indicator is not a
    cross-indicator rule however many series it touches.
    """

    key: str
    label: str
    is_price: bool = False


@dataclass(frozen=True, slots=True)
class Series:
    """One line, belonging to a source and living on one scale."""

    key: str
    label: str
    source: Source
    scale: ScaleName

    @property
    def levels(self) -> tuple[float, ...]:
        return SCALE_LEVELS[self.scale]


@dataclass(frozen=True, slots=True)
class ScaleGroup:
    """The series sharing one scale, in the order they were added."""

    scale: ScaleName
    members: tuple[Series, ...]


@dataclass(frozen=True, slots=True)
class Primitive:
    """One statement, with everything needed to prune and evaluate it."""

    key: str
    kind: PrimitiveKind
    label: str
    # The series this statement is about, in the order it names them.
    series: tuple[Series, ...]
    direction: str = ""
    level: float | None = None
    # Two primitives of the same kind over the same subject are mutually
    # exclusive: a series cannot be both rising and falling. Sharing a
    # subject is how the pruner finds them without a table of special cases.
    subject: str = ""
    sources: frozenset[str] = field(default_factory=frozenset)
    # The sources that are indicators. Price is a source but not an
    # indicator, so a rule pairing price with one indicator mixes one
    # indicator, not two.
    indicator_sources: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_trigger(self) -> bool:
        return self.kind.is_trigger


def group_by_scale(series: list[Series]) -> list[ScaleGroup]:
    """The scale groups present, in the order their first member appears."""
    order: list[ScaleName] = []
    members: dict[ScaleName, list[Series]] = {}
    for line in series:
        if line.scale not in members:
            members[line.scale] = []
            order.append(line.scale)
        members[line.scale].append(line)
    return [ScaleGroup(scale, tuple(members[scale])) for scale in order]


def _sources(*series: Series) -> frozenset[str]:
    return frozenset(line.source.key for line in series)


def _indicators(*series: Series) -> frozenset[str]:
    return frozenset(line.source.key for line in series if not line.source.is_price)


def build_primitives(series: list[Series]) -> list[Primitive]:
    """Every primitive the given series support (SPEC §3.2, step 3).

    The order is fixed — per-series, then per-pair, then per-group, then
    divergence — so a rule's identity does not depend on dictionary order
    between runs.
    """
    out: list[Primitive] = []
    groups = group_by_scale(series)

    # --- per series -----------------------------------------------------
    for line in series:
        subject = f"slope:{line.key}"
        for direction in ("rising", "falling"):
            out.append(
                Primitive(
                    key=f"slope:{line.key}:{direction}",
                    kind=PrimitiveKind.SLOPE,
                    label=f"{line.label} {direction}",
                    series=(line,),
                    direction=direction,
                    subject=subject,
                    sources=_sources(line),
                    indicator_sources=_indicators(line),
                )
            )

        # A turn shares the slope's subject: "turns up" is a statement
        # about the slope, so pairing it with "rising" repeats itself and
        # pairing it with "falling" contradicts it.
        for direction in ("up", "down"):
            out.append(
                Primitive(
                    key=f"turn:{line.key}:{direction}",
                    kind=PrimitiveKind.TURN,
                    label=f"{line.label} turns {direction}",
                    series=(line,),
                    direction=direction,
                    subject=subject,
                    sources=_sources(line),
                    indicator_sources=_indicators(line),
                )
            )

        subject = f"extreme:{line.key}"
        for direction in ("high", "low"):
            out.append(
                Primitive(
                    key=f"extreme:{line.key}:{direction}",
                    kind=PrimitiveKind.EXTREME,
                    label=f"{line.label} N-bar {direction}",
                    series=(line,),
                    direction=direction,
                    subject=subject,
                    sources=_sources(line),
                    indicator_sources=_indicators(line),
                )
            )

        for level in line.levels:
            subject = f"level:{line.key}:{level}"
            for direction in ("above", "below"):
                out.append(
                    Primitive(
                        key=f"level:{line.key}:{level}:{direction}",
                        kind=PrimitiveKind.LEVEL,
                        label=f"{line.label} {direction} {level:g}",
                        series=(line,),
                        direction=direction,
                        level=level,
                        subject=subject,
                        sources=_sources(line),
                        indicator_sources=_indicators(line),
                    )
                )
            for direction in ("above", "below"):
                out.append(
                    Primitive(
                        key=f"level_cross:{line.key}:{level}:{direction}",
                        kind=PrimitiveKind.LEVEL_CROSS,
                        label=f"{line.label} crosses {direction} {level:g}",
                        series=(line,),
                        direction=direction,
                        level=level,
                        # Shares the level's subject: "crosses above 70"
                        # implies "above 70", so the two must never be
                        # combined into one rule.
                        subject=subject,
                        sources=_sources(line),
                        indicator_sources=_indicators(line),
                    )
                )

    # --- per same-scale pair --------------------------------------------
    for group in groups:
        for left, right in itertools.combinations(group.members, 2):
            pair = f"{left.key}|{right.key}"

            subject = f"position:{pair}"
            for direction in ("above", "below"):
                out.append(
                    Primitive(
                        key=f"position:{pair}:{direction}",
                        kind=PrimitiveKind.POSITION,
                        label=f"{left.label} {direction} {right.label}",
                        series=(left, right),
                        direction=direction,
                        subject=subject,
                        sources=_sources(left, right),
                        indicator_sources=_indicators(left, right),
                    )
                )
            for direction in ("above", "below"):
                out.append(
                    Primitive(
                        key=f"pair_cross:{pair}:{direction}",
                        kind=PrimitiveKind.PAIR_CROSS,
                        label=f"{left.label} crosses {direction} {right.label}",
                        series=(left, right),
                        direction=direction,
                        subject=subject,
                        sources=_sources(left, right),
                        indicator_sources=_indicators(left, right),
                    )
                )

            subject = f"spread:{pair}"
            for direction in ("converging", "diverging"):
                out.append(
                    Primitive(
                        key=f"spread:{pair}:{direction}",
                        kind=PrimitiveKind.SPREAD,
                        label=f"{left.label}/{right.label} spread {direction}",
                        series=(left, right),
                        direction=direction,
                        subject=subject,
                        sources=_sources(left, right),
                        indicator_sources=_indicators(left, right),
                    )
                )

    # --- three or more on one scale: stack order ------------------------
    for group in groups:
        if len(group.members) < 3:
            continue
        subject = f"stack:{group.scale}"
        for order in itertools.permutations(group.members):
            names = ">".join(line.key for line in order)
            out.append(
                Primitive(
                    key=f"stack:{names}",
                    kind=PrimitiveKind.STACK,
                    label=" > ".join(line.label for line in order),
                    series=order,
                    # Every ordering of a group excludes every other, so
                    # they all share one subject.
                    subject=subject,
                    sources=_sources(*order),
                    indicator_sources=_indicators(*order),
                )
            )

    # --- price versus each series on another scale ----------------------
    # Divergence between price and a series that tracks price — an EMA of
    # it — is not a finding, so only series on a different scale qualify.
    price_series = [line for line in series if line.source.is_price]
    for price in price_series:
        for line in series:
            if line.scale == price.scale:
                continue
            pair = f"{price.key}|{line.key}"
            for kind in ("regular", "hidden"):
                for direction in ("bullish", "bearish"):
                    out.append(
                        Primitive(
                            key=f"divergence:{pair}:{kind}:{direction}",
                            kind=PrimitiveKind.DIVERGENCE,
                            label=f"{kind} {direction} divergence, {price.label} vs {line.label}",
                            series=(price, line),
                            direction=f"{kind}_{direction}",
                            subject=f"divergence:{pair}:{kind}:{direction}",
                            sources=_sources(price, line),
                            indicator_sources=_indicators(price, line),
                        )
                    )

    return out
