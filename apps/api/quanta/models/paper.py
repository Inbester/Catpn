"""Paper trading: the last gate before real money (SPEC §3.3).

A backtest says what would have happened. Paper trading says what is
happening — same rules, same sizing, live prices, no money. The gap
between the two is the whole point: fills that a backtest assumed at the
next open arrive late or not at all, funding lands on real settlement
times, and a signal the engine produced at 03:00 can find nobody to trade
against.

The promotion checklist exists so that "it works" has to mean something
specific before a Setup may place real orders. SPEC §3.3 fixes the bar:
fourteen days, thirty trades, inside the cone, drawdown under the limit,
drift within 0.025%.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from quanta.db.base import Base, Timestamped, UUIDPrimaryKey

SESSION_STATES = ("running", "paused", "stopped", "promoted")


class PaperSession(UUIDPrimaryKey, Timestamped, Base):
    """One Setup being traded on paper."""

    __tablename__ = "paper_sessions"
    __table_args__ = (Index("ix_paper_sessions_user_state", "user_id", "state"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    setup_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("setups.id", ondelete="CASCADE"), nullable=False
    )

    state: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    initial_capital: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, default=10_000)
    equity: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, default=10_000)

    # The band the backtest said to expect, so live can be read against
    # something rather than against nothing.
    expected_net_percent: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    expected_low_percent: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    expected_high_percent: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    drawdown_limit_percent: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)

    # Signals the engine produced that no fill was recorded for.
    missed_signals: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_bar_time: Mapped[int | None] = mapped_column(nullable=True)

    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # True when promotion was taken despite a failing check, which SPEC
    # §3.3 allows behind 2FA. Kept because it changes what the green tick
    # on a bot means.
    promoted_by_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class PaperFill(UUIDPrimaryKey, Timestamped, Base):
    """One paper fill, with the execution quality it was measured at."""

    __tablename__ = "paper_fills"
    __table_args__ = (Index("ix_paper_fills_session_time", "session_id", "filled_at"),)

    session_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("paper_sessions.id", ondelete="CASCADE"), nullable=False
    )

    side: Mapped[str] = mapped_column(String(8), nullable=False)
    action: Mapped[str] = mapped_column(String(8), nullable=False, default="entry")
    bar_time: Mapped[int] = mapped_column(nullable=False)
    signal_price: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    fill_price: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False, default=0)

    # What the gap between signal and fill actually cost, in basis points.
    # The number a backtest has to assume and paper trading can measure.
    slippage_bps: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fee: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False, default=0)
    funding: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False, default=0)
    net_pnl: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False, default=0)
    equity_after: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, default=0)

    filled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
