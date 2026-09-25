"""Running period comparisons and walk-forward analyses."""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from quanta_engine.backtest.engine import run_backtest
from quanta_engine.backtest.types import FundingEvent
from quanta_engine.forward.compare import compare_periods
from quanta_engine.forward.walkforward import run_walk_forward
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from quanta.exchanges.base import Interval
from quanta.models.setup import PIPELINE_STAGES, Setup, default_pipeline
from quanta.models.strategy import StrategyRecord
from quanta.services import market_store
from quanta.services.backtest_service import (
    MAX_BARS_PER_RUN,
    BacktestError,
    build_strategy,
    load_tiers,
    to_bars,
    to_config,
)

logger = structlog.get_logger(__name__)

# A comparison on fewer bars than this cannot say anything useful.
MIN_BARS_PER_PERIOD = 30


async def _load_period(
    db: AsyncSession,
    symbol: str,
    interval: Interval,
    start: int,
    end: int,
    *,
    apply_funding: bool,
) -> tuple[Any, list[FundingEvent]]:
    rows = await market_store.read_bars(
        db, symbol, interval, start=start, end=end, limit=MAX_BARS_PER_RUN
    )
    if len(rows) < MIN_BARS_PER_PERIOD:
        raise BacktestError(
            f"Only {len(rows)} stored bars for {symbol} {interval.value} in that "
            "period. Open the symbol on the chart so the history is downloaded, "
            "or choose a longer range."
        )

    bars = to_bars(rows)
    funding: list[FundingEvent] = []
    if apply_funding:
        settled = await market_store.read_funding(db, symbol, start=start, end=end)
        funding = [
            FundingEvent(time=entry.funding_time, rate=float(entry.funding_rate))
            for entry in settled
        ]
    return bars, funding


async def compare(
    db: AsyncSession,
    *,
    record: StrategyRecord,
    symbol: str,
    interval: str,
    reference: dict[str, Any],
    test: dict[str, Any],
    config_payload: dict[str, Any],
    runs: int,
    confidence: float,
) -> dict[str, Any]:
    """Run the same frozen strategy over two periods and compare them."""
    strategy = build_strategy(record)

    try:
        parsed = Interval(interval)
    except ValueError as exc:
        raise BacktestError(f"Unsupported interval {interval!r}.") from exc

    apply_funding = bool(config_payload.get("apply_funding", True))
    reference_bars, reference_funding = await _load_period(
        db, symbol, parsed, reference["start"], reference["end"], apply_funding=apply_funding
    )
    test_bars, test_funding = await _load_period(
        db, symbol, parsed, test["start"], test["end"], apply_funding=apply_funding
    )

    tiers = await load_tiers(symbol)
    config = to_config(config_payload, tiers)

    reference_result = run_backtest(strategy, reference_bars, config, funding=reference_funding)
    test_result = run_backtest(strategy, test_bars, config, funding=test_funding)

    comparison = compare_periods(
        reference=reference_result,
        reference_bars=reference_bars,
        reference_label=reference["label"],
        test=test_result,
        test_bars=test_bars,
        test_label=test["label"],
        initial_capital=config.initial_capital,
        runs=runs,
        confidence=confidence,
    )

    logger.info(
        "period_comparison",
        symbol=symbol,
        interval=parsed.value,
        verdict=str(comparison.verdict),
        reference_trades=reference_result.stats["total_trades"],
        test_trades=test_result.stats["total_trades"],
    )
    return comparison.to_dict()


async def walk_forward(
    db: AsyncSession,
    *,
    record: StrategyRecord,
    symbol: str,
    interval: str,
    start: int | None,
    end: int | None,
    in_sample_days: int,
    out_of_sample_days: int,
    max_windows: int,
    grid: dict[str, list[float]],
    config_payload: dict[str, Any],
) -> dict[str, Any]:
    strategy = build_strategy(record)

    try:
        parsed = Interval(interval)
    except ValueError as exc:
        raise BacktestError(f"Unsupported interval {interval!r}.") from exc

    rows = await market_store.read_bars(
        db, symbol, parsed, start=start, end=end, limit=MAX_BARS_PER_RUN
    )
    if len(rows) < MIN_BARS_PER_PERIOD:
        raise BacktestError(
            f"Only {len(rows)} stored bars for {symbol} {parsed.value}. "
            "Open the symbol on the chart so the history is downloaded."
        )

    bars = to_bars(rows)
    funding: list[FundingEvent] = []
    if config_payload.get("apply_funding", True):
        settled = await market_store.read_funding(
            db, symbol, start=int(bars.time[0]), end=int(bars.time[-1]) + 1
        )
        funding = [
            FundingEvent(time=entry.funding_time, rate=float(entry.funding_rate))
            for entry in settled
        ]

    tiers = await load_tiers(symbol)
    config = to_config(config_payload, tiers)

    try:
        result = run_walk_forward(
            strategy,
            bars,
            grid=grid,
            config=config,
            funding=funding,
            in_sample_days=in_sample_days,
            out_of_sample_days=out_of_sample_days,
            max_windows=max_windows,
        )
    except ValueError as exc:
        raise BacktestError(str(exc)) from exc

    logger.info(
        "walk_forward",
        symbol=symbol,
        windows=len(result.windows),
        wfe=result.walk_forward_efficiency,
    )
    return result.to_dict()


# --- Setups -------------------------------------------------------------


async def create_setup(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    record: StrategyRecord,
    payload: dict[str, Any],
) -> Setup:
    """Lock a strategy version into a Setup."""
    pipeline = default_pipeline()
    # A Setup created from a completed run has already cleared research and
    # backtest; recording that is what makes the overview meaningful.
    if payload.get("source_run_id"):
        for stage in ("research", "backtest"):
            pipeline[stage]["status"] = "passed"

    setup = Setup(
        user_id=user_id,
        name=payload["name"],
        color=payload.get("color", "#6EA8FE"),
        strategy_id=record.id,
        strategy_version=record.version,
        strategy_snapshot={
            "name": record.name,
            "long_entry": record.long_entry,
            "short_entry": record.short_entry,
            "exits": record.exits,
            "params": record.params,
        },
        symbol=payload["symbol"].upper(),
        interval=payload["interval"],
        margin_percent=payload["margin_percent"],
        leverage=payload["leverage"],
        margin_mode=payload.get("margin_mode", "isolated"),
        fee_tier=payload.get("fee_tier", "VIP0"),
        maker_fee=payload.get("maker_fee", 0.0002),
        taker_fee=payload.get("taker_fee", 0.0006),
        max_drawdown_budget_percent=payload.get("max_drawdown_budget_percent"),
        risk_of_ruin_limit_percent=payload.get("risk_of_ruin_limit_percent"),
        source_run_id=payload.get("source_run_id"),
        pipeline=pipeline,
        use_in_backtest=payload.get("use_in_backtest", True),
        use_in_forward=payload.get("use_in_forward", True),
        use_in_paper=payload.get("use_in_paper", False),
        use_in_alerts=payload.get("use_in_alerts", False),
        # Never settable from the client: the bot stage unlocks only when
        # paper trading passes (SPEC §3.3).
        use_in_bot=False,
    )
    db.add(setup)
    await db.flush()
    return setup


def advance_stage(setup: Setup, stage: str, status: str, note: str = "") -> None:
    """Record progress through the pipeline.

    Marking paper as passed is what unlocks the bot, so the gate lives here
    rather than only in the UI where it could be bypassed.
    """
    from datetime import UTC, datetime

    if stage not in PIPELINE_STAGES:
        raise BacktestError(f"Unknown stage {stage!r}.")

    pipeline = dict(setup.pipeline or default_pipeline())
    pipeline[stage] = {
        "status": status,
        "updated_at": datetime.now(UTC).isoformat(),
        "note": note,
    }
    setup.pipeline = pipeline

    if stage == "paper":
        setup.use_in_bot = status == "passed"
        if status == "passed":
            setup.use_in_paper = True


async def list_setups(
    db: AsyncSession, user_id: uuid.UUID, *, include_archived: bool = False
) -> list[Setup]:
    query = select(Setup).where(Setup.user_id == user_id)
    if not include_archived:
        query = query.where(Setup.archived_at.is_(None))
    result = await db.execute(query.order_by(Setup.created_at.desc()))
    return list(result.scalars().all())


def find_conflicts(setups: list[Setup]) -> list[dict[str, Any]]:
    """Risks that only appear across Setups (SPEC §3.2).

    Two Setups trading the same symbol on one account in one-way mode will
    fight each other: one closes the other's position. The exchange will not
    refuse it, so the warning has to come from here.
    """
    conflicts: list[dict[str, Any]] = []

    by_symbol: dict[str, list[Setup]] = {}
    for setup in setups:
        by_symbol.setdefault(setup.symbol, []).append(setup)

    for symbol, group in by_symbol.items():
        live = [s for s in group if s.use_in_bot or s.use_in_paper]
        if len(live) > 1:
            conflicts.append(
                {
                    "kind": "same_symbol",
                    "message": (
                        f"{len(live)} setups trade {symbol} on the same account. "
                        "Use hedge mode or sub-accounts, or they will close each "
                        "other's positions."
                    ),
                    "setup_ids": [s.id for s in live],
                }
            )

    total_exposure = sum(setup.exposure for setup in setups if setup.use_in_bot)
    if total_exposure > 100:
        conflicts.append(
            {
                "kind": "exposure",
                "message": (
                    f"Live setups commit {total_exposure:.0f}% of equity as "
                    "exposure. A simultaneous adverse move would hit all of them."
                ),
                "setup_ids": [s.id for s in setups if s.use_in_bot],
            }
        )

    budgeted = [s for s in setups if s.max_drawdown_budget_percent is not None and s.use_in_bot]
    if len(budgeted) > 1:
        combined = sum(float(s.max_drawdown_budget_percent or 0) for s in budgeted)
        if combined < -50:
            conflicts.append(
                {
                    "kind": "drawdown_budget",
                    "message": (
                        f"Combined drawdown budgets total {combined:.0f}%. "
                        "Drawdowns rarely arrive one at a time."
                    ),
                    "setup_ids": [s.id for s in budgeted],
                }
            )

    return conflicts


def total_exposure(setups: list[Setup]) -> float:
    return sum(setup.exposure for setup in setups)
