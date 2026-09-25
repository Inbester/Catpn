"""Stored strategies and their backtest runs.

A strategy row holds the *current* draft; every version that has been run
is pinned by its content hash (SPEC §4), so a result can always be traced
back to the exact rules that produced it — which is what makes a forward
test's "frozen v3" meaningful.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from quanta.db.base import Base, Timestamped, UUIDPrimaryKey


class StrategyRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "strategies"
    __table_args__ = (Index("ix_strategies_user_name", "user_id", "name"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    long_entry: Mapped[str | None] = mapped_column(Text, nullable=True)
    short_entry: Mapped[str | None] = mapped_column(Text, nullable=True)
    exits: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    params: Mapped[dict[str, float]] = mapped_column(JSONB, nullable=False, default=dict)

    # The hash of the current draft, recomputed on every save.
    version: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    runs: Mapped[list[BacktestRun]] = relationship(
        back_populates="strategy", cascade="all, delete-orphan", lazy="raise"
    )


class BacktestRun(UUIDPrimaryKey, Base):
    """One completed backtest.

    Results are stored rather than recomputed: a run is the evidence behind
    a decision, and it has to keep saying the same thing after the strategy
    draft moves on.
    """

    __tablename__ = "backtest_runs"
    __table_args__ = (
        Index("ix_backtest_runs_user_created", "user_id", "created_at"),
        Index("ix_backtest_runs_strategy_version", "strategy_id", "strategy_version"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    strategy_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("strategies.id", ondelete="CASCADE"), nullable=False
    )
    # The version that actually ran, which may differ from the draft now.
    strategy_version: Mapped[str] = mapped_column(String(64), nullable=False)

    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    interval: Mapped[str] = mapped_column(String(8), nullable=False)
    # Epoch milliseconds, so BigInteger: 1.7e12 does not fit in 32 bits.
    start_time: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_time: Mapped[int] = mapped_column(BigInteger, nullable=False)

    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    trades: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    equity: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    strategy: Mapped[StrategyRecord] = relationship(back_populates="runs")
