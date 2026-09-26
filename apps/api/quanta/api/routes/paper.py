"""Paper trading: live rules, no money (SPEC §3.3)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from quanta.api.deps import CurrentUser, DbDep
from quanta.models.paper import PaperFill, PaperSession
from quanta.models.setup import Setup
from quanta.schemas.alert import PaperFillRequest, PaperStartRequest, PromoteRequest
from quanta.services import paper_service

router = APIRouter(prefix="/paper", tags=["paper"])


async def _owned(db: DbDep, user: CurrentUser, session_id: uuid.UUID) -> PaperSession:
    session = await db.get(PaperSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such session.")
    return session


@router.get("")
async def list_sessions(user: CurrentUser, db: DbDep) -> list[dict]:
    result = await db.execute(
        select(PaperSession)
        .where(PaperSession.user_id == user.id)
        .order_by(PaperSession.created_at.desc())
    )
    return [await paper_service.session_summary(db, session) for session in result.scalars().all()]


@router.post("", status_code=status.HTTP_201_CREATED)
async def start_session(payload: PaperStartRequest, user: CurrentUser, db: DbDep) -> dict:
    setup = await db.get(Setup, payload.setup_id)
    if setup is None or setup.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such setup.")

    session = PaperSession(
        user_id=user.id,
        setup_id=setup.id,
        state="running",
        started_at=datetime.now(UTC),
        initial_capital=payload.initial_capital,
        equity=payload.initial_capital,
        expected_net_percent=payload.expected_net_percent,
        expected_low_percent=payload.expected_low_percent,
        expected_high_percent=payload.expected_high_percent,
        drawdown_limit_percent=payload.drawdown_limit_percent,
        missed_signals=0,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return await paper_service.session_summary(db, session)


@router.get("/{session_id}")
async def get_session(session_id: uuid.UUID, user: CurrentUser, db: DbDep) -> dict:
    return await paper_service.session_summary(db, await _owned(db, user, session_id))


@router.post("/{session_id}/fills", status_code=status.HTTP_201_CREATED)
async def record_fill(
    session_id: uuid.UUID, payload: PaperFillRequest, user: CurrentUser, db: DbDep
) -> dict:
    """Record what the live feed actually did with a signal."""
    session = await _owned(db, user, session_id)
    if session.state != "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This session is {session.state}, so it takes no more fills.",
        )

    # Signed against the direction the trade wanted to go, so a long
    # filled high and a short filled low are both adverse.
    direction = 1.0 if payload.side == "long" else -1.0
    if payload.action == "exit":
        direction = -direction
    slippage_bps = (
        (payload.fill_price - payload.signal_price) / payload.signal_price * 10_000.0 * direction
    )

    equity = float(session.equity) + payload.net_pnl
    fill = PaperFill(
        session_id=session.id,
        side=payload.side,
        action=payload.action,
        bar_time=payload.bar_time,
        signal_price=payload.signal_price,
        fill_price=payload.fill_price,
        quantity=payload.quantity,
        slippage_bps=slippage_bps,
        latency_ms=payload.latency_ms,
        fee=payload.fee,
        funding=payload.funding,
        net_pnl=payload.net_pnl,
        equity_after=equity,
        filled_at=datetime.now(UTC),
    )
    session.equity = equity
    session.last_bar_time = payload.bar_time
    db.add(fill)
    await db.commit()
    await db.refresh(session)
    return await paper_service.session_summary(db, session)


@router.post("/{session_id}/missed", status_code=status.HTTP_202_ACCEPTED)
async def record_missed(session_id: uuid.UUID, user: CurrentUser, db: DbDep) -> dict:
    """A signal the engine produced that no fill was recorded for.

    Counted rather than ignored: a strategy whose signals routinely find
    nobody to trade against is not tradeable, and a backtest cannot see
    that at all.
    """
    session = await _owned(db, user, session_id)
    session.missed_signals += 1
    await db.commit()
    await db.refresh(session)
    return await paper_service.session_summary(db, session)


@router.post("/{session_id}/stop")
async def stop_session(session_id: uuid.UUID, user: CurrentUser, db: DbDep) -> dict:
    session = await _owned(db, user, session_id)
    session.state = "stopped"
    session.stopped_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(session)
    return await paper_service.session_summary(db, session)


@router.post("/{session_id}/promote")
async def promote_session(
    session_id: uuid.UUID, payload: PromoteRequest, user: CurrentUser, db: DbDep
) -> dict:
    """Unlock the bot stage, or say exactly what is still missing."""
    session = await _owned(db, user, session_id)
    setup = await db.get(Setup, session.setup_id)
    if setup is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such setup.")

    if payload.override and not user.totp_enabled:
        # SPEC §3.3 puts the override behind 2FA. Without it enabled there
        # is no second factor to check, so the override is not available.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Overriding the checklist needs two-factor authentication enabled.",
        )

    try:
        summary = await paper_service.promote(db, session, setup, override=payload.override)
    except paper_service.PromotionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    await db.commit()
    return summary
