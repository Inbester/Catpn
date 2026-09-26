"""The loop that makes alerts fire with the browser closed (SPEC §3.4).

One pass over every enabled alert, on a tick short enough that a bar close
is noticed promptly. SPEC §8 sets the target: a signal reaches a Telegram
group within two seconds of bar close. Most of that budget is the network;
the evaluation itself is milliseconds against bars already in Timescale.

Burst merge lives here because it is a decision about a *group* of
firings, which neither the evaluator (one alert at a time) nor the
notifier (one destination at a time) can see.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from quanta.models.alert import AlertEvent
from quanta.services import alert_service
from quanta.services.alert_templates import merge_messages
from quanta.services.notifier import Notifier

logger = structlog.get_logger(__name__)

# Short enough that a 1m bar close is noticed promptly, long enough that
# an idle account costs almost nothing.
TICK_SECONDS = 2.0


async def run_once(
    db: AsyncSession, notifier: Notifier, *, now: datetime | None = None
) -> list[AlertEvent]:
    """Evaluate every enabled alert once and deliver what fired."""
    now = now or datetime.now(UTC)
    alerts = await alert_service.due_alerts(db, now=now)

    fired: list[tuple[Any, AlertEvent]] = []
    for alert in alerts:
        try:
            event = await alert_service.evaluate_alert(db, alert, now=now)
        except alert_service.AlertError as exc:
            # One broken alert must not stop the others: a typo in a
            # user's expression would otherwise silence their whole
            # account.
            logger.warning("alert_evaluation_failed", alert=str(alert.id), error=str(exc))
            continue
        if event is not None:
            fired.append((alert, event))

    await _deliver(db, notifier, fired, quiet_override=None)
    await db.commit()
    return [event for _, event in fired]


async def _deliver(
    db: AsyncSession,
    notifier: Notifier,
    fired: list[tuple[Any, AlertEvent]],
    *,
    quiet_override: bool | None,
) -> None:
    """Send the firings, folding bursts to one message per destination."""
    # Grouped by alert: two different alerts firing together are two
    # different things to say, and merging them would lose one.
    by_alert: dict[Any, list[tuple[Any, AlertEvent]]] = defaultdict(list)
    for alert, event in fired:
        if any(d.get("state") == "suppressed" for d in event.deliveries):
            continue
        by_alert[alert.id].append((alert, event))

    for group in by_alert.values():
        alert = group[0][0]
        events = [event for _, event in group]
        primary = events[0]

        if len(events) > 1:
            primary.message = merge_messages([e.message for e in events], alert.locale)
            primary.merged_count = len(events)
            for extra in events[1:]:
                extra.deliveries = [
                    {"kind": "merged", "state": "suppressed", "note": "folded into one message"}
                ]

        quiet = primary.quiet if quiet_override is None else quiet_override
        deliveries = await notifier.deliver(alert.destinations, primary.message, quiet=quiet)
        primary.deliveries = [d.to_dict() for d in deliveries]
        db.add(primary)


class AlertRunner:
    """The background loop. Started at boot, stopped at shutdown."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], notifier: Notifier) -> None:
        self._sessions = sessions
        self._notifier = notifier
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                async with self._sessions() as db:
                    await run_once(db, self._notifier)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # The loop is the product's only always-on component. It
                # logs and carries on rather than dying on a bad tick.
                logger.warning("alert_tick_failed", error=str(exc))
            await asyncio.sleep(TICK_SECONDS)
