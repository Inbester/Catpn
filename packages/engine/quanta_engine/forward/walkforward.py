"""Walk-forward analysis (SPEC §3.3).

A backtest tuned on all its data tells you nothing: with enough parameters
any series can be fitted. Walk-forward answers the question that matters —
would the parameters chosen from what was known *then* have worked on what
came next.

Each window optimises on an in-sample stretch and is then tested on the
unseen stretch that follows. The out-of-sample results are chained into one
equity curve, which is the only equity curve in the product not produced by
hindsight.

Walk-forward efficiency is that out-of-sample return divided by the
in-sample return it was selected on. Near 1 means the optimisation found
something real; near 0 means it found the past.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray

from quanta_engine.backtest.engine import run_backtest
from quanta_engine.backtest.types import BacktestConfig, Bars, FundingEvent
from quanta_engine.strategy import Strategy

Array = NDArray[np.float64]

MS_PER_DAY = 86_400_000
# A window that trades this little cannot support a parameter choice.
MIN_TRADES_FOR_SELECTION = 5
# Guard against a grid that would take hours; the job runner (phase 4)
# lifts this for background runs.
MAX_COMBINATIONS = 400


@dataclass(frozen=True, slots=True)
class Window:
    """One in-sample / out-of-sample pair."""

    index: int
    in_sample_start: int
    in_sample_end: int
    out_of_sample_start: int
    out_of_sample_end: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "in_sample_start": self.in_sample_start,
            "in_sample_end": self.in_sample_end,
            "out_of_sample_start": self.out_of_sample_start,
            "out_of_sample_end": self.out_of_sample_end,
        }


@dataclass(slots=True)
class WindowResult:
    window: Window
    chosen_params: dict[str, float]
    in_sample_net_percent: float
    out_of_sample_net_percent: float
    out_of_sample_max_drawdown: float
    out_of_sample_trades: int
    # None when the window had too little activity to choose from.
    selected: bool = True
    note: str = ""

    @property
    def efficiency(self) -> float | None:
        """This window's out-of-sample return over its in-sample return.

        Undefined when the in-sample return was not positive: dividing by a
        loss produces a number that looks like a score and means nothing.
        """
        if self.in_sample_net_percent <= 0:
            return None
        return self.out_of_sample_net_percent / self.in_sample_net_percent

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.window.to_dict(),
            "chosen_params": self.chosen_params,
            "in_sample_net_percent": self.in_sample_net_percent,
            "out_of_sample_net_percent": self.out_of_sample_net_percent,
            "out_of_sample_max_drawdown": self.out_of_sample_max_drawdown,
            "out_of_sample_trades": self.out_of_sample_trades,
            "efficiency": self.efficiency,
            "selected": self.selected,
            "note": self.note,
        }


@dataclass(slots=True)
class WalkForwardResult:
    windows: list[WindowResult] = field(default_factory=list)
    chained_time: list[int] = field(default_factory=list)
    chained_equity: list[float] = field(default_factory=list)
    chained_drawdown: list[float] = field(default_factory=list)
    walk_forward_efficiency: float | None = None
    total_net_percent: float = 0.0
    max_drawdown_percent: float = 0.0
    total_trades: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "windows": [window.to_dict() for window in self.windows],
            "chained": {
                "time": self.chained_time,
                "value": self.chained_equity,
                "drawdown": self.chained_drawdown,
            },
            "walk_forward_efficiency": self.walk_forward_efficiency,
            "total_net_percent": self.total_net_percent,
            "max_drawdown_percent": self.max_drawdown_percent,
            "total_trades": self.total_trades,
        }


def build_windows(
    start: int,
    end: int,
    *,
    in_sample_days: int = 90,
    out_of_sample_days: int = 30,
    max_windows: int = 12,
) -> list[Window]:
    """Rolling windows: ``in_sample_days`` to fit, the next ``out_of_sample_days`` to test.

    Windows roll forward by the out-of-sample length, so every bar after the
    first in-sample stretch is tested exactly once and never twice.
    """
    if in_sample_days < 1 or out_of_sample_days < 1:
        raise ValueError("window lengths must be at least one day")

    in_ms = in_sample_days * MS_PER_DAY
    out_ms = out_of_sample_days * MS_PER_DAY

    windows: list[Window] = []
    cursor = start
    index = 0

    while cursor + in_ms + out_ms <= end and index < max_windows:
        windows.append(
            Window(
                index=index,
                in_sample_start=cursor,
                in_sample_end=cursor + in_ms,
                out_of_sample_start=cursor + in_ms,
                out_of_sample_end=cursor + in_ms + out_ms,
            )
        )
        cursor += out_ms
        index += 1

    return windows


def _slice(bars: Bars, start: int, end: int) -> Bars:
    lo = int(np.searchsorted(bars.time, start, side="left"))
    hi = int(np.searchsorted(bars.time, end, side="left"))
    return Bars(
        time=bars.time[lo:hi],
        open=bars.open[lo:hi],
        high=bars.high[lo:hi],
        low=bars.low[lo:hi],
        close=bars.close[lo:hi],
        volume=bars.volume[lo:hi],
    )


def expand_grid(grid: dict[str, list[float]]) -> list[dict[str, float]]:
    """Every combination of the parameter values to search."""
    if not grid:
        return [{}]

    names = sorted(grid)
    combinations = list(itertools.product(*(grid[name] for name in names)))
    if len(combinations) > MAX_COMBINATIONS:
        raise ValueError(
            f"{len(combinations)} parameter combinations exceeds the "
            f"{MAX_COMBINATIONS} limit for an interactive run."
        )
    return [dict(zip(names, values, strict=True)) for values in combinations]


def _with_params(strategy: Strategy, params: dict[str, float]) -> Strategy:
    return Strategy(
        name=strategy.name,
        long_entry=strategy.long_entry,
        short_entry=strategy.short_entry,
        exits=strategy.exits,
        params={**strategy.params, **params},
    )


def run_walk_forward(
    strategy: Strategy,
    bars: Bars,
    *,
    grid: dict[str, list[float]] | None = None,
    config: BacktestConfig | None = None,
    funding: list[FundingEvent] | None = None,
    in_sample_days: int = 90,
    out_of_sample_days: int = 30,
    max_windows: int = 12,
) -> WalkForwardResult:
    """Optimise on each in-sample window, test on the next unseen stretch."""
    if len(bars) < 2:
        raise ValueError("walk-forward needs bars")

    config = config or BacktestConfig()
    combinations = expand_grid(grid or {})

    windows = build_windows(
        int(bars.time[0]),
        int(bars.time[-1]),
        in_sample_days=in_sample_days,
        out_of_sample_days=out_of_sample_days,
        max_windows=max_windows,
    )
    if not windows:
        raise ValueError(
            "The range is too short for even one window. Load more history, "
            "or shorten the in-sample and out-of-sample lengths."
        )

    result = WalkForwardResult()
    # The chained curve compounds: each window starts from where the last
    # one ended, which is what actually trading it would have done.
    equity_multiplier = 1.0
    chained_time: list[int] = []
    chained_equity: list[float] = []
    in_sample_total = 0.0
    out_of_sample_total = 0.0

    for window in windows:
        in_bars = _slice(bars, window.in_sample_start, window.in_sample_end)
        out_bars = _slice(bars, window.out_of_sample_start, window.out_of_sample_end)

        if len(in_bars) < 2 or len(out_bars) < 2:
            result.windows.append(
                WindowResult(
                    window=window,
                    chosen_params=dict(strategy.params),
                    in_sample_net_percent=0.0,
                    out_of_sample_net_percent=0.0,
                    out_of_sample_max_drawdown=0.0,
                    out_of_sample_trades=0,
                    selected=False,
                    note="not enough bars in this window",
                )
            )
            continue

        # --- choose parameters on the in-sample stretch only -------------
        best_params = dict(strategy.params)
        best_score = -np.inf
        best_in_sample = 0.0
        selected = False

        for candidate in combinations:
            trial = run_backtest(
                _with_params(strategy, candidate), in_bars, config, funding=funding
            )
            stats = trial.stats
            if int(stats["total_trades"]) < MIN_TRADES_FOR_SELECTION:
                continue
            score = float(stats["net_profit_percent"])
            if score > best_score:
                best_score = score
                best_params = {**strategy.params, **candidate}
                best_in_sample = score
                selected = True

        note = "" if selected else "no parameter set traded enough in-sample"

        # --- test on the unseen stretch ----------------------------------
        out_result = run_backtest(
            _with_params(strategy, best_params), out_bars, config, funding=funding
        )
        out_stats = out_result.stats
        out_net = float(out_stats["net_profit_percent"])

        result.windows.append(
            WindowResult(
                window=window,
                chosen_params=best_params,
                in_sample_net_percent=best_in_sample,
                out_of_sample_net_percent=out_net,
                out_of_sample_max_drawdown=float(out_stats["max_drawdown_percent"]),
                out_of_sample_trades=int(out_stats["total_trades"]),
                selected=selected,
                note=note,
            )
        )

        in_sample_total += best_in_sample
        out_of_sample_total += out_net
        result.total_trades += int(out_stats["total_trades"])

        # Chain this window's equity on top of everything before it.
        window_start_equity = float(out_result.equity[0]) if out_result.equity.size else 1.0
        for index in range(out_result.equity.size):
            relative = float(out_result.equity[index]) / window_start_equity
            chained_time.append(int(out_result.equity_time[index]))
            chained_equity.append(equity_multiplier * relative * config.initial_capital)
        if out_result.equity.size:
            equity_multiplier *= float(out_result.equity[-1]) / window_start_equity

    if chained_equity:
        curve = np.array(chained_equity, dtype=np.float64)
        peaks = np.maximum.accumulate(curve)
        with np.errstate(divide="ignore", invalid="ignore"):
            underwater = np.where(peaks > 0, (curve - peaks) / peaks * 100.0, 0.0)

        result.chained_time = chained_time
        result.chained_equity = chained_equity
        result.chained_drawdown = underwater.tolist()
        result.total_net_percent = (
            (curve[-1] - config.initial_capital) / config.initial_capital * 100.0
        )
        result.max_drawdown_percent = float(np.min(underwater))

    # WFE compares what the chosen parameters delivered on unseen data with
    # what they promised in-sample. Undefined if in-sample never made money.
    result.walk_forward_efficiency = (
        out_of_sample_total / in_sample_total if in_sample_total > 0 else None
    )
    return result
