"""Evaluating alerts on the server (SPEC §3.4).

The evaluator runs on bar close, against bars already stored, and it never
looks at the bar that is still forming. That is the whole reason bar close
is the default: a rule evaluated mid-bar can un-fire — the condition holds,
the bar turns, and the signal was never real. An alert that repaints is a
lie told in real time, and nobody can check it afterwards because the bar
it fired on no longer exists.

Repeat rules and quiet hours are applied here rather than at the notifier,
because both are decisions about whether this firing counts at all. A
suppressed firing is still recorded — the user needs to see that their own
"once" rule is why the second signal never arrived.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import structlog
from quanta_engine.dsl.errors import DslError
from quanta_engine.dsl.evaluator import evaluate
from quanta_engine.dsl.parser import parse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from quanta.exchanges.base import Interval
from quanta.models.alert import Alert, AlertEvent
from quanta.models.setup import Setup
from quanta.services import market_store
from quanta.services.alert_templates import build_context, render
from quanta.services.backtest_service import to_bars

logger = structlog.get_logger(__name__)

# Enough history for the indicators an alert expression can reach for.
EVALUATION_BARS = 400

# SPEC §3.4: signals inside this window become one message.
BURST_WINDOW_SECONDS = 10


class AlertError(Exception):
    """An alert that cannot be evaluated, with a message safe to show."""


def _tehran_time(moment: datetime) -> str:
    """Tehran is UTC+3:30, and does not observe DST since 1402."""
    return (moment + timedelta(hours=3, minutes=30)).strftime("%Y-%m-%d %H:%M")


def in_quiet_hours(alert: Alert, moment: datetime) -> bool:
    """Whether this firing lands in the user's quiet window.

    Quiet means sent silently, not skipped — a missed alert is not quiet,
    it is lost. The window may wrap midnight, which is the common case.
    """
    if alert.quiet_from_hour is None or alert.quiet_to_hour is None:
        return False
    hour = moment.hour
    start, end = alert.quiet_from_hour, alert.quiet_to_hour
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def may_fire(alert: Alert, bar_time: int, now: datetime) -> tuple[bool, str]:
    """Whether the repeat rule and expiry allow this firing."""
    if not alert.enabled:
        return False, "the alert is switched off"
    if alert.expires_at is not None and now >= alert.expires_at:
        return False, "the alert has expired"

    if alert.repeat_mode == "once" and alert.fire_count > 0:
        return False, "set to fire once, and it already has"
    if alert.repeat_mode == "once_per_bar" and alert.last_fired_bar == bar_time:
        return False, "already fired on this bar"
    return True, ""


def _condition_signal(
    alert: Alert, bars: Any, setup: Setup | None
) -> tuple[bool, dict[str, float]]:
    """Whether the alert's condition holds on the last closed bar."""
    source = alert.source
    close = bars.close
    if close.size == 0:
        return False, {}
    last = float(close[-1])
    previous = float(close[-2]) if close.size > 1 else last

    if source == "price":
        level = float(alert.condition.get("price", 0.0))
        direction = str(alert.condition.get("direction", "above"))
        if direction == "above":
            # A crossing, not a state: "price above 68,000" would fire on
            # every bar it stayed there, which is a stream, not an alert.
            return previous <= level < last, {"level": level}
        return previous >= level > last, {"level": level}

    if source == "market":
        rate = float(alert.condition.get("funding_rate", 0.0))
        observed = float(alert.condition.get("observed", 0.0))
        return abs(observed) >= abs(rate), {"funding_rate": observed}

    if source in {"indicator", "strategy"}:
        expression = str(alert.condition.get("expression", "")).strip()
        if not expression and setup is not None:
            snapshot = setup.strategy_snapshot or {}
            side = str(alert.condition.get("side", "long"))
            expression = str(snapshot.get(f"{side}_entry", "")).strip()
        if not expression:
            raise AlertError("This alert has no condition to evaluate.")

        params = dict(alert.condition.get("params", {}))
        if setup is not None:
            params = {**(setup.strategy_snapshot or {}).get("params", {}), **params}
        try:
            series = evaluate(parse(expression), bars, params)
        except DslError as exc:
            raise AlertError(str(exc)) from exc

        values = np.asarray(series, dtype=np.float64)
        if values.size == 0:
            return False, {}
        return bool(values[-1] > 0.5), {}

    # Risk and system alerts are fed by the bot and the runtime rather
    # than by bars; they arrive already decided.
    return bool(alert.condition.get("fired", False)), {}


async def evaluate_alert(
    db: AsyncSession, alert: Alert, *, now: datetime | None = None
) -> AlertEvent | None:
    """Evaluate one alert on its last closed bar.

    Returns the event when it fired, or None. A suppressed firing is
    recorded with its reason rather than dropped, so the activity view can
    explain a signal that never arrived.
    """
    now = now or datetime.now(UTC)
    try:
        interval = Interval(alert.interval)
    except ValueError as exc:
        raise AlertError(f"Unsupported interval {alert.interval!r}.") from exc

    rows = await market_store.read_bars(db, alert.symbol, interval, limit=EVALUATION_BARS)
    # Never the forming bar: a condition that holds mid-bar can stop
    # holding before the bar closes, and the signal was never real.
    closed = [row for row in rows if row.closed]
    if len(closed) < 2:
        return None

    bars = to_bars(closed)
    bar_time = int(bars.time[-1])

    setup: Setup | None = None
    if alert.setup_id is not None:
        setup = await db.get(Setup, alert.setup_id)

    fired, extra = _condition_signal(alert, bars, setup)
    if not fired:
        return None

    allowed, reason = may_fire(alert, bar_time, now)
    price = float(bars.close[-1])
    quiet = in_quiet_hours(alert, now)

    context = build_context(
        side=str(alert.condition.get("side", "long")),
        symbol=alert.symbol,
        interval=alert.interval,
        price=price,
        strategy=setup.name if setup else alert.name,
        version=setup.strategy_version if setup else "",
        size=f"{setup.margin_percent:g}%" if setup else "",
        leverage=f"{setup.leverage:g}x" if setup else "",
        indicators=extra,
        time_tehran=_tehran_time(now),
        chart_link=f"/chart?symbol={alert.symbol}&interval={alert.interval}",
    )

    event = AlertEvent(
        alert_id=alert.id,
        user_id=alert.user_id,
        bar_time=bar_time,
        price=f"{price:g}",
        message=render(alert.template, context, alert.locale),
        context=context,
        quiet=quiet,
        deliveries=[],
    )

    if not allowed:
        # Recorded, not dropped: the user needs to see that their own
        # "once" rule is why the second signal never arrived.
        event.deliveries = [
            {"kind": destination.get("kind", "?"), "state": "suppressed", "note": reason}
            for destination in alert.destinations
        ] or [{"kind": "none", "state": "suppressed", "note": reason}]
        db.add(event)
        return event

    alert.last_fired_at = now
    alert.last_fired_bar = bar_time
    alert.fire_count += 1
    db.add(event)
    return event


async def due_alerts(db: AsyncSession, *, now: datetime | None = None) -> list[Alert]:
    """Alerts that should be looked at, oldest firing first."""
    now = now or datetime.now(UTC)
    result = await db.execute(
        select(Alert)
        .where(Alert.enabled.is_(True))
        .order_by(Alert.last_fired_at.asc().nulls_first())
    )
    alerts = list(result.scalars().all())
    return [a for a in alerts if a.expires_at is None or a.expires_at > now]


async def recent_events(
    db: AsyncSession, user_id: uuid.UUID, *, limit: int = 100
) -> list[AlertEvent]:
    result = await db.execute(
        select(AlertEvent)
        .where(AlertEvent.user_id == user_id)
        .order_by(AlertEvent.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
