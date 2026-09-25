"""Vectorised series primitives.

These must agree exactly with the chart's TypeScript versions in
``apps/web/src/features/chart/lib/indicators.ts``. A chart that disagrees
with the backtest is worse than no chart, so both follow the same standard
formulas: SMA-seeded EMA, Wilder smoothing for RSI and ATR, population
standard deviation for Bollinger.

Warm-up periods are NaN, never a partial value. A half-warmed average that
looks like a number is a signal the strategy never really had, and it would
show up as free profit in the first bars of every backtest.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

Array = NDArray[np.float64]


def _as_array(values: Array | float) -> Array:
    if isinstance(values, np.ndarray):
        return values.astype(np.float64, copy=False)
    return np.asarray(values, dtype=np.float64)


def sma(values: Array, length: int) -> Array:
    """Simple moving average."""
    if length < 1:
        raise ValueError("sma length must be at least 1")

    values = _as_array(values)
    out = np.full(values.shape, np.nan, dtype=np.float64)
    if values.size < length:
        return out

    # Cumulative sums give an O(n) rolling mean. The leading 0 avoids a
    # special case for the first window.
    cumulative = np.concatenate(([0.0], np.nancumsum(values)))
    windows = cumulative[length:] - cumulative[:-length]
    out[length - 1 :] = windows / length
    return out


def ema(values: Array, length: int) -> Array:
    """Exponential moving average, seeded with the SMA of the first window.

    Seeding from the SMA rather than the first value makes the result
    independent of how much history happens to be loaded — otherwise the
    same strategy would score differently on a longer backtest.
    """
    if length < 1:
        raise ValueError("ema length must be at least 1")

    values = _as_array(values)
    out = np.full(values.shape, np.nan, dtype=np.float64)
    if values.size < length:
        return out

    k = 2.0 / (length + 1.0)
    previous = float(np.mean(values[:length]))
    out[length - 1] = previous

    for i in range(length, values.size):
        previous = values[i] * k + previous * (1.0 - k)
        out[i] = previous
    return out


def wilder(values: Array, length: int) -> Array:
    """Wilder's smoothing. Not the same as an EMA of the same length."""
    if length < 1:
        raise ValueError("length must be at least 1")

    values = _as_array(values)
    out = np.full(values.shape, np.nan, dtype=np.float64)
    if values.size < length:
        return out

    previous = float(np.mean(values[:length]))
    out[length - 1] = previous

    for i in range(length, values.size):
        previous = (previous * (length - 1) + values[i]) / length
        out[i] = previous
    return out


def rsi(values: Array, length: int = 14) -> Array:
    """Relative strength index, Wilder's original formulation."""
    values = _as_array(values)
    out = np.full(values.shape, np.nan, dtype=np.float64)
    if values.size <= length:
        return out

    change = np.diff(values)
    gains = np.maximum(change, 0.0)
    losses = np.maximum(-change, 0.0)

    avg_gain = wilder(gains, length)
    avg_loss = wilder(losses, length)

    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.divide(avg_gain, avg_loss)
        computed = 100.0 - 100.0 / (1.0 + rs)

    # A window with no losses is RSI 100 by definition, not a division error.
    computed = np.where(avg_loss == 0.0, 100.0, computed)
    computed = np.where(np.isnan(avg_gain), np.nan, computed)

    out[1:] = computed
    return out


def true_range(high: Array, low: Array, close: Array) -> Array:
    """True range. The first bar has no previous close, so it is high-low."""
    high, low, close = _as_array(high), _as_array(low), _as_array(close)
    previous_close = np.concatenate(([close[0]], close[:-1])) if close.size else close

    out = np.maximum(
        high - low,
        np.maximum(np.abs(high - previous_close), np.abs(low - previous_close)),
    )
    if out.size:
        out[0] = high[0] - low[0]
    return out


def atr(high: Array, low: Array, close: Array, length: int = 14) -> Array:
    """Average true range, Wilder-smoothed."""
    return wilder(true_range(high, low, close), length)


def stdev(values: Array, length: int) -> Array:
    """Rolling population standard deviation, matching Bollinger's usual form."""
    if length < 1:
        raise ValueError("stdev length must be at least 1")

    values = _as_array(values)
    out = np.full(values.shape, np.nan, dtype=np.float64)
    if values.size < length:
        return out

    for i in range(length - 1, values.size):
        window = values[i - length + 1 : i + 1]
        out[i] = float(np.std(window))
    return out


def highest(values: Array, length: int) -> Array:
    """Highest value over the last ``length`` bars, including this one."""
    if length < 1:
        raise ValueError("highest length must be at least 1")

    values = _as_array(values)
    out = np.full(values.shape, np.nan, dtype=np.float64)
    for i in range(length - 1, values.size):
        out[i] = np.max(values[i - length + 1 : i + 1])
    return out


def lowest(values: Array, length: int) -> Array:
    if length < 1:
        raise ValueError("lowest length must be at least 1")

    values = _as_array(values)
    out = np.full(values.shape, np.nan, dtype=np.float64)
    for i in range(length - 1, values.size):
        out[i] = np.min(values[i - length + 1 : i + 1])
    return out


def shift(values: Array, periods: int = 1) -> Array:
    """Values from ``periods`` bars ago.

    Only ever shifts forward in time — a negative shift would read the
    future, which is the definition of lookahead.
    """
    if periods < 0:
        raise ValueError("shift cannot look into the future")

    values = _as_array(values)
    out = np.full(values.shape, np.nan, dtype=np.float64)
    if periods == 0:
        return values.copy()
    if periods < values.size:
        out[periods:] = values[:-periods]
    return out


def crossover(a: Array, b: Array) -> NDArray[np.bool_]:
    """True on the bar where ``a`` crosses from below ``b`` to above it."""
    a, b = _as_array(a), _as_array(b)
    previous_a, previous_b = shift(a), shift(b)

    with np.errstate(invalid="ignore"):
        crossed = (previous_a <= previous_b) & (a > b)
    # NaN anywhere in the comparison means "not yet warmed up", not False
    # by luck; make that explicit.
    valid = ~(np.isnan(a) | np.isnan(b) | np.isnan(previous_a) | np.isnan(previous_b))
    return np.asarray(crossed & valid, dtype=np.bool_)


def crossunder(a: Array, b: Array) -> NDArray[np.bool_]:
    """True on the bar where ``a`` crosses from above ``b`` to below it."""
    return crossover(b, a)


def _monotonic(values: Array, length: int, increasing: bool) -> NDArray[np.bool_]:
    """True where the last ``length`` steps all moved the same way.

    Each step compares consecutive bars: ``rising(x, 2)`` needs both
    ``x[i] > x[i-1]`` and ``x[i-1] > x[i-2]``.
    """
    values = _as_array(values)
    out = np.ones(values.shape, dtype=np.bool_)

    for step in range(length):
        later = shift(values, step)
        earlier = shift(values, step + 1)
        with np.errstate(invalid="ignore"):
            moved = later > earlier if increasing else later < earlier
        # NaN comparisons are False either way; make the warm-up explicit.
        out &= moved & ~np.isnan(later) & ~np.isnan(earlier)

    return out


def rising(values: Array, length: int = 1) -> NDArray[np.bool_]:
    """True when the series rose on each of the last ``length`` bars."""
    if length < 1:
        raise ValueError("rising length must be at least 1")
    return _monotonic(values, length, increasing=True)


def falling(values: Array, length: int = 1) -> NDArray[np.bool_]:
    """True when the series fell on each of the last ``length`` bars."""
    if length < 1:
        raise ValueError("falling length must be at least 1")
    return _monotonic(values, length, increasing=False)


def macd_lines(
    values: Array, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[Array, Array, Array]:
    """MACD line, signal line and histogram."""
    values = _as_array(values)
    line = ema(values, fast) - ema(values, slow)

    # The signal is an EMA of the MACD line, which only starts once the slow
    # EMA has warmed up; feeding it NaNs would poison the recursion.
    signal_line = np.full(values.shape, np.nan, dtype=np.float64)
    warm = np.flatnonzero(~np.isnan(line))
    if warm.size:
        start = int(warm[0])
        dense = ema(line[start:], signal)
        signal_line[start:] = dense

    return line, signal_line, line - signal_line


def bollinger(
    values: Array, length: int = 20, multiplier: float = 2.0
) -> tuple[Array, Array, Array]:
    """Bollinger middle, upper and lower bands."""
    middle = sma(values, length)
    deviation = stdev(values, length) * multiplier
    return middle, middle + deviation, middle - deviation
