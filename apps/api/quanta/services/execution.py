"""Placing a bot's orders (SPEC §3.5, §4, §9).

This is the only module that can move money. It holds no ORM models on
purpose: everything comes in as arguments and goes out as results, the way
`risk.py` does, so the whole of it can be tested against the simulated
venue without a database.

**Idempotency is structural, not hopeful.** The `client_id` is *derived*
from the bot, the bar and what the order is for — never random. So the
same signal produces the same id however many times the code runs, and the
exchange refuses the duplicate. This is what makes a crash between "order
sent" and "order recorded" safe: on restart the same signal recomputes the
same id and the venue returns the original order instead of placing a
second one.

**An uncertain order is resolved, never resent.** A timeout does not mean
the order failed; it means nobody knows. Retrying is how you end up with
twice the position. `resolve()` asks the venue what happened to that
`client_id` and believes the answer.

**The exchange is the truth.** Reconciliation adopts what the venue says
and records the difference; it does not trade to force the venue to agree
with our records. If the difference is material the bot halts, because a
bot whose idea of its own position is wrong should not be sending orders.

**Order traffic leaves from the server's static IP** and is never routed
through a user's VPN (SPEC §9). Nothing here takes a proxy argument, which
is the cheapest way to keep that true.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

import structlog

from quanta.exchanges.trading import (
    Credentials,
    MarginMode,
    Order,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    PositionMode,
    TradeSide,
    TradingAdapter,
    TradingError,
)
from quanta.services.risk import RiskGuard, RiskVerdict

logger = structlog.get_logger(__name__)

#: Client ids are short because venues cap them and long ids get truncated
#: silently, which would quietly break idempotency.
CLIENT_ID_BYTES = 12


class Purpose(StrEnum):
    """What an order is for. Part of the client id, so an entry and the
    exit on the same bar can never collide."""

    ENTRY = "entry"
    EXIT = "exit"
    ADD = "add"
    REDUCE = "reduce"
    FLATTEN = "flatten"


class Outcome(StrEnum):
    PLACED = "placed"
    #: The venue already had this client id. Not an error: it is the
    #: retry path working.
    DUPLICATE = "duplicate"
    BLOCKED = "blocked"
    REJECTED = "rejected"
    #: Sent, but we do not know what happened. Resolve, do not resend.
    UNCERTAIN = "uncertain"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class BotContext:
    """Everything about one bot that placing an order needs."""

    bot_id: str
    symbol: str
    leverage: int
    margin_mode: MarginMode
    position_mode: PositionMode
    credentials: Credentials


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    outcome: Outcome
    client_id: str
    order: Order | None = None
    verdict: RiskVerdict | None = None
    error: str | None = None

    @property
    def is_live(self) -> bool:
        """True when an order exists at the venue because of this call."""
        return self.outcome in (Outcome.PLACED, Outcome.DUPLICATE)


@dataclass(frozen=True, slots=True)
class Difference:
    """One way the venue disagrees with our records."""

    symbol: str
    kind: str
    expected: Decimal
    actual: Decimal

    @property
    def is_material(self) -> bool:
        """A difference worth halting for.

        An untracked position, or ours having vanished, means our idea of
        the account is wrong. A size that merely drifted — a partial fill
        we have not seen yet — is recorded and left alone.
        """
        return self.kind in ("untracked_position", "missing_position")


@dataclass(frozen=True, slots=True)
class ReconcileReport:
    positions: list[Position]
    open_orders: list[Order]
    differences: list[Difference] = field(default_factory=list)

    @property
    def should_halt(self) -> bool:
        return any(d.is_material for d in self.differences)


@dataclass
class KillReport:
    """What the kill switch managed to do.

    Partial failures are reported rather than rolled back: a half-flattened
    account the user can see beats an error that hid what happened.
    """

    orders_cancelled: int = 0
    positions_closed: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.failures


def client_id_for(bot_id: str, bar_time: int, purpose: Purpose, *, attempt: int = 0) -> str:
    """A deterministic id for one order.

    Derived, never random: the same signal must produce the same id on
    every run, because that is what stops a retry becoming a second
    position. `attempt` exists for the one case where a *new* order really
    is wanted for the same bar and purpose — a deliberate re-entry after a
    rejection, never an automatic retry.
    """
    seed = f"{bot_id}|{bar_time}|{purpose.value}|{attempt}".encode()
    digest = hashlib.blake2b(seed, digest_size=CLIENT_ID_BYTES).digest()
    # base32 without padding: case-insensitive and alphanumeric, which
    # venues accept more consistently than base64's + and /.
    return "q" + base64.b32encode(digest).decode().rstrip("=").lower()


class ExecutionService:
    """Places orders for one venue."""

    def __init__(self, adapter: TradingAdapter) -> None:
        self._adapter = adapter

    # --- Placing ---------------------------------------------------------

    async def place(
        self,
        context: BotContext,
        *,
        side: OrderSide,
        qty: Decimal,
        purpose: Purpose,
        bar_time: int,
        price: Decimal,
        equity: Decimal,
        positions: list[Position],
        guard: RiskGuard,
        reduce_only: bool = False,
        order_type: OrderType = OrderType.MARKET,
        limit_price: Decimal | None = None,
        stop_loss: Decimal | None = None,
        take_profit: Decimal | None = None,
        attempt: int = 0,
        at: datetime | None = None,
    ) -> ExecutionResult:
        """Risk-check and send one order."""
        client_id = client_id_for(context.bot_id, bar_time, purpose, attempt=attempt)

        request = OrderRequest(
            symbol=context.symbol,
            side=side,
            order_type=order_type,
            qty=qty,
            client_id=client_id,
            price=limit_price,
            trade_side=self._trade_side(context, reduce_only=reduce_only),
            reduce_only=reduce_only,
            sl_price=stop_loss,
            tp_price=take_profit,
        )

        verdict = guard.check_order(
            request,
            price=price,
            equity=equity,
            positions=positions,
            leverage=context.leverage,
            at=at,
        )
        if not verdict.allowed:
            logger.info(
                "bot.order.blocked",
                bot_id=context.bot_id,
                code=verdict.code.value,
                halt=verdict.halt,
            )
            return ExecutionResult(outcome=Outcome.BLOCKED, client_id=client_id, verdict=verdict)

        try:
            order = await self._adapter.place_order(context.credentials, request)
        except TradingError as exc:
            if exc.retryable:
                # A read-shaped failure: nothing was sent.
                return ExecutionResult(
                    outcome=Outcome.FAILED, client_id=client_id, error=exc.message
                )
            # It may or may not have arrived. Ask, do not resend.
            logger.warning(
                "bot.order.uncertain",
                bot_id=context.bot_id,
                client_id=client_id,
                error=exc.message,
            )
            return ExecutionResult(
                outcome=Outcome.UNCERTAIN, client_id=client_id, error=exc.message
            )

        # The rate window counts what was sent, not what filled.
        guard.state.record_order(at)

        if order.status is OrderStatus.REJECTED:
            return ExecutionResult(
                outcome=Outcome.REJECTED,
                client_id=client_id,
                order=order,
                error=order.reject_reason,
            )
        return ExecutionResult(outcome=Outcome.PLACED, client_id=client_id, order=order)

    async def resolve(self, context: BotContext, client_id: str) -> ExecutionResult:
        """Find out what happened to an order we are unsure about.

        Called after `Outcome.UNCERTAIN`. An order that is not among the
        open ones either never arrived or has already finished; either way
        the caller reconciles rather than guessing.
        """
        try:
            open_orders = await self._adapter.open_orders(
                context.credentials, symbol=context.symbol
            )
        except TradingError as exc:
            return ExecutionResult(
                outcome=Outcome.UNCERTAIN, client_id=client_id, error=exc.message
            )

        for order in open_orders:
            if order.client_id == client_id:
                return ExecutionResult(outcome=Outcome.DUPLICATE, client_id=client_id, order=order)
        return ExecutionResult(outcome=Outcome.UNCERTAIN, client_id=client_id)

    # --- Reconciliation --------------------------------------------------

    async def reconcile(
        self, context: BotContext, *, expected: dict[str, Decimal] | None = None
    ) -> ReconcileReport:
        """Ask the venue what this account actually holds.

        `expected` maps symbol to the signed quantity our records claim —
        positive for long, negative for short. Anything it disagrees with
        is recorded; the venue's answer is the one kept.
        """
        positions = await self._adapter.positions(context.credentials, symbol=context.symbol)
        open_orders = await self._adapter.open_orders(context.credentials, symbol=context.symbol)

        if expected is None:
            return ReconcileReport(positions=positions, open_orders=open_orders)

        differences: list[Difference] = []
        actual = {p.symbol: (p.qty if p.side is OrderSide.BUY else -p.qty) for p in positions}

        for symbol, held in actual.items():
            if symbol not in expected:
                differences.append(Difference(symbol, "untracked_position", Decimal(0), held))
            elif expected[symbol] != held:
                differences.append(Difference(symbol, "size_differs", expected[symbol], held))
        for symbol, claimed in expected.items():
            if symbol not in actual and claimed != 0:
                differences.append(Difference(symbol, "missing_position", claimed, Decimal(0)))

        if differences:
            logger.warning(
                "bot.reconcile.differences",
                bot_id=context.bot_id,
                differences=[d.kind for d in differences],
            )
        return ReconcileReport(
            positions=positions, open_orders=open_orders, differences=differences
        )

    # --- Hedge mode ------------------------------------------------------

    async def check_position_mode(self, context: BotContext) -> str | None:
        """Confirm the account is in the mode the bot was set up for.

        Returns a reason to refuse, or None. Getting this wrong in hedge
        mode opens a second position where a close was intended, which is
        why it is checked before arming rather than discovered on a fill.
        """
        actual = await self._adapter.position_mode(context.credentials)
        if actual is not context.position_mode:
            return (
                f"The account is in {actual.value} mode but this bot expects "
                f"{context.position_mode.value}."
            )
        return None

    @staticmethod
    def conflicting_symbol(context: BotContext, other_bot_symbols: list[str]) -> str | None:
        """Two bots on one symbol in one-way mode share a position.

        Each would see the other's fills as its own and act on them, so
        this is refused at arming (SPEC §3.2, §3.5). Hedge mode and
        sub-accounts are the documented ways around it.
        """
        if context.position_mode is PositionMode.HEDGE:
            return None
        if context.symbol in other_bot_symbols:
            return (
                f"Another bot already trades {context.symbol} on this account in "
                "one-way mode. Use hedge mode or a separate sub-account."
            )
        return None

    # --- Kill switch -----------------------------------------------------

    async def kill(self, contexts: list[BotContext]) -> KillReport:
        """Cancel everything, then close everything (SPEC §3.5).

        Order matters: resting orders go first, so a stop that would fire
        mid-flatten cannot reopen what we are closing. Then each position
        is closed with a reduce-only market order, which cannot overshoot
        into a new position however stale the size was.

        Nothing is rolled back on failure. What failed is named, per
        symbol, so a half-flattened account is visible rather than hidden
        behind one error.
        """
        report = KillReport()
        for context in contexts:
            await self._kill_one(context, report)
        return report

    async def _kill_one(self, context: BotContext, report: KillReport) -> None:
        try:
            report.orders_cancelled += await self._adapter.cancel_all(
                context.credentials, symbol=context.symbol
            )
        except TradingError as exc:
            report.failures.append(f"{context.symbol}: could not cancel orders ({exc.message})")
            # Carry on to the positions: an uncancelled order is bad, an
            # open position left behind is worse.

        try:
            positions = await self._adapter.positions(context.credentials, symbol=context.symbol)
        except TradingError as exc:
            report.failures.append(f"{context.symbol}: could not read positions ({exc.message})")
            return

        for index, position in enumerate(positions):
            if position.qty <= 0:
                continue
            client_id = client_id_for(
                context.bot_id,
                int(datetime.now(UTC).timestamp()),
                Purpose.FLATTEN,
                attempt=index,
            )
            request = OrderRequest(
                symbol=position.symbol,
                # Closing a long is a sell.
                side=position.side.opposite,
                order_type=OrderType.MARKET,
                qty=position.qty,
                client_id=client_id,
                trade_side=(
                    TradeSide.CLOSE if context.position_mode is PositionMode.HEDGE else None
                ),
                # The guarantee that a stale size cannot open a new
                # position in the opposite direction.
                reduce_only=True,
            )
            try:
                await self._adapter.place_order(context.credentials, request)
                report.positions_closed += 1
            except TradingError as exc:
                report.failures.append(
                    f"{position.symbol}: could not close {position.qty} ({exc.message})"
                )

        logger.warning(
            "bot.kill",
            bot_id=context.bot_id,
            cancelled=report.orders_cancelled,
            closed=report.positions_closed,
            failures=len(report.failures),
        )

    # --- Helpers ---------------------------------------------------------

    @staticmethod
    def _trade_side(context: BotContext, *, reduce_only: bool) -> TradeSide | None:
        """Hedge mode needs this field; one-way mode must not send it."""
        if context.position_mode is not PositionMode.HEDGE:
            return None
        return TradeSide.CLOSE if reduce_only else TradeSide.OPEN
