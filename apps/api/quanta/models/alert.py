"""Alerts and their delivery record (SPEC §3.4).

Alerts are the first thing in the product that acts while nobody is
watching. Everything else — a backtest, a search, a chart — runs because
someone asked for it just now. An alert has to fire at three in the
morning with the browser closed, which is why evaluation lives on the
server and why every send is recorded: an alert that silently failed to
deliver is worse than one that never existed, because the user believes
they are being watched over.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from quanta.db.base import Base, Timestamped, UUIDPrimaryKey

# What an alert watches.
ALERT_SOURCES = ("strategy", "price", "indicator", "risk", "market", "system")

# When it is allowed to fire again.
REPEAT_MODES = ("every", "once", "once_per_bar")

# Bar close is the default because a rule evaluated mid-bar can un-fire:
# the condition holds, the bar turns, and the signal was never real. That
# is repainting, and an alert that repaints is a lie told in real time.
TRIGGER_MODES = ("bar_close", "tick")

DESTINATION_KINDS = ("telegram", "web_push", "webhook", "email")

DELIVERY_STATES = ("pending", "sent", "failed", "suppressed")


class Alert(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_user_enabled", "user_id", "enabled"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)

    # A strategy alert acts through a Setup, so it fires on the exact
    # version that was validated rather than on whatever the draft says.
    setup_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("setups.id", ondelete="CASCADE"), nullable=True
    )

    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    interval: Mapped[str] = mapped_column(String(8), nullable=False, default="1h")

    # Source-specific: {"expression": "..."} for indicator alerts,
    # {"price": 68000, "direction": "above"} for price, and so on.
    condition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    trigger_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="bar_close")
    repeat_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="once_per_bar")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Quiet hours are local to the user's timezone and send silently
    # rather than not at all: a missed alert is not quiet, it is lost.
    quiet_from_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quiet_to_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)

    template: Mapped[str] = mapped_column(Text, nullable=False, default="")
    locale: Mapped[str] = mapped_column(String(8), nullable=False, default="en")

    # [{"kind": "telegram", "target": "-1001234", ...}]
    destinations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The open time of the bar that last fired, so once-per-bar can tell
    # a new bar from a re-evaluation of the same one.
    last_fired_bar: Mapped[int | None] = mapped_column(nullable=True)
    fire_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AlertEvent(UUIDPrimaryKey, Timestamped, Base):
    """One firing, with what was sent where and how it went."""

    __tablename__ = "alert_events"
    __table_args__ = (Index("ix_alert_events_alert_created", "alert_id", "created_at"),)

    alert_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    bar_time: Mapped[int] = mapped_column(nullable=False)
    price: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # The values the template was rendered from, kept so a message can be
    # explained after the fact.
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    # How many signals this event stands for. Above one means the burst
    # merge folded several into a single message.
    merged_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    quiet: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # [{"kind": ..., "target": ..., "state": ..., "latency_ms": ...,
    #   "attempts": 1, "note": "429 → retried"}]
    deliveries: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)


class Channel(UUIDPrimaryKey, Timestamped, Base):
    """A destination the user connected once and can reuse (SPEC §7)."""

    __tablename__ = "channels"
    __table_args__ = (Index("ix_channels_user_kind", "user_id", "kind"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    # A Telegram chat id, a push endpoint, a webhook URL, an address.
    target: Mapped[str] = mapped_column(Text, nullable=False)
    # Push keys, webhook secret. Never returned to the client.
    secrets: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
