"""An in-memory exchange to trade against (SPEC §8).

The bot has to be exercised somewhere that is not a live account. This is
that somewhere: it implements the same `TradingAdapter` protocol the real
venue does, so the execution service cannot tell the difference, and it is
deterministic, so a test that passes here passes for a reason.

What it models, because the execution service depends on each of them:

- **Idempotency.** A `client_id` already seen returns the original order
  rather than placing a second one. This is the single most important
  behaviour to get right, so it is the one modelled first.
- **Hedge and one-way mode.** In one-way mode an opposing order nets off
  the existing position and can flip it; in hedge mode long and short live
  side by side and `trade_side` decides which is touched.
- **Key permissions.** Configurable, so the refusals in SPEC §3.5 —
  withdrawal permission, and a key not pinned to the server's IP — can be
  tested rather than assumed.
- **Rejections.** Insufficient margin, reduce-only with nothing to reduce,
  and unknown symbols all fail the way the venue would.

What it does not model: partial fills on market orders, the order book, and
funding. Limit orders rest until a test moves the price through them.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field, replace
from decimal import Decimal

from quanta.exchanges.trading import (
    Balance,
    Credentials,
    KeyPermissions,
    MarginMode,
    Order,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    PositionMode,
    TimeInForce,
    TradeSide,
    TradingError,
)

#: The IP the simulated venue believes the caller is using. Tests pin keys
#: to this to exercise the happy path of the whitelist check.
SIM_SERVER_IP = "203.0.113.7"


@dataclass
class SimAccount:
    """One simulated exchange account, addressed by its API key."""

    permissions: KeyPermissions
    # Not a credential: the simulator checks it only so a test can prove
    # a wrong secret is refused.
    secret: str = "sim-secret"  # noqa: S105
    equity: Decimal = Decimal(10_000)
    currency: str = "USDT"
    position_mode: PositionMode = PositionMode.ONE_WAY
    leverage: dict[str, int] = field(default_factory=dict)
    margin_mode: dict[str, MarginMode] = field(default_factory=dict)
    positions: dict[str, Position] = field(default_factory=dict)
    orders: dict[str, Order] = field(default_factory=dict)
    #: client_id -> order_id. The idempotency index.
    by_client_id: dict[str, str] = field(default_factory=dict)
    realised_pnl: Decimal = Decimal(0)


def default_permissions(*, whitelist_ip: str | None = SIM_SERVER_IP) -> KeyPermissions:
    """A well-formed key: read and trade, no withdrawal, pinned to one IP."""
    return KeyPermissions(
        can_read=True,
        can_trade=True,
        can_withdraw=False,
        ip_whitelist=(whitelist_ip,) if whitelist_ip else (),
    )


def _position_key(symbol: str, side: OrderSide, mode: PositionMode) -> str:
    """Where a position lives.

    One key per symbol in one-way mode; one per symbol *and side* in hedge
    mode, which is the whole difference between the two.
    """
    return symbol if mode is PositionMode.ONE_WAY else f"{symbol}:{side.value}"


class SimulatedTradingAdapter:
    """A `TradingAdapter` backed by dictionaries."""

    name = "sim"

    def __init__(
        self,
        *,
        prices: dict[str, Decimal] | None = None,
        server_ip: str = SIM_SERVER_IP,
    ) -> None:
        self._accounts: dict[str, SimAccount] = {}
        self._prices: dict[str, Decimal] = dict(prices or {})
        self._server_ip = server_ip
        self._ids = itertools.count(1)

    # --- Test and dev setup ---------------------------------------------

    def add_account(self, api_key: str, account: SimAccount | None = None) -> SimAccount:
        created = account or SimAccount(permissions=default_permissions())
        self._accounts[api_key] = created
        return created

    def set_price(self, symbol: str, price: Decimal) -> None:
        """Move the market. Resting limit orders that the move crosses fill."""
        self._prices[symbol] = price
        for account in self._accounts.values():
            self._fill_crossed_limits(account, symbol, price)

    def price(self, symbol: str) -> Decimal:
        try:
            return self._prices[symbol]
        except KeyError:
            raise TradingError(f"no price for {symbol}", code="unknown_symbol") from None

    # --- Plumbing --------------------------------------------------------

    def _account(self, credentials: Credentials) -> SimAccount:
        account = self._accounts.get(credentials.api_key)
        if account is None:
            raise TradingError("unknown api key", code="invalid_key")
        if account.secret != credentials.api_secret:
            raise TradingError("bad signature", code="invalid_key")
        # The venue enforces the whitelist; so does the simulator, or the
        # whole point of pinning the key goes untested.
        if account.permissions.is_ip_restricted and not account.permissions.allows_ip(
            self._server_ip
        ):
            raise TradingError("request from a non-whitelisted IP", code="ip_not_whitelisted")
        return account

    def _next_id(self) -> str:
        return f"sim-{next(self._ids):08d}"

    # --- Account ---------------------------------------------------------

    async def key_permissions(self, credentials: Credentials) -> KeyPermissions:
        account = self._accounts.get(credentials.api_key)
        if account is None or account.secret != credentials.api_secret:
            raise TradingError("unknown api key", code="invalid_key")
        # Deliberately not behind _account(): a key that is not whitelisted
        # still has to report its permissions, or the check that refuses it
        # could never run.
        return account.permissions

    async def balances(self, credentials: Credentials) -> list[Balance]:
        account = self._account(credentials)
        used = sum(
            (p.margin or Decimal(0) for p in account.positions.values()),
            Decimal(0),
        )
        unrealised = sum(
            (self._unrealised(p) for p in account.positions.values()),
            Decimal(0),
        )
        return [
            Balance(
                currency=account.currency,
                equity=account.equity + unrealised,
                available=account.equity - used,
                used_margin=used,
                unrealised_pnl=unrealised,
            )
        ]

    async def position_mode(self, credentials: Credentials) -> PositionMode:
        return self._account(credentials).position_mode

    async def positions(
        self, credentials: Credentials, *, symbol: str | None = None
    ) -> list[Position]:
        account = self._account(credentials)
        live = [self._marked(p) for p in account.positions.values()]
        return [p for p in live if symbol is None or p.symbol == symbol]

    async def open_orders(
        self, credentials: Credentials, *, symbol: str | None = None
    ) -> list[Order]:
        account = self._account(credentials)
        return [
            order
            for order in account.orders.values()
            if order.status.is_open and (symbol is None or order.symbol == symbol)
        ]

    async def set_leverage(
        self,
        credentials: Credentials,
        symbol: str,
        leverage: int,
        *,
        margin_mode: MarginMode,
    ) -> None:
        account = self._account(credentials)
        if leverage < 1:
            raise TradingError("leverage must be at least 1", code="bad_leverage")
        account.leverage[symbol] = leverage
        account.margin_mode[symbol] = margin_mode

    # --- Orders ----------------------------------------------------------

    async def place_order(self, credentials: Credentials, request: OrderRequest) -> Order:
        account = self._account(credentials)
        if not account.permissions.can_trade:
            raise TradingError("this key cannot trade", code="not_permitted")

        # Idempotency first, before anything can have an effect. A retry
        # after a timeout must be indistinguishable from the first call.
        existing_id = account.by_client_id.get(request.client_id)
        if existing_id is not None:
            return account.orders[existing_id]

        price = self.price(request.symbol)
        if request.order_type is OrderType.LIMIT:
            assert request.price is not None  # OrderRequest guarantees it
            crosses = (
                request.price >= price if request.side is OrderSide.BUY else request.price <= price
            )
            if request.time_in_force is TimeInForce.POST_ONLY and crosses:
                return self._record(
                    account,
                    request,
                    status=OrderStatus.REJECTED,
                    reason="POST_ONLY would have taken liquidity",
                )
            if not crosses:
                if request.time_in_force in (TimeInForce.IOC, TimeInForce.FOK):
                    return self._record(
                        account,
                        request,
                        status=OrderStatus.CANCELLED,
                        reason=f"{request.time_in_force.value} could not fill",
                    )
                return self._record(account, request, status=OrderStatus.NEW)
            price = request.price

        return self._fill(account, request, price)

    async def cancel_order(
        self,
        credentials: Credentials,
        symbol: str,
        *,
        client_id: str | None = None,
        order_id: str | None = None,
    ) -> Order:
        account = self._account(credentials)
        if client_id is not None:
            order_id = account.by_client_id.get(client_id)
        if order_id is None or order_id not in account.orders:
            raise TradingError("no such order", code="unknown_order")

        order = account.orders[order_id]
        if order.status.is_final:
            # Not an error: cancelling an order that already finished is
            # exactly what a retry looks like.
            return order
        cancelled = replace(order, status=OrderStatus.CANCELLED)
        account.orders[order_id] = cancelled
        return cancelled

    async def cancel_all(self, credentials: Credentials, *, symbol: str | None = None) -> int:
        account = self._account(credentials)
        count = 0
        for order_id, order in list(account.orders.items()):
            if order.status.is_final:
                continue
            if symbol is not None and order.symbol != symbol:
                continue
            account.orders[order_id] = replace(order, status=OrderStatus.CANCELLED)
            count += 1
        return count

    async def close(self) -> None:
        return None

    # --- Fills and positions ---------------------------------------------

    def _record(
        self,
        account: SimAccount,
        request: OrderRequest,
        *,
        status: OrderStatus,
        filled: Decimal = Decimal(0),
        average: Decimal | None = None,
        reason: str | None = None,
    ) -> Order:
        order = Order(
            order_id=self._next_id(),
            client_id=request.client_id,
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            status=status,
            qty=request.qty,
            filled_qty=filled,
            price=request.price,
            average_price=average,
            trade_side=request.trade_side,
            reduce_only=request.reduce_only,
            reject_reason=reason,
        )
        account.orders[order.order_id] = order
        account.by_client_id[request.client_id] = order.order_id
        return order

    def _fill(self, account: SimAccount, request: OrderRequest, price: Decimal) -> Order:
        mode = account.position_mode
        key = _position_key(request.symbol, request.side, mode)
        leverage = account.leverage.get(request.symbol, 1)
        margin_mode = account.margin_mode.get(request.symbol, MarginMode.ISOLATED)

        if mode is PositionMode.HEDGE and request.trade_side is TradeSide.CLOSE:
            # Closing in hedge mode acts on the *opposite* book: a SELL that
            # closes is reducing the long.
            key = _position_key(request.symbol, request.side.opposite, mode)

        existing = account.positions.get(key)
        closing = request.reduce_only or request.trade_side is TradeSide.CLOSE

        if closing and existing is None:
            return self._record(
                account,
                request,
                status=OrderStatus.REJECTED,
                reason="nothing to reduce",
            )

        margin_needed = (request.qty * price) / Decimal(leverage)
        if not closing and margin_needed > self._available(account):
            return self._record(
                account,
                request,
                status=OrderStatus.REJECTED,
                reason="insufficient margin",
            )

        self._apply(account, key, request, price, leverage, margin_mode, closing=closing)
        return self._record(
            account,
            request,
            status=OrderStatus.FILLED,
            filled=request.qty,
            average=price,
        )

    def _apply(
        self,
        account: SimAccount,
        key: str,
        request: OrderRequest,
        price: Decimal,
        leverage: int,
        margin_mode: MarginMode,
        *,
        closing: bool,
    ) -> None:
        existing = account.positions.get(key)

        if existing is None:
            account.positions[key] = Position(
                symbol=request.symbol,
                side=request.side,
                qty=request.qty,
                entry_price=price,
                leverage=leverage,
                margin_mode=margin_mode,
                position_id=key,
                mark_price=price,
                margin=(request.qty * price) / Decimal(leverage),
            )
            return

        same_direction = existing.side is request.side and not closing
        if same_direction:
            total = existing.qty + request.qty
            # Weighted average entry: the cost basis has to survive adding to
            # a position, or every P&L after it is wrong.
            entry = ((existing.entry_price * existing.qty) + (price * request.qty)) / total
            account.positions[key] = replace(
                existing,
                qty=total,
                entry_price=entry,
                margin=(total * entry) / Decimal(leverage),
            )
            return

        # Reducing, closing, or flipping.
        closed = min(existing.qty, request.qty)
        account.realised_pnl += self._pnl(existing.side, existing.entry_price, price, closed)
        account.equity += self._pnl(existing.side, existing.entry_price, price, closed)
        remainder = request.qty - closed

        if existing.qty > closed:
            left = existing.qty - closed
            account.positions[key] = replace(
                existing, qty=left, margin=(left * existing.entry_price) / Decimal(leverage)
            )
            return

        del account.positions[key]
        if remainder > 0 and not request.reduce_only:
            # A flip: the order was larger than the position it closed.
            flipped = _position_key(request.symbol, request.side, account.position_mode)
            account.positions[flipped] = Position(
                symbol=request.symbol,
                side=request.side,
                qty=remainder,
                entry_price=price,
                leverage=leverage,
                margin_mode=margin_mode,
                position_id=flipped,
                mark_price=price,
                margin=(remainder * price) / Decimal(leverage),
            )

    def _fill_crossed_limits(self, account: SimAccount, symbol: str, price: Decimal) -> None:
        for order_id, order in list(account.orders.items()):
            if order.status is not OrderStatus.NEW or order.symbol != symbol:
                continue
            if order.price is None:
                continue
            crosses = price <= order.price if order.side is OrderSide.BUY else price >= order.price
            if not crosses:
                continue
            request = OrderRequest(
                symbol=order.symbol,
                side=order.side,
                order_type=OrderType.LIMIT,
                qty=order.qty,
                client_id=order.client_id,
                price=order.price,
                trade_side=order.trade_side,
                reduce_only=order.reduce_only,
            )
            key = _position_key(order.symbol, order.side, account.position_mode)
            if account.position_mode is PositionMode.HEDGE and order.trade_side is TradeSide.CLOSE:
                key = _position_key(order.symbol, order.side.opposite, account.position_mode)
            self._apply(
                account,
                key,
                request,
                order.price,
                account.leverage.get(symbol, 1),
                account.margin_mode.get(symbol, MarginMode.ISOLATED),
                closing=order.reduce_only or order.trade_side is TradeSide.CLOSE,
            )
            account.orders[order_id] = replace(
                order,
                status=OrderStatus.FILLED,
                filled_qty=order.qty,
                average_price=order.price,
            )

    @staticmethod
    def _pnl(side: OrderSide, entry: Decimal, exit_price: Decimal, qty: Decimal) -> Decimal:
        direction = Decimal(1) if side is OrderSide.BUY else Decimal(-1)
        return (exit_price - entry) * qty * direction

    def _unrealised(self, position: Position) -> Decimal:
        mark = self._prices.get(position.symbol, position.entry_price)
        return self._pnl(position.side, position.entry_price, mark, position.qty)

    def _marked(self, position: Position) -> Position:
        mark = self._prices.get(position.symbol, position.entry_price)
        return replace(position, mark_price=mark, unrealised_pnl=self._unrealised(position))

    def _available(self, account: SimAccount) -> Decimal:
        used = sum((p.margin or Decimal(0) for p in account.positions.values()), Decimal(0))
        return account.equity - used
