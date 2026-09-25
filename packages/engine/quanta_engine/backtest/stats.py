"""Backtest statistics (SPEC §3.3 Overview).

Every ratio here is reported *after* costs, because that is the only
version a trader can act on. Where a metric is undefined — no losing
trades, no volatility — it is None rather than a made-up large number.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from quanta_engine.backtest.types import Array, BacktestConfig, BacktestResult, Bars, Trade

# Bars per year, used to annualise. Crypto trades continuously.
MINUTES_PER_YEAR = 365 * 24 * 60


def _safe_divide(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def max_drawdown(equity: Array) -> tuple[float, int, int]:
    """Deepest peak-to-trough fall, as a percentage, with its bar indices."""
    if equity.size == 0:
        return 0.0, 0, 0

    peaks = np.maximum.accumulate(equity)
    with np.errstate(divide="ignore", invalid="ignore"):
        drops = np.where(peaks > 0, (equity - peaks) / peaks * 100.0, 0.0)

    trough = int(np.argmin(drops))
    peak = int(np.argmax(equity[: trough + 1])) if trough > 0 else 0
    return float(drops[trough]), peak, trough


def longest_drawdown_bars(equity: Array) -> int:
    """Longest run spent below a previous peak.

    SPEC §3.3 asks for this alongside depth: a shallow drawdown lasting a
    year is harder to sit through than a deep one that recovers in a week.
    """
    if equity.size == 0:
        return 0

    peaks = np.maximum.accumulate(equity)
    underwater = equity < peaks

    longest = 0
    current = 0
    for flag in underwater:
        current = current + 1 if flag else 0
        longest = max(longest, current)
    return longest


def _returns_per_bar(equity: Array) -> Array:
    if equity.size < 2:
        return np.array([], dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        changes = np.diff(equity) / equity[:-1]
    return np.nan_to_num(changes, nan=0.0, posinf=0.0, neginf=0.0)


def sharpe_ratio(equity: Array, bars_per_year: float) -> float | None:
    """Annualised Sharpe at a zero risk-free rate."""
    returns = _returns_per_bar(equity)
    if returns.size < 2:
        return None
    deviation = float(np.std(returns, ddof=1))
    if deviation == 0:
        return None
    return float(np.mean(returns)) / deviation * math.sqrt(bars_per_year)


def sortino_ratio(equity: Array, bars_per_year: float) -> float | None:
    """Like Sharpe, but only downside deviation counts against a strategy."""
    returns = _returns_per_bar(equity)
    if returns.size < 2:
        return None
    downside = returns[returns < 0]
    if downside.size == 0:
        return None
    deviation = float(np.sqrt(np.mean(downside**2)))
    if deviation == 0:
        return None
    return float(np.mean(returns)) / deviation * math.sqrt(bars_per_year)


def profit_factor(trades: list[Trade]) -> float | None:
    """Gross profit divided by gross loss. None when nothing was lost."""
    wins = sum(t.net_pnl for t in trades if t.net_pnl > 0)
    losses = -sum(t.net_pnl for t in trades if t.net_pnl < 0)
    return wins / losses if losses > 0 else None


def buy_and_hold_return(bars: Bars) -> float:
    """What simply holding the asset would have returned, as a percentage."""
    if len(bars) < 2:
        return 0.0
    first = float(bars.close[0])
    last = float(bars.close[-1])
    return (last - first) / first * 100.0 if first else 0.0


def _bars_per_year(bars: Bars) -> float:
    if len(bars) < 2:
        return float(MINUTES_PER_YEAR)
    step_ms = float(np.median(np.diff(bars.time)))
    if step_ms <= 0:
        return float(MINUTES_PER_YEAR)
    return (365.0 * 24 * 3_600_000) / step_ms


def compute_stats(result: BacktestResult, config: BacktestConfig, bars: Bars) -> dict[str, Any]:
    trades = result.trades
    equity = result.equity
    start_equity = config.initial_capital
    end_equity = float(equity[-1]) if equity.size else start_equity

    wins = [t for t in trades if t.net_pnl > 0]
    losses = [t for t in trades if t.net_pnl < 0]

    depth, peak_index, trough_index = max_drawdown(equity)
    bars_per_year = _bars_per_year(bars)

    gross = sum(t.gross_pnl for t in trades)
    fees = sum(t.total_fees for t in trades)
    funding = sum(t.funding_paid for t in trades)

    longs = [t for t in trades if t.is_long]
    shorts = [t for t in trades if not t.is_long]

    return {
        # Headline
        "net_profit": end_equity - start_equity,
        "net_profit_percent": (end_equity - start_equity) / start_equity * 100.0,
        "ending_equity": end_equity,
        "buy_and_hold_percent": buy_and_hold_return(bars),
        # Risk
        "max_drawdown_percent": depth,
        "max_drawdown_peak_index": peak_index,
        "max_drawdown_trough_index": trough_index,
        "longest_drawdown_bars": longest_drawdown_bars(equity),
        "sharpe": sharpe_ratio(equity, bars_per_year),
        "sortino": sortino_ratio(equity, bars_per_year),
        # Trades
        "total_trades": len(trades),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate_percent": (len(wins) / len(trades) * 100.0) if trades else 0.0,
        "profit_factor": profit_factor(trades),
        "average_win": _safe_divide(sum(t.net_pnl for t in wins), len(wins)),
        "average_loss": _safe_divide(sum(t.net_pnl for t in losses), len(losses)),
        "largest_win": max((t.net_pnl for t in trades), default=0.0),
        "largest_loss": min((t.net_pnl for t in trades), default=0.0),
        "average_bars_held": _safe_divide(float(sum(t.bars_held for t in trades)), len(trades)),
        # Costs — shown separately because they are what most strategies
        # actually lose to (SPEC §3.3 cost breakdown).
        "gross_profit": gross,
        "total_fees": fees,
        "total_funding": funding,
        "costs_over_gross": _safe_divide(fees + funding, abs(gross)) if gross else None,
        # Sides
        "long_trades": len(longs),
        "short_trades": len(shorts),
        "long_net_pnl": sum(t.net_pnl for t in longs),
        "short_net_pnl": sum(t.net_pnl for t in shorts),
        # Liquidations are a separate count: one is a different kind of
        # event from a losing trade.
        "liquidations": sum(1 for t in trades if t.exit_reason == "liquidation"),
    }
