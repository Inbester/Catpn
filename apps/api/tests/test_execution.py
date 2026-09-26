"""The execution service, against the simulated venue.

The tests that matter most here are the ones about *not* doing something
twice: the same signal placed again, an order that timed out, a crash
between sending and recording. Each of those is a way to end up holding
twice what you meant to.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quanta.exchanges.sim.trading import (
    SimAccount,
    SimulatedTradingAdapter,
    default_permissions,
)
from quanta.exchanges.trading import (
    Credentials,
    MarginMode,
    OrderSide,
    Position,
    PositionMode,
    TradeSide,
    TradingError,
)
from quanta.services.execution import (
    BotContext,
    ExecutionService,
    Outcome,
    Purpose,
    client_id_for,
)
from quanta.services.risk import RiskGuard, RiskLimits, RiskState

NOON = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
SYMBOL = "BTCUSDT"
BAR = 1_773_000_000_000

LIMITS = RiskLimits(
    max_position_notional=Decimal(1_000_000),
    max_daily_loss=Decimal(5_000),
    max_drawdown_percent=Decimal(50),
    max_leverage=20,
    max_orders_per_minute=60,
)


def guard(equity: Decimal = Decimal(10_000)) -> RiskGuard:
    return RiskGuard(LIMITS, RiskState.starting_at(equity, NOON))


def context(mode: PositionMode = PositionMode.ONE_WAY, bot_id: str = "bot-1") -> BotContext:
    return BotContext(
        bot_id=bot_id,
        symbol=SYMBOL,
        leverage=10,
        margin_mode=MarginMode.ISOLATED,
        position_mode=mode,
        credentials=Credentials(api_key="k", api_secret="sim-secret"),
    )


@pytest.fixture
def venue() -> SimulatedTradingAdapter:
    adapter = SimulatedTradingAdapter(prices={SYMBOL: Decimal(100)})
    adapter.add_account("k")
    return adapter


@pytest.fixture
def service(venue: SimulatedTradingAdapter) -> ExecutionService:
    return ExecutionService(venue)


async def open_long(
    service: ExecutionService,
    *,
    qty: str = "1",
    g: RiskGuard | None = None,
    ctx: BotContext | None = None,
    positions: list[Position] | None = None,
    purpose: Purpose = Purpose.ENTRY,
):
    return await service.place(
        ctx or context(),
        side=OrderSide.BUY,
        qty=Decimal(qty),
        purpose=purpose,
        bar_time=BAR,
        price=Decimal(100),
        equity=Decimal(10_000),
        positions=positions or [],
        guard=g or guard(),
        at=NOON,
    )


class TestClientIds:
    def test_the_same_signal_gives_the_same_id(self) -> None:
        assert client_id_for("bot-1", BAR, Purpose.ENTRY) == client_id_for(
            "bot-1", BAR, Purpose.ENTRY
        )

    def test_different_bots_differ(self) -> None:
        assert client_id_for("bot-1", BAR, Purpose.ENTRY) != client_id_for(
            "bot-2", BAR, Purpose.ENTRY
        )

    def test_different_bars_differ(self) -> None:
        assert client_id_for("bot-1", BAR, Purpose.ENTRY) != client_id_for(
            "bot-1", BAR + 60_000, Purpose.ENTRY
        )

    def test_entry_and_exit_on_one_bar_differ(self) -> None:
        """Otherwise the exit would be refused as a duplicate of the entry."""
        assert client_id_for("bot-1", BAR, Purpose.ENTRY) != client_id_for(
            "bot-1", BAR, Purpose.EXIT
        )

    def test_a_deliberate_re_entry_differs(self) -> None:
        assert client_id_for("bot-1", BAR, Purpose.ENTRY) != client_id_for(
            "bot-1", BAR, Purpose.ENTRY, attempt=1
        )

    def test_ids_are_short_and_alphanumeric(self) -> None:
        """A venue that truncates a long id would silently break
        idempotency."""
        client_id = client_id_for("bot-1", BAR, Purpose.ENTRY)
        assert len(client_id) <= 32
        assert client_id.isalnum()


class TestIdempotency:
    async def test_the_same_signal_twice_places_one_order(
        self, service: ExecutionService, venue: SimulatedTradingAdapter
    ) -> None:
        await open_long(service)
        await open_long(service)

        positions = await venue.positions(context().credentials)
        assert [p.qty for p in positions] == [Decimal(1)]

    async def test_a_replay_after_a_crash_places_one_order(
        self, service: ExecutionService, venue: SimulatedTradingAdapter
    ) -> None:
        """The crash is between sending and recording: nothing local
        remembers the first send, and the id is recomputed from scratch."""
        await open_long(service)

        fresh = ExecutionService(venue)
        await open_long(fresh)

        positions = await venue.positions(context().credentials)
        assert [p.qty for p in positions] == [Decimal(1)]

    async def test_a_new_bar_does_place_another(
        self, service: ExecutionService, venue: SimulatedTradingAdapter
    ) -> None:
        g = guard()
        await open_long(service, g=g)
        await service.place(
            context(),
            side=OrderSide.BUY,
            qty=Decimal(1),
            purpose=Purpose.ADD,
            bar_time=BAR + 60_000,
            price=Decimal(100),
            equity=Decimal(10_000),
            positions=[],
            guard=g,
            at=NOON,
        )
        positions = await venue.positions(context().credentials)
        assert [p.qty for p in positions] == [Decimal(2)]


class TestRiskIntegration:
    async def test_a_blocked_order_never_reaches_the_venue(
        self, service: ExecutionService, venue: SimulatedTradingAdapter
    ) -> None:
        tight = RiskGuard(
            RiskLimits(
                max_position_notional=Decimal(10),
                max_daily_loss=Decimal(5_000),
                max_drawdown_percent=Decimal(50),
                max_leverage=20,
                max_orders_per_minute=60,
            ),
            RiskState.starting_at(Decimal(10_000), NOON),
        )
        result = await open_long(service, qty="100", g=tight)

        assert result.outcome is Outcome.BLOCKED
        assert result.verdict is not None
        assert await venue.positions(context().credentials) == []

    async def test_a_blocked_order_does_not_count_against_the_rate_limit(
        self, service: ExecutionService
    ) -> None:
        """It was never sent, so it cannot use up the venue's budget."""
        tight = RiskGuard(
            RiskLimits(
                max_position_notional=Decimal(10),
                max_daily_loss=Decimal(5_000),
                max_drawdown_percent=Decimal(50),
                max_leverage=20,
                max_orders_per_minute=60,
            ),
            RiskState.starting_at(Decimal(10_000), NOON),
        )
        await open_long(service, qty="100", g=tight)
        assert tight.state.orders_in_last_minute(NOON) == 0

    async def test_a_sent_order_counts_against_the_rate_limit(
        self, service: ExecutionService
    ) -> None:
        g = guard()
        await open_long(service, g=g)
        assert g.state.orders_in_last_minute(NOON) == 1

    async def test_a_venue_rejection_is_reported_not_raised(
        self, service: ExecutionService
    ) -> None:
        result = await service.place(
            context(),
            side=OrderSide.SELL,
            qty=Decimal(1),
            purpose=Purpose.EXIT,
            bar_time=BAR,
            price=Decimal(100),
            equity=Decimal(10_000),
            positions=[],
            guard=guard(),
            reduce_only=True,
            at=NOON,
        )
        assert result.outcome is Outcome.REJECTED
        assert result.error == "nothing to reduce"


class TestUncertainOrders:
    class Flaky(SimulatedTradingAdapter):
        """A venue that times out on placing, the way a real one does."""

        async def place_order(self, credentials, request):  # type: ignore[no-untyped-def]
            raise TradingError("timed out", code="timeout", retryable=False)

    async def test_a_timeout_is_uncertain_not_failed(self) -> None:
        adapter = self.Flaky(prices={SYMBOL: Decimal(100)})
        adapter.add_account("k")
        result = await open_long(ExecutionService(adapter))
        assert result.outcome is Outcome.UNCERTAIN

    async def test_a_retryable_error_is_a_clean_failure(self) -> None:
        class Refused(SimulatedTradingAdapter):
            async def place_order(self, credentials, request):  # type: ignore[no-untyped-def]
                raise TradingError("network", code="network", retryable=True)

        adapter = Refused(prices={SYMBOL: Decimal(100)})
        adapter.add_account("k")
        result = await open_long(ExecutionService(adapter))
        # Nothing was sent, so nothing has to be resolved.
        assert result.outcome is Outcome.FAILED

    async def test_resolving_finds_an_order_that_did_arrive(
        self, service: ExecutionService, venue: SimulatedTradingAdapter
    ) -> None:
        # A resting limit order, so it is still open to be found.
        client_id = client_id_for("bot-1", BAR, Purpose.ENTRY)
        from quanta.exchanges.trading import OrderRequest, OrderType

        await venue.place_order(
            context().credentials,
            OrderRequest(
                symbol=SYMBOL,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                qty=Decimal(1),
                client_id=client_id,
                price=Decimal(90),
            ),
        )
        result = await service.resolve(context(), client_id)
        assert result.outcome is Outcome.DUPLICATE
        assert result.order is not None

    async def test_resolving_an_order_that_never_arrived_stays_uncertain(
        self, service: ExecutionService
    ) -> None:
        result = await service.resolve(context(), "q-never-sent")
        assert result.outcome is Outcome.UNCERTAIN
        assert result.order is None


class TestHedgeMode:
    async def test_one_way_mode_sends_no_trade_side(
        self, service: ExecutionService, venue: SimulatedTradingAdapter
    ) -> None:
        await open_long(service)
        orders = list(venue._accounts["k"].orders.values())
        assert orders[0].trade_side is None

    async def test_hedge_mode_marks_an_entry_as_open(self) -> None:
        adapter = SimulatedTradingAdapter(prices={SYMBOL: Decimal(100)})
        adapter.add_account(
            "k", SimAccount(permissions=default_permissions(), position_mode=PositionMode.HEDGE)
        )
        service = ExecutionService(adapter)
        await open_long(service, ctx=context(PositionMode.HEDGE))

        orders = list(adapter._accounts["k"].orders.values())
        assert orders[0].trade_side is TradeSide.OPEN

    async def test_hedge_mode_marks_a_reduce_as_close(self) -> None:
        adapter = SimulatedTradingAdapter(prices={SYMBOL: Decimal(100)})
        adapter.add_account(
            "k", SimAccount(permissions=default_permissions(), position_mode=PositionMode.HEDGE)
        )
        service = ExecutionService(adapter)
        ctx = context(PositionMode.HEDGE)
        await open_long(service, ctx=ctx)
        await service.place(
            ctx,
            side=OrderSide.SELL,
            qty=Decimal(1),
            purpose=Purpose.EXIT,
            bar_time=BAR,
            price=Decimal(100),
            equity=Decimal(10_000),
            positions=[],
            guard=guard(),
            reduce_only=True,
            at=NOON,
        )
        assert await adapter.positions(ctx.credentials) == []

    async def test_a_mismatched_account_mode_is_refused(self) -> None:
        adapter = SimulatedTradingAdapter(prices={SYMBOL: Decimal(100)})
        adapter.add_account("k")  # one-way
        service = ExecutionService(adapter)
        reason = await service.check_position_mode(context(PositionMode.HEDGE))
        assert reason is not None
        assert "ONE_WAY" in reason

    async def test_a_matching_account_mode_passes(self, service: ExecutionService) -> None:
        assert await service.check_position_mode(context()) is None

    def test_two_bots_on_one_symbol_in_one_way_mode_conflict(self) -> None:
        reason = ExecutionService.conflicting_symbol(context(), [SYMBOL])
        assert reason is not None
        assert "hedge mode" in reason

    def test_hedge_mode_allows_two_bots_on_one_symbol(self) -> None:
        assert ExecutionService.conflicting_symbol(context(PositionMode.HEDGE), [SYMBOL]) is None

    def test_different_symbols_never_conflict(self) -> None:
        assert ExecutionService.conflicting_symbol(context(), ["ETHUSDT"]) is None


class TestReconciliation:
    async def test_it_reports_what_the_venue_holds(self, service: ExecutionService) -> None:
        await open_long(service)
        report = await service.reconcile(context())
        assert [p.qty for p in report.positions] == [Decimal(1)]

    async def test_agreement_produces_no_differences(self, service: ExecutionService) -> None:
        await open_long(service)
        report = await service.reconcile(context(), expected={SYMBOL: Decimal(1)})
        assert report.differences == []
        assert not report.should_halt

    async def test_a_position_we_do_not_know_about_halts(self, service: ExecutionService) -> None:
        await open_long(service)
        report = await service.reconcile(context(), expected={})
        assert [d.kind for d in report.differences] == ["untracked_position"]
        assert report.should_halt

    async def test_a_position_that_vanished_halts(self, service: ExecutionService) -> None:
        report = await service.reconcile(context(), expected={SYMBOL: Decimal(1)})
        assert [d.kind for d in report.differences] == ["missing_position"]
        assert report.should_halt

    async def test_a_size_that_merely_drifted_is_recorded_not_halted(
        self, service: ExecutionService
    ) -> None:
        """A partial fill we have not seen yet is not a reason to stop."""
        await open_long(service, qty="2")
        report = await service.reconcile(context(), expected={SYMBOL: Decimal(1)})
        assert [d.kind for d in report.differences] == ["size_differs"]
        assert not report.should_halt

    async def test_direction_is_part_of_the_comparison(self, service: ExecutionService) -> None:
        """A long where we expected a short is a difference, not a match."""
        await open_long(service)
        report = await service.reconcile(context(), expected={SYMBOL: Decimal(-1)})
        assert report.differences != []


class TestKillSwitch:
    async def test_it_cancels_resting_orders(
        self, service: ExecutionService, venue: SimulatedTradingAdapter
    ) -> None:
        from quanta.exchanges.trading import OrderRequest, OrderType

        await venue.place_order(
            context().credentials,
            OrderRequest(
                symbol=SYMBOL,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                qty=Decimal(1),
                client_id="resting",
                price=Decimal(90),
            ),
        )
        report = await service.kill([context()])

        assert report.orders_cancelled == 1
        assert await venue.open_orders(context().credentials) == []

    async def test_it_closes_open_positions(
        self, service: ExecutionService, venue: SimulatedTradingAdapter
    ) -> None:
        await open_long(service, qty="3")
        report = await service.kill([context()])

        assert report.positions_closed == 1
        assert await venue.positions(context().credentials) == []

    async def test_it_closes_a_short_too(
        self, service: ExecutionService, venue: SimulatedTradingAdapter
    ) -> None:
        await service.place(
            context(),
            side=OrderSide.SELL,
            qty=Decimal(2),
            purpose=Purpose.ENTRY,
            bar_time=BAR,
            price=Decimal(100),
            equity=Decimal(10_000),
            positions=[],
            guard=guard(),
            at=NOON,
        )
        await service.kill([context()])
        assert await venue.positions(context().credentials) == []

    async def test_closing_orders_are_reduce_only(
        self, service: ExecutionService, venue: SimulatedTradingAdapter
    ) -> None:
        """A stale size must not flip the position instead of closing it."""
        await open_long(service, qty="2")
        await service.kill([context()])

        closes = [o for o in venue._accounts["k"].orders.values() if o.reduce_only]
        assert closes
        assert all(o.reduce_only for o in closes)

    async def test_it_kills_every_bot_it_is_given(self, venue: SimulatedTradingAdapter) -> None:
        venue.set_price("ETHUSDT", Decimal(50))
        service = ExecutionService(venue)
        btc = context()
        eth = BotContext(
            bot_id="bot-2",
            symbol="ETHUSDT",
            leverage=10,
            margin_mode=MarginMode.ISOLATED,
            position_mode=PositionMode.HEDGE,
            credentials=btc.credentials,
        )
        await open_long(service, ctx=btc)
        await service.place(
            eth,
            side=OrderSide.BUY,
            qty=Decimal(1),
            purpose=Purpose.ENTRY,
            bar_time=BAR,
            price=Decimal(50),
            equity=Decimal(10_000),
            positions=[],
            guard=guard(),
            at=NOON,
        )

        report = await service.kill([btc, eth])
        assert report.positions_closed == 2
        assert report.clean

    async def test_nothing_to_do_is_a_clean_kill(self, service: ExecutionService) -> None:
        report = await service.kill([context()])
        assert report.clean
        assert report.positions_closed == 0

    async def test_a_failure_is_named_rather_than_raised(self) -> None:
        class Broken(SimulatedTradingAdapter):
            async def place_order(self, credentials, request):  # type: ignore[no-untyped-def]
                raise TradingError("venue is down", code="upstream")

        adapter = Broken(prices={SYMBOL: Decimal(100)})
        adapter.add_account("k")
        # A position placed behind the service's back, so closing it fails.
        from quanta.exchanges.trading import OrderRequest, OrderType

        await SimulatedTradingAdapter.place_order(
            adapter,
            context().credentials,
            OrderRequest(
                symbol=SYMBOL,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                qty=Decimal(1),
                client_id="seed",
            ),
        )

        report = await ExecutionService(adapter).kill([context()])
        assert not report.clean
        assert "could not close" in report.failures[0]

    async def test_a_cancel_failure_still_tries_to_close(self) -> None:
        """An uncancelled order is bad; an open position left behind is
        worse."""

        class NoCancel(SimulatedTradingAdapter):
            async def cancel_all(self, credentials, *, symbol=None):  # type: ignore[no-untyped-def]
                raise TradingError("cannot cancel", code="upstream")

        adapter = NoCancel(prices={SYMBOL: Decimal(100)})
        adapter.add_account("k")
        service = ExecutionService(adapter)
        await open_long(service)

        report = await service.kill([context()])
        assert report.positions_closed == 1
        assert any("cancel" in f for f in report.failures)
