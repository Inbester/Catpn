"""Running the research studies against stored market data (SPEC §3.2)."""

from __future__ import annotations

from typing import Any

import numpy as np
import structlog
from quanta_engine.backtest.engine import run_backtest
from quanta_engine.backtest.types import BacktestConfig, Bars, FundingEvent
from quanta_engine.dsl.errors import DslError
from quanta_engine.research import (
    analyse_trades,
    compare_margin_modes,
    holding_histogram,
    parameter_surface,
    reshuffled_years,
    risk_measures,
    stress_tests,
    sweep_leverage,
)
from sqlalchemy.ext.asyncio import AsyncSession

from quanta.exchanges.base import Interval
from quanta.models.strategy import StrategyRecord
from quanta.services import market_store
from quanta.services.backtest_service import (
    BacktestError,
    build_strategy,
    load_tiers,
    to_bars,
    to_config,
)

logger = structlog.get_logger(__name__)

MAX_BARS = 200_000
# A sweep runs one backtest per cell, so the grid is capped rather than
# left to the caller: 12 x 12 is already 144 full runs.
MAX_CELLS = 144


async def _load(
    db: AsyncSession,
    symbol: str,
    interval: str,
    start: int | None,
    end: int | None,
    *,
    apply_funding: bool,
) -> tuple[Bars, list[FundingEvent]]:
    try:
        parsed = Interval(interval)
    except ValueError as exc:
        raise BacktestError(f"Unsupported interval {interval!r}.") from exc

    rows = await market_store.read_bars(db, symbol, parsed, start=start, end=end, limit=MAX_BARS)
    if len(rows) < 2:
        raise BacktestError(
            f"No stored bars for {symbol} {interval}. Open it on the chart first "
            "so the history is downloaded."
        )
    bars = to_bars(rows)

    funding: list[FundingEvent] = []
    if apply_funding:
        settled = await market_store.read_funding(
            db, symbol, start=int(bars.time[0]), end=int(bars.time[-1]) + 1
        )
        funding = [
            FundingEvent(time=entry.funding_time, rate=float(entry.funding_rate))
            for entry in settled
        ]
    return bars, funding


async def _prepare(
    db: AsyncSession,
    record: StrategyRecord,
    symbol: str,
    interval: str,
    start: int | None,
    end: int | None,
    config_payload: dict[str, Any],
) -> tuple[Any, Bars, list[FundingEvent], BacktestConfig]:
    strategy = build_strategy(record)
    bars, funding = await _load(
        db,
        symbol,
        interval,
        start,
        end,
        apply_funding=bool(config_payload.get("apply_funding", True)),
    )
    config = to_config(config_payload, await load_tiers(symbol))
    return strategy, bars, funding, config


async def leverage_study(
    db: AsyncSession,
    *,
    record: StrategyRecord,
    symbol: str,
    interval: str,
    start: int | None,
    end: int | None,
    margins: list[float],
    leverages: list[float],
    budget_percent: float | None,
    config_payload: dict[str, Any],
) -> dict[str, Any]:
    """The margin x leverage surface, plus isolated against cross."""
    if len(margins) * len(leverages) > MAX_CELLS:
        raise BacktestError(
            f"{len(margins) * len(leverages)} cells is more than the {MAX_CELLS} "
            "an interactive sweep runs. Narrow the ranges or widen the steps."
        )

    strategy, bars, funding, config = await _prepare(
        db, record, symbol, interval, start, end, config_payload
    )

    try:
        sweep = sweep_leverage(
            strategy,
            bars,
            margins=margins,
            leverages=leverages,
            config=config,
            funding=funding,
            budget_percent=budget_percent,
        )
    except DslError as exc:
        raise BacktestError(str(exc)) from exc

    pick = sweep.recommendation.cell
    modes = compare_margin_modes(
        strategy,
        bars,
        margin_percent=pick.margin_percent if pick else config.margin_percent,
        leverage=pick.leverage if pick else config.leverage,
        config=config,
        funding=funding,
    )

    return {
        "symbol": symbol,
        "interval": interval,
        "strategy_version": record.version,
        "bars": len(bars),
        "budget_percent": budget_percent,
        "cells": [_cell(cell) for cell in sweep.cells],
        "recommendation": {
            "cell": _cell(pick) if pick else None,
            "reason": sweep.recommendation.reason,
            "best_net_cell": (
                _cell(sweep.recommendation.best_net_cell)
                if sweep.recommendation.best_net_cell
                else None
            ),
        },
        "margin_modes": [
            {
                "margin_mode": row.margin_mode,
                "exposure": row.exposure,
                "liquidation_distance_percent": row.liquidation_distance_percent,
                "net_percent": row.net_percent,
                "max_drawdown_percent": row.max_drawdown_percent,
                "worst_trade_percent": row.worst_trade_percent,
                "liquidations": row.liquidations,
                "costs_over_gross": row.costs_over_gross,
                "risk_of_ruin_percent": row.risk_of_ruin_percent,
            }
            for row in modes
        ],
    }


def _cell(cell: Any) -> dict[str, Any]:
    return {
        "margin_percent": cell.margin_percent,
        "leverage": cell.leverage,
        "net_percent": cell.net_percent,
        "annualised_percent": cell.annualised_percent,
        "max_drawdown_percent": cell.max_drawdown_percent,
        "liquidations": cell.liquidations,
        "trades": cell.trades,
        "costs_over_gross": cell.costs_over_gross,
        "worst_trade_percent": cell.worst_trade_percent,
        "exposure": cell.exposure,
    }


async def trade_risk_study(
    db: AsyncSession,
    *,
    record: StrategyRecord,
    symbol: str,
    interval: str,
    start: int | None,
    end: int | None,
    config_payload: dict[str, Any],
) -> dict[str, Any]:
    """MAE scatter and the dip KPIs (SPEC §3.2)."""
    strategy, bars, funding, config = await _prepare(
        db, record, symbol, interval, start, end, config_payload
    )
    try:
        result = run_backtest(strategy, bars, config, funding=funding)
    except DslError as exc:
        raise BacktestError(str(exc)) from exc

    risk = analyse_trades(result.trades)
    return {
        "symbol": symbol,
        "interval": interval,
        "strategy_version": record.version,
        "points": [
            {
                "index": p.index,
                "side": p.side,
                "entry_time": p.entry_time,
                "bars_held": p.bars_held,
                "adverse_percent": p.adverse_percent,
                "favourable_percent": p.favourable_percent,
                "result_percent": p.result_percent,
                "funding_paid": p.funding_paid,
                "was_liquidated": p.was_liquidated,
                "recovered": p.recovered,
            }
            for p in risk.points
        ],
        "kpis": {
            "winners": risk.winners,
            "winners_that_were_red": risk.winners_that_were_red,
            "median_dip_percent": risk.median_dip_percent,
            "p95_dip_percent": risk.p95_dip_percent,
            "deepest_dip_percent": risk.deepest_dip_percent,
            "survives_up_to_leverage": risk.survives_up_to_leverage,
            "worst_closed_trade_percent": risk.worst_closed_trade_percent,
            "average_bars_held": risk.average_bars_held,
            "funding_events": risk.funding_events,
            "total_funding": risk.total_funding,
        },
        "holding": holding_histogram(risk.points),
    }


async def robustness_study(
    db: AsyncSession,
    *,
    record: StrategyRecord,
    symbol: str,
    interval: str,
    start: int | None,
    end: int | None,
    grid: dict[str, list[float]],
    config_payload: dict[str, Any],
) -> dict[str, Any]:
    """Stress cases, reshuffled years, tail risk and the parameter surface."""
    strategy, bars, funding, config = await _prepare(
        db, record, symbol, interval, start, end, config_payload
    )
    try:
        result = run_backtest(strategy, bars, config, funding=funding)
        cases = stress_tests(strategy, bars, config=config, funding=funding)
        surface = parameter_surface(strategy, bars, grid=grid, config=config, funding=funding)
    except DslError as exc:
        raise BacktestError(str(exc)) from exc

    equity_before = [t.equity_after - t.net_pnl for t in result.trades]
    returns = np.array(
        [
            t.net_pnl / before if before > 0 else 0.0
            for t, before in zip(result.trades, equity_before, strict=True)
        ],
        dtype=np.float64,
    )
    span_ms = int(bars.time[-1] - bars.time[0]) or 1
    per_year = max(1, int(len(result.trades) * (365 * 24 * 3_600_000) / span_ms))

    measures = risk_measures(returns)
    return {
        "symbol": symbol,
        "interval": interval,
        "strategy_version": record.version,
        "stress": [
            {
                "name": case.name,
                "description": case.description,
                "net_percent": case.net_percent,
                "max_drawdown_percent": case.max_drawdown_percent,
                "trades": case.trades,
                "delta_percent": case.delta_percent,
                "survived": case.survived,
                "adverse": case.adverse,
            }
            for case in cases
        ],
        "reshuffled": reshuffled_years(returns, trades_per_year=per_year),
        "trades_per_year": per_year,
        "risk": {
            "var_95_percent": measures.var_95_percent,
            "cvar_95_percent": measures.cvar_95_percent,
            "kelly_fraction": measures.kelly_fraction,
            "half_kelly_fraction": measures.half_kelly_fraction,
        },
        "surface": {
            "points": [
                {
                    "params": point.params,
                    "net_percent": point.net_percent,
                    "max_drawdown_percent": point.max_drawdown_percent,
                    "trades": point.trades,
                }
                for point in surface.points
            ],
            "best": (
                {
                    "params": surface.best.params,
                    "net_percent": surface.best.net_percent,
                    "max_drawdown_percent": surface.best.max_drawdown_percent,
                    "trades": surface.best.trades,
                }
                if surface.best
                else None
            ),
            "neighbourhood_mean_percent": surface.neighbourhood_mean_percent,
            "plateau": surface.plateau,
        },
    }
