"""Risk limits for a live bot (SPEC §3.5).

Five limits, and one rule that outranks all of them.

**The rule: a limit never blocks an exit.** A daily-loss limit that trips
while a position is open, and then refuses the order that would close it,
has taken a bad day and made it unbounded. So every check lets a
reduce-only order through. The limits exist to stop a bot opening more
risk, not to trap it in what it already holds.

**Block versus halt.** Two limits are about pace — position size and order
rate — and a breach means "not this order", so the bot keeps running and
the next signal is judged afresh. Three are about damage — daily loss,
drawdown, leverage — and a breach means the bot's own premise is wrong, so
it halts and a person has to look at it. Nothing un-halts itself.

**Where the numbers come from.** Daily loss is measured from the equity at
the UTC day boundary, the same boundary the bars close on. Drawdown is
measured from the bot's own equity peak since it started, not the
account's, because a bot is only answerable for what it did.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from quanta.exchanges.trading import OrderRequest, Position


class RiskCode(StrEnum):
    """Why an order was refused. Stored on the halt, shown in the UI."""

    OK = "ok"
    POSITION_TOO_LARGE = "position_too_large"
    DAILY_LOSS = "daily_loss"
    MAX_DRAWDOWN = "max_drawdown"
    LEVERAGE_TOO_HIGH = "leverage_too_high"
    RATE_LIMITED = "rate_limited"


@dataclass(frozen=True, slots=True)
class RiskLimits:
    """What a bot is allowed to do. Every figure is in the quote currency
    except the percentages and the counts."""

    #: Largest notional the bot may hold at once, across all its positions.
    max_position_notional: Decimal
    #: Realised plus unrealised loss in one UTC day, as a positive number.
    max_daily_loss: Decimal
    #: Peak-to-trough on the bot's own equity, as a positive percentage.
    max_drawdown_percent: Decimal
    max_leverage: int
    max_orders_per_minute: int

    def __post_init__(self) -> None:
        if self.max_position_notional <= 0:
            raise ValueError("max_position_notional must be positive")
        if self.max_daily_loss <= 0:
            raise ValueError("max_daily_loss must be positive")
        if not (0 < self.max_drawdown_percent <= 100):
            raise ValueError("max_drawdown_percent must be between 0 and 100")
        if self.max_leverage < 1:
            raise ValueError("max_leverage must be at least 1")
        if self.max_orders_per_minute < 1:
            raise ValueError("max_orders_per_minute must be at least 1")


@dataclass(frozen=True, slots=True)
class RiskVerdict:
    """The answer to "may this order go?"."""

    allowed: bool
    code: RiskCode = RiskCode.OK
    #: True when the bot should stop, not merely skip this order.
    halt: bool = False
    #: The figure that tripped it and the limit it crossed, so the log and
    #: the UI can say *why* rather than just *no*.
    observed: Decimal | None = None
    limit: Decimal | None = None
    message: str = ""

    @classmethod
    def ok(cls) -> RiskVerdict:
        return cls(allowed=True)


def _day_start(at: datetime) -> datetime:
    return at.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


@dataclass
class RiskState:
    """What the guard has to remember between orders.

    Held per bot and rebuilt from the audit log on restart, so a restart
    cannot be used to reset a daily loss limit.
    """

    #: Equity at the last UTC day boundary the guard saw.
    day_start_equity: Decimal
    #: Highest equity since the bot started.
    peak_equity: Decimal
    day_started_at: datetime
    #: Timestamps of recent orders, for the per-minute window.
    recent_orders: deque[datetime] = field(default_factory=deque)

    @classmethod
    def starting_at(cls, equity: Decimal, at: datetime | None = None) -> RiskState:
        moment = at or datetime.now(UTC)
        return cls(
            day_start_equity=equity,
            peak_equity=equity,
            day_started_at=_day_start(moment),
        )

    def observe(self, equity: Decimal, at: datetime | None = None) -> None:
        """Record the bot's current equity.

        Rolls the day at the UTC boundary and tracks the peak. Called
        before every check so the figures are never stale.
        """
        moment = (at or datetime.now(UTC)).astimezone(UTC)
        if _day_start(moment) > self.day_started_at:
            self.day_started_at = _day_start(moment)
            self.day_start_equity = equity
        if equity > self.peak_equity:
            self.peak_equity = equity

    def record_order(self, at: datetime | None = None) -> None:
        self.recent_orders.append((at or datetime.now(UTC)).astimezone(UTC))
        self._trim(at)

    def orders_in_last_minute(self, at: datetime | None = None) -> int:
        self._trim(at)
        return len(self.recent_orders)

    def _trim(self, at: datetime | None = None) -> None:
        moment = (at or datetime.now(UTC)).astimezone(UTC)
        while self.recent_orders and (moment - self.recent_orders[0]).total_seconds() >= 60:
            self.recent_orders.popleft()


class RiskGuard:
    """Judges one bot's orders against its limits."""

    def __init__(self, limits: RiskLimits, state: RiskState) -> None:
        self.limits = limits
        self.state = state

    # --- Damage limits ---------------------------------------------------

    def check_equity(self, equity: Decimal, at: datetime | None = None) -> RiskVerdict:
        """The two limits that do not depend on an order.

        Run on every equity update, not only before an order: a position
        already open can breach a drawdown limit with no order in sight,
        and that is exactly when the bot should stop.
        """
        self.state.observe(equity, at)

        lost = self.state.day_start_equity - equity
        if lost >= self.limits.max_daily_loss:
            return RiskVerdict(
                allowed=False,
                code=RiskCode.DAILY_LOSS,
                halt=True,
                observed=lost,
                limit=self.limits.max_daily_loss,
                message=(f"Down {lost} today against a limit of {self.limits.max_daily_loss}."),
            )

        if self.state.peak_equity > 0:
            drop = (self.state.peak_equity - equity) / self.state.peak_equity * 100
            if drop >= self.limits.max_drawdown_percent:
                return RiskVerdict(
                    allowed=False,
                    code=RiskCode.MAX_DRAWDOWN,
                    halt=True,
                    observed=drop,
                    limit=self.limits.max_drawdown_percent,
                    message=(
                        f"Down {drop:.2f}% from its peak against a limit of "
                        f"{self.limits.max_drawdown_percent}%."
                    ),
                )

        return RiskVerdict.ok()

    # --- Order limits ----------------------------------------------------

    def check_order(
        self,
        request: OrderRequest,
        *,
        price: Decimal,
        equity: Decimal,
        positions: list[Position],
        leverage: int,
        at: datetime | None = None,
    ) -> RiskVerdict:
        """May this order go?

        An exit is always allowed. Everything below is about opening or
        adding risk — see the module docstring.
        """
        if request.reduce_only:
            return RiskVerdict.ok()

        damage = self.check_equity(equity, at)
        if not damage.allowed:
            return damage

        if leverage > self.limits.max_leverage:
            return RiskVerdict(
                allowed=False,
                code=RiskCode.LEVERAGE_TOO_HIGH,
                halt=True,
                observed=Decimal(leverage),
                limit=Decimal(self.limits.max_leverage),
                message=(
                    f"Leverage is {leverage}x against a limit of {self.limits.max_leverage}x."
                ),
            )

        rate = self.state.orders_in_last_minute(at)
        if rate >= self.limits.max_orders_per_minute:
            return RiskVerdict(
                allowed=False,
                code=RiskCode.RATE_LIMITED,
                # Not a halt: a burst is usually one signal seen several
                # times, and the next minute is a fresh judgement.
                halt=False,
                observed=Decimal(rate),
                limit=Decimal(self.limits.max_orders_per_minute),
                message=(
                    f"{rate} orders in the last minute against a limit of "
                    f"{self.limits.max_orders_per_minute}."
                ),
            )

        held = sum((p.notional for p in positions), Decimal(0))
        after = held + (request.qty * price)
        if after > self.limits.max_position_notional:
            return RiskVerdict(
                allowed=False,
                code=RiskCode.POSITION_TOO_LARGE,
                halt=False,
                observed=after,
                limit=self.limits.max_position_notional,
                message=(
                    f"Would hold {after} against a limit of {self.limits.max_position_notional}."
                ),
            )

        return RiskVerdict.ok()

    def largest_allowed_qty(self, *, price: Decimal, positions: list[Position]) -> Decimal:
        """How much room is left under the position limit.

        Offered so a caller can trim an order to fit rather than lose the
        signal entirely — the choice of which to do is the caller's.
        """
        if price <= 0:
            return Decimal(0)
        held = sum((p.notional for p in positions), Decimal(0))
        room = self.limits.max_position_notional - held
        return max(Decimal(0), room / price)

    def budgets(self, equity: Decimal) -> dict[str, Decimal]:
        """How much of each damage limit is used, as a percentage.

        This is what the bot card draws as bars: "how much room is left" is
        the question a person actually asks, and a bar answers it without
        arithmetic.
        """
        lost = max(Decimal(0), self.state.day_start_equity - equity)
        daily = min(Decimal(100), lost / self.limits.max_daily_loss * 100)

        drawdown = Decimal(0)
        if self.state.peak_equity > 0:
            drop = max(Decimal(0), (self.state.peak_equity - equity) / self.state.peak_equity * 100)
            drawdown = min(Decimal(100), drop / self.limits.max_drawdown_percent * 100)

        return {"daily_loss_used_percent": daily, "drawdown_used_percent": drawdown}
