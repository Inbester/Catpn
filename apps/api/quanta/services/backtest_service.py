"""Running backtests against stored market data."""

from __future__ import annotations

import time
import uuid
from typing import Any

import numpy as np
import structlog
from quanta_engine.backtest.engine import run_backtest
from quanta_engine.backtest.liquidation import FLAT_TIER, PositionTier
from quanta_engine.backtest.types import BacktestConfig, Bars, FundingEvent
from quanta_engine.dsl.errors import DslError
from quanta_engine.strategy import ExitRules, MarginMode, Strategy
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from quanta.exchanges.base import Interval
from quanta.models.strategy import BacktestRun, StrategyRecord
from quanta.services import market_store

logger = structlog.get_logger(__name__)

# A backtest is synchronous for now; phase 4 moves long runs to the job
# runner. This cap keeps a single request from occupying a worker.
MAX_BARS_PER_RUN = 200_000
# Loading 1m bars for the magnifier over a long range is expensive, so it
# is skipped past this many bars rather than silently timing out.
MAX_MAGNIFIER_BARS = 500_000


class BacktestError(Exception):
    """A run that could not start, with a message safe to show the user."""


def build_strategy(record: StrategyRecord) -> Strategy:
    """Turn a stored row into an engine strategy, validating it."""
    try:
        strategy = Strategy(
            name=record.name,
            long_entry=record.long_entry,
            short_entry=record.short_entry,
            exits=ExitRules(**(record.exits or {})),
            params=dict(record.params or {}),
        )
        strategy.validate()
    except (DslError, ValueError, TypeError) as exc:
        raise BacktestError(str(exc)) from exc
    return strategy


def _to_bars(rows: list[Any]) -> Bars:
    return Bars(
        time=np.array([bar.open_time for bar in rows], dtype=np.int64),
        open=np.array([float(bar.open) for bar in rows], dtype=np.float64),
        high=np.array([float(bar.high) for bar in rows], dtype=np.float64),
        low=np.array([float(bar.low) for bar in rows], dtype=np.float64),
        close=np.array([float(bar.close) for bar in rows], dtype=np.float64),
        volume=np.array([float(bar.volume) for bar in rows], dtype=np.float64),
    )


def _to_config(payload: dict[str, Any], tiers: tuple[PositionTier, ...]) -> BacktestConfig:
    return BacktestConfig(
        initial_capital=float(payload.get("initial_capital", 10_000.0)),
        margin_percent=float(payload.get("margin_percent", 10.0)),
        leverage=float(payload.get("leverage", 10.0)),
        margin_mode=MarginMode(payload.get("margin_mode", "isolated")),
        maker_fee=float(payload.get("maker_fee", 0.0002)),
        taker_fee=float(payload.get("taker_fee", 0.0006)),
        slippage_bps=float(payload.get("slippage_bps", 1.0)),
        apply_funding=bool(payload.get("apply_funding", True)),
        tiers=tiers,
    )


async def _load_tiers(symbol: str) -> tuple[PositionTier, ...]:
    """The venue's maintenance-margin ladder, or a flat fallback.

    A flat rate understates liquidation risk on large positions, so the real
    ladder is used whenever the exchange is reachable.
    """
    from quanta.api.market_runtime import get_market_service

    service = get_market_service()
    if service is None:
        return FLAT_TIER

    try:
        rows = await service.adapter.position_tiers(symbol)
    except Exception as exc:  # the venue being down must not block a backtest
        logger.warning("position_tiers_unavailable", symbol=symbol, error=str(exc))
        return FLAT_TIER

    if not rows:
        return FLAT_TIER

    return tuple(
        PositionTier(
            level=row.level,
            start_value=float(row.start_value),
            end_value=float(row.end_value),
            max_leverage=row.leverage,
            maintenance_margin_rate=float(row.maintenance_margin_rate),
        )
        for row in rows
    )


async def run(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    record: StrategyRecord,
    symbol: str,
    interval: str,
    start: int | None,
    end: int | None,
    config_payload: dict[str, Any],
) -> BacktestRun:
    """Run a backtest and store the result."""
    strategy = build_strategy(record)

    try:
        parsed_interval = Interval(interval)
    except ValueError as exc:
        raise BacktestError(f"Unsupported interval {interval!r}.") from exc

    rows = await market_store.read_bars(
        db, symbol, parsed_interval, start=start, end=end, limit=MAX_BARS_PER_RUN
    )
    if len(rows) < 2:
        raise BacktestError(
            f"No stored bars for {symbol} {interval}. Open it on the chart first "
            "so the history is downloaded."
        )

    bars = _to_bars(rows)

    funding: list[FundingEvent] = []
    if config_payload.get("apply_funding", True):
        settled = await market_store.read_funding(
            db, symbol, start=int(bars.time[0]), end=int(bars.time[-1]) + 1
        )
        funding = [
            FundingEvent(time=entry.funding_time, rate=float(entry.funding_rate))
            for entry in settled
        ]

    magnifier: Bars | None = None
    if config_payload.get("use_magnifier", True) and parsed_interval is not Interval.M1:
        span_minutes = (int(bars.time[-1]) - int(bars.time[0])) // 60_000
        if span_minutes <= MAX_MAGNIFIER_BARS:
            minute_rows = await market_store.read_bars(
                db,
                symbol,
                Interval.M1,
                start=int(bars.time[0]),
                end=int(bars.time[-1]) + parsed_interval.milliseconds,
                limit=MAX_MAGNIFIER_BARS,
            )
            if len(minute_rows) > 1:
                magnifier = _to_bars(minute_rows)

    tiers = await _load_tiers(symbol)
    config = _to_config(config_payload, tiers)

    started = time.perf_counter()
    try:
        result = run_backtest(strategy, bars, config, funding=funding, magnifier=magnifier)
    except DslError as exc:
        raise BacktestError(str(exc)) from exc
    duration_ms = int((time.perf_counter() - started) * 1000)

    payload = result.to_dict()
    run_row = BacktestRun(
        user_id=user_id,
        strategy_id=record.id,
        strategy_version=result.strategy_version,
        symbol=symbol,
        interval=parsed_interval.value,
        start_time=int(bars.time[0]),
        end_time=int(bars.time[-1]),
        config={**config_payload, "magnifier_used": magnifier is not None},
        stats=payload["stats"],
        trades=payload["trades"],
        equity=payload["equity"],
        duration_ms=duration_ms,
    )
    db.add(run_row)
    await db.flush()

    logger.info(
        "backtest_complete",
        symbol=symbol,
        interval=parsed_interval.value,
        bars=len(bars),
        trades=len(result.trades),
        duration_ms=duration_ms,
        magnifier=magnifier is not None,
    )
    return run_row


async def list_runs(
    db: AsyncSession, user_id: uuid.UUID, *, strategy_id: uuid.UUID | None = None, limit: int = 50
) -> list[BacktestRun]:
    query = select(BacktestRun).where(BacktestRun.user_id == user_id)
    if strategy_id is not None:
        query = query.where(BacktestRun.strategy_id == strategy_id)
    result = await db.execute(query.order_by(BacktestRun.created_at.desc()).limit(limit))
    return list(result.scalars().all())


def trades_to_csv(trades: list[dict[str, Any]]) -> str:
    """CSV export for the list of trades (SPEC §3.3)."""
    import csv
    import io

    columns = [
        "side",
        "entry_time",
        "entry_price",
        "exit_time",
        "exit_price",
        "quantity",
        "leverage",
        "exit_reason",
        "gross_pnl",
        "fees",
        "funding",
        "net_pnl",
        "return_on_margin",
        "run_up",
        "drawdown",
        "bars_held",
        "equity_after",
    ]

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for trade in trades:
        writer.writerow(trade)
    return buffer.getvalue()
