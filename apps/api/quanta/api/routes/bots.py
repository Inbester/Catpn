"""Exchange keys and trading bots (SPEC §3.5, §3.6).

Two routers, because the two live in different menus: keys belong to
Settings, bots to the Trading bot menu. They share this file because they
share the vault and the adapter, and splitting them would mean two copies
of the same wiring.

**Every action that can move money takes 2FA**, verified here rather than
trusted from the client: arming, going live, raising a risk limit, and the
kill switch. Lowering a limit does not, because making yourself safer
should not be gated behind a phone.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from quanta.api.deps import CurrentUser, DbDep, SettingsDep, client_ip
from quanta.exchanges.bitunix_trading import BitunixTradingAdapter
from quanta.exchanges.trading import (
    Credentials,
    KeyRejectedError,
    PositionMode,
    TradingAdapter,
    TradingError,
)
from quanta.models.bot import Bot, BotOrder, ExchangeKey
from quanta.models.setup import Setup
from quanta.schemas.bot import (
    BotCreate,
    BotUpdate,
    ExchangeKeyCreate,
    KillRequest,
    SecondFactor,
)
from quanta.services import auth_service, bot_service
from quanta.services.execution import ExecutionService
from quanta.services.keyvault import KeyVault, VaultError, verify_admissible

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/bots", tags=["bots"])
keys_router = APIRouter(prefix="/exchange-keys", tags=["exchange-keys"])

#: Swapped for the simulator in tests. Module-level rather than a FastAPI
#: dependency because the execution path must not be overridable by a
#: request: nothing a client sends can change where orders go.
_adapter: TradingAdapter | None = None


def set_trading_adapter(adapter: TradingAdapter | None) -> None:
    """Point trading at a different venue. Tests use this."""
    global _adapter
    _adapter = adapter


def trading_adapter() -> TradingAdapter:
    global _adapter
    if _adapter is None:
        _adapter = BitunixTradingAdapter()
    return _adapter


def _require_2fa(user: Any, code: str | None) -> None:
    """SPEC §3.5: live actions need a second factor.

    An account without 2FA cannot do these at all, rather than being
    waved through — that is the whole point of requiring it.
    """
    if not user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Turn on two-factor authentication in Settings first.",
        )
    if not code or not auth_service.verify_second_factor(user, code):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="That code was not right."
        )


async def _owned_bot(db: DbDep, user: CurrentUser, bot_id: uuid.UUID) -> Bot:
    bot = await db.get(Bot, bot_id)
    if bot is None or bot.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such bot.")
    return bot


async def _owned_key(db: DbDep, user: CurrentUser, key_id: uuid.UUID) -> ExchangeKey:
    key = await db.get(ExchangeKey, key_id)
    if key is None or key.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such key.")
    return key


# --- Exchange keys (Settings, SPEC §3.6) ---------------------------------


@keys_router.get("")
async def list_keys(user: CurrentUser, db: DbDep, settings: SettingsDep) -> dict[str, Any]:
    result = await db.execute(
        select(ExchangeKey).where(ExchangeKey.user_id == user.id).order_by(ExchangeKey.created_at)
    )
    return {
        # Returned with the list so the page can show it above the form:
        # a key pasted before the whitelist exists is refused for a reason
        # the user cannot see.
        "server_ip": settings.exchange_static_ip,
        "keys": [bot_service.key_summary(key) for key in result.scalars().all()],
    }


@keys_router.post("", status_code=status.HTTP_201_CREATED)
async def add_key(
    payload: ExchangeKeyCreate,
    user: CurrentUser,
    db: DbDep,
    settings: SettingsDep,
    request: Request,
) -> dict[str, Any]:
    """Verify a key at the venue, then seal it (SPEC §3.5, §3.6)."""
    if not settings.exchange_static_ip:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="This server has no static IP configured, so no key can be whitelisted to it.",
        )

    existing = await db.execute(
        select(ExchangeKey).where(
            ExchangeKey.user_id == user.id,
            ExchangeKey.exchange == payload.exchange,
            ExchangeKey.label == payload.label,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"You already have a key called “{payload.label}”.",
        )

    credentials = Credentials(api_key=payload.api_key, api_secret=payload.api_secret)
    try:
        permissions = await verify_admissible(
            trading_adapter(), credentials, server_ip=settings.exchange_static_ip
        )
    except KeyRejectedError as exc:
        await auth_service.record_audit(
            db,
            "exchange_key.rejected",
            user_id=user.id,
            outcome="failure",
            detail={"reason": exc.reason},
            ip_address=client_ip(request),
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc
    except TradingError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"The exchange would not confirm that key: {exc.message}",
        ) from exc

    key = ExchangeKey(
        user_id=user.id,
        exchange=payload.exchange,
        label=payload.label,
        can_trade=permissions.can_trade,
        ip_whitelist=list(permissions.ip_whitelist),
        verified_at=datetime.now(UTC),
        # Placeholders: seal_key needs the row's id, which needs a flush.
        api_key_sealed=b"",
        api_key_wrapped_key=b"",
        api_secret_sealed=b"",
        api_secret_wrapped_key=b"",
        key_version="",
        fingerprint="",
    )
    db.add(key)
    await db.flush()

    bot_service.seal_key(
        KeyVault.local(settings), key, api_key=payload.api_key, api_secret=payload.api_secret
    )
    await auth_service.record_audit(
        db,
        "exchange_key.added",
        user_id=user.id,
        # The fingerprint, never the key.
        detail={"label": key.label, "fingerprint": key.fingerprint},
        ip_address=client_ip(request),
    )
    await db.commit()
    await db.refresh(key)
    return bot_service.key_summary(key)


@keys_router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_key(key_id: uuid.UUID, user: CurrentUser, db: DbDep, request: Request) -> None:
    key = await _owned_key(db, user, key_id)

    # A bot without its key cannot close what it holds, so the delete is
    # refused and names the bot rather than cascading.
    users = await bot_service.bots_using_key(db, key.id)
    if users:
        names = ", ".join(f"“{bot.name}”" for bot in users)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{names} still uses this key. Delete the bot first.",
        )

    await db.delete(key)
    await auth_service.record_audit(
        db,
        "exchange_key.deleted",
        user_id=user.id,
        detail={"label": key.label, "fingerprint": key.fingerprint},
        ip_address=client_ip(request),
    )
    await db.commit()


# --- Bots ----------------------------------------------------------------


@router.get("")
async def list_bots(user: CurrentUser, db: DbDep) -> list[dict[str, Any]]:
    result = await db.execute(select(Bot).where(Bot.user_id == user.id).order_by(Bot.created_at))
    out = []
    for bot in result.scalars().all():
        guard = bot_service.guard_for(bot)
        equity = Decimal(str(bot.equity)) if bot.equity is not None else Decimal(0)
        out.append(bot_service.bot_summary(bot, budgets=guard.budgets(equity)))
    return out


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_bot(payload: BotCreate, user: CurrentUser, db: DbDep) -> dict[str, Any]:
    setup = await db.get(Setup, payload.setup_id)
    if setup is None or setup.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such setup.")
    await _owned_key(db, user, payload.exchange_key_id)

    bot = Bot(
        user_id=user.id,
        setup_id=setup.id,
        exchange_key_id=payload.exchange_key_id,
        name=payload.name,
        symbol=payload.symbol,
        interval=payload.interval,
        leverage=payload.leverage,
        margin_mode=payload.margin_mode,
        position_mode=payload.position_mode,
        max_position_notional=float(payload.limits.max_position_notional),
        max_daily_loss=float(payload.limits.max_daily_loss),
        max_drawdown_percent=float(payload.limits.max_drawdown_percent),
        max_leverage=payload.limits.max_leverage,
        max_orders_per_minute=payload.limits.max_orders_per_minute,
        state="stopped",
    )
    db.add(bot)
    await db.commit()
    await db.refresh(bot)
    return bot_service.bot_summary(bot)


@router.patch("/{bot_id}")
async def update_bot(
    bot_id: uuid.UUID, payload: BotUpdate, user: CurrentUser, db: DbDep
) -> dict[str, Any]:
    bot = await _owned_bot(db, user, bot_id)
    if bot.state in ("armed", "running"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Stop the bot before changing it.",
        )

    if payload.limits is not None:
        # Raising a limit needs 2FA; lowering one does not. Making
        # yourself safer should not be gated behind a phone.
        loosened = (
            payload.limits.max_position_notional > Decimal(str(bot.max_position_notional))
            or payload.limits.max_daily_loss > Decimal(str(bot.max_daily_loss))
            or payload.limits.max_drawdown_percent > Decimal(str(bot.max_drawdown_percent))
            or payload.limits.max_leverage > bot.max_leverage
            or payload.limits.max_orders_per_minute > bot.max_orders_per_minute
        )
        if loosened:
            _require_2fa(user, payload.code)
        bot.max_position_notional = float(payload.limits.max_position_notional)
        bot.max_daily_loss = float(payload.limits.max_daily_loss)
        bot.max_drawdown_percent = float(payload.limits.max_drawdown_percent)
        bot.max_leverage = payload.limits.max_leverage
        bot.max_orders_per_minute = payload.limits.max_orders_per_minute

    if payload.leverage is not None:
        if payload.leverage > bot.leverage:
            _require_2fa(user, payload.code)
        bot.leverage = payload.leverage
    if payload.name is not None:
        bot.name = payload.name

    await db.commit()
    await db.refresh(bot)
    return bot_service.bot_summary(bot)


@router.delete("/{bot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bot(bot_id: uuid.UUID, user: CurrentUser, db: DbDep) -> None:
    bot = await _owned_bot(db, user, bot_id)
    if bot.state in ("armed", "running"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Stop the bot before deleting it."
        )
    await db.delete(bot)
    await db.commit()


@router.get("/{bot_id}/preflight")
async def bot_preflight(
    bot_id: uuid.UUID, user: CurrentUser, db: DbDep, settings: SettingsDep
) -> dict[str, Any]:
    """The checklist that gates arming (SPEC §3.5)."""
    bot = await _owned_bot(db, user, bot_id)
    key = await db.get(ExchangeKey, bot.exchange_key_id)
    setup = await db.get(Setup, bot.setup_id)
    if key is None or setup is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such bot.")

    mode, equity = await _account_snapshot(db, settings, key, bot)
    result = await bot_service.preflight(
        db,
        bot,
        user,
        key,
        setup,
        server_ip=settings.exchange_static_ip,
        account_position_mode=mode,
        account_equity=equity,
    )
    return {
        "ready": result.ready,
        "blocking": result.blocking,
        "checks": [
            {"key": c.key, "label": c.label, "passed": c.passed, "detail": c.detail}
            for c in result.checks
        ],
    }


async def _account_snapshot(
    db: DbDep, settings: SettingsDep, key: ExchangeKey, bot: Bot
) -> tuple[PositionMode | None, Decimal | None]:
    """Read the venue, or admit that we could not.

    Returns None rather than a guess when the venue is unreachable: an
    unanswered question about a live account must not read as a yes.
    """
    try:
        credentials = bot_service.open_key(KeyVault.local(settings), key)
    except VaultError:
        logger.error("bot.key.unreadable", key_id=str(key.id))
        return None, None

    adapter = trading_adapter()
    try:
        mode = await adapter.position_mode(credentials)
        balances = await adapter.balances(credentials)
    except TradingError as exc:
        logger.warning("bot.account.unreachable", bot_id=str(bot.id), error=exc.message)
        return None, None

    equity = balances[0].equity if balances else Decimal(0)
    key.last_used_at = datetime.now(UTC)
    await db.commit()
    return mode, equity


@router.post("/{bot_id}/arm")
async def arm_bot(
    bot_id: uuid.UUID,
    payload: SecondFactor,
    user: CurrentUser,
    db: DbDep,
    settings: SettingsDep,
    request: Request,
) -> dict[str, Any]:
    """Arm a bot: it will act on its next signal (SPEC §3.5)."""
    bot = await _owned_bot(db, user, bot_id)
    _require_2fa(user, payload.code)

    if bot.state == "halted":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This bot halted: {bot.halt_detail or bot.halt_reason}. Clear it first.",
        )

    key = await db.get(ExchangeKey, bot.exchange_key_id)
    setup = await db.get(Setup, bot.setup_id)
    if key is None or setup is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such bot.")

    mode, equity = await _account_snapshot(db, settings, key, bot)
    result = await bot_service.preflight(
        db,
        bot,
        user,
        key,
        setup,
        server_ip=settings.exchange_static_ip,
        account_position_mode=mode,
        account_equity=equity,
    )
    if not result.ready:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Not ready: " + "; ".join(result.blocking).lower() + ".",
        )

    bot.state = "armed"
    bot.armed_at = datetime.now(UTC)
    if equity is not None:
        guard = bot_service.guard_for(bot)
        guard.state.observe(equity)
        bot_service.remember_state(bot, guard, equity)

    await auth_service.record_audit(
        db,
        "bot.armed",
        user_id=user.id,
        detail={"bot": bot.name, "symbol": bot.symbol},
        ip_address=client_ip(request),
    )
    await db.commit()
    await db.refresh(bot)
    return bot_service.bot_summary(bot)


@router.post("/{bot_id}/stop")
async def stop_bot(
    bot_id: uuid.UUID, user: CurrentUser, db: DbDep, request: Request
) -> dict[str, Any]:
    """Stop a bot. No 2FA: stopping is always allowed to be easy."""
    bot = await _owned_bot(db, user, bot_id)
    bot.state = "stopped"
    bot.armed_at = None
    await auth_service.record_audit(
        db,
        "bot.stopped",
        user_id=user.id,
        detail={"bot": bot.name},
        ip_address=client_ip(request),
    )
    await db.commit()
    await db.refresh(bot)
    return bot_service.bot_summary(bot)


@router.post("/{bot_id}/clear-halt")
async def clear_halt(
    bot_id: uuid.UUID, user: CurrentUser, db: DbDep, request: Request
) -> dict[str, Any]:
    """Acknowledge a halt. The bot returns to stopped, not to armed.

    Re-arming is a separate, 2FA-gated act, so clearing a halt can never
    put a bot straight back to work by accident.
    """
    bot = await _owned_bot(db, user, bot_id)
    if bot.state != "halted":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This bot has not halted.")
    previous = bot.halt_reason
    bot_service.clear_halt(bot)
    await auth_service.record_audit(
        db,
        "bot.halt_cleared",
        user_id=user.id,
        detail={"bot": bot.name, "was": previous},
        ip_address=client_ip(request),
    )
    await db.commit()
    await db.refresh(bot)
    return bot_service.bot_summary(bot)


@router.get("/{bot_id}/orders")
async def bot_orders(
    bot_id: uuid.UUID, user: CurrentUser, db: DbDep, limit: int = 100
) -> list[dict[str, Any]]:
    """The audit log for one bot (SPEC §3.5)."""
    bot = await _owned_bot(db, user, bot_id)
    result = await db.execute(
        select(BotOrder)
        .where(BotOrder.bot_id == bot.id)
        .order_by(BotOrder.sent_at.desc())
        .limit(min(limit, 500))
    )
    return [bot_service.order_summary(order) for order in result.scalars().all()]


@router.post("/kill")
async def kill_switch(
    payload: KillRequest,
    user: CurrentUser,
    db: DbDep,
    settings: SettingsDep,
    request: Request,
) -> dict[str, Any]:
    """Halt every bot, cancel every order, close every position.

    The order is deliberate and the confirmation is explicit: see SPEC
    §3.5. `confirm_flatten` has no default, so nobody reaches this by
    accident.
    """
    _require_2fa(user, payload.code)
    if not payload.confirm_flatten:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The kill switch closes open positions at market. Confirm to continue.",
        )

    result = await db.execute(select(Bot).where(Bot.user_id == user.id))
    bots = list(result.scalars().all())

    vault = KeyVault.local(settings)
    contexts = []
    unreadable = []
    for bot in bots:
        # Halt first, so nothing new is sent while we are flattening.
        bot_service.halt(bot, "kill_switch", "Stopped by the kill switch.")
        key = await db.get(ExchangeKey, bot.exchange_key_id)
        if key is None:
            continue
        try:
            contexts.append(bot_service.context_of(bot, bot_service.open_key(vault, key)))
        except VaultError:
            unreadable.append(bot.name)

    report = await ExecutionService(trading_adapter()).kill(contexts)
    failures = list(report.failures) + [
        f"{name}: its key could not be opened, so nothing was closed" for name in unreadable
    ]

    await auth_service.record_audit(
        db,
        "bot.kill_switch",
        user_id=user.id,
        outcome="success" if not failures else "failure",
        detail={
            "bots": len(bots),
            "orders_cancelled": report.orders_cancelled,
            "positions_closed": report.positions_closed,
            "failures": failures,
        },
        ip_address=client_ip(request),
    )
    await db.commit()

    logger.warning(
        "bot.kill_switch",
        user_id=str(user.id),
        bots=len(bots),
        cancelled=report.orders_cancelled,
        closed=report.positions_closed,
    )
    return {
        "bots_halted": len(bots),
        "orders_cancelled": report.orders_cancelled,
        "positions_closed": report.positions_closed,
        "failures": failures,
    }
