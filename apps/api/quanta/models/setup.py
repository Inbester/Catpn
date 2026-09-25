"""Setups: the locked bundle every later menu picks from (SPEC §0).

A Setup is the product's core object. It pins a *specific strategy version*
together with the market, sizing, costs and risk budget it was validated
under, so that Test, Alerts and the Bot all act on the same thing. Without
that pinning, "the strategy" means whatever the draft happens to say today,
and an alert could fire on rules nobody ever tested.

The pipeline fields record how far a Setup has been validated. SPEC §3.3
locks the Bot stage behind paper trading, so that gate lives in the data
rather than only in the UI.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from quanta.db.base import Base, Timestamped, UUIDPrimaryKey

# The stages a Setup moves through, in order.
PIPELINE_STAGES = ("research", "backtest", "forward", "paper", "alerts", "bot")

STAGE_STATUSES = ("not_started", "running", "passed", "failed")

# The palette Setups are coloured from. Colour identifies a Setup across
# menus; it never encodes a value, per the design system's rule that
# colour carries meaning only.
SETUP_COLORS = (
    "#6EA8FE",
    "#2EBD85",
    "#F59E0B",
    "#F0506E",
    "#A78BFA",
    "#38BDF8",
    "#FB923C",
    "#94A3B8",
)


class Setup(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "setups"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_setups_user_name"),
        Index("ix_setups_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    color: Mapped[str] = mapped_column(String(9), nullable=False, default=SETUP_COLORS[0])

    strategy_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("strategies.id", ondelete="CASCADE"), nullable=False
    )
    # The locked version. This is the point of a Setup: it does not follow
    # the strategy draft.
    strategy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    # A copy of the rules as they were at lock time, so the Setup stays
    # readable even if the strategy row is edited afterwards.
    strategy_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    interval: Mapped[str] = mapped_column(String(8), nullable=False)

    # --- position sizing --------------------------------------------------
    margin_percent: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    leverage: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    margin_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="isolated")

    # --- costs and risk budget -------------------------------------------
    fee_tier: Mapped[str] = mapped_column(String(16), nullable=False, default="VIP0")
    maker_fee: Mapped[float] = mapped_column(Numeric(12, 8), nullable=False)
    taker_fee: Mapped[float] = mapped_column(Numeric(12, 8), nullable=False)
    max_drawdown_budget_percent: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    risk_of_ruin_limit_percent: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)

    # The run this Setup was created from, so a number can be traced back.
    source_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("backtest_runs.id", ondelete="SET NULL"), nullable=True
    )

    # --- pipeline ---------------------------------------------------------
    # {stage: {"status": ..., "updated_at": ..., "note": ...}}
    pipeline: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # Where the Setup may be used. The bot flag stays false until paper
    # trading passes (SPEC §3.3).
    use_in_backtest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    use_in_forward: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    use_in_paper: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    use_in_alerts: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    use_in_bot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    strategy = relationship("StrategyRecord", lazy="raise")

    @property
    def exposure(self) -> float:
        """Margin share times leverage — what the Setup actually controls.

        SPEC §3.2 calls this out as the key insight: two Setups with the
        same exposure carry the same market risk, but the one at lower
        leverage has its liquidation price further away.
        """
        return float(self.margin_percent) * float(self.leverage)


def default_pipeline() -> dict[str, Any]:
    return {
        stage: {"status": "not_started", "updated_at": None, "note": ""}
        for stage in PIPELINE_STAGES
    }
