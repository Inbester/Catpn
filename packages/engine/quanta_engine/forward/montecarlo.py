"""Monte Carlo expectation bands (SPEC §3.3).

The question a forward test has to answer is not "did the strategy make
money last month" but "is this result consistent with the strategy that
was tested". One month of trading is a small sample, and a strategy with a
real edge still loses in plenty of months.

So the reference period's per-trade returns are resampled with replacement
into thousands of alternative orderings of the *test* period's trade count.
That produces the range of outcomes the strategy could plausibly have
produced, and the test result is judged against it rather than against
zero.

Resampling assumes trades are independent and identically distributed. They
are not, quite — streaks and regime effects are real — so the band is a
guide, not a guarantee. It is still far better than comparing a single
number to a single number.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

Array = NDArray[np.float64]

DEFAULT_RUNS = 3000
DEFAULT_BAND = 0.90


@dataclass(frozen=True, slots=True)
class Band:
    """A percentile interval, with the median for reference."""

    low: float
    high: float
    median: float
    runs: int
    confidence: float

    def contains(self, value: float) -> bool:
        return self.low <= value <= self.high

    def position(self, value: float) -> float:
        """Where ``value`` sits in the band, 0 at the low end and 1 at the high.

        Values outside the band clamp, so a bar drawn from this never runs
        off its track.
        """
        if self.high <= self.low:
            return 0.5
        return float(np.clip((value - self.low) / (self.high - self.low), 0.0, 1.0))


def _max_drawdown_percent(equity: Array) -> float:
    """Deepest peak-to-trough fall of an equity path, as a negative percent."""
    if equity.size == 0:
        return 0.0
    peaks = np.maximum.accumulate(equity)
    with np.errstate(divide="ignore", invalid="ignore"):
        drops = np.where(peaks > 0, (equity - peaks) / peaks * 100.0, 0.0)
    return float(np.min(drops))


@dataclass(frozen=True, slots=True)
class MonteCarloResult:
    net_percent: Band
    max_drawdown_percent: Band
    # One representative worst-case path, for the chart's shaded band.
    worst_case_equity: Array
    best_case_equity: Array
    median_equity: Array


def simulate(
    trade_returns: Array,
    *,
    trade_count: int,
    runs: int = DEFAULT_RUNS,
    confidence: float = DEFAULT_BAND,
    seed: int = 12345,
) -> MonteCarloResult:
    """Bootstrap ``trade_count`` trades from ``trade_returns``.

    ``trade_returns`` are per-trade returns on equity as fractions, so 0.01
    is a trade that added one percent. The seed is fixed: the same inputs
    must give the same band every time, or a verdict would change on a
    re-run for no reason the user can see.
    """
    if trade_returns.size == 0 or trade_count <= 0:
        empty = np.array([0.0])
        flat = Band(0.0, 0.0, 0.0, 0, confidence)
        return MonteCarloResult(flat, flat, empty, empty, empty)

    if not 0 < confidence < 1:
        raise ValueError("confidence must be between 0 and 1")

    rng = np.random.default_rng(seed)
    # (runs, trade_count) of resampled returns.
    draws = rng.choice(trade_returns, size=(runs, trade_count), replace=True)

    # Compound each path. Equity starts at 1.0 and each trade multiplies it,
    # which is how a percentage-of-equity sizing rule actually behaves.
    paths = np.cumprod(1.0 + draws, axis=1)
    starts = np.ones((runs, 1), dtype=np.float64)
    paths = np.hstack([starts, paths])

    nets = (paths[:, -1] - 1.0) * 100.0
    drawdowns = np.array([_max_drawdown_percent(path) for path in paths])

    tail = (1.0 - confidence) / 2.0
    low_q, high_q = tail * 100.0, (1.0 - tail) * 100.0

    net_band = Band(
        low=float(np.percentile(nets, low_q)),
        high=float(np.percentile(nets, high_q)),
        median=float(np.median(nets)),
        runs=runs,
        confidence=confidence,
    )
    # A drawdown band runs from the worst plausible to the mildest, so the
    # percentiles are read the same way round as the numbers themselves.
    drawdown_band = Band(
        low=float(np.percentile(drawdowns, low_q)),
        high=float(np.percentile(drawdowns, high_q)),
        median=float(np.median(drawdowns)),
        runs=runs,
        confidence=confidence,
    )

    order = np.argsort(nets)
    worst_index = int(order[int(tail * runs)])
    best_index = int(order[min(runs - 1, int((1.0 - tail) * runs))])
    median_index = int(order[runs // 2])

    return MonteCarloResult(
        net_percent=net_band,
        max_drawdown_percent=drawdown_band,
        worst_case_equity=(paths[worst_index] - 1.0) * 100.0,
        best_case_equity=(paths[best_index] - 1.0) * 100.0,
        median_equity=(paths[median_index] - 1.0) * 100.0,
    )


def trade_returns_on_equity(net_pnls: list[float], equity_before: list[float]) -> Array:
    """Per-trade returns as a fraction of the equity each trade started with.

    Using equity-relative returns rather than absolute PnL is what makes the
    bootstrap meaningful: the strategy risks a share of equity, so a run of
    resampled trades has to compound the same way.
    """
    if not net_pnls:
        return np.array([], dtype=np.float64)

    returns = []
    for pnl, equity in zip(net_pnls, equity_before, strict=False):
        returns.append(pnl / equity if equity > 0 else 0.0)
    return np.array(returns, dtype=np.float64)
