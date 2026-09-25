"""Market data tables.

Klines and funding are time series, so they live in TimescaleDB hypertables
(SPEC §4). The composite primary keys include the time column because
Timescale requires the partitioning column in every unique constraint.

SPEC §6 is explicit that history is fetched once and stored here, never
queried live per user — the venue allows only 10 requests a second per IP,
which a handful of concurrent chart loads would exhaust on their own.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from quanta.db.base import Base

# Prices and volumes are Numeric, never float: a backtest that rounds a
# fee or a liquidation price in binary floating point is a backtest that
# lies about its own results.
PRICE = Numeric(38, 12)
VOLUME = Numeric(38, 12)
RATE = Numeric(20, 12)


class Kline(Base):
    """One OHLCV bar for a symbol, interval and price type."""

    __tablename__ = "klines"
    __table_args__ = (
        PrimaryKeyConstraint("symbol", "interval", "price_type", "open_time", name="pk_klines"),
        Index("ix_klines_lookup", "symbol", "interval", "price_type", "open_time"),
    )

    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    interval: Mapped[str] = mapped_column(String(8), nullable=False)
    # LAST or MARK — the chart lets the user pick the candle source.
    price_type: Mapped[str] = mapped_column(String(8), nullable=False, default="LAST")
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    open: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    high: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    low: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    close: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    volume: Mapped[Decimal] = mapped_column(VOLUME, nullable=False, default=0)
    quote_volume: Mapped[Decimal | None] = mapped_column(VOLUME, nullable=True)

    # A forming bar is stored so a reload shows the live candle, and is
    # overwritten until the exchange confirms it closed.
    closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class FundingRate(Base):
    """A settled funding payment (SPEC §6: every 8h, longs pay shorts when positive)."""

    __tablename__ = "funding_rates"
    __table_args__ = (PrimaryKeyConstraint("symbol", "funding_time", name="pk_funding_rates"),)

    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    funding_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    funding_rate: Mapped[Decimal] = mapped_column(RATE, nullable=False)
    mark_price: Mapped[Decimal | None] = mapped_column(PRICE, nullable=True)


class InstrumentMeta(Base):
    """Cached contract metadata, refreshed periodically.

    Leverage limits and precision drive the research range controls
    (SPEC §3.2), so they are read from here rather than hit per request.
    """

    __tablename__ = "instruments"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False, default="bitunix")
    base: Mapped[str] = mapped_column(String(16), nullable=False)
    quote: Mapped[str] = mapped_column(String(16), nullable=False)

    min_leverage: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_leverage: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    default_leverage: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    base_precision: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    quote_precision: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    min_trade_volume: Mapped[Decimal] = mapped_column(VOLUME, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="OPEN")
    api_supported: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    refreshed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class BackfillState(Base):
    """How far history has been downloaded for a series.

    Lets a backfill resume where it stopped instead of re-downloading, and
    tells the chart whether a requested range is already local.
    """

    __tablename__ = "backfill_state"
    __table_args__ = (
        PrimaryKeyConstraint("symbol", "interval", "price_type", name="pk_backfill_state"),
    )

    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    interval: Mapped[str] = mapped_column(String(8), nullable=False)
    price_type: Mapped[str] = mapped_column(String(8), nullable=False, default="LAST")

    # Epoch milliseconds, matching the exchange's own units.
    earliest_open_time: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    latest_open_time: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    bar_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
