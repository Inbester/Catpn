"""Trade risk: how far underwater a trade went before it worked (SPEC §3.2).

A strategy's average result says nothing about what holding it felt like.
Maximum adverse excursion — the worst mark-to-market a trade reached
before it closed — is what decides whether a position survives to reach
its target, and it is the number leverage acts on. A rule whose winners
routinely dip 8% before turning is untradeable at 12x however good its
win rate, because the liquidation price is nearer than the dip.

The headline measure is the deepest dip its winners survived, expressed
as the leverage at which that dip would have been a liquidation instead.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np

from quanta_engine.backtest.types import Trade

# Maintenance margin eats into the buffer, so liquidation arrives slightly
# before 1/leverage of adverse move. SPEC §6 puts the first tier at 0.4%.
DEFAULT_MAINTENANCE_MARGIN = 0.004


@dataclass(frozen=True, slots=True)
class TradePoint:
    """One trade as the scatter plots it."""

    index: int
    side: str
    entry_time: int
    bars_held: int
    # Worst adverse move while open, as a positive percent of margin.
    adverse_percent: float
    # Best favourable move, same units.
    favourable_percent: float
    result_percent: float
    funding_paid: float
    was_liquidated: bool
    # True when the trade ended green after having been red.
    recovered: bool


@dataclass(frozen=True, slots=True)
class TradeRisk:
    points: list[TradePoint]
    winners_that_were_red: int
    winners: int
    median_dip_percent: float
    p95_dip_percent: float
    deepest_dip_percent: float
    survives_up_to_leverage: float
    worst_closed_trade_percent: float
    average_bars_held: float
    funding_events: int
    total_funding: float


def liquidation_leverage(
    adverse_percent: float, maintenance: float = DEFAULT_MAINTENANCE_MARGIN
) -> float:
    """The leverage at which a dip of this size becomes a liquidation.

    A position is liquidated once the adverse move eats the margin less
    maintenance, so the leverage that survives a dip of d is roughly
    1 / (d + maintenance). Reported as the honest ceiling rather than an
    exact figure: tiers and funding move it, always downward.
    """
    dip = max(adverse_percent, 0.0) / 100.0
    if dip + maintenance <= 0:
        return float("inf")
    return 1.0 / (dip + maintenance)


def analyse_trades(
    trades: list[Trade], *, maintenance: float = DEFAULT_MAINTENANCE_MARGIN
) -> TradeRisk:
    """Turn a run's trades into the Trade risk study.

    Excursions are scaled by the margin committed, not by the notional:
    the question is how much of what was put at risk went away, which is
    what the liquidation engine actually measures.
    """
    points: list[TradePoint] = []
    for index, trade in enumerate(trades):
        base = trade.margin if trade.margin > 0 else 1.0
        adverse = abs(min(trade.drawdown, 0.0)) / base * 100.0
        favourable = max(trade.run_up, 0.0) / base * 100.0
        result = trade.net_pnl / base * 100.0
        points.append(
            TradePoint(
                index=index,
                side=trade.side,
                entry_time=trade.entry_time,
                bars_held=trade.bars_held,
                adverse_percent=adverse,
                favourable_percent=favourable,
                result_percent=result,
                funding_paid=trade.funding_paid,
                was_liquidated=str(trade.exit_reason.value) == "liquidation"
                if hasattr(trade.exit_reason, "value")
                else str(trade.exit_reason) == "liquidation",
                recovered=trade.net_pnl > 0 and adverse > 0,
            )
        )

    winners = [p for p in points if p.result_percent > 0]
    red_first = [p for p in winners if p.adverse_percent > 0]
    dips = np.array([p.adverse_percent for p in winners], dtype=np.float64)

    median = float(np.median(dips)) if dips.size else 0.0
    p95 = float(np.percentile(dips, 95)) if dips.size else 0.0
    deepest = float(np.max(dips)) if dips.size else 0.0

    return TradeRisk(
        points=points,
        winners_that_were_red=len(red_first),
        winners=len(winners),
        median_dip_percent=median,
        p95_dip_percent=p95,
        deepest_dip_percent=deepest,
        survives_up_to_leverage=liquidation_leverage(deepest, maintenance),
        worst_closed_trade_percent=(
            float(min(p.result_percent for p in points)) if points else 0.0
        ),
        average_bars_held=float(np.mean([p.bars_held for p in points])) if points else 0.0,
        funding_events=sum(1 for p in points if p.funding_paid != 0.0),
        total_funding=float(sum(p.funding_paid for p in points)),
    )


def holding_histogram(points: list[TradePoint], buckets: int = 8) -> list[dict[str, float]]:
    """Trades and net funding by how long they were held.

    Funding is grouped with holding time because that is the relationship:
    a rule that holds through many 8-hour settlements pays for them, and
    the cost is invisible in a per-trade average.
    """
    if not points:
        return []

    held = np.array([p.bars_held for p in points], dtype=np.float64)
    edges = np.histogram_bin_edges(held, bins=min(buckets, max(1, len(set(held.tolist())))))
    out: list[dict[str, float]] = []
    for low, high in itertools.pairwise(edges):
        inside = [p for p in points if low <= p.bars_held <= high]
        out.append(
            {
                "from_bars": float(low),
                "to_bars": float(high),
                "trades": float(len(inside)),
                "net_funding": float(sum(p.funding_paid for p in inside)),
                "mean_result_percent": (
                    float(np.mean([p.result_percent for p in inside])) if inside else 0.0
                ),
            }
        )
    return out
