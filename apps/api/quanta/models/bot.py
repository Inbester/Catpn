"""Exchange keys, bots and their order log (SPEC §3.5, §3.6).

Three tables and one rule between them: **nothing here ever holds a
readable secret**. `ExchangeKey` stores sealed bytes and the three things
needed to tell one key from another — a label the user chose, the last
four characters, and a fingerprint. The secret itself is opened only
inside the execution service, for the length of one call.

`BotOrder` is the audit log SPEC §3.5 asks for. It is append-only: rows
are inserted and updated as the venue reports back, never deleted, because
a log you can delete from is not a log. Its `client_id` is unique per bot,
which is the database half of the idempotency the execution service
builds — even a bug that tried to place the same order twice would fail
here.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from quanta.db.base import Base, Timestamped, UUIDPrimaryKey

#: stopped -> armed -> running, and halted from any of them. Halted is not
#: stopped: it carries a reason and only a person clears it (SPEC §3.5).
BOT_STATES = ("stopped", "armed", "running", "halted")

#: Why a bot halted. "kill_switch" and "reconcile" sit alongside the risk
#: codes so every halt has one vocabulary.
HALT_REASONS = (
    "daily_loss",
    "max_drawdown",
    "leverage_too_high",
    "reconcile",
    "kill_switch",
    "manual",
    "venue_error",
)


class ExchangeKey(UUIDPrimaryKey, Timestamped, Base):
    """One user's API key for one venue, sealed (SPEC §3.6).

    The user connects their own key and trades their own account; the
    platform never holds funds (SPEC §9).
    """

    __tablename__ = "exchange_keys"
    __table_args__ = (
        # One label per user per venue, so a list of keys is readable.
        UniqueConstraint("user_id", "exchange", "label", name="uq_exchange_keys_label"),
        Index("ix_exchange_keys_user", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    exchange: Mapped[str] = mapped_column(String(32), nullable=False, default="bitunix")
    label: Mapped[str] = mapped_column(String(64), nullable=False)

    # --- The sealed parts. Useless without the master key. ---------------
    api_key_sealed: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    api_key_wrapped_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    api_secret_sealed: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    api_secret_wrapped_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    #: Which master key sealed these, so rotation can be staged.
    key_version: Mapped[str] = mapped_column(String(32), nullable=False)

    # --- What may be shown. ----------------------------------------------
    last_four: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    fingerprint: Mapped[str] = mapped_column(String(32), nullable=False)

    # What the venue said this key could do when it was admitted. Kept so
    # the UI can show it without a round trip, and re-checked before use:
    # permissions can be changed at the exchange after we stored them.
    can_trade: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ip_whitelist: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Bot(UUIDPrimaryKey, Timestamped, Base):
    """One Setup traded live with one key and one set of risk limits."""

    __tablename__ = "bots"
    __table_args__ = (Index("ix_bots_user_state", "user_id", "state"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    setup_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("setups.id", ondelete="CASCADE"), nullable=False
    )
    # RESTRICT, not CASCADE: deleting a key out from under a running bot
    # would leave it unable to close what it holds. The route refuses the
    # delete instead, and says which bot is using it.
    exchange_key_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("exchange_keys.id", ondelete="RESTRICT"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(80), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="stopped")
    halt_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: The sentence shown to the user, with the figure that tripped it.
    halt_detail: Mapped[str | None] = mapped_column(String(400), nullable=True)
    halted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    interval: Mapped[str] = mapped_column(String(8), nullable=False)
    leverage: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    margin_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="ISOLATED")
    position_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="ONE_WAY")

    # --- Risk limits (SPEC §3.5). Every figure in the quote currency
    # except the percentage and the counts.
    max_position_notional: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    max_daily_loss: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    max_drawdown_percent: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    max_leverage: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    max_orders_per_minute: Mapped[int] = mapped_column(Integer, nullable=False, default=6)

    # --- Live state, rebuilt from here on restart so a restart cannot be
    # used to reset a daily loss limit.
    day_start_equity: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    peak_equity: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    day_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    equity: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)

    armed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_signal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BotOrder(UUIDPrimaryKey, Base):
    """Every order, as sent and as answered (SPEC §3.5: audit log).

    Append-only. Rows are updated as the venue reports back, never
    deleted. Timestamps are explicit rather than inherited so the row
    records when the order was *sent*, not when it was written.
    """

    __tablename__ = "bot_orders"
    __table_args__ = (
        # The database half of idempotency: the same client id cannot be
        # recorded twice for one bot, whatever the code above does.
        UniqueConstraint("bot_id", "client_id", name="uq_bot_orders_client_id"),
        Index("ix_bot_orders_bot_sent", "bot_id", "sent_at"),
    )

    bot_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("bots.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[str] = mapped_column(String(40), nullable=False)
    exchange_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    order_type: Mapped[str] = mapped_column(String(16), nullable=False)
    qty: Mapped[float] = mapped_column(Numeric(28, 12), nullable=False)
    price: Mapped[float | None] = mapped_column(Numeric(28, 12), nullable=True)
    filled_qty: Mapped[float | None] = mapped_column(Numeric(28, 12), nullable=True)
    average_price: Mapped[float | None] = mapped_column(Numeric(28, 12), nullable=True)
    fee: Mapped[float | None] = mapped_column(Numeric(28, 12), nullable=True)
    reduce_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str | None] = mapped_column(String(24), nullable=True)

    #: The bar that produced the signal, so an order can be traced back to
    #: the rule that asked for it.
    bar_time: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    #: How long the venue took, in milliseconds. SPEC §3.5 shows it in the
    #: activity log, where a creeping number is the first sign of trouble.
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(String(400), nullable=True)
    #: The request as sent and the response as received. Never contains
    #: credentials: the signature headers are not part of this.
    request: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    response: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
