"""Paper trading and the promotion checklist (SPEC §3.3)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from quanta.models.paper import PaperFill, PaperSession
from quanta.models.setup import Setup

logger = structlog.get_logger(__name__)

# SPEC §3.3 fixes these. They are the difference between "it works" and
# something a bot may act on.
MIN_DAYS = 14
MIN_TRADES = 30
MAX_DRIFT_PERCENT = 0.025


@dataclass(frozen=True, slots=True)
class Check:
    key: str
    label: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class Promotion:
    checks: list[Check]
    ready: bool
    # What it would take, said plainly, when it is not ready.
    blocking: list[str]


def execution_quality(fills: list[PaperFill]) -> dict[str, Any]:
    """What the live feed cost that a backtest had to assume.

    Drift is the mean signed slippage: a backtest charges a fixed
    slippage in one direction, and this is how far reality differed from
    that assumption on average. It is the number the checklist gates on,
    because a strategy whose edge is smaller than its drift has no edge.
    """
    if not fills:
        return {
            "fills": 0,
            "mean_latency_ms": 0.0,
            "mean_slippage_bps": 0.0,
            "drift_percent": 0.0,
            "total_fees": 0.0,
            "total_funding": 0.0,
        }

    count = len(fills)
    slippage = [float(f.slippage_bps) for f in fills]
    mean_slippage = sum(slippage) / count
    return {
        "fills": count,
        "mean_latency_ms": sum(f.latency_ms for f in fills) / count,
        "mean_slippage_bps": mean_slippage,
        # Basis points to percent.
        "drift_percent": abs(mean_slippage) / 100.0,
        "total_fees": sum(float(f.fee) for f in fills),
        "total_funding": sum(float(f.funding) for f in fills),
    }


def evaluate_promotion(
    session: PaperSession,
    fills: list[PaperFill],
    *,
    now: datetime | None = None,
) -> Promotion:
    """The five checks SPEC §3.3 names, each answered with its evidence."""
    now = now or datetime.now(UTC)
    started = session.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    days = (now - started).total_seconds() / 86_400.0

    quality = execution_quality(fills)
    net_percent = (
        (float(session.equity) - float(session.initial_capital))
        / float(session.initial_capital)
        * 100.0
        if float(session.initial_capital) > 0
        else 0.0
    )

    low = session.expected_low_percent
    high = session.expected_high_percent
    inside_cone = low is not None and high is not None and float(low) <= net_percent <= float(high)

    drawdown = _max_drawdown_percent(session, fills)
    limit = session.drawdown_limit_percent

    checks = [
        Check(
            "days",
            f"At least {MIN_DAYS} days running",
            days >= MIN_DAYS,
            f"{days:.1f} days so far",
        ),
        Check(
            "trades",
            f"At least {MIN_TRADES} trades",
            len(fills) >= MIN_TRADES,
            f"{len(fills)} fills so far",
        ),
        Check(
            "cone",
            "Inside the expected range",
            inside_cone,
            (
                f"{net_percent:+.2f}% against {float(low):+.1f}% to {float(high):+.1f}%"
                if low is not None and high is not None
                else "no expected range was recorded, so there is nothing to be inside"
            ),
        ),
        Check(
            "drawdown",
            "Drawdown under the limit",
            limit is None or drawdown >= float(limit),
            (
                f"{drawdown:.2f}% against a {float(limit):.1f}% limit"
                if limit is not None
                else f"{drawdown:.2f}%, no limit set"
            ),
        ),
        Check(
            "drift",
            f"Execution drift at most {MAX_DRIFT_PERCENT}%",
            quality["drift_percent"] <= MAX_DRIFT_PERCENT,
            f"{quality['drift_percent']:.4f}% mean slippage against the assumption",
        ),
    ]

    blocking = [check.label for check in checks if not check.passed]
    return Promotion(checks=checks, ready=not blocking, blocking=blocking)


def _max_drawdown_percent(session: PaperSession, fills: list[PaperFill]) -> float:
    """Deepest peak-to-trough on the paper equity curve, as a negative."""
    equity = [float(session.initial_capital)] + [float(f.equity_after) for f in fills]
    peak = equity[0]
    worst = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, (value - peak) / peak * 100.0)
    return worst


async def session_summary(
    db: AsyncSession, session: PaperSession, *, now: datetime | None = None
) -> dict[str, Any]:
    """Everything the paper panel shows for one session."""
    result = await db.execute(
        select(PaperFill)
        .where(PaperFill.session_id == session.id)
        .order_by(PaperFill.filled_at.asc())
    )
    fills = list(result.scalars().all())
    promotion = evaluate_promotion(session, fills, now=now)
    capital = float(session.initial_capital)
    net_percent = (float(session.equity) - capital) / capital * 100.0 if capital > 0 else 0.0

    return {
        "id": str(session.id),
        "setup_id": str(session.setup_id),
        "state": session.state,
        "started_at": session.started_at.isoformat(),
        "initial_capital": capital,
        "equity": float(session.equity),
        "net_percent": net_percent,
        "max_drawdown_percent": _max_drawdown_percent(session, fills),
        "missed_signals": session.missed_signals,
        "expected": {
            "net_percent": _optional(session.expected_net_percent),
            "low_percent": _optional(session.expected_low_percent),
            "high_percent": _optional(session.expected_high_percent),
            "drawdown_limit_percent": _optional(session.drawdown_limit_percent),
        },
        "execution": execution_quality(fills),
        "equity_curve": [{"time": int(f.bar_time), "equity": float(f.equity_after)} for f in fills],
        "promotion": {
            "ready": promotion.ready,
            "blocking": promotion.blocking,
            "checks": [
                {
                    "key": c.key,
                    "label": c.label,
                    "passed": c.passed,
                    "detail": c.detail,
                }
                for c in promotion.checks
            ],
        },
        "promoted_at": session.promoted_at.isoformat() if session.promoted_at else None,
        "promoted_by_override": session.promoted_by_override,
    }


def _optional(value: Any) -> float | None:
    return None if value is None else float(value)


class PromotionError(Exception):
    """A promotion that is not allowed, with the reason to show."""


async def promote(
    db: AsyncSession,
    session: PaperSession,
    setup: Setup,
    *,
    override: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Unlock the bot stage for this Setup.

    The override exists because SPEC §3.3 allows it behind 2FA, but it is
    recorded: a bot promoted past a failing check is not the same thing as
    one that passed, and whoever looks at it later needs to know which.
    """
    now = now or datetime.now(UTC)
    result = await db.execute(select(PaperFill).where(PaperFill.session_id == session.id))
    fills = list(result.scalars().all())
    promotion = evaluate_promotion(session, fills, now=now)

    if not promotion.ready and not override:
        raise PromotionError("Not ready: " + "; ".join(promotion.blocking).lower() + ".")

    session.state = "promoted"
    session.promoted_at = now
    session.promoted_by_override = not promotion.ready
    # The gate SPEC §3.3 puts in the data, not only in the UI.
    setup.use_in_bot = True
    setup.use_in_paper = True
    pipeline = dict(setup.pipeline or {})
    pipeline["paper"] = {
        "status": "passed",
        "updated_at": now.isoformat(),
        "note": "promoted with an override" if session.promoted_by_override else "",
    }
    setup.pipeline = pipeline

    return await session_summary(db, session, now=now)


async def count_active(db: AsyncSession, user_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(PaperSession)
        .where(PaperSession.user_id == user_id, PaperSession.state == "running")
    )
    return int(result.scalar_one())
