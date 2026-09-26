"""Risk limits, with the exit rule first.

The most important test in this file is that a tripped limit still lets the
closing order through. A limit that traps a bot in a losing position has
taken a bad day and made it unbounded, which is the opposite of the job.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from quanta.exchanges.trading import (
    MarginMode,
    OrderRequest,
    OrderSide,
    OrderType,
    Position,
)
from quanta.services.risk import RiskCode, RiskGuard, RiskLimits, RiskState

NOON = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)

LIMITS = RiskLimits(
    max_position_notional=Decimal(10_000),
    max_daily_loss=Decimal(500),
    max_drawdown_percent=Decimal(20),
    max_leverage=10,
    max_orders_per_minute=5,
)


def guard(equity: Decimal = Decimal(10_000), limits: RiskLimits = LIMITS) -> RiskGuard:
    return RiskGuard(limits, RiskState.starting_at(equity, NOON))


def order(qty: str, *, reduce_only: bool = False) -> OrderRequest:
    return OrderRequest(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        qty=Decimal(qty),
        client_id="cid",
        reduce_only=reduce_only,
    )


def position(qty: str, price: str = "100") -> Position:
    return Position(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        qty=Decimal(qty),
        entry_price=Decimal(price),
        leverage=1,
        margin_mode=MarginMode.ISOLATED,
        mark_price=Decimal(price),
    )


class TestExitsAreNeverBlocked:
    """The rule that outranks every limit."""

    def test_a_reduce_only_order_passes_a_breached_daily_loss(self) -> None:
        g = guard()
        # Far past the daily loss limit.
        assert not g.check_equity(Decimal(9_000), NOON).allowed

        verdict = g.check_order(
            order("1", reduce_only=True),
            price=Decimal(100),
            equity=Decimal(9_000),
            positions=[position("1")],
            leverage=1,
            at=NOON,
        )
        assert verdict.allowed

    def test_a_reduce_only_order_passes_a_breached_drawdown(self) -> None:
        g = guard()
        g.state.observe(Decimal(20_000), NOON)  # a new peak
        verdict = g.check_order(
            order("1", reduce_only=True),
            price=Decimal(100),
            equity=Decimal(10_000),  # 50% off the peak
            positions=[position("1")],
            leverage=1,
            at=NOON,
        )
        assert verdict.allowed

    def test_a_reduce_only_order_passes_the_position_limit(self) -> None:
        verdict = guard().check_order(
            order("1000", reduce_only=True),
            price=Decimal(100),
            equity=Decimal(10_000),
            positions=[position("900")],
            leverage=1,
            at=NOON,
        )
        assert verdict.allowed

    def test_a_reduce_only_order_passes_the_rate_limit(self) -> None:
        g = guard()
        for _ in range(20):
            g.state.record_order(NOON)
        verdict = g.check_order(
            order("1", reduce_only=True),
            price=Decimal(100),
            equity=Decimal(10_000),
            positions=[],
            leverage=1,
            at=NOON,
        )
        assert verdict.allowed


class TestDailyLoss:
    def test_within_the_limit_is_allowed(self) -> None:
        assert guard().check_equity(Decimal(9_600), NOON).allowed

    def test_at_the_limit_halts(self) -> None:
        verdict = guard().check_equity(Decimal(9_500), NOON)
        assert not verdict.allowed
        assert verdict.code is RiskCode.DAILY_LOSS
        assert verdict.halt

    def test_the_message_names_both_figures(self) -> None:
        verdict = guard().check_equity(Decimal(9_000), NOON)
        assert "1000" in verdict.message
        assert "500" in verdict.message
        assert verdict.observed == Decimal(1_000)
        assert verdict.limit == Decimal(500)

    def test_the_day_rolls_at_the_utc_boundary(self) -> None:
        g = guard()
        g.check_equity(Decimal(9_600), NOON)
        # Next day: the loss is measured from this morning, not yesterday's.
        tomorrow = NOON + timedelta(days=1)
        assert g.check_equity(Decimal(9_600), tomorrow).allowed
        assert g.state.day_start_equity == Decimal(9_600)

    def test_a_loss_carried_into_a_new_day_does_not_trip_again(self) -> None:
        g = guard()
        assert not g.check_equity(Decimal(9_400), NOON).allowed
        assert g.check_equity(Decimal(9_400), NOON + timedelta(days=1)).allowed

    def test_profit_does_not_count_as_loss(self) -> None:
        assert guard().check_equity(Decimal(12_000), NOON).allowed


class TestDrawdown:
    def test_measured_from_the_peak_not_the_start(self) -> None:
        g = guard()
        g.check_equity(Decimal(20_000), NOON)
        # 20% off 20,000 is 16,000, which is still above the 10,000 start.
        verdict = g.check_equity(Decimal(16_000), NOON)
        assert not verdict.allowed
        assert verdict.code is RiskCode.MAX_DRAWDOWN
        assert verdict.halt

    def test_just_inside_the_limit_is_allowed(self) -> None:
        # A daily-loss limit wide enough to stay out of the way: this is
        # about the drawdown boundary, and the daily check runs first.
        g = guard(limits=replace(LIMITS, max_daily_loss=Decimal(1_000_000)))
        g.check_equity(Decimal(10_000), NOON)
        assert g.check_equity(Decimal(8_001), NOON).allowed

    def test_daily_loss_is_reported_before_drawdown(self) -> None:
        """Both are breached; the user is told about the day, which is the
        one that resets on its own."""
        g = guard()
        g.check_equity(Decimal(10_000), NOON)
        verdict = g.check_equity(Decimal(5_000), NOON)
        assert verdict.code is RiskCode.DAILY_LOSS

    def test_the_peak_only_goes_up(self) -> None:
        g = guard()
        g.check_equity(Decimal(15_000), NOON)
        g.check_equity(Decimal(14_000), NOON)
        assert g.state.peak_equity == Decimal(15_000)


class TestLeverage:
    def test_above_the_limit_halts(self) -> None:
        verdict = guard().check_order(
            order("1"),
            price=Decimal(100),
            equity=Decimal(10_000),
            positions=[],
            leverage=25,
            at=NOON,
        )
        assert not verdict.allowed
        assert verdict.code is RiskCode.LEVERAGE_TOO_HIGH
        # A bot trading at the wrong leverage is misconfigured, not unlucky.
        assert verdict.halt

    def test_at_the_limit_is_allowed(self) -> None:
        verdict = guard().check_order(
            order("1"),
            price=Decimal(100),
            equity=Decimal(10_000),
            positions=[],
            leverage=10,
            at=NOON,
        )
        assert verdict.allowed


class TestPositionSize:
    def test_an_order_that_would_exceed_the_limit_is_blocked(self) -> None:
        verdict = guard().check_order(
            order("60"),
            price=Decimal(100),
            equity=Decimal(10_000),
            positions=[position("50")],  # 5,000 held
            leverage=1,
            at=NOON,
        )
        assert not verdict.allowed
        assert verdict.code is RiskCode.POSITION_TOO_LARGE

    def test_it_blocks_without_halting(self) -> None:
        """Too big an order is not a reason to stop the bot."""
        verdict = guard().check_order(
            order("200"),
            price=Decimal(100),
            equity=Decimal(10_000),
            positions=[],
            leverage=1,
            at=NOON,
        )
        assert not verdict.halt

    def test_existing_positions_count_towards_it(self) -> None:
        g = guard()
        alone = g.check_order(
            order("50"),
            price=Decimal(100),
            equity=Decimal(10_000),
            positions=[],
            leverage=1,
            at=NOON,
        )
        assert alone.allowed

        with_held = g.check_order(
            order("50"),
            price=Decimal(100),
            equity=Decimal(10_000),
            positions=[position("60")],
            leverage=1,
            at=NOON,
        )
        assert not with_held.allowed

    def test_largest_allowed_qty_is_the_room_left(self) -> None:
        g = guard()
        assert g.largest_allowed_qty(price=Decimal(100), positions=[position("50")]) == Decimal(50)

    def test_largest_allowed_qty_is_zero_when_full(self) -> None:
        g = guard()
        assert g.largest_allowed_qty(price=Decimal(100), positions=[position("200")]) == Decimal(0)


class TestOrderRate:
    def test_under_the_limit_is_allowed(self) -> None:
        g = guard()
        for _ in range(4):
            g.state.record_order(NOON)
        verdict = g.check_order(
            order("1"),
            price=Decimal(100),
            equity=Decimal(10_000),
            positions=[],
            leverage=1,
            at=NOON,
        )
        assert verdict.allowed

    def test_at_the_limit_is_blocked_but_not_halted(self) -> None:
        g = guard()
        for _ in range(5):
            g.state.record_order(NOON)
        verdict = g.check_order(
            order("1"),
            price=Decimal(100),
            equity=Decimal(10_000),
            positions=[],
            leverage=1,
            at=NOON,
        )
        assert not verdict.allowed
        assert verdict.code is RiskCode.RATE_LIMITED
        # A burst is usually one signal seen several times.
        assert not verdict.halt

    def test_the_window_slides(self) -> None:
        g = guard()
        for _ in range(5):
            g.state.record_order(NOON)
        later = NOON + timedelta(seconds=61)
        verdict = g.check_order(
            order("1"),
            price=Decimal(100),
            equity=Decimal(10_000),
            positions=[],
            leverage=1,
            at=later,
        )
        assert verdict.allowed

    def test_old_orders_are_forgotten_rather_than_accumulating(self) -> None:
        g = guard()
        for i in range(100):
            g.state.record_order(NOON + timedelta(seconds=i * 2))
        # Only the last minute is kept in memory.
        assert len(g.state.recent_orders) <= 31


class TestBudgets:
    def test_nothing_used_at_the_start(self) -> None:
        budgets = guard().budgets(Decimal(10_000))
        assert budgets["daily_loss_used_percent"] == Decimal(0)
        assert budgets["drawdown_used_percent"] == Decimal(0)

    def test_half_the_daily_loss_reads_fifty_percent(self) -> None:
        budgets = guard().budgets(Decimal(9_750))
        assert budgets["daily_loss_used_percent"] == Decimal(50)

    def test_a_breach_is_capped_at_one_hundred(self) -> None:
        """The bar is a bar; 300% of a budget would draw off the end."""
        budgets = guard().budgets(Decimal(5_000))
        assert budgets["daily_loss_used_percent"] == Decimal(100)
        assert budgets["drawdown_used_percent"] == Decimal(100)

    def test_profit_does_not_read_as_negative(self) -> None:
        budgets = guard().budgets(Decimal(12_000))
        assert budgets["daily_loss_used_percent"] == Decimal(0)


class TestLimitsValidation:
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("max_position_notional", Decimal(0)),
            ("max_daily_loss", Decimal(-1)),
            ("max_drawdown_percent", Decimal(0)),
            ("max_drawdown_percent", Decimal(101)),
            ("max_leverage", 0),
            ("max_orders_per_minute", 0),
        ],
    )
    def test_nonsense_limits_are_refused(self, field: str, value: object) -> None:
        kwargs = {
            "max_position_notional": Decimal(1),
            "max_daily_loss": Decimal(1),
            "max_drawdown_percent": Decimal(10),
            "max_leverage": 1,
            "max_orders_per_minute": 1,
            field: value,
        }
        with pytest.raises(ValueError, match=field.replace("_", "_")):
            RiskLimits(**kwargs)  # type: ignore[arg-type]
