"""Deciding which discovered rules survive chance (SPEC §3.2, step 6).

Searching hundreds of thousands of rules against one price history will
turn up thousands that look profitable, and almost all of them will be
noise. Two defences are applied, and both are reported rather than hidden:

*Benjamini-Hochberg* at 5% controls the share of false findings among the
rules called significant, and the count of hits it would let through by
chance is shown next to the result. A search that reports 40 hits when 2
were expected by chance is a different finding from one that reports 3.

*A 70/30 split* holds the last 30% of the history back. The correction is
computed on the first 70% only; the held-out stretch is scored afterwards
with no selection of any kind, so it is the one number in the search that
was never fitted.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

Array = NDArray[np.float64]
Mask = NDArray[np.bool_]

# SPEC §3.2 step 5: four horizons. Bars, not days, so the same set means
# the same thing on every timeframe.
HORIZONS = (1, 4, 12, 24)
SIDES = ("long", "short")

FDR_ALPHA = 0.05
IN_SAMPLE_SHARE = 0.70
# Below this a t-statistic is meaningless however good the mean looks.
MIN_SIGNALS = 20


@dataclass(frozen=True, slots=True)
class Outcome:
    """What one rule did on one side over one horizon."""

    rule_key: str
    side: str
    horizon: int
    signals: int
    mean_return_percent: float
    mean_net_percent: float
    t_statistic: float
    p_value: float
    win_rate: float
    # Filled in after the correction, on the held-out stretch only.
    out_of_sample_mean_percent: float = 0.0
    out_of_sample_signals: int = 0
    passed_fdr: bool = False


@dataclass(frozen=True, slots=True)
class SearchResult:
    tested: int
    hits: list[Outcome]
    expected_false_hits: float
    threshold_p: float
    in_sample_bars: int
    out_of_sample_bars: int
    # How many tests an uncorrected search at the same alpha would have
    # called significant. Shown beside the corrected count because the gap
    # is what the correction is for.
    significant_uncorrected: int = 0


def forward_returns(close: Array, horizon: int) -> Array:
    """Percent change from each bar's close to the close ``horizon`` later.

    A signal on the last bars has no future to measure, so those entries
    are NaN and are dropped rather than counted as zero — treating an
    unmeasurable trade as a flat one would shrink every mean toward zero
    and flatter a rule that fires late.
    """
    out = np.full(close.shape, np.nan, dtype=np.float64)
    if horizon < 1 or horizon >= close.size:
        return out
    out[:-horizon] = (close[horizon:] - close[:-horizon]) / close[:-horizon] * 100.0
    return out


def score(
    mask: Mask,
    returns: Array,
    *,
    side: str,
    cost_percent: float,
) -> tuple[int, float, float, float, float, float]:
    """Signals, gross mean, net mean, t, p and win rate for one test.

    The t-test is two-sided against a zero mean. It is a screen, not a
    claim that returns are normal: the correction that follows only needs
    the p-values to be comparable to each other.
    """
    usable = mask & np.isfinite(returns)
    n = int(np.count_nonzero(usable))
    if n < MIN_SIGNALS:
        return n, 0.0, 0.0, 0.0, 1.0, 0.0

    sample = returns[usable]
    if side == "short":
        sample = -sample

    mean = float(np.mean(sample))
    # Costs land on the mean, not on the t-statistic: whether an edge is
    # distinguishable from noise is a fact about the signal, and whether
    # it survives fees is a separate question the user also needs.
    net = mean - cost_percent
    spread = float(np.std(sample, ddof=1))
    if spread == 0.0:
        return n, mean, net, 0.0, 1.0, float(np.mean(sample > 0))

    t = mean / (spread / math.sqrt(n))
    return n, mean, net, t, _two_sided_p(t, n - 1), float(np.mean(sample > 0))


def _two_sided_p(t: float, degrees: int) -> float:
    """Two-sided p for a t-statistic, without pulling in SciPy.

    Uses the normal approximation, which is within a thousandth of the
    t-distribution past about thirty degrees of freedom — and MIN_SIGNALS
    already refuses anything smaller than that would matter for.
    """
    if degrees <= 0 or not math.isfinite(t):
        return 1.0
    z = abs(t)
    # Abramowitz and Stegun 7.1.26 via the complementary error function.
    return float(math.erfc(z / math.sqrt(2.0)))


def benjamini_hochberg(p_values: list[float], alpha: float = FDR_ALPHA) -> tuple[list[bool], float]:
    """Which p-values pass at ``alpha``, and the threshold that was used.

    Sorted ascending, the largest k with p(k) <= k/m * alpha sets the
    threshold; everything at or below it passes. Returns a flat list in the
    caller's original order so results stay aligned with their rules.
    """
    m = len(p_values)
    if m == 0:
        return [], 0.0

    order = sorted(range(m), key=lambda i: p_values[i])
    threshold = 0.0
    cutoff = -1
    for rank, index in enumerate(order, start=1):
        if p_values[index] <= rank / m * alpha:
            cutoff = rank
            threshold = rank / m * alpha

    passed = [False] * m
    for rank, index in enumerate(order, start=1):
        if rank <= cutoff:
            passed[index] = True
    return passed, threshold


def expected_false_hits(tested: int, hits: int, alpha: float = FDR_ALPHA) -> float:
    """How many of the hits the procedure allows to be chance.

    Benjamini-Hochberg controls the false discovery *rate*, so the honest
    number to show beside a count of hits is alpha times that count — not
    alpha times everything tested, which describes a different procedure.
    """
    if hits <= 0 or tested <= 0:
        return 0.0
    return alpha * hits


def split_index(bar_count: int, share: float = IN_SAMPLE_SHARE) -> int:
    """The bar the held-out stretch starts at."""
    return max(1, min(bar_count - 1, round(bar_count * share)))
