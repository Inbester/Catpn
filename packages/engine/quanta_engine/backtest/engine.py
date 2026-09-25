"""The backtest engine (SPEC §3.3).

Execution model, and the reasoning behind each rule:

* **Fill at the next bar's open.** A signal is computed from a bar's close,
  so it cannot be acted on until the next bar exists. Filling at the same
  bar's close would be lookahead, and it is the single most common way a
  backtest flatters a strategy.
* **1-minute magnifier.** Within one 15m bar, price may touch both the take
  profit and the stop. Which came first decides the trade, and the bar's
  OHLC does not say. Given 1m bars the engine walks them in order; without
  them it assumes the *stop* was hit first, because an optimistic guess
  here is indistinguishable from a profitable strategy.
* **Costs are always applied.** Commission on both sides, slippage on every
  fill, and funding every 8 hours a position is held.
* **Liquidation on the mark price** with the tiered maintenance margin.
"""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray

from quanta_engine import series as ta
from quanta_engine.backtest.liquidation import liquidation_price
from quanta_engine.backtest.types import (
    Array,
    BacktestConfig,
    BacktestResult,
    Bars,
    FundingEvent,
    Trade,
)
from quanta_engine.dsl.evaluator import Context, evaluate_bool
from quanta_engine.strategy import ExitReason, MarginMode, Strategy

FUNDING_INTERVAL_MS = 8 * 3_600_000


class _OpenPosition:
    """Mutable state for the trade currently open."""

    __slots__ = (
        "break_even_armed",
        "initial_stop_distance",
        "next_funding_time",
        "peak_price",
        "stop_price",
        "take_profit_price",
        "trade",
    )

    def __init__(self, trade: Trade) -> None:
        self.trade = trade
        self.stop_price: float | None = None
        self.take_profit_price: float | None = None
        self.initial_stop_distance: float = 0.0
        self.break_even_armed = False
        self.next_funding_time = 0
        self.peak_price = trade.entry_price


def _apply_slippage(price: float, bps: float, *, buying: bool) -> float:
    """Slippage always moves the fill against the trader."""
    factor = 1.0 + (bps / 10_000.0) * (1.0 if buying else -1.0)
    return price * factor


def _next_funding_after(timestamp: int) -> int:
    """The next 00:00 / 08:00 / 16:00 UTC boundary strictly after ``timestamp``."""
    return ((timestamp // FUNDING_INTERVAL_MS) + 1) * FUNDING_INTERVAL_MS


def _funding_rate_at(events: list[FundingEvent], timestamp: int) -> float:
    """The rate settled at ``timestamp``, or 0 if none is recorded."""
    for event in events:
        if event.time == timestamp:
            return event.rate
    return 0.0


class Backtester:
    def __init__(
        self,
        strategy: Strategy,
        config: BacktestConfig | None = None,
        *,
        funding: list[FundingEvent] | None = None,
        magnifier: Bars | None = None,
    ) -> None:
        strategy.validate()
        self.strategy = strategy
        self.config = config or BacktestConfig()
        self.funding = sorted(funding or [], key=lambda e: e.time)
        self.magnifier = magnifier

    # --- signals --------------------------------------------------------

    def _signals(self, bars: Bars) -> tuple[NDArray[np.bool_], NDArray[np.bool_]]:
        context = Context(series=bars.series(), params=dict(self.strategy.params))
        size = len(bars)

        long_node = self.strategy.compiled_long()
        short_node = self.strategy.compiled_short()

        longs = (
            evaluate_bool(long_node, context)
            if long_node is not None
            else np.zeros(size, dtype=np.bool_)
        )
        shorts = (
            evaluate_bool(short_node, context)
            if short_node is not None
            else np.zeros(size, dtype=np.bool_)
        )
        return longs, shorts

    # --- magnifier ------------------------------------------------------

    def _magnifier_slice(self, start_ms: int, end_ms: int) -> Bars | None:
        """The 1m bars inside ``[start_ms, end_ms)``, if any are loaded."""
        if self.magnifier is None or len(self.magnifier) == 0:
            return None
        times = self.magnifier.time
        lo = int(np.searchsorted(times, start_ms, side="left"))
        hi = int(np.searchsorted(times, end_ms, side="left"))
        if hi <= lo:
            return None
        return Bars(
            time=times[lo:hi],
            open=self.magnifier.open[lo:hi],
            high=self.magnifier.high[lo:hi],
            low=self.magnifier.low[lo:hi],
            close=self.magnifier.close[lo:hi],
            volume=self.magnifier.volume[lo:hi],
        )

    def _resolve_intrabar(
        self,
        position: _OpenPosition,
        bar_high: float,
        bar_low: float,
        start_ms: int,
        end_ms: int,
    ) -> tuple[ExitReason, float] | None:
        """Which exit level was reached first inside this bar, if any.

        With 1m bars loaded this is answered by walking them. Without, the
        engine assumes the adverse level came first — see the module note.
        """
        stop = position.stop_price
        take = position.take_profit_price
        liq = position.trade.liquidation_price
        is_long = position.trade.is_long

        def touched(level: float | None, *, above: bool, high: float, low: float) -> bool:
            if level is None:
                return False
            return high >= level if above else low <= level

        fine = self._magnifier_slice(start_ms, end_ms)
        if fine is not None:
            for i in range(len(fine)):
                high = float(fine.high[i])
                low = float(fine.low[i])
                # Liquidation first: the exchange acts before any of our
                # orders would.
                if is_long and liq > 0 and low <= liq:
                    return ExitReason.LIQUIDATION, liq
                if not is_long and math.isfinite(liq) and high >= liq:
                    return ExitReason.LIQUIDATION, liq
                if touched(stop, above=not is_long, high=high, low=low):
                    return ExitReason.STOP_LOSS, stop  # type: ignore[return-value]
                if touched(take, above=is_long, high=high, low=low):
                    return ExitReason.TAKE_PROFIT, take  # type: ignore[return-value]
            return None

        # No magnifier: resolve in worst-to-best order.
        if is_long and liq > 0 and bar_low <= liq:
            return ExitReason.LIQUIDATION, liq
        if not is_long and math.isfinite(liq) and bar_high >= liq:
            return ExitReason.LIQUIDATION, liq
        if touched(stop, above=not is_long, high=bar_high, low=bar_low):
            return ExitReason.STOP_LOSS, stop  # type: ignore[return-value]
        if touched(take, above=is_long, high=bar_high, low=bar_low):
            return ExitReason.TAKE_PROFIT, take  # type: ignore[return-value]
        return None

    # --- the run --------------------------------------------------------

    def run(self, bars: Bars) -> BacktestResult:
        if len(bars) < 2:
            raise ValueError("A backtest needs at least two bars.")

        config = self.config
        longs, shorts = self._signals(bars)

        atr = (
            ta.atr(bars.high, bars.low, bars.close, self.strategy.exits.atr_length)
            if self.strategy.exits.atr_stop_multiple is not None
            or self.strategy.exits.trailing_atr_multiple is not None
            else np.full(len(bars), np.nan)
        )

        equity = config.initial_capital
        equity_path = np.empty(len(bars), dtype=np.float64)
        trades: list[Trade] = []
        position: _OpenPosition | None = None
        # A signal on bar i is filled at bar i+1's open.
        pending: str | None = None

        for i in range(len(bars)):
            bar_open = float(bars.open[i])
            bar_high = float(bars.high[i])
            bar_low = float(bars.low[i])
            bar_close = float(bars.close[i])
            bar_time = int(bars.time[i])
            bar_end = int(bars.time[i + 1]) if i + 1 < len(bars) else bar_time + 1

            # 1. Fill anything queued from the previous bar's close.
            if pending is not None and position is None:
                position = self._open(
                    pending, i, bar_time, bar_open, equity, float(atr[i - 1]) if i else math.nan
                )
                pending = None

            # 2. Manage the open position within this bar.
            if position is not None:
                position = self._update_position(position, bars, i, atr)

                exit_hit = self._resolve_intrabar(position, bar_high, bar_low, bar_time, bar_end)
                if exit_hit is not None:
                    reason, price = exit_hit
                    equity = self._close(position, i, bar_time, price, reason, equity)
                    trades.append(position.trade)
                    position = None
                else:
                    self._accrue_funding(position, bar_time, bar_end, bar_close)
                    self._track_excursion(position, bar_high, bar_low)

            # 3. Signals, read from this bar's close, queued for the next open.
            if position is not None:
                signal_reason = self._signal_exit(position, i, longs, shorts)
                if signal_reason is not None and i + 1 < len(bars):
                    next_open = float(bars.open[i + 1])
                    equity = self._close(
                        position,
                        i + 1,
                        int(bars.time[i + 1]),
                        next_open,
                        signal_reason,
                        equity,
                    )
                    trades.append(position.trade)
                    position = None
                    # An opposite signal flips straight into the new side,
                    # filling at the same next open the exit used.
                    if signal_reason is ExitReason.OPPOSITE_SIGNAL:
                        pending = "long" if longs[i] else "short"

            elif pending is None:
                if longs[i]:
                    pending = "long"
                elif shorts[i]:
                    pending = "short"

            # 4. Mark to market.
            equity_path[i] = equity + self._unrealised(position, bar_close) if position else equity

        # Close anything still open at the last bar.
        if position is not None:
            last = len(bars) - 1
            equity = self._close(
                position,
                last,
                int(bars.time[last]),
                float(bars.close[last]),
                ExitReason.END_OF_DATA,
                equity,
            )
            trades.append(position.trade)
            equity_path[last] = equity

        drawdown = self._drawdown(equity_path)
        return BacktestResult(
            trades=trades,
            equity_time=bars.time.copy(),
            equity=equity_path,
            drawdown=drawdown,
            stats={},
            config=config,
            strategy_version=self.strategy.version_hash(),
        )

    # --- position lifecycle ---------------------------------------------

    def _open(
        self,
        side: str,
        index: int,
        time_ms: int,
        price: float,
        equity: float,
        atr_value: float,
    ) -> _OpenPosition:
        config = self.config
        is_long = side == "long"

        fill = _apply_slippage(price, config.slippage_bps, buying=is_long)
        margin = equity * (config.margin_percent / 100.0)
        notional = margin * config.leverage
        quantity = notional / fill if fill > 0 else 0.0

        # Cross mode backs the position with the whole balance (SPEC §6).
        backing = equity if config.margin_mode is MarginMode.CROSS else margin

        trade = Trade(
            side=side,
            entry_index=index,
            entry_time=time_ms,
            entry_price=fill,
            quantity=quantity,
            margin=margin,
            leverage=config.leverage,
            liquidation_price=liquidation_price(
                entry_price=fill,
                quantity=quantity,
                margin=backing,
                is_long=is_long,
                tiers=config.tiers,
            )
            if quantity > 0
            else 0.0,
        )
        trade.entry_fee = notional * config.entry_fee_rate

        position = _OpenPosition(trade)
        position.next_funding_time = _next_funding_after(time_ms)

        exits = self.strategy.exits
        if exits.atr_stop_multiple is not None and not math.isnan(atr_value):
            distance = atr_value * exits.atr_stop_multiple
            position.initial_stop_distance = distance
            position.stop_price = fill - distance if is_long else fill + distance
            if exits.take_profit_r is not None:
                reward = distance * exits.take_profit_r
                position.take_profit_price = fill + reward if is_long else fill - reward

        return position

    def _update_position(
        self, position: _OpenPosition, bars: Bars, index: int, atr: Array
    ) -> _OpenPosition:
        """Move the stop for break-even and trailing rules."""
        exits = self.strategy.exits
        trade = position.trade
        is_long = trade.is_long
        distance = position.initial_stop_distance

        # Track the best price seen, which both rules key off.
        if is_long:
            position.peak_price = max(position.peak_price, float(bars.high[index]))
        else:
            position.peak_price = min(position.peak_price, float(bars.low[index]))

        if exits.break_even_at_r is not None and distance > 0 and not position.break_even_armed:
            target = distance * exits.break_even_at_r
            moved = (
                position.peak_price - trade.entry_price
                if is_long
                else trade.entry_price - position.peak_price
            )
            if moved >= target:
                position.stop_price = trade.entry_price
                position.break_even_armed = True

        if exits.trailing_atr_multiple is not None:
            current_atr = float(atr[index])
            if not math.isnan(current_atr):
                trail = current_atr * exits.trailing_atr_multiple
                candidate = position.peak_price - trail if is_long else position.peak_price + trail
                if position.stop_price is None:
                    position.stop_price = candidate
                elif is_long:
                    # A trailing stop only ever moves in the trade's favour.
                    position.stop_price = max(position.stop_price, candidate)
                else:
                    position.stop_price = min(position.stop_price, candidate)

        return position

    def _signal_exit(
        self,
        position: _OpenPosition,
        index: int,
        longs: NDArray[np.bool_],
        shorts: NDArray[np.bool_],
    ) -> ExitReason | None:
        exits = self.strategy.exits
        trade = position.trade

        if exits.time_exit_bars is not None and index - trade.entry_index >= exits.time_exit_bars:
            return ExitReason.TIME_EXIT

        if exits.exit_on_opposite:
            if trade.is_long and shorts[index]:
                return ExitReason.OPPOSITE_SIGNAL
            if not trade.is_long and longs[index]:
                return ExitReason.OPPOSITE_SIGNAL

        return None

    def _close(
        self,
        position: _OpenPosition,
        index: int,
        time_ms: int,
        price: float,
        reason: ExitReason,
        equity: float,
    ) -> float:
        config = self.config
        trade = position.trade
        is_long = trade.is_long

        # Closing a long is a sell, so slippage pushes the fill down.
        fill = (
            price
            if reason is ExitReason.LIQUIDATION
            else _apply_slippage(price, config.slippage_bps, buying=not is_long)
        )

        trade.exit_index = index
        trade.exit_time = time_ms
        trade.exit_price = fill
        trade.exit_reason = reason

        direction = 1.0 if is_long else -1.0
        trade.gross_pnl = (fill - trade.entry_price) * trade.quantity * direction
        trade.exit_fee = fill * trade.quantity * config.exit_fee_rate

        trade.net_pnl = trade.gross_pnl - trade.total_fees - trade.funding_paid

        # A liquidated position cannot lose more than the collateral behind
        # it: the isolated margin, or the whole balance in cross mode
        # (SPEC §6), which is exactly why cross is the more dangerous choice.
        if reason is ExitReason.LIQUIDATION:
            backing = equity if config.margin_mode is MarginMode.CROSS else trade.margin
            trade.net_pnl = max(trade.net_pnl, -backing)

        equity += trade.net_pnl
        trade.equity_after = equity
        return equity

    def _accrue_funding(
        self, position: _OpenPosition, bar_start: int, bar_end: int, price: float
    ) -> None:
        """Charge funding for every settlement inside this bar.

        SPEC §6: fee = position value x rate, every 8h, and a positive rate
        means longs pay shorts.
        """
        if not self.config.apply_funding:
            return

        while position.next_funding_time < bar_end:
            settlement = position.next_funding_time
            if settlement >= bar_start:
                rate = _funding_rate_at(self.funding, settlement)
                notional = price * position.trade.quantity
                direction = 1.0 if position.trade.is_long else -1.0
                position.trade.funding_paid += notional * rate * direction
            position.next_funding_time += FUNDING_INTERVAL_MS

    def _track_excursion(self, position: _OpenPosition, high: float, low: float) -> None:
        """Best and worst open profit, for the MAE study (SPEC §3.2)."""
        trade = position.trade
        direction = 1.0 if trade.is_long else -1.0

        best = (high - trade.entry_price) * direction * trade.quantity
        worst = (low - trade.entry_price) * direction * trade.quantity
        if not trade.is_long:
            best, worst = worst, best

        trade.run_up = max(trade.run_up, best)
        trade.drawdown = min(trade.drawdown, worst)

    def _unrealised(self, position: _OpenPosition | None, price: float) -> float:
        if position is None:
            return 0.0
        trade = position.trade
        direction = 1.0 if trade.is_long else -1.0
        return (price - trade.entry_price) * trade.quantity * direction

    @staticmethod
    def _drawdown(equity: Array) -> Array:
        """Percentage below the running peak, at each bar."""
        if equity.size == 0:
            return equity
        peaks = np.maximum.accumulate(equity)
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(peaks > 0, (equity - peaks) / peaks * 100.0, 0.0)


def run_backtest(
    strategy: Strategy,
    bars: Bars,
    config: BacktestConfig | None = None,
    *,
    funding: list[FundingEvent] | None = None,
    magnifier: Bars | None = None,
) -> BacktestResult:
    """Run ``strategy`` over ``bars`` and compute its statistics."""
    from quanta_engine.backtest.stats import compute_stats

    result = Backtester(strategy, config, funding=funding, magnifier=magnifier).run(bars)
    result.stats = compute_stats(result, config or BacktestConfig(), bars)
    return result
