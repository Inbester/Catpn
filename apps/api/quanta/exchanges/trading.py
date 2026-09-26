"""The private, order-placing side of an exchange adapter (SPEC §3.5, §4, §6).

This is deliberately a separate module from `base.py`. The public adapter is
imported all over the web process — the chart, the backtest, the alert
evaluator — and none of that code has any business being able to trade. Only
the execution service imports this one, so "can this code place an order?" is
answered by looking at its imports.

Two things follow from SPEC §9 and are not negotiable in any implementation:

- Order traffic leaves from the server's static IP and is never routed
  through a user's VPN tunnel. The key is whitelisted to that IP, which is
  also what stops a key from being used from anywhere else.
- A key that can withdraw is refused. The platform never holds funds and
  never needs that permission, so a key carrying it is a mistake worth
  failing loudly on rather than storing.

Every request carries a `client_id`. The exchange treats it as an
idempotency key, so a retry after a timeout cannot place a second order —
which is the failure this design exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def opposite(self) -> OrderSide:
        return OrderSide.SELL if self is OrderSide.BUY else OrderSide.BUY


class TradeSide(StrEnum):
    """Whether an order opens or closes, in hedge mode.

    In one-way mode the venue infers this from the resulting net position and
    the field is not sent. In hedge mode it is required and getting it wrong
    opens a second position instead of closing the first, so it is explicit
    here rather than derived.
    """

    OPEN = "OPEN"
    CLOSE = "CLOSE"


class OrderType(StrEnum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


class TimeInForce(StrEnum):
    IOC = "IOC"
    FOK = "FOK"
    GTC = "GTC"
    POST_ONLY = "POST_ONLY"


class StopType(StrEnum):
    """Which price a stop watches.

    Mark price is the one liquidation uses, so a stop on last price can be
    triggered by a wick that would never have liquidated the position.
    """

    MARK_PRICE = "MARK_PRICE"
    LAST_PRICE = "LAST_PRICE"


class OrderStatus(StrEnum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"

    @property
    def is_final(self) -> bool:
        """True once the exchange will not change this order again."""
        return self in (
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        )

    @property
    def is_open(self) -> bool:
        return not self.is_final


class PositionMode(StrEnum):
    ONE_WAY = "ONE_WAY"
    HEDGE = "HEDGE"


class MarginMode(StrEnum):
    ISOLATED = "ISOLATED"
    CROSS = "CROSS"


@dataclass(frozen=True, slots=True)
class Credentials:
    """One user's exchange API key.

    Held only for the length of a call. It is decrypted from the vault, used,
    and dropped; nothing here is ever logged or returned to a client.
    """

    api_key: str
    api_secret: str
    passphrase: str | None = None

    def __repr__(self) -> str:
        # A traceback or a repr in a log must not leak the secret.
        return f"Credentials(api_key={self.api_key[:4]}…, api_secret=…)"


@dataclass(frozen=True, slots=True)
class KeyPermissions:
    """What a key is allowed to do, as the exchange reports it.

    `can_withdraw` is the one that matters: a key carrying it is refused.
    `ip_whitelist` empty means the key is unrestricted, which is also a
    refusal — an unrestricted key works from anywhere, which is exactly what
    the whitelist is there to prevent.
    """

    can_read: bool
    can_trade: bool
    can_withdraw: bool
    ip_whitelist: tuple[str, ...] = ()

    @property
    def is_ip_restricted(self) -> bool:
        return len(self.ip_whitelist) > 0

    def allows_ip(self, ip: str) -> bool:
        return ip in self.ip_whitelist


@dataclass(frozen=True, slots=True)
class OrderRequest:
    """One order to place (SPEC §6 field list).

    `client_id` is the idempotency key and is required, not optional: an
    order placed without one cannot be safely retried, and every order this
    platform sends is one that might have to be.
    """

    symbol: str
    side: OrderSide
    order_type: OrderType
    qty: Decimal
    client_id: str
    price: Decimal | None = None
    trade_side: TradeSide | None = None
    time_in_force: TimeInForce = TimeInForce.GTC
    reduce_only: bool = False
    position_id: str | None = None
    # Attached exits, placed with the order so a fill is never naked even
    # for the moment between two calls.
    tp_price: Decimal | None = None
    tp_stop_type: StopType = StopType.MARK_PRICE
    tp_order_type: OrderType = OrderType.MARKET
    tp_order_price: Decimal | None = None
    sl_price: Decimal | None = None
    sl_stop_type: StopType = StopType.MARK_PRICE
    sl_order_type: OrderType = OrderType.MARKET
    sl_order_price: Decimal | None = None

    def __post_init__(self) -> None:
        if self.qty <= 0:
            raise ValueError("qty must be positive")
        if not self.client_id:
            raise ValueError("client_id is required: it is the idempotency key")
        if self.order_type is OrderType.LIMIT and self.price is None:
            raise ValueError("a LIMIT order needs a price")
        if self.order_type is OrderType.MARKET and self.time_in_force is TimeInForce.POST_ONLY:
            raise ValueError("POST_ONLY makes no sense on a MARKET order")


@dataclass(frozen=True, slots=True)
class Order:
    """An order as the exchange currently sees it."""

    order_id: str
    client_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    status: OrderStatus
    qty: Decimal
    filled_qty: Decimal
    price: Decimal | None = None
    average_price: Decimal | None = None
    fee: Decimal | None = None
    trade_side: TradeSide | None = None
    reduce_only: bool = False
    created_at: int | None = None
    updated_at: int | None = None
    reject_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def remaining_qty(self) -> Decimal:
        return self.qty - self.filled_qty


@dataclass(frozen=True, slots=True)
class Position:
    """An open position.

    `qty` is always positive; `side` carries the direction. A signed quantity
    reads more cleanly in arithmetic but loses hedge mode, where a symbol can
    hold a long and a short at once.
    """

    symbol: str
    side: OrderSide
    qty: Decimal
    entry_price: Decimal
    leverage: int
    margin_mode: MarginMode
    position_id: str | None = None
    mark_price: Decimal | None = None
    liquidation_price: Decimal | None = None
    unrealised_pnl: Decimal | None = None
    realised_pnl: Decimal | None = None
    margin: Decimal | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def notional(self) -> Decimal:
        return self.qty * (self.mark_price if self.mark_price is not None else self.entry_price)


@dataclass(frozen=True, slots=True)
class Balance:
    """The account's margin balance in one currency."""

    currency: str
    equity: Decimal
    available: Decimal
    used_margin: Decimal = Decimal(0)
    unrealised_pnl: Decimal = Decimal(0)


class TradingError(Exception):
    """An order the exchange refused, or a response that made no sense.

    `retryable` decides whether the execution service may send it again. It
    is False by default because the dangerous mistake is retrying an order
    that actually went through, not failing to retry one that did not.
    """

    def __init__(self, message: str, *, code: str | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.retryable = retryable


class KeyRejectedError(TradingError):
    """A key that must not be stored: it can withdraw, or it is not pinned
    to the server's IP (SPEC §3.5, §9)."""

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message, code=reason)
        self.reason = reason


@runtime_checkable
class TradingAdapter(Protocol):
    """The private surface. Only the execution service holds one of these."""

    name: str

    async def key_permissions(self, credentials: Credentials) -> KeyPermissions:
        """What this key can do. Called before a key is ever stored."""
        ...

    async def balances(self, credentials: Credentials) -> list[Balance]: ...

    async def position_mode(self, credentials: Credentials) -> PositionMode: ...

    async def positions(
        self, credentials: Credentials, *, symbol: str | None = None
    ) -> list[Position]: ...

    async def open_orders(
        self, credentials: Credentials, *, symbol: str | None = None
    ) -> list[Order]: ...

    async def place_order(self, credentials: Credentials, request: OrderRequest) -> Order:
        """Place an order, idempotently on `request.client_id`.

        Sending the same `client_id` twice must return the original order
        rather than placing a second one.
        """
        ...

    async def cancel_order(
        self,
        credentials: Credentials,
        symbol: str,
        *,
        client_id: str | None = None,
        order_id: str | None = None,
    ) -> Order: ...

    async def cancel_all(self, credentials: Credentials, *, symbol: str | None = None) -> int:
        """Cancel every open order and return how many were cancelled."""
        ...

    async def set_leverage(
        self, credentials: Credentials, symbol: str, leverage: int, *, margin_mode: MarginMode
    ) -> None: ...

    async def close(self) -> None: ...
