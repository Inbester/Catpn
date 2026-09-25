"""Backtest inputs and results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray

from quanta_engine.backtest.liquidation import FLAT_TIER, PositionTier
from quanta_engine.strategy import ExitReason, MarginMode

Array = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class Bars:
    """An aligned OHLCV series. Times are epoch milliseconds, UTC boundaries."""

    time: NDArray[np.int64]
    open: Array
    high: Array
    low: Array
    close: Array
    volume: Array
    # Mark price closes, used for liquidation (SPEC §6). Falls back to last.
    mark_close: Array | None = None

    def __post_init__(self) -> None:
        sizes = {
            len(self.time),
            len(self.open),
            len(self.high),
            len(self.low),
            len(self.close),
            len(self.volume),
        }
        if len(sizes) != 1:
            raise ValueError("All bar columns must be the same length.")
        if self.mark_close is not None and len(self.mark_close) != len(self.time):
            raise ValueError("mark_close must match the bar count.")

    def __len__(self) -> int:
        return len(self.time)

    def mark(self, index: int) -> float:
        source = self.mark_close if self.mark_close is not None else self.close
        return float(source[index])

    def series(self) -> dict[str, Array]:
        """The columns a strategy expression can read."""
        return {
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "hl2": (self.high + self.low) / 2.0,
            "hlc3": (self.high + self.low + self.close) / 3.0,
            "ohlc4": (self.open + self.high + self.low + self.close) / 4.0,
        }


@dataclass(frozen=True, slots=True)
class FundingEvent:
    """A settled funding payment. Positive rate means longs pay shorts."""

    time: int
    rate: float


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    """Execution assumptions.

    Defaults are Bitunix VIP0 (SPEC §6). Costs are never zero by default:
    a backtest that forgets fees and funding reports a strategy that does
    not exist.
    """

    initial_capital: float = 10_000.0
    # Share of equity committed as margin on each trade.
    margin_percent: float = 10.0
    leverage: float = 10.0
    margin_mode: MarginMode = MarginMode.ISOLATED

    maker_fee: float = 0.0002
    taker_fee: float = 0.0006
    # Slippage applied to every fill, in basis points of price.
    slippage_bps: float = 1.0

    apply_funding: bool = True
    tiers: tuple[PositionTier, ...] = FLAT_TIER

    # Entries and exits cross the spread, so they pay taker by default.
    entry_is_maker: bool = False
    exit_is_maker: bool = False

    def __post_init__(self) -> None:
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        if not 0 < self.margin_percent <= 100:
            raise ValueError("margin_percent must be between 0 and 100")
        if self.leverage < 1:
            raise ValueError("leverage must be at least 1")
        if self.slippage_bps < 0:
            raise ValueError("slippage_bps cannot be negative")

    @property
    def entry_fee_rate(self) -> float:
        return self.maker_fee if self.entry_is_maker else self.taker_fee

    @property
    def exit_fee_rate(self) -> float:
        return self.maker_fee if self.exit_is_maker else self.taker_fee


@dataclass(slots=True)
class Trade:
    """One round trip."""

    side: str  # "long" or "short"
    entry_index: int
    entry_time: int
    entry_price: float
    quantity: float
    margin: float
    leverage: float
    liquidation_price: float

    exit_index: int = -1
    exit_time: int = 0
    exit_price: float = 0.0
    exit_reason: ExitReason = ExitReason.END_OF_DATA

    gross_pnl: float = 0.0
    entry_fee: float = 0.0
    exit_fee: float = 0.0
    funding_paid: float = 0.0
    net_pnl: float = 0.0

    # Best and worst mark-to-market while the trade was open, in quote
    # currency. MAE drives the Trade risk study (SPEC §3.2).
    run_up: float = 0.0
    drawdown: float = 0.0

    equity_after: float = 0.0

    @property
    def bars_held(self) -> int:
        return max(0, self.exit_index - self.entry_index)

    @property
    def is_long(self) -> bool:
        return self.side == "long"

    @property
    def total_fees(self) -> float:
        return self.entry_fee + self.exit_fee

    @property
    def return_on_margin(self) -> float:
        return self.net_pnl / self.margin * 100.0 if self.margin else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "side": self.side,
            "entry_time": self.entry_time,
            "entry_price": self.entry_price,
            "exit_time": self.exit_time,
            "exit_price": self.exit_price,
            "quantity": self.quantity,
            "margin": self.margin,
            "leverage": self.leverage,
            "liquidation_price": self.liquidation_price,
            "exit_reason": str(self.exit_reason),
            "gross_pnl": self.gross_pnl,
            "fees": self.total_fees,
            "funding": self.funding_paid,
            "net_pnl": self.net_pnl,
            "return_on_margin": self.return_on_margin,
            "run_up": self.run_up,
            "drawdown": self.drawdown,
            "bars_held": self.bars_held,
            "equity_after": self.equity_after,
        }


@dataclass(slots=True)
class BacktestResult:
    """Trades, the equity path and the headline numbers."""

    trades: list[Trade] = field(default_factory=list)
    equity_time: NDArray[np.int64] = field(default_factory=lambda: np.array([], dtype=np.int64))
    equity: Array = field(default_factory=lambda: np.array([], dtype=np.float64))
    drawdown: Array = field(default_factory=lambda: np.array([], dtype=np.float64))
    stats: dict[str, Any] = field(default_factory=dict)
    config: BacktestConfig | None = None
    strategy_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_version": self.strategy_version,
            "stats": self.stats,
            "trades": [trade.to_dict() for trade in self.trades],
            "equity": {
                "time": self.equity_time.tolist(),
                "value": self.equity.tolist(),
                "drawdown": self.drawdown.tolist(),
            },
        }
