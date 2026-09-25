"""Market-regime metrics (SPEC §3.3).

When a strategy does worse in a new period, there are two explanations: the
edge decayed, or the market changed. These measurements separate them. A
trend-following rule that loses in a choppy month has not necessarily
broken — but the user needs the evidence to say so, rather than a verdict
that just reads "worse".
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

Array = NDArray[np.float64]

# Crypto trades continuously, so annualising uses calendar time.
BARS_PER_YEAR_MS = 365 * 24 * 3_600_000


@dataclass(frozen=True, slots=True)
class Regime:
    """What the market did over one period."""

    return_percent: float
    volatility_annual_percent: float
    trend_efficiency: float
    average_candle_range_percent: float
    bars: int

    def to_dict(self) -> dict[str, float | int]:
        return {
            "return_percent": self.return_percent,
            "volatility_annual_percent": self.volatility_annual_percent,
            "trend_efficiency": self.trend_efficiency,
            "average_candle_range_percent": self.average_candle_range_percent,
            "bars": self.bars,
        }


def trend_efficiency(closes: Array) -> float:
    """Kaufman's efficiency ratio: net movement over total movement.

    1.0 is a straight line; near 0 is chop that went nowhere. This is the
    single most useful number for explaining why a trend strategy had a
    bad month — and why a mean-reversion one had a good one.
    """
    if closes.size < 2:
        return 0.0

    net = abs(float(closes[-1]) - float(closes[0]))
    total = float(np.sum(np.abs(np.diff(closes))))
    return net / total if total > 0 else 0.0


def realised_volatility(closes: Array, bar_ms: int) -> float:
    """Annualised standard deviation of log returns, as a percentage."""
    if closes.size < 3 or bar_ms <= 0:
        return 0.0

    with np.errstate(divide="ignore", invalid="ignore"):
        log_returns = np.diff(np.log(closes))
    log_returns = log_returns[np.isfinite(log_returns)]
    if log_returns.size < 2:
        return 0.0

    bars_per_year = BARS_PER_YEAR_MS / bar_ms
    return float(np.std(log_returns, ddof=1) * np.sqrt(bars_per_year) * 100.0)


def describe(time: NDArray[np.int64], high: Array, low: Array, close: Array) -> Regime:
    """Measure one period."""
    if close.size < 2:
        return Regime(0.0, 0.0, 0.0, 0.0, int(close.size))

    first, last = float(close[0]), float(close[-1])
    change = (last - first) / first * 100.0 if first else 0.0

    bar_ms = int(np.median(np.diff(time))) if time.size > 1 else 0

    with np.errstate(divide="ignore", invalid="ignore"):
        ranges = np.where(close > 0, (high - low) / close * 100.0, 0.0)
    average_range = float(np.mean(ranges[np.isfinite(ranges)])) if ranges.size else 0.0

    return Regime(
        return_percent=change,
        volatility_annual_percent=realised_volatility(close, bar_ms),
        trend_efficiency=trend_efficiency(close),
        average_candle_range_percent=average_range,
        bars=int(close.size),
    )
