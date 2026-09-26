"""Leverage and costs (SPEC §3.2).

The study answers one question: how much leverage is worth taking. Its
whole shape follows from a single identity —

    exposure = margin share x leverage

— which means the same market risk can be bought at many different
leverages. 20% of equity at 5x and 10% at 10x both control half the
account. They win and lose the same amount on the same move.

What differs is the distance to liquidation. The lower-leverage position
has its liquidation price further away, so it survives moves that close
the other one out. That makes the recommendation unambiguous: among cells
that earn the same, prefer the lowest leverage. Higher leverage is never
free; it is paid for in the moves you no longer survive.

Costs are why the surface is not monotonic. More leverage means a larger
position, and fees scale with position size while the edge does not, so
past some point every extra turn of leverage buys more cost than return.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from quanta_engine.backtest.engine import run_backtest
from quanta_engine.backtest.types import (
    BacktestConfig,
    BacktestResult,
    Bars,
    FundingEvent,
    Trade,
)
from quanta_engine.strategy import MarginMode, Strategy

# A year of calendar time, for annualising a run of any length.
MS_PER_YEAR = 365 * 24 * 3_600_000


@dataclass(frozen=True, slots=True)
class Cell:
    """One margin and leverage pairing, run end to end."""

    margin_percent: float
    leverage: float
    net_percent: float
    annualised_percent: float
    max_drawdown_percent: float
    liquidations: int
    trades: int
    costs_over_gross: float | None
    worst_trade_percent: float
    # Margin share times leverage: what the position actually controls.
    exposure: float

    @property
    def wiped_out(self) -> bool:
        """A drawdown this deep is not a number to compare, it is a stop."""
        return self.max_drawdown_percent <= -99.0


@dataclass(frozen=True, slots=True)
class Recommendation:
    """The cell to take, and why it beat the one with the best raw return."""

    cell: Cell | None
    reason: str
    # The highest net inside the budget, which may be at a higher leverage
    # than the recommendation. Shown so the trade-off is visible.
    best_net_cell: Cell | None = None


@dataclass(frozen=True, slots=True)
class LeverageSweep:
    cells: list[Cell]
    budget_percent: float | None
    recommendation: Recommendation


@dataclass(frozen=True, slots=True)
class MarginModeRow:
    """Isolated against cross at one sizing (SPEC §3.2)."""

    margin_mode: str
    exposure: float
    liquidation_distance_percent: float
    net_percent: float
    max_drawdown_percent: float
    worst_trade_percent: float
    liquidations: int
    costs_over_gross: float | None
    risk_of_ruin_percent: float


def _annualise(net_percent: float, bars: Bars) -> float:
    """Scale a run's return to a year.

    Compounded, not multiplied: a 10% gain over six months is 21% a year,
    not 20%. A run that lost everything stays at -100% however short it
    was, because there is nothing left to compound.
    """
    if len(bars) < 2:
        return net_percent
    span = float(bars.time[-1] - bars.time[0])
    if span <= 0:
        return net_percent
    growth = 1.0 + net_percent / 100.0
    if growth <= 0.0:
        return -100.0
    return float((growth ** (MS_PER_YEAR / span) - 1.0) * 100.0)


def _worst_trade_percent(result: BacktestResult, capital: float) -> float:
    if not result.trades or capital <= 0:
        return 0.0
    return float(min(t.net_pnl for t in result.trades) / capital * 100.0)


def _cell(
    strategy: Strategy,
    bars: Bars,
    config: BacktestConfig,
    funding: list[FundingEvent] | None,
    margin_percent: float,
    leverage: float,
) -> Cell:
    trial = replace(config, margin_percent=margin_percent, leverage=leverage)
    result = run_backtest(strategy, bars, trial, funding=funding)
    stats = result.stats
    net = float(stats["net_profit_percent"])
    return Cell(
        margin_percent=margin_percent,
        leverage=leverage,
        net_percent=net,
        annualised_percent=_annualise(net, bars),
        max_drawdown_percent=float(stats["max_drawdown_percent"]),
        liquidations=int(stats["liquidations"]),
        trades=int(stats["total_trades"]),
        costs_over_gross=(
            float(stats["costs_over_gross"]) if stats["costs_over_gross"] is not None else None
        ),
        worst_trade_percent=_worst_trade_percent(result, trial.initial_capital),
        exposure=margin_percent * leverage / 100.0,
    )


def sweep_leverage(
    strategy: Strategy,
    bars: Bars,
    *,
    margins: list[float],
    leverages: list[float],
    config: BacktestConfig | None = None,
    funding: list[FundingEvent] | None = None,
    budget_percent: float | None = None,
) -> LeverageSweep:
    """Run every margin and leverage pairing, then pick one.

    ``budget_percent`` is the deepest drawdown the user will accept, as a
    negative number. Cells past it are kept and returned — the shape of the
    surface outside the budget is information — but never recommended.
    """
    config = config or BacktestConfig()
    cells = [
        _cell(strategy, bars, config, funding, margin, leverage)
        for margin in margins
        for leverage in leverages
    ]
    return LeverageSweep(
        cells=cells,
        budget_percent=budget_percent,
        recommendation=recommend(cells, budget_percent=budget_percent),
    )


def recommend(cells: list[Cell], *, budget_percent: float | None = None) -> Recommendation:
    """The best net inside the budget, at the lowest leverage that earns it.

    "Earns it" is deliberately loose: cells within a tenth of the best are
    treated as equal, because the difference between 41.2% and 41.4% over
    one history is noise, and paying for it in liquidation distance is a
    bad trade.
    """
    affordable = [
        cell
        for cell in cells
        if cell.trades > 0
        and not cell.wiped_out
        and (budget_percent is None or cell.max_drawdown_percent >= budget_percent)
    ]
    if not affordable:
        if budget_percent is None:
            return Recommendation(None, "No pairing traded at all.")
        return Recommendation(
            None,
            f"No pairing stayed inside a {budget_percent:.0f}% drawdown budget. "
            "Either the budget is tighter than this strategy can trade, or the "
            "sizing needs to come down further than the sweep went.",
        )

    best = max(affordable, key=lambda c: c.net_percent)
    if best.net_percent <= 0:
        return Recommendation(
            None,
            "Nothing inside the budget made money, so there is no leverage "
            "worth taking. Leverage multiplies an edge; it does not create one.",
            best_net_cell=best,
        )

    # Everything within a tenth of the best return, then the safest of them.
    margin = abs(best.net_percent) * 0.001
    equals = [c for c in affordable if c.net_percent >= best.net_percent - margin]
    pick = min(equals, key=lambda c: (c.leverage, -c.net_percent))
    # Compare against the most leveraged cell that earns the same, not the
    # one that happened to top the list: the point of the recommendation is
    # what it declined to take, and a tie makes that invisible otherwise.
    rival = max(equals, key=lambda c: c.leverage)

    if rival.leverage > pick.leverage:
        reason = (
            f"{pick.margin_percent:g}% at {pick.leverage:g}x earns what "
            f"{rival.margin_percent:g}% at {rival.leverage:g}x earns, at "
            f"{rival.leverage / pick.leverage:.1f}x less leverage. Same exposure, "
            "liquidation price further away."
        )
    else:
        reason = (
            f"{pick.margin_percent:g}% at {pick.leverage:g}x is the best net "
            f"inside the budget, and nothing lower matches it."
        )
    return Recommendation(pick, reason, best_net_cell=best)


def liquidation_distance_percent(result_trades: list[Trade]) -> float:
    """Average distance from entry to liquidation, as a percent of entry.

    The number that makes the leverage trade-off concrete: it is how far
    the market may go against the position before the exchange closes it.
    """
    distances = [
        abs(t.liquidation_price - t.entry_price) / t.entry_price * 100.0
        for t in result_trades
        if t.entry_price > 0 and t.liquidation_price > 0
    ]
    return float(np.mean(distances)) if distances else 0.0


def risk_of_ruin_percent(
    net_pnls: list[float],
    equity_before: list[float],
    *,
    ruin_percent: float = -50.0,
    runs: int = 2_000,
    seed: int = 20260926,
) -> float:
    """The chance of a ``ruin_percent`` drawdown, by reshuffling the trades.

    Bootstrapped rather than solved from a formula, because the closed
    forms assume every trade is the same size and independent, and a
    percent-of-equity strategy is neither. Resampling the actual trade
    returns keeps their real spread, including the tail that does the
    damage.
    """
    if not net_pnls or len(net_pnls) != len(equity_before):
        return 0.0

    returns = np.array(
        [
            pnl / equity if equity > 0 else 0.0
            for pnl, equity in zip(net_pnls, equity_before, strict=True)
        ],
        dtype=np.float64,
    )
    if returns.size == 0:
        return 0.0

    rng = np.random.default_rng(seed)
    draws = rng.integers(0, returns.size, size=(runs, returns.size))
    paths = np.cumprod(1.0 + returns[draws], axis=1)
    peaks = np.maximum.accumulate(paths, axis=1)
    worst = np.min((paths - peaks) / peaks, axis=1) * 100.0
    return float(np.mean(worst <= ruin_percent) * 100.0)


def compare_margin_modes(
    strategy: Strategy,
    bars: Bars,
    *,
    margin_percent: float,
    leverage: float,
    config: BacktestConfig | None = None,
    funding: list[FundingEvent] | None = None,
    ruin_percent: float = -50.0,
) -> list[MarginModeRow]:
    """The same sizing run isolated and cross (SPEC §3.2).

    Isolated caps a loss at the margin committed; cross lets the rest of
    the account defend the position, which buys survival at the price of
    risking everything rather than a slice.
    """
    config = config or BacktestConfig()
    rows: list[MarginModeRow] = []

    for mode in (MarginMode.ISOLATED, MarginMode.CROSS):
        trial = replace(config, margin_percent=margin_percent, leverage=leverage, margin_mode=mode)
        result = run_backtest(strategy, bars, trial, funding=funding)
        stats = result.stats
        rows.append(
            MarginModeRow(
                margin_mode=mode.value,
                exposure=margin_percent * leverage / 100.0,
                liquidation_distance_percent=liquidation_distance_percent(result.trades),
                net_percent=float(stats["net_profit_percent"]),
                max_drawdown_percent=float(stats["max_drawdown_percent"]),
                worst_trade_percent=_worst_trade_percent(result, trial.initial_capital),
                liquidations=int(stats["liquidations"]),
                costs_over_gross=(
                    float(stats["costs_over_gross"])
                    if stats["costs_over_gross"] is not None
                    else None
                ),
                risk_of_ruin_percent=risk_of_ruin_percent(
                    [t.net_pnl for t in result.trades],
                    [t.equity_after - t.net_pnl for t in result.trades],
                    ruin_percent=ruin_percent,
                ),
            )
        )
    return rows
