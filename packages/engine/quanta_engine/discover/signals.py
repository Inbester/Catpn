"""Compiling primitives into boolean series (SPEC §3.2, step 5).

Every primitive becomes one boolean array the length of the bars, true on
the bars where it holds. Rules then combine them with `and`, which is why
a rule costs almost nothing to evaluate once its primitives are compiled:
half a million tests over one pass of the data is only affordable because
the expensive part — the indicators — is computed once and shared.

Warm-up bars are false, never true-by-default. A primitive that reads as
satisfied while its indicator is still warming would hand every rule free
signals in the first bars of the sample, and those are exactly the bars a
search over hundreds of thousands of rules would seize on.
"""

from __future__ import annotations

import itertools

import numpy as np
from numpy.typing import NDArray

from quanta_engine.discover.primitives import Primitive, PrimitiveKind, Series
from quanta_engine.series import crossover, crossunder, falling, highest, lowest, rising

Array = NDArray[np.float64]
Mask = NDArray[np.bool_]

# How far back an N-bar extreme looks, and the window a divergence compares
# across. Fixed rather than searched: they are part of what a primitive
# means, and sweeping them would multiply the search space by their range
# without saying anything new about the market.
EXTREME_LOOKBACK = 20
DIVERGENCE_LOOKBACK = 20
# A spread is converging or diverging relative to its own recent width, so
# that "the gap is closing" does not depend on the units of the series.
SPREAD_LOOKBACK = 5


def _finite(values: Array) -> Mask:
    return np.isfinite(values)


def _both(values: Array, other: Array) -> Mask:
    return _finite(values) & _finite(other)


def compile_primitive(primitive: Primitive, data: dict[str, Array]) -> Mask:
    """The bars on which this primitive holds."""
    kind = primitive.kind
    first = data[primitive.series[0].key]

    if kind is PrimitiveKind.SLOPE:
        mask = rising(first) if primitive.direction == "rising" else falling(first)
        return mask & _finite(first)

    if kind is PrimitiveKind.TURN:
        # A turn is the bar the slope changes sign, so it needs the two
        # bars before it as well as this one.
        up = falling(np.roll(first, 1)) & rising(first)
        down = rising(np.roll(first, 1)) & falling(first)
        mask = up if primitive.direction == "up" else down
        mask[:3] = False
        return mask & _finite(first)

    if kind is PrimitiveKind.EXTREME:
        if primitive.direction == "high":
            reference = highest(first, EXTREME_LOOKBACK)
            mask = first >= reference
        else:
            reference = lowest(first, EXTREME_LOOKBACK)
            mask = first <= reference
        return mask & _both(first, reference)

    if kind is PrimitiveKind.LEVEL:
        threshold = float(primitive.level or 0.0)
        mask = first > threshold if primitive.direction == "above" else first < threshold
        return mask & _finite(first)

    if kind is PrimitiveKind.LEVEL_CROSS:
        # crossover compares two series, so the level becomes a flat one.
        level: Array = np.full(first.shape, float(primitive.level or 0.0))
        mask = (
            crossover(first, level) if primitive.direction == "above" else crossunder(first, level)
        )
        return mask & _finite(first)

    second = data[primitive.series[1].key] if len(primitive.series) > 1 else None

    if kind is PrimitiveKind.POSITION and second is not None:
        mask = first > second if primitive.direction == "above" else first < second
        return mask & _both(first, second)

    if kind is PrimitiveKind.PAIR_CROSS and second is not None:
        mask = (
            crossover(first, second)
            if primitive.direction == "above"
            else crossunder(first, second)
        )
        return mask & _both(first, second)

    if kind is PrimitiveKind.SPREAD and second is not None:
        gap = np.abs(first - second)
        before = np.roll(gap, SPREAD_LOOKBACK)
        mask = gap < before if primitive.direction == "converging" else gap > before
        mask[:SPREAD_LOOKBACK] = False
        return mask & _both(first, second)

    if kind is PrimitiveKind.STACK:
        values = [data[line.key] for line in primitive.series]
        mask = np.ones(first.shape, dtype=bool)
        for upper, lower in itertools.pairwise(values):
            mask &= upper > lower
        for line in values:
            mask &= _finite(line)
        return mask

    if kind is PrimitiveKind.DIVERGENCE and second is not None:
        return _divergence(first, second, primitive.direction)

    raise ValueError(f"no compiler for {primitive.key}")


def _divergence(price: Array, other: Array, direction: str) -> Mask:
    """Price and an oscillator disagreeing about a new extreme.

    Regular: price makes a new extreme the oscillator does not confirm —
    read as exhaustion. Hidden: the oscillator makes the extreme and price
    does not — read as continuation. Both are compared over the same
    window so the two are mirror images rather than different tests.
    """
    kind, way = direction.split("_")
    n = DIVERGENCE_LOOKBACK

    price_prev_high = np.roll(highest(price, n), 1)
    price_prev_low = np.roll(lowest(price, n), 1)
    other_prev_high = np.roll(highest(other, n), 1)
    other_prev_low = np.roll(lowest(other, n), 1)

    if way == "bearish":
        price_higher = price > price_prev_high
        other_higher = other > other_prev_high
        mask = (
            (price_higher & ~other_higher) if kind == "regular" else (~price_higher & other_higher)
        )
    else:
        price_lower = price < price_prev_low
        other_lower = other < other_prev_low
        mask = (price_lower & ~other_lower) if kind == "regular" else (~price_lower & other_lower)

    # Outside a fresh extreme on one side or the other there is no
    # disagreement to read, so hidden divergence needs the same trigger.
    if kind == "hidden":
        mask &= (other > other_prev_high) if way == "bearish" else (other < other_prev_low)

    mask[: n + 1] = False
    return mask & _both(price, other) & _both(price_prev_high, other_prev_high)


def compile_all(primitives: list[Primitive], data: dict[str, Array]) -> dict[str, Mask]:
    """Compile every primitive once, keyed for the rule evaluator."""
    return {item.key: compile_primitive(item, data) for item in primitives}


def series_values(series: list[Series], data: dict[str, Array]) -> dict[str, Array]:
    """Check that every series has data, and that the lengths agree."""
    missing = [line.key for line in series if line.key not in data]
    if missing:
        raise KeyError(f"no data for {', '.join(missing)}")

    lengths = {len(data[line.key]) for line in series}
    if len(lengths) > 1:
        raise ValueError(f"series have different lengths: {sorted(lengths)}")
    return {line.key: data[line.key] for line in series}
