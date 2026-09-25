"""Hand-checked backtest fixtures.

This is phase 2's acceptance test (SPEC §8): "Backtest reproduces
hand-checked fixtures". Every expected number below is worked out by
arithmetic written in the comments, not copied from what the engine
happened to print. If the engine and the arithmetic disagree, the engine
is wrong.

The scenarios are deliberately tiny — a handful of bars with round numbers
— so each rule can be isolated and checked on paper.
"""

from __future__ import annotations

import numpy as np
import pytest

from quanta_engine.backtest.engine import run_backtest
from quanta_engine.backtest.liquidation import PositionTier
from quanta_engine.backtest.types import BacktestConfig, Bars, FundingEvent
from quanta_engine.strategy import ExitReason, ExitRules, MarginMode, Strategy

MINUTE = 60_000
HOUR = 3_600_000
# A round start time that is exactly a funding boundary (00:00 UTC).
T0 = 1_700_000_000_000 - (1_700_000_000_000 % (8 * HOUR))


def make_bars(
    closes: list[float],
    *,
    step_ms: int = HOUR,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    opens: list[float] | None = None,
    start: int = T0,
) -> Bars:
    """Bars with explicit prices. Defaults make open == close and a 1% range."""
    n = len(closes)
    close = np.array(closes, dtype=np.float64)
    open_ = np.array(opens if opens is not None else closes, dtype=np.float64)
    high = np.array(highs if highs is not None else [c * 1.001 for c in closes])
    low = np.array(lows if lows is not None else [c * 0.999 for c in closes])

    return Bars(
        time=np.arange(n, dtype=np.int64) * step_ms + start,
        open=open_,
        high=np.maximum(high, np.maximum(open_, close)),
        low=np.minimum(low, np.minimum(open_, close)),
        close=close,
        volume=np.full(n, 1000.0),
    )


def no_cost_config(**overrides: object) -> BacktestConfig:
    """Costs off, so a scenario can isolate one rule at a time."""
    defaults: dict[str, object] = {
        "initial_capital": 10_000.0,
        "margin_percent": 10.0,
        "leverage": 1.0,
        "maker_fee": 0.0,
        "taker_fee": 0.0,
        "slippage_bps": 0.0,
        "apply_funding": False,
    }
    defaults.update(overrides)
    return BacktestConfig(**defaults)  # type: ignore[arg-type]


# A strategy that goes long when close crosses above 100 and never exits on
# its own, so the exit rules under test are the only thing that can close it.
def crossover_strategy(**exit_kwargs: object) -> Strategy:
    return Strategy(
        name="Fixture",
        long_entry="crossover(close, 100)",
        exits=ExitRules(exit_on_opposite=False, **exit_kwargs),  # type: ignore[arg-type]
    )


class TestFillTiming:
    def test_entry_fills_at_the_next_bar_open(self) -> None:
        """A signal on bar 2's close cannot be filled before bar 3 exists.

        closes:  99, 99, 101, 105
        crossover(close, 100) is true on bar 2 (99 -> 101).
        The fill must therefore be bar 3's OPEN of 104, not bar 2's close.
        """
        bars = make_bars([99, 99, 101, 105], opens=[99, 99, 100, 104])
        result = run_backtest(crossover_strategy(), bars, no_cost_config())

        assert len(result.trades) == 1
        trade = result.trades[0]
        assert trade.entry_index == 3
        assert trade.entry_price == pytest.approx(104.0)

    def test_a_signal_on_the_last_bar_never_fills(self) -> None:
        """There is no next bar to fill at, so no trade is opened."""
        bars = make_bars([99, 99, 101])
        result = run_backtest(crossover_strategy(), bars, no_cost_config())
        assert result.trades == []

    def test_no_lookahead_in_the_entry_price(self) -> None:
        """Changing bars after the fill must not change the fill price."""
        base = [99, 99, 101, 105, 106, 107]
        opens = [99, 99, 100, 104, 105, 106]

        first = run_backtest(crossover_strategy(), make_bars(base, opens=opens), no_cost_config())
        # Rewrite everything after the entry bar.
        altered = run_backtest(
            crossover_strategy(),
            make_bars([99, 99, 101, 105, 200, 300], opens=[99, 99, 100, 104, 150, 250]),
            no_cost_config(),
        )
        assert first.trades[0].entry_price == altered.trades[0].entry_price


class TestPnlArithmetic:
    def test_long_profit_is_exact(self) -> None:
        """10,000 capital, 10% margin, 1x leverage, entry 104, exit 120.

        margin   = 10,000 x 10%     = 1,000
        notional = 1,000 x 1        = 1,000
        quantity = 1,000 / 104      = 9.615384615...
        gross    = (120 - 104) x qty = 16 x 9.615384615 = 153.846153...
        """
        bars = make_bars([99, 99, 101, 105, 110, 120], opens=[99, 99, 100, 104, 108, 118])
        strategy = Strategy(
            name="Exit at the end",
            long_entry="crossover(close, 100)",
            exits=ExitRules(exit_on_opposite=False),
        )
        result = run_backtest(strategy, bars, no_cost_config())

        trade = result.trades[0]
        expected_quantity = 1_000.0 / 104.0
        assert trade.quantity == pytest.approx(expected_quantity)
        assert trade.entry_price == pytest.approx(104.0)
        # Closed at the final bar's close of 120.
        assert trade.exit_reason is ExitReason.END_OF_DATA
        assert trade.exit_price == pytest.approx(120.0)
        assert trade.gross_pnl == pytest.approx(16.0 * expected_quantity)
        assert trade.net_pnl == pytest.approx(16.0 * expected_quantity)
        assert result.stats["ending_equity"] == pytest.approx(10_000.0 + 16.0 * expected_quantity)

    def test_short_profit_has_the_opposite_sign(self) -> None:
        """A short entered at 104 and closed at 90 gains 14 per unit.

        quantity = 1,000 / 104
        gross    = (104 - 90) x qty = 14 x 9.615384615 = 134.615384...
        """
        bars = make_bars([101, 101, 99, 95, 90], opens=[101, 101, 100, 104, 92])
        strategy = Strategy(
            name="Short",
            short_entry="crossunder(close, 100)",
            exits=ExitRules(exit_on_opposite=False),
        )
        result = run_backtest(strategy, bars, no_cost_config())

        trade = result.trades[0]
        assert trade.side == "short"
        assert trade.entry_price == pytest.approx(104.0)
        expected_quantity = 1_000.0 / 104.0
        assert trade.gross_pnl == pytest.approx(14.0 * expected_quantity)

    def test_leverage_multiplies_size_not_risk_free_return(self) -> None:
        """At 10x the same margin controls ten times the quantity.

        margin 1,000 at 10x -> notional 10,000 -> quantity 10,000/104.
        """
        bars = make_bars([99, 99, 101, 105, 120], opens=[99, 99, 100, 104, 118])
        result = run_backtest(crossover_strategy(), bars, no_cost_config(leverage=10.0))
        trade = result.trades[0]
        assert trade.quantity == pytest.approx(10_000.0 / 104.0)
        assert trade.margin == pytest.approx(1_000.0)


class TestCosts:
    def test_fees_are_charged_on_both_sides(self) -> None:
        """Taker 0.06% on entry and exit notional.

        entry notional = 1,000            -> fee 0.60
        exit  notional = qty x 120
                       = (1,000/104) x 120 = 1,153.846...  -> fee 0.692307...
        """
        bars = make_bars([99, 99, 101, 105, 120], opens=[99, 99, 100, 104, 118])
        config = no_cost_config(taker_fee=0.0006, maker_fee=0.0002)
        result = run_backtest(crossover_strategy(), bars, config)

        trade = result.trades[0]
        quantity = 1_000.0 / 104.0
        assert trade.entry_fee == pytest.approx(1_000.0 * 0.0006)
        assert trade.exit_fee == pytest.approx(120.0 * quantity * 0.0006)
        assert trade.net_pnl == pytest.approx(trade.gross_pnl - trade.entry_fee - trade.exit_fee)

    def test_slippage_always_moves_against_the_trade(self) -> None:
        """10 bps: a buy fills 0.1% higher, the closing sell 0.1% lower.

        entry 104 x 1.001 = 104.104
        exit  120 x 0.999 = 119.88
        """
        bars = make_bars([99, 99, 101, 105, 120], opens=[99, 99, 100, 104, 118])
        result = run_backtest(crossover_strategy(), bars, no_cost_config(slippage_bps=10.0))

        trade = result.trades[0]
        assert trade.entry_price == pytest.approx(104.104)
        assert trade.exit_price == pytest.approx(119.88)
        # Slippage must reduce the result, never improve it.
        clean = run_backtest(crossover_strategy(), bars, no_cost_config())
        assert trade.net_pnl < clean.trades[0].net_pnl

    def test_funding_is_charged_every_eight_hours(self) -> None:
        """Longs pay when the rate is positive (SPEC §6).

        Bars are hourly from a 00:00 boundary. Entry fills at bar 3, so the
        position is open across the 08:00 settlement at bar 8.

        fee = notional at that bar x rate = (qty x close) x 0.0001
        """
        closes = [99, 99, 101] + [105] * 8
        opens = [99, 99, 100] + [104] * 8
        bars = make_bars(closes, opens=opens, step_ms=HOUR)

        settlement = T0 + 8 * HOUR
        config = no_cost_config(apply_funding=True)
        result = run_backtest(
            crossover_strategy(),
            bars,
            config,
            funding=[FundingEvent(time=settlement, rate=0.0001)],
        )

        trade = result.trades[0]
        quantity = 1_000.0 / 104.0
        expected = 105.0 * quantity * 0.0001
        assert trade.funding_paid == pytest.approx(expected)
        assert trade.net_pnl == pytest.approx(trade.gross_pnl - expected)

    def test_a_short_receives_funding_when_the_rate_is_positive(self) -> None:
        """The sign flips for shorts: they are paid, so funding is negative."""
        closes = [101, 101, 99] + [95] * 8
        opens = [101, 101, 100] + [96] * 8
        bars = make_bars(closes, opens=opens, step_ms=HOUR)

        strategy = Strategy(
            name="Short",
            short_entry="crossunder(close, 100)",
            exits=ExitRules(exit_on_opposite=False),
        )
        result = run_backtest(
            strategy,
            bars,
            no_cost_config(apply_funding=True),
            funding=[FundingEvent(time=T0 + 8 * HOUR, rate=0.0001)],
        )
        assert result.trades[0].funding_paid < 0

    def test_funding_is_skipped_when_disabled(self) -> None:
        closes = [99, 99, 101] + [105] * 8
        bars = make_bars(closes, opens=[99, 99, 100] + [104] * 8)
        result = run_backtest(
            crossover_strategy(),
            bars,
            no_cost_config(apply_funding=False),
            funding=[FundingEvent(time=T0 + 8 * HOUR, rate=0.01)],
        )
        assert result.trades[0].funding_paid == 0.0


class TestExitResolution:
    def test_stop_is_assumed_first_without_a_magnifier(self) -> None:
        """When one bar spans both levels, the pessimistic outcome is taken.

        ATR-based stop with a wide bar: without 1m data the engine cannot
        know which came first, and guessing the profitable one would make
        every such strategy look better than it is.
        """
        # Flat bars so ATR is a clean 1.0, then one bar spanning both levels.
        closes = [99] * 16 + [101, 105, 105]
        opens = [99] * 16 + [100, 104, 104]
        highs = [99.5] * 16 + [101.5, 130.0, 105.5]
        lows = [98.5] * 16 + [100.5, 70.0, 104.5]
        bars = make_bars(closes, opens=opens, highs=highs, lows=lows)

        strategy = crossover_strategy(atr_stop_multiple=1.0, atr_length=14, take_profit_r=1.0)
        result = run_backtest(strategy, bars, no_cost_config())

        assert len(result.trades) == 1
        assert result.trades[0].exit_reason is ExitReason.STOP_LOSS

    def test_the_magnifier_decides_the_real_order(self) -> None:
        """With 1m bars showing the take profit reached first, it wins.

        The same wide bar as above, but the minute bars inside it rise to
        the target before falling to the stop.
        """
        closes = [99] * 16 + [101, 105, 105]
        opens = [99] * 16 + [100, 104, 104]
        highs = [99.5] * 16 + [101.5, 130.0, 105.5]
        lows = [98.5] * 16 + [100.5, 70.0, 104.5]
        bars = make_bars(closes, opens=opens, highs=highs, lows=lows)

        entry_bar_start = int(bars.time[17])
        # Minute 0-4 climb to 130; minute 5 onward collapse to 70.
        minute_times = np.arange(60, dtype=np.int64) * MINUTE + entry_bar_start
        minute_high = np.where(np.arange(60) < 5, 130.0, 105.0)
        minute_low = np.where(np.arange(60) < 5, 104.0, 70.0)
        magnifier = Bars(
            time=minute_times,
            open=np.full(60, 104.0),
            high=minute_high,
            low=minute_low,
            close=np.full(60, 104.0),
            volume=np.full(60, 1.0),
        )

        strategy = crossover_strategy(atr_stop_multiple=1.0, atr_length=14, take_profit_r=1.0)
        result = run_backtest(strategy, bars, no_cost_config(), magnifier=magnifier)

        assert result.trades[0].exit_reason is ExitReason.TAKE_PROFIT

    def test_take_profit_fills_at_the_level_not_the_extreme(self) -> None:
        """The target fills at its own price even if the bar ran to 130.

        Working out the level, which is also a check on Wilder's warm-up:

        Bars 0-15 are flat with a true range of 1.0, so the 14-period seed
        (the mean of TR over bars 0-13) is 1.0, and bars 14-15 keep it there.

        Bar 16 closes at 101 against a previous close of 99, so its true
        range is max(101.5-100.5, |101.5-99|, |100.5-99|) = 2.5, giving

            ATR[16] = (1.0 x 13 + 2.5) / 14 = 1.1071428571...

        The entry fills on bar 17 using bar 16's ATR (no lookahead), so

            stop distance = 2 x 1.1071428571 = 2.2142857142
            take profit   = 104 + 2.2142857142 = 106.2142857142
        """
        closes = [99] * 16 + [101, 105, 105]
        opens = [99] * 16 + [100, 104, 104]
        highs = [99.5] * 16 + [101.5, 130.0, 105.5]
        lows = [98.5] * 16 + [100.5, 103.9, 104.5]
        bars = make_bars(closes, opens=opens, highs=highs, lows=lows)

        strategy = crossover_strategy(atr_stop_multiple=2.0, atr_length=14, take_profit_r=1.0)
        result = run_backtest(strategy, bars, no_cost_config())

        trade = result.trades[0]
        assert trade.exit_reason is ExitReason.TAKE_PROFIT
        assert trade.exit_price == pytest.approx(104.0 + 2.0 * (1.0 * 13 + 2.5) / 14)

    def test_time_exit_closes_after_the_configured_bars(self) -> None:
        """Entered at bar 3, a 2-bar limit closes at bar 5's open."""
        bars = make_bars([99, 99, 101, 105, 105, 105, 105], opens=[99, 99, 100, 104, 104, 104, 104])
        strategy = crossover_strategy(time_exit_bars=2)
        result = run_backtest(strategy, bars, no_cost_config())

        trade = result.trades[0]
        assert trade.exit_reason is ExitReason.TIME_EXIT
        assert trade.entry_index == 3
        assert trade.exit_index == 6

    def test_opposite_signal_flips_the_position(self) -> None:
        """A short signal while long closes and reverses at the same fill."""
        bars = make_bars(
            [99, 99, 101, 105, 105, 99, 95, 95],
            opens=[99, 99, 100, 104, 104, 100, 96, 96],
        )
        strategy = Strategy(
            name="Flip",
            long_entry="crossover(close, 100)",
            short_entry="crossunder(close, 100)",
            exits=ExitRules(exit_on_opposite=True),
        )
        result = run_backtest(strategy, bars, no_cost_config())

        assert len(result.trades) == 2
        first, second = result.trades
        assert first.side == "long"
        assert first.exit_reason is ExitReason.OPPOSITE_SIGNAL
        assert second.side == "short"
        # The reversal happens at one price, on one bar.
        assert second.entry_time == first.exit_time
        assert second.entry_price == pytest.approx(first.exit_price)


class TestLiquidation:
    def test_a_long_is_liquidated_at_the_computed_price(self) -> None:
        """20x long, isolated, flat 0.5% MMR.

        margin   = 1,000, notional = 20,000, entry 100 -> quantity 200
        maint    = 20,000 x 0.005 = 100
        liq      = 100 - (1,000 - 100)/200 = 100 - 4.5 = 95.5
        """
        closes = [99, 99, 101, 100, 90]
        bars = make_bars(closes, opens=[99, 99, 100, 100, 94], lows=[98, 98, 100, 99, 80])

        config = no_cost_config(leverage=20.0, margin_mode=MarginMode.ISOLATED)
        result = run_backtest(crossover_strategy(), bars, config)

        trade = result.trades[0]
        assert trade.entry_price == pytest.approx(100.0)
        assert trade.quantity == pytest.approx(200.0)
        assert trade.liquidation_price == pytest.approx(95.5)
        assert trade.exit_reason is ExitReason.LIQUIDATION
        assert trade.exit_price == pytest.approx(95.5)

    def test_a_liquidated_isolated_position_loses_only_its_margin(self) -> None:
        """However far price gapped, isolated risk is capped at the margin."""
        closes = [99, 99, 101, 100, 10]
        bars = make_bars(closes, opens=[99, 99, 100, 100, 20], lows=[98, 98, 100, 99, 5])

        result = run_backtest(crossover_strategy(), bars, no_cost_config(leverage=20.0))
        trade = result.trades[0]
        assert trade.exit_reason is ExitReason.LIQUIDATION
        assert trade.net_pnl >= -trade.margin

    def test_tiers_make_a_large_position_liquidate_sooner(self) -> None:
        """A higher maintenance rate brings the liquidation price closer."""
        from quanta_engine.backtest.liquidation import liquidation_price

        low_tier = (PositionTier(1, 0.0, 1e9, 100, 0.004),)
        high_tier = (PositionTier(1, 0.0, 1e9, 100, 0.02),)

        near = liquidation_price(
            entry_price=100, quantity=200, margin=1_000, is_long=True, tiers=high_tier
        )
        far = liquidation_price(
            entry_price=100, quantity=200, margin=1_000, is_long=True, tiers=low_tier
        )
        assert near > far

    def test_liquidation_uses_the_mark_price(self) -> None:
        """Mark and last diverge; liquidation follows mark (SPEC §6)."""
        from quanta_engine.backtest.liquidation import liquidation_price

        price = liquidation_price(entry_price=100.0, quantity=200.0, margin=1_000.0, is_long=True)
        # maint = 100 x 200 x 0.005 = 100; liq = 100 - (1000-100)/200 = 95.5
        assert price == pytest.approx(95.5)


class TestEquityAndStats:
    def test_equity_is_marked_to_market_each_bar(self) -> None:
        """While a trade is open, equity moves with the close."""
        bars = make_bars([99, 99, 101, 105, 110, 120], opens=[99, 99, 100, 104, 108, 118])
        result = run_backtest(crossover_strategy(), bars, no_cost_config())

        # Before the entry, equity is flat at the starting capital.
        assert result.equity[0] == pytest.approx(10_000.0)
        assert result.equity[2] == pytest.approx(10_000.0)
        # After it, equity rises with price.
        assert result.equity[4] > result.equity[3]

    def test_drawdown_is_zero_at_a_new_high(self) -> None:
        bars = make_bars([99, 99, 101, 105, 110, 120], opens=[99, 99, 100, 104, 108, 118])
        result = run_backtest(crossover_strategy(), bars, no_cost_config())
        assert result.drawdown[-1] == pytest.approx(0.0)
        assert float(np.max(result.drawdown)) <= 0.0

    def test_stats_add_up(self) -> None:
        bars = make_bars([99, 99, 101, 105, 110, 120], opens=[99, 99, 100, 104, 108, 118])
        result = run_backtest(crossover_strategy(), bars, no_cost_config(taker_fee=0.0006))
        stats = result.stats
        trade = result.trades[0]

        assert stats["total_trades"] == 1
        assert stats["net_profit"] == pytest.approx(trade.net_pnl)
        assert stats["ending_equity"] == pytest.approx(10_000.0 + trade.net_pnl)
        assert stats["total_fees"] == pytest.approx(trade.total_fees)
        assert stats["gross_profit"] == pytest.approx(trade.gross_pnl)

    def test_buy_and_hold_is_the_honest_comparison(self) -> None:
        """Closes run 99 -> 120, i.e. +21.21%."""
        bars = make_bars([99, 99, 101, 105, 110, 120], opens=[99, 99, 100, 104, 108, 118])
        result = run_backtest(crossover_strategy(), bars, no_cost_config())
        assert result.stats["buy_and_hold_percent"] == pytest.approx((120 - 99) / 99 * 100)


class TestVersioning:
    def test_the_result_records_the_strategy_version(self) -> None:
        """A forward test freezes this hash (SPEC §3.3)."""
        bars = make_bars([99, 99, 101, 105, 120], opens=[99, 99, 100, 104, 118])
        strategy = crossover_strategy()
        result = run_backtest(strategy, bars, no_cost_config())
        assert result.strategy_version == strategy.version_hash()
        assert len(result.strategy_version) == 64
