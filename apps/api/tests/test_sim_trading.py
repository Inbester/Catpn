"""The simulated venue has to behave like a venue.

Everything the execution service does is tested against this simulator, so
a wrong simulator would make those tests agree with each other and with
nothing else. These pin the behaviours the service actually relies on.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from quanta.exchanges.sim.trading import (
    SIM_SERVER_IP,
    SimAccount,
    SimulatedTradingAdapter,
    default_permissions,
)
from quanta.exchanges.trading import (
    Credentials,
    KeyPermissions,
    MarginMode,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionMode,
    TimeInForce,
    TradeSide,
    TradingError,
)

KEY = "sim-key"
CREDENTIALS = Credentials(api_key=KEY, api_secret="sim-secret")
SYMBOL = "BTCUSDT"


@pytest.fixture
def venue() -> SimulatedTradingAdapter:
    adapter = SimulatedTradingAdapter(prices={SYMBOL: Decimal(100)})
    adapter.add_account(KEY)
    return adapter


def market(
    side: OrderSide,
    qty: str,
    client_id: str,
    *,
    reduce_only: bool = False,
    trade_side: TradeSide | None = None,
) -> OrderRequest:
    return OrderRequest(
        symbol=SYMBOL,
        side=side,
        order_type=OrderType.MARKET,
        qty=Decimal(qty),
        client_id=client_id,
        reduce_only=reduce_only,
        trade_side=trade_side,
    )


class TestIdempotency:
    """The behaviour the whole design rests on."""

    async def test_the_same_client_id_does_not_place_a_second_order(
        self, venue: SimulatedTradingAdapter
    ) -> None:
        first = await venue.place_order(CREDENTIALS, market(OrderSide.BUY, "1", "abc"))
        second = await venue.place_order(CREDENTIALS, market(OrderSide.BUY, "1", "abc"))

        assert first.order_id == second.order_id
        positions = await venue.positions(CREDENTIALS)
        # One position of 1, not 2: the retry had no effect.
        assert [p.qty for p in positions] == [Decimal(1)]

    async def test_a_different_client_id_does_place_another(
        self, venue: SimulatedTradingAdapter
    ) -> None:
        await venue.place_order(CREDENTIALS, market(OrderSide.BUY, "1", "one"))
        await venue.place_order(CREDENTIALS, market(OrderSide.BUY, "1", "two"))

        positions = await venue.positions(CREDENTIALS)
        assert [p.qty for p in positions] == [Decimal(2)]

    async def test_a_client_id_is_required(self) -> None:
        with pytest.raises(ValueError, match="idempotency key"):
            OrderRequest(
                symbol=SYMBOL,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                qty=Decimal(1),
                client_id="",
            )


class TestOneWayMode:
    async def test_opening_records_entry_and_margin(self, venue: SimulatedTradingAdapter) -> None:
        await venue.set_leverage(CREDENTIALS, SYMBOL, 10, margin_mode=MarginMode.ISOLATED)
        await venue.place_order(CREDENTIALS, market(OrderSide.BUY, "2", "open"))

        (position,) = await venue.positions(CREDENTIALS)
        assert position.entry_price == Decimal(100)
        assert position.qty == Decimal(2)
        # 2 * 100 / 10x.
        assert position.margin == Decimal(20)

    async def test_adding_averages_the_entry(self, venue: SimulatedTradingAdapter) -> None:
        await venue.place_order(CREDENTIALS, market(OrderSide.BUY, "1", "a"))
        venue.set_price(SYMBOL, Decimal(200))
        await venue.place_order(CREDENTIALS, market(OrderSide.BUY, "1", "b"))

        (position,) = await venue.positions(CREDENTIALS)
        assert position.qty == Decimal(2)
        assert position.entry_price == Decimal(150)

    async def test_an_opposing_order_reduces_then_closes(
        self, venue: SimulatedTradingAdapter
    ) -> None:
        await venue.place_order(CREDENTIALS, market(OrderSide.BUY, "3", "open"))
        await venue.place_order(CREDENTIALS, market(OrderSide.SELL, "1", "trim"))

        (position,) = await venue.positions(CREDENTIALS)
        assert position.qty == Decimal(2)

        await venue.place_order(CREDENTIALS, market(OrderSide.SELL, "2", "close"))
        assert await venue.positions(CREDENTIALS) == []

    async def test_an_oversized_opposing_order_flips_the_position(
        self, venue: SimulatedTradingAdapter
    ) -> None:
        await venue.place_order(CREDENTIALS, market(OrderSide.BUY, "1", "open"))
        await venue.place_order(CREDENTIALS, market(OrderSide.SELL, "3", "flip"))

        (position,) = await venue.positions(CREDENTIALS)
        assert position.side is OrderSide.SELL
        assert position.qty == Decimal(2)

    async def test_reduce_only_never_flips(self, venue: SimulatedTradingAdapter) -> None:
        await venue.place_order(CREDENTIALS, market(OrderSide.BUY, "1", "open"))
        await venue.place_order(CREDENTIALS, market(OrderSide.SELL, "5", "exit", reduce_only=True))
        # The excess is discarded rather than opening a short.
        assert await venue.positions(CREDENTIALS) == []

    async def test_reduce_only_with_nothing_to_reduce_is_rejected(
        self, venue: SimulatedTradingAdapter
    ) -> None:
        order = await venue.place_order(
            CREDENTIALS, market(OrderSide.SELL, "1", "exit", reduce_only=True)
        )
        assert order.status is OrderStatus.REJECTED
        assert order.reject_reason == "nothing to reduce"

    async def test_profit_is_realised_into_equity(self, venue: SimulatedTradingAdapter) -> None:
        await venue.place_order(CREDENTIALS, market(OrderSide.BUY, "2", "open"))
        venue.set_price(SYMBOL, Decimal(110))
        await venue.place_order(CREDENTIALS, market(OrderSide.SELL, "2", "close"))

        (balance,) = await venue.balances(CREDENTIALS)
        # 2 contracts * 10 of move.
        assert balance.equity == Decimal(10_020)


class TestHedgeMode:
    @pytest.fixture
    def hedged(self) -> SimulatedTradingAdapter:
        adapter = SimulatedTradingAdapter(prices={SYMBOL: Decimal(100)})
        adapter.add_account(
            KEY,
            SimAccount(permissions=default_permissions(), position_mode=PositionMode.HEDGE),
        )
        return adapter

    async def test_long_and_short_coexist(self, hedged: SimulatedTradingAdapter) -> None:
        await hedged.place_order(
            CREDENTIALS, market(OrderSide.BUY, "1", "long", trade_side=TradeSide.OPEN)
        )
        await hedged.place_order(
            CREDENTIALS, market(OrderSide.SELL, "1", "short", trade_side=TradeSide.OPEN)
        )

        positions = await hedged.positions(CREDENTIALS)
        assert {p.side for p in positions} == {OrderSide.BUY, OrderSide.SELL}

    async def test_closing_acts_on_the_opposite_book(self, hedged: SimulatedTradingAdapter) -> None:
        await hedged.place_order(
            CREDENTIALS, market(OrderSide.BUY, "1", "long", trade_side=TradeSide.OPEN)
        )
        await hedged.place_order(
            CREDENTIALS, market(OrderSide.SELL, "1", "exit", trade_side=TradeSide.CLOSE)
        )
        # The long is closed, not a short opened.
        assert await hedged.positions(CREDENTIALS) == []


class TestLimitOrders:
    async def test_a_limit_away_from_the_market_rests(self, venue: SimulatedTradingAdapter) -> None:
        order = await venue.place_order(
            CREDENTIALS,
            OrderRequest(
                symbol=SYMBOL,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                qty=Decimal(1),
                client_id="rest",
                price=Decimal(90),
            ),
        )
        assert order.status is OrderStatus.NEW
        assert await venue.positions(CREDENTIALS) == []

    async def test_a_resting_limit_fills_when_price_crosses(
        self, venue: SimulatedTradingAdapter
    ) -> None:
        await venue.place_order(
            CREDENTIALS,
            OrderRequest(
                symbol=SYMBOL,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                qty=Decimal(1),
                client_id="rest",
                price=Decimal(90),
            ),
        )
        venue.set_price(SYMBOL, Decimal(89))

        (position,) = await venue.positions(CREDENTIALS)
        # Filled at the limit, not at the worse market price.
        assert position.entry_price == Decimal(90)
        assert await venue.open_orders(CREDENTIALS) == []

    async def test_post_only_that_would_take_is_rejected(
        self, venue: SimulatedTradingAdapter
    ) -> None:
        order = await venue.place_order(
            CREDENTIALS,
            OrderRequest(
                symbol=SYMBOL,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                qty=Decimal(1),
                client_id="post",
                price=Decimal(110),
                time_in_force=TimeInForce.POST_ONLY,
            ),
        )
        assert order.status is OrderStatus.REJECTED

    async def test_ioc_that_cannot_fill_is_cancelled(self, venue: SimulatedTradingAdapter) -> None:
        order = await venue.place_order(
            CREDENTIALS,
            OrderRequest(
                symbol=SYMBOL,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                qty=Decimal(1),
                client_id="ioc",
                price=Decimal(90),
                time_in_force=TimeInForce.IOC,
            ),
        )
        assert order.status is OrderStatus.CANCELLED


class TestCancelling:
    async def test_cancel_by_client_id(self, venue: SimulatedTradingAdapter) -> None:
        await venue.place_order(
            CREDENTIALS,
            OrderRequest(
                symbol=SYMBOL,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                qty=Decimal(1),
                client_id="rest",
                price=Decimal(90),
            ),
        )
        cancelled = await venue.cancel_order(CREDENTIALS, SYMBOL, client_id="rest")
        assert cancelled.status is OrderStatus.CANCELLED

    async def test_cancelling_twice_is_not_an_error(self, venue: SimulatedTradingAdapter) -> None:
        """A retried cancel must look like the first one."""
        await venue.place_order(
            CREDENTIALS,
            OrderRequest(
                symbol=SYMBOL,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                qty=Decimal(1),
                client_id="rest",
                price=Decimal(90),
            ),
        )
        await venue.cancel_order(CREDENTIALS, SYMBOL, client_id="rest")
        again = await venue.cancel_order(CREDENTIALS, SYMBOL, client_id="rest")
        assert again.status is OrderStatus.CANCELLED

    async def test_cancel_all_reports_how_many(self, venue: SimulatedTradingAdapter) -> None:
        for i in range(3):
            await venue.place_order(
                CREDENTIALS,
                OrderRequest(
                    symbol=SYMBOL,
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    qty=Decimal(1),
                    client_id=f"rest-{i}",
                    price=Decimal(90),
                ),
            )
        assert await venue.cancel_all(CREDENTIALS) == 3
        assert await venue.cancel_all(CREDENTIALS) == 0


class TestKeys:
    async def test_a_wrong_secret_is_refused(self, venue: SimulatedTradingAdapter) -> None:
        with pytest.raises(TradingError, match="bad signature"):
            await venue.balances(Credentials(api_key=KEY, api_secret="wrong"))

    async def test_a_key_pinned_elsewhere_cannot_trade(self) -> None:
        adapter = SimulatedTradingAdapter(prices={SYMBOL: Decimal(100)})
        adapter.add_account(
            KEY,
            SimAccount(permissions=default_permissions(whitelist_ip="198.51.100.1")),
        )
        with pytest.raises(TradingError, match="non-whitelisted"):
            await adapter.balances(CREDENTIALS)

    async def test_permissions_are_readable_even_for_a_key_pinned_elsewhere(self) -> None:
        """Otherwise the check that refuses such a key could never run."""
        adapter = SimulatedTradingAdapter(prices={SYMBOL: Decimal(100)})
        adapter.add_account(
            KEY,
            SimAccount(permissions=default_permissions(whitelist_ip="198.51.100.1")),
        )
        permissions = await adapter.key_permissions(CREDENTIALS)
        assert permissions.ip_whitelist == ("198.51.100.1",)
        assert not permissions.allows_ip(SIM_SERVER_IP)

    async def test_a_read_only_key_cannot_trade(self) -> None:
        adapter = SimulatedTradingAdapter(prices={SYMBOL: Decimal(100)})
        adapter.add_account(
            KEY,
            SimAccount(
                permissions=KeyPermissions(
                    can_read=True,
                    can_trade=False,
                    can_withdraw=False,
                    ip_whitelist=(SIM_SERVER_IP,),
                )
            ),
        )
        with pytest.raises(TradingError, match="cannot trade"):
            await adapter.place_order(CREDENTIALS, market(OrderSide.BUY, "1", "x"))

    def test_credentials_do_not_leak_in_a_repr(self) -> None:
        text = repr(Credentials(api_key="abcdefgh", api_secret="super-secret"))
        assert "super-secret" not in text
        assert "abcd" in text


class TestMargin:
    async def test_an_order_beyond_available_margin_is_rejected(
        self, venue: SimulatedTradingAdapter
    ) -> None:
        # 1,000 contracts at 100 with no leverage is 100,000 against 10,000.
        order = await venue.place_order(CREDENTIALS, market(OrderSide.BUY, "1000", "big"))
        assert order.status is OrderStatus.REJECTED
        assert order.reject_reason == "insufficient margin"

    async def test_leverage_makes_the_same_order_affordable(
        self, venue: SimulatedTradingAdapter
    ) -> None:
        await venue.set_leverage(CREDENTIALS, SYMBOL, 20, margin_mode=MarginMode.CROSS)
        order = await venue.place_order(CREDENTIALS, market(OrderSide.BUY, "1000", "big"))
        assert order.status is OrderStatus.FILLED


class TestUnknowns:
    async def test_an_unknown_symbol_fails_rather_than_guessing(
        self, venue: SimulatedTradingAdapter
    ) -> None:
        with pytest.raises(TradingError, match="no price"):
            await venue.place_order(
                CREDENTIALS,
                OrderRequest(
                    symbol="NOPEUSDT",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    qty=Decimal(1),
                    client_id="x",
                ),
            )

    async def test_cancelling_an_unknown_order_fails(self, venue: SimulatedTradingAdapter) -> None:
        with pytest.raises(TradingError, match="no such order"):
            await venue.cancel_order(CREDENTIALS, SYMBOL, client_id="never-placed")
