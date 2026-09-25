"""The exchange adapter interface (SPEC §4).

Bitunix is adapter #1. Everything above this layer — the chart, the backtest
engine, the alert evaluator — talks only to these types, so a second venue
can be added without touching them. That matters for more than tidiness:
SPEC §9 requires the exchange layer to stay pluggable so a compliant venue
can replace Bitunix where it is restricted.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Protocol, runtime_checkable

PriceType = Literal["LAST", "MARK"]


class Interval(StrEnum):
    """Kline intervals supported by Bitunix (SPEC §6)."""

    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H2 = "2h"
    H4 = "4h"
    H6 = "6h"
    H8 = "8h"
    H12 = "12h"
    D1 = "1d"
    D3 = "3d"
    W1 = "1w"
    MO1 = "1M"

    @property
    def seconds(self) -> int:
        """Bar length in seconds.

        Months are not a fixed length; 30 days is only used for coarse
        sizing (never for bar boundaries, which come from the exchange).
        """
        unit = self.value[-1]
        amount = int(self.value[:-1])
        per_unit = {"m": 60, "h": 3600, "d": 86_400, "w": 604_800, "M": 2_592_000}
        return amount * per_unit[unit]

    @property
    def milliseconds(self) -> int:
        return self.seconds * 1000


@dataclass(frozen=True, slots=True)
class Symbol:
    """A tradable contract and its constraints."""

    symbol: str
    base: str
    quote: str
    min_leverage: int
    max_leverage: int
    default_leverage: int
    base_precision: int
    quote_precision: int
    min_trade_volume: Decimal
    max_market_order_volume: Decimal | None
    status: str
    max_funding_rate: Decimal | None = None
    min_funding_rate: Decimal | None = None
    api_supported: bool = True

    @property
    def is_tradable(self) -> bool:
        return self.status.upper() in ("OPEN", "TRADING", "NORMAL") and self.api_supported


@dataclass(frozen=True, slots=True)
class PositionTier:
    """One row of the tiered maintenance-margin table.

    Liquidation price depends on which tier the position's notional falls in
    (SPEC §6), so these have to be exact rather than a flat rate.
    """

    level: int
    start_value: Decimal
    end_value: Decimal
    leverage: int
    maintenance_margin_rate: Decimal


@dataclass(frozen=True, slots=True)
class FeeTier:
    """A VIP fee level. Maker and taker are fractions, not percentages."""

    tier: str
    maker: Decimal
    taker: Decimal
    requirement_volume_30d: Decimal | None = None
    requirement_balance: Decimal | None = None


@dataclass(frozen=True, slots=True)
class Bar:
    """One kline.

    ``open_time`` is the bar's opening timestamp in epoch milliseconds, on a
    UTC boundary. ``closed`` is False for the bar still forming.
    """

    open_time: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    quote_volume: Decimal | None = None
    closed: bool = True

    @property
    def is_up(self) -> bool:
        return self.close >= self.open


@dataclass(frozen=True, slots=True)
class Funding:
    """A settled funding payment. A positive rate means longs pay shorts."""

    funding_time: int
    funding_rate: Decimal
    mark_price: Decimal | None = None


@dataclass(frozen=True, slots=True)
class Ticker:
    """24h rollup plus the current marks, for the watchlist and detail card."""

    symbol: str
    last: Decimal
    change_percent_24h: Decimal
    high_24h: Decimal | None = None
    low_24h: Decimal | None = None
    base_volume_24h: Decimal | None = None
    quote_volume_24h: Decimal | None = None
    mark_price: Decimal | None = None
    index_price: Decimal | None = None
    funding_rate: Decimal | None = None
    next_funding_time: int | None = None
    open_interest: Decimal | None = None


class EventType(StrEnum):
    KLINE = "kline"
    TICKER = "ticker"
    MARK_PRICE = "mark_price"
    TRADE = "trade"
    DEPTH = "depth"


@dataclass(frozen=True, slots=True)
class StreamEvent:
    """A normalised message off the public stream."""

    type: EventType
    symbol: str
    received_at: int
    interval: Interval | None = None
    bar: Bar | None = None
    ticker: Ticker | None = None
    price: Decimal | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Subscription:
    """One channel to subscribe to on the public stream."""

    channel: EventType
    symbol: str
    interval: Interval | None = None
    price_type: PriceType = "LAST"


class ExchangeError(Exception):
    """A call the exchange rejected, or a response that made no sense."""

    def __init__(self, message: str, *, code: str | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.retryable = retryable


class RateLimitError(ExchangeError):
    """The venue's rate limit was hit. Always retryable, after a wait."""

    def __init__(self, message: str, retry_after: float = 1.0) -> None:
        super().__init__(message, code="rate_limited", retryable=True)
        self.retry_after = retry_after


@runtime_checkable
class ExchangeAdapter(Protocol):
    """What every venue must provide.

    Only the public surface is declared here. Private, order-placing calls
    live in the isolated execution service (SPEC §4, §9) and are added in
    phase 6 — keeping them out means nothing in the web process can trade.
    """

    name: str

    async def symbols(self) -> list[Symbol]: ...

    async def position_tiers(self, symbol: str) -> list[PositionTier]: ...

    async def fee_tiers(self) -> list[FeeTier]: ...

    async def klines(
        self,
        symbol: str,
        interval: Interval,
        *,
        start: int | None = None,
        end: int | None = None,
        limit: int = 200,
        price_type: PriceType = "LAST",
    ) -> list[Bar]: ...

    async def funding_history(
        self, symbol: str, *, start: int | None = None, end: int | None = None, limit: int = 200
    ) -> list[Funding]: ...

    async def tickers(self) -> list[Ticker]: ...

    def stream(self, subscriptions: list[Subscription]) -> AsyncIterator[StreamEvent]: ...

    async def close(self) -> None: ...
