"""Bots and exchange keys, against the database (SPEC §3.5, §3.6).

The parts that can be tested without a database already are — `risk.py`,
`execution.py`, `keyvault.py`. What is left here is the joining up: sealing
a key into a row, turning a row back into a `BotContext`, and the
pre-flight checklist, which is the one piece of real judgement in this
file.

**Pre-flight is shown, not just enforced.** Each check carries the figure
it was judged on, the same way the paper-promotion checklist does, because
a checklist that says "failed" without saying what the number was cannot
be acted on.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from quanta.exchanges.trading import Credentials, MarginMode, PositionMode
from quanta.models.bot import Bot, BotOrder, ExchangeKey
from quanta.models.setup import Setup
from quanta.models.user import User
from quanta.services.execution import BotContext
from quanta.services.keyvault import KeyVault, SealedSecret, context_for
from quanta.services.risk import RiskGuard, RiskLimits, RiskState


@dataclass(frozen=True, slots=True)
class Check:
    """One pre-flight row: what was checked, whether it passed, and the
    figure it was judged on."""

    key: str
    label: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class Preflight:
    checks: list[Check]

    @property
    def ready(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def blocking(self) -> list[str]:
        return [check.label for check in self.checks if not check.passed]


# --- Exchange keys -------------------------------------------------------


def seal_key(
    vault: KeyVault,
    key: ExchangeKey,
    *,
    api_key: str,
    api_secret: str,
) -> None:
    """Put the sealed credentials on the row.

    The row must already have an id, because the id is part of the
    context the ciphertext is bound to — that is what stops a row being
    moved to another key or another user.
    """
    context = context_for(key.user_id, key.id)
    sealed_key = vault.seal(api_key, context=context)
    sealed_secret = vault.seal(api_secret, context=context)

    key.api_key_sealed = sealed_key.ciphertext
    key.api_key_wrapped_key = sealed_key.wrapped_key
    key.api_secret_sealed = sealed_secret.ciphertext
    key.api_secret_wrapped_key = sealed_secret.wrapped_key
    key.key_version = sealed_key.key_version
    key.last_four = vault.last_four(api_key)
    key.fingerprint = vault.fingerprint(api_key)


def open_key(vault: KeyVault, key: ExchangeKey) -> Credentials:
    """Decrypt one key for the length of a call.

    Nothing holds the result: it goes to the adapter and is dropped.
    """
    context = context_for(key.user_id, key.id)
    return Credentials(
        api_key=vault.open(
            SealedSecret(key.api_key_wrapped_key, key.api_key_sealed, key.key_version),
            context=context,
        ),
        api_secret=vault.open(
            SealedSecret(key.api_secret_wrapped_key, key.api_secret_sealed, key.key_version),
            context=context,
        ),
    )


def key_summary(key: ExchangeKey) -> dict[str, Any]:
    """What a key looks like from outside. No secret, ever."""
    return {
        "id": str(key.id),
        "exchange": key.exchange,
        "label": key.label,
        "last_four": key.last_four,
        "fingerprint": key.fingerprint,
        "can_trade": key.can_trade,
        "ip_whitelist": list(key.ip_whitelist or []),
        "verified_at": key.verified_at.isoformat() if key.verified_at else None,
        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
        "created_at": key.created_at.isoformat() if key.created_at else None,
    }


async def bots_using_key(db: AsyncSession, key_id: uuid.UUID) -> list[Bot]:
    result = await db.execute(select(Bot).where(Bot.exchange_key_id == key_id))
    return list(result.scalars().all())


# --- Bots ----------------------------------------------------------------


def limits_of(bot: Bot) -> RiskLimits:
    return RiskLimits(
        max_position_notional=Decimal(str(bot.max_position_notional)),
        max_daily_loss=Decimal(str(bot.max_daily_loss)),
        max_drawdown_percent=Decimal(str(bot.max_drawdown_percent)),
        max_leverage=bot.max_leverage,
        max_orders_per_minute=bot.max_orders_per_minute,
    )


def guard_for(bot: Bot) -> RiskGuard:
    """Rebuild the risk guard from the row.

    The day's starting equity and the peak live in the database precisely
    so a restart cannot be used to reset a daily loss limit.
    """
    equity = Decimal(str(bot.equity)) if bot.equity is not None else Decimal(0)
    state = RiskState(
        day_start_equity=(
            Decimal(str(bot.day_start_equity)) if bot.day_start_equity is not None else equity
        ),
        peak_equity=Decimal(str(bot.peak_equity)) if bot.peak_equity is not None else equity,
        day_started_at=bot.day_started_at or datetime.now(UTC),
    )
    return RiskGuard(limits_of(bot), state)


def remember_state(bot: Bot, guard: RiskGuard, equity: Decimal) -> None:
    """Write the guard's memory back to the row."""
    bot.equity = float(equity)
    bot.day_start_equity = float(guard.state.day_start_equity)
    bot.peak_equity = float(guard.state.peak_equity)
    bot.day_started_at = guard.state.day_started_at


def context_of(bot: Bot, credentials: Credentials) -> BotContext:
    return BotContext(
        bot_id=str(bot.id),
        symbol=bot.symbol,
        leverage=bot.leverage,
        margin_mode=MarginMode(bot.margin_mode),
        position_mode=PositionMode(bot.position_mode),
        credentials=credentials,
    )


def halt(bot: Bot, reason: str, detail: str) -> None:
    """Stop a bot and record why.

    Halted is not stopped: the reason stays on the row until a person
    clears it, because a bot that halted itself and then quietly looked
    idle would be read as "nothing happened".
    """
    bot.state = "halted"
    bot.halt_reason = reason
    bot.halt_detail = detail[:400]
    bot.halted_at = datetime.now(UTC)


def clear_halt(bot: Bot) -> None:
    bot.state = "stopped"
    bot.halt_reason = None
    bot.halt_detail = None
    bot.halted_at = None


# --- Pre-flight ----------------------------------------------------------


async def preflight(
    db: AsyncSession,
    bot: Bot,
    user: User,
    key: ExchangeKey,
    setup: Setup,
    *,
    server_ip: str,
    account_position_mode: PositionMode | None = None,
    account_equity: Decimal | None = None,
) -> Preflight:
    """Every condition that must hold before a bot may be armed.

    `account_position_mode` and `account_equity` come from the venue when
    it is reachable. When they are None the checks that need them fail
    rather than pass: an unanswered question about a live account is not
    a yes.
    """
    checks: list[Check] = []

    # use_in_bot is set by paper_service on promotion and by nothing else,
    # so it is the gate rather than a stage name that could drift.
    checks.append(
        Check(
            key="paper",
            label="Passed paper trading",
            passed=bool(setup.use_in_bot),
            detail=(
                "Promoted from paper trading"
                if setup.use_in_bot
                else f"“{setup.name}” has not passed paper trading yet"
            ),
        )
    )

    checks.append(
        Check(
            key="key_trade",
            label="Key can place orders",
            passed=bool(key.can_trade),
            detail=f"{key.label} ·{key.last_four}"
            if key.can_trade
            else "This key has no trading permission",
        )
    )

    whitelist = list(key.ip_whitelist or [])
    pinned = server_ip in whitelist if server_ip else False
    checks.append(
        Check(
            key="key_ip",
            label="Key is pinned to this server",
            passed=pinned,
            detail=(
                f"Whitelisted for {server_ip}"
                if pinned
                else f"Whitelist {server_ip or 'the server IP'} on this key"
            ),
        )
    )

    checks.append(
        Check(
            key="totp",
            label="2FA is on",
            passed=bool(user.totp_enabled),
            detail="Enabled" if user.totp_enabled else "Turn it on in Settings",
        )
    )

    others = await db.execute(
        select(Bot).where(
            Bot.user_id == bot.user_id,
            Bot.exchange_key_id == bot.exchange_key_id,
            Bot.symbol == bot.symbol,
            Bot.id != bot.id,
            Bot.state.in_(("armed", "running")),
        )
    )
    clash = list(others.scalars().all())
    hedged = bot.position_mode == PositionMode.HEDGE.value
    conflict_free = hedged or not clash
    checks.append(
        Check(
            key="symbol",
            label="No other bot on this symbol",
            passed=conflict_free,
            detail=(
                "Hedge mode: separate long and short books"
                if hedged
                else "Nothing else trades it"
                if conflict_free
                else f"“{clash[0].name}” already trades {bot.symbol} on this key"
            ),
        )
    )

    mode_ok = account_position_mode is not None and (
        account_position_mode.value == bot.position_mode
    )
    checks.append(
        Check(
            key="mode",
            label="Account mode matches",
            passed=mode_ok,
            detail=(
                f"Account is in {account_position_mode.value}"
                if account_position_mode is not None
                else "Could not read the account's position mode"
            ),
        )
    )

    leverage_ok = bot.leverage <= bot.max_leverage
    checks.append(
        Check(
            key="leverage",
            label="Leverage within its own limit",
            passed=leverage_ok,
            detail=f"{bot.leverage}x against a limit of {bot.max_leverage}x",
        )
    )

    if account_equity is None:
        checks.append(
            Check(
                key="limits",
                label="Risk limits fit the account",
                passed=False,
                detail="Could not read the account balance",
            )
        )
    else:
        # A daily-loss limit larger than the account can never trip, which
        # makes it decoration rather than a limit.
        fits = Decimal(str(bot.max_daily_loss)) <= account_equity
        checks.append(
            Check(
                key="limits",
                label="Risk limits fit the account",
                passed=fits,
                detail=(f"Daily loss limit {bot.max_daily_loss} against equity {account_equity}"),
            )
        )

    return Preflight(checks=checks)


# --- Summaries -----------------------------------------------------------


def bot_summary(bot: Bot, *, budgets: dict[str, Decimal] | None = None) -> dict[str, Any]:
    return {
        "id": str(bot.id),
        "name": bot.name,
        "setup_id": str(bot.setup_id),
        "exchange_key_id": str(bot.exchange_key_id),
        "state": bot.state,
        "halt_reason": bot.halt_reason,
        "halt_detail": bot.halt_detail,
        "halted_at": bot.halted_at.isoformat() if bot.halted_at else None,
        "symbol": bot.symbol,
        "interval": bot.interval,
        "leverage": bot.leverage,
        "margin_mode": bot.margin_mode,
        "position_mode": bot.position_mode,
        "limits": {
            "max_position_notional": float(bot.max_position_notional),
            "max_daily_loss": float(bot.max_daily_loss),
            "max_drawdown_percent": float(bot.max_drawdown_percent),
            "max_leverage": bot.max_leverage,
            "max_orders_per_minute": bot.max_orders_per_minute,
        },
        "equity": float(bot.equity) if bot.equity is not None else None,
        "budgets": {
            key: float(value)
            for key, value in (
                budgets
                or {"daily_loss_used_percent": Decimal(0), "drawdown_used_percent": Decimal(0)}
            ).items()
        },
        "armed_at": bot.armed_at.isoformat() if bot.armed_at else None,
        "last_signal_at": bot.last_signal_at.isoformat() if bot.last_signal_at else None,
    }


def order_summary(order: BotOrder) -> dict[str, Any]:
    return {
        "id": str(order.id),
        "client_id": order.client_id,
        "exchange_order_id": order.exchange_order_id,
        "purpose": order.purpose,
        "outcome": order.outcome,
        "symbol": order.symbol,
        "side": order.side,
        "order_type": order.order_type,
        "qty": float(order.qty),
        "price": float(order.price) if order.price is not None else None,
        "filled_qty": float(order.filled_qty) if order.filled_qty is not None else None,
        "average_price": (float(order.average_price) if order.average_price is not None else None),
        "reduce_only": order.reduce_only,
        "status": order.status,
        "bar_time": order.bar_time,
        "latency_ms": order.latency_ms,
        "error": order.error,
        "sent_at": order.sent_at.isoformat() if order.sent_at else None,
    }
