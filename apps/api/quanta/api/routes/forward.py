"""Forward test and Setup routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, Response, status

from quanta.api.deps import CurrentUser, DbDep
from quanta.models.setup import Setup
from quanta.models.strategy import StrategyRecord
from quanta.schemas.forward import (
    ConflictWarning,
    PeriodComparisonRequest,
    SetupPayload,
    SetupResponse,
    SetupsOverview,
    StageUpdate,
    WalkForwardRequest,
)
from quanta.services import forward_service
from quanta.services.backtest_service import BacktestError

router = APIRouter(prefix="/forward", tags=["forward"])
setups_router = APIRouter(prefix="/setups", tags=["setups"])


async def _owned_strategy(db: DbDep, user: CurrentUser, strategy_id: uuid.UUID) -> StrategyRecord:
    record = await db.get(StrategyRecord, strategy_id)
    if record is None or record.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such strategy.")
    return record


async def _owned_setup(db: DbDep, user: CurrentUser, setup_id: uuid.UUID) -> Setup:
    setup = await db.get(Setup, setup_id)
    if setup is None or setup.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such setup.")
    return setup


@router.post("/{strategy_id}/periods")
async def compare_periods_route(
    strategy_id: uuid.UUID,
    payload: PeriodComparisonRequest,
    user: CurrentUser,
    db: DbDep,
) -> dict:
    """Compare one frozen strategy version across two periods."""
    record = await _owned_strategy(db, user, strategy_id)

    try:
        return await forward_service.compare(
            db,
            record=record,
            symbol=payload.symbol.upper(),
            interval=payload.interval,
            reference=payload.reference.model_dump(),
            test=payload.test.model_dump(),
            config_payload=payload.config.model_dump(),
            runs=payload.monte_carlo_runs,
            confidence=payload.confidence,
        )
    except (BacktestError, ValueError) as exc:
        raise HTTPException(
            status_code=422,  # Unprocessable Content
            detail=str(exc),
        ) from exc


@router.post("/{strategy_id}/walk-forward")
async def walk_forward_route(
    strategy_id: uuid.UUID,
    payload: WalkForwardRequest,
    user: CurrentUser,
    db: DbDep,
) -> dict:
    """Optimise on each in-sample window and test on the unseen stretch."""
    record = await _owned_strategy(db, user, strategy_id)

    try:
        return await forward_service.walk_forward(
            db,
            record=record,
            symbol=payload.symbol.upper(),
            interval=payload.interval,
            start=payload.start,
            end=payload.end,
            in_sample_days=payload.in_sample_days,
            out_of_sample_days=payload.out_of_sample_days,
            max_windows=payload.max_windows,
            grid=payload.grid,
            config_payload=payload.config.model_dump(),
        )
    except (BacktestError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# --- Setups -------------------------------------------------------------


def _to_response(setup: Setup) -> SetupResponse:
    return SetupResponse(
        id=setup.id,
        name=setup.name,
        color=setup.color,
        strategy_id=setup.strategy_id,
        strategy_version=setup.strategy_version,
        strategy_snapshot=setup.strategy_snapshot,
        symbol=setup.symbol,
        interval=setup.interval,
        margin_percent=float(setup.margin_percent),
        leverage=float(setup.leverage),
        margin_mode=setup.margin_mode,
        exposure=setup.exposure,
        fee_tier=setup.fee_tier,
        maker_fee=float(setup.maker_fee),
        taker_fee=float(setup.taker_fee),
        max_drawdown_budget_percent=(
            float(setup.max_drawdown_budget_percent)
            if setup.max_drawdown_budget_percent is not None
            else None
        ),
        risk_of_ruin_limit_percent=(
            float(setup.risk_of_ruin_limit_percent)
            if setup.risk_of_ruin_limit_percent is not None
            else None
        ),
        source_run_id=setup.source_run_id,
        pipeline=setup.pipeline,
        use_in_backtest=setup.use_in_backtest,
        use_in_forward=setup.use_in_forward,
        use_in_paper=setup.use_in_paper,
        use_in_alerts=setup.use_in_alerts,
        use_in_bot=setup.use_in_bot,
        created_at=setup.created_at,
        updated_at=setup.updated_at,
    )


@setups_router.get("", response_model=list[SetupResponse])
async def list_setups(
    user: CurrentUser,
    db: DbDep,
    include_archived: bool = Query(default=False),
) -> list[SetupResponse]:
    setups = await forward_service.list_setups(db, user.id, include_archived=include_archived)
    return [_to_response(setup) for setup in setups]


@setups_router.get("/overview", response_model=SetupsOverview)
async def setups_overview(user: CurrentUser, db: DbDep) -> SetupsOverview:
    """The pipeline table plus the risks that only appear across Setups."""
    setups = await forward_service.list_setups(db, user.id)
    return SetupsOverview(
        setups=[_to_response(setup) for setup in setups],
        total_exposure=forward_service.total_exposure(setups),
        conflicts=[
            ConflictWarning(**conflict) for conflict in forward_service.find_conflicts(setups)
        ],
    )


@setups_router.post("", response_model=SetupResponse, status_code=status.HTTP_201_CREATED)
async def create_setup(payload: SetupPayload, user: CurrentUser, db: DbDep) -> SetupResponse:
    """Lock a strategy version into a Setup."""
    record = await _owned_strategy(db, user, payload.strategy_id)

    existing = await forward_service.list_setups(db, user.id, include_archived=True)
    if any(setup.name == payload.name for setup in existing):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A setup called {payload.name!r} already exists.",
        )

    setup = await forward_service.create_setup(
        db, user_id=user.id, record=record, payload=payload.model_dump()
    )
    await db.commit()
    await db.refresh(setup)
    return _to_response(setup)


@setups_router.get("/{setup_id}", response_model=SetupResponse)
async def get_setup(setup_id: uuid.UUID, user: CurrentUser, db: DbDep) -> SetupResponse:
    return _to_response(await _owned_setup(db, user, setup_id))


@setups_router.post("/{setup_id}/stage", response_model=SetupResponse)
async def advance_stage(
    setup_id: uuid.UUID, payload: StageUpdate, user: CurrentUser, db: DbDep
) -> SetupResponse:
    """Record pipeline progress.

    Marking paper as passed is what unlocks the bot stage; the client
    cannot set that flag directly.
    """
    setup = await _owned_setup(db, user, setup_id)
    try:
        forward_service.advance_stage(setup, payload.stage, payload.status, payload.note)
    except BacktestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    await db.commit()
    await db.refresh(setup)
    return _to_response(setup)


@setups_router.delete("/{setup_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_setup(
    setup_id: uuid.UUID, user: CurrentUser, db: DbDep, response: Response
) -> Response:
    """Archive rather than delete: a Setup is the provenance of past runs."""
    from datetime import UTC, datetime

    setup = await _owned_setup(db, user, setup_id)
    setup.archived_at = datetime.now(UTC)
    setup.use_in_bot = False
    setup.use_in_alerts = False
    await db.commit()

    response.status_code = status.HTTP_204_NO_CONTENT
    return response
