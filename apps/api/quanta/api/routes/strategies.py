"""Strategy CRUD, validation and backtest routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, Response, status
from quanta_engine.dsl.errors import DslError
from quanta_engine.dsl.evaluator import describe_functions
from quanta_engine.strategy import ExitRules, Strategy
from sqlalchemy import select

from quanta.api.deps import CurrentUser, DbDep
from quanta.models.strategy import BacktestRun, StrategyRecord
from quanta.schemas.strategy import (
    BacktestRequest,
    BacktestResponse,
    BacktestSummary,
    FunctionReference,
    StrategyPayload,
    StrategyResponse,
    ValidationResponse,
)
from quanta.services import backtest_service
from quanta.services.backtest_service import BacktestError

router = APIRouter(prefix="/strategies", tags=["strategies"])


def _to_engine(payload: StrategyPayload) -> Strategy:
    """Build an engine strategy, surfacing DSL errors as 422."""
    try:
        strategy = Strategy(
            name=payload.name,
            long_entry=payload.long_entry or None,
            short_entry=payload.short_entry or None,
            exits=ExitRules(**payload.exits.model_dump()),
            params=dict(payload.params),
        )
        strategy.validate()
    except DslError as exc:
        raise HTTPException(
            status_code=422,  # Unprocessable Content
            detail=str(exc),
        ) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=422,  # Unprocessable Content
            detail=str(exc),
        ) from exc
    return strategy


async def _owned(db: DbDep, user: CurrentUser, strategy_id: uuid.UUID) -> StrategyRecord:
    record = await db.get(StrategyRecord, strategy_id)
    if record is None or record.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such strategy.")
    return record


@router.get("/functions", response_model=list[FunctionReference])
async def functions(_user: CurrentUser) -> list[FunctionReference]:
    """The whitelisted function reference the Formula view shows."""
    return [FunctionReference(**entry) for entry in describe_functions()]


@router.post("/validate", response_model=ValidationResponse)
async def validate(payload: StrategyPayload, _user: CurrentUser) -> ValidationResponse:
    """Check an expression without saving it.

    Returns the error and its character position rather than a 4xx, so the
    editor can underline the problem while the user is still typing.
    """
    try:
        strategy = Strategy(
            name=payload.name,
            long_entry=payload.long_entry or None,
            short_entry=payload.short_entry or None,
            exits=ExitRules(**payload.exits.model_dump()),
            params=dict(payload.params),
        )
        strategy.validate()
    except DslError as exc:
        return ValidationResponse(valid=False, error=exc.message, position=exc.position)
    except (ValueError, TypeError) as exc:
        return ValidationResponse(valid=False, error=str(exc))

    long_node = strategy.compiled_long()
    short_node = strategy.compiled_short()
    return ValidationResponse(
        valid=True,
        version=strategy.version_hash(),
        normalized_long=str(long_node) if long_node else None,
        normalized_short=str(short_node) if short_node else None,
    )


@router.get("", response_model=list[StrategyResponse])
async def list_strategies(user: CurrentUser, db: DbDep) -> list[StrategyResponse]:
    result = await db.execute(
        select(StrategyRecord)
        .where(StrategyRecord.user_id == user.id)
        .order_by(StrategyRecord.updated_at.desc())
    )
    return [StrategyResponse.model_validate(row) for row in result.scalars().all()]


@router.post("", response_model=StrategyResponse, status_code=status.HTTP_201_CREATED)
async def create_strategy(
    payload: StrategyPayload, user: CurrentUser, db: DbDep
) -> StrategyResponse:
    strategy = _to_engine(payload)

    record = StrategyRecord(
        user_id=user.id,
        name=payload.name,
        description=payload.description,
        long_entry=payload.long_entry or None,
        short_entry=payload.short_entry or None,
        exits=payload.exits.model_dump(),
        params=dict(payload.params),
        version=strategy.version_hash(),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return StrategyResponse.model_validate(record)


@router.get("/{strategy_id}", response_model=StrategyResponse)
async def get_strategy(strategy_id: uuid.UUID, user: CurrentUser, db: DbDep) -> StrategyResponse:
    return StrategyResponse.model_validate(await _owned(db, user, strategy_id))


@router.put("/{strategy_id}", response_model=StrategyResponse)
async def update_strategy(
    strategy_id: uuid.UUID, payload: StrategyPayload, user: CurrentUser, db: DbDep
) -> StrategyResponse:
    record = await _owned(db, user, strategy_id)
    strategy = _to_engine(payload)

    record.name = payload.name
    record.description = payload.description
    record.long_entry = payload.long_entry or None
    record.short_entry = payload.short_entry or None
    record.exits = payload.exits.model_dump()
    record.params = dict(payload.params)
    # Recomputed from the parsed tree, so reformatting leaves it alone.
    record.version = strategy.version_hash()

    await db.commit()
    await db.refresh(record)
    return StrategyResponse.model_validate(record)


@router.delete("/{strategy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_strategy(
    strategy_id: uuid.UUID, user: CurrentUser, db: DbDep, response: Response
) -> Response:
    record = await _owned(db, user, strategy_id)
    await db.delete(record)
    await db.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


# --- backtests ----------------------------------------------------------


@router.post("/{strategy_id}/backtest", response_model=BacktestResponse)
async def run_backtest_route(
    strategy_id: uuid.UUID,
    payload: BacktestRequest,
    user: CurrentUser,
    db: DbDep,
) -> BacktestResponse:
    """Run the strategy over stored bars and save the result."""
    record = await _owned(db, user, strategy_id)

    try:
        run_row = await backtest_service.run(
            db,
            user_id=user.id,
            record=record,
            symbol=payload.symbol.upper(),
            interval=payload.interval,
            start=payload.start,
            end=payload.end,
            config_payload=payload.config.model_dump(),
        )
    except BacktestError as exc:
        raise HTTPException(
            status_code=422,  # Unprocessable Content
            detail=str(exc),
        ) from exc

    await db.commit()
    await db.refresh(run_row)
    return BacktestResponse.model_validate(run_row)


@router.get("/{strategy_id}/backtests", response_model=list[BacktestSummary])
async def list_backtests(
    strategy_id: uuid.UUID,
    user: CurrentUser,
    db: DbDep,
    limit: int = Query(default=25, ge=1, le=200),
) -> list[BacktestSummary]:
    await _owned(db, user, strategy_id)
    runs = await backtest_service.list_runs(db, user.id, strategy_id=strategy_id, limit=limit)
    return [BacktestSummary.model_validate(row) for row in runs]


backtests_router = APIRouter(prefix="/backtests", tags=["backtests"])


@backtests_router.get("/{run_id}", response_model=BacktestResponse)
async def get_backtest(run_id: uuid.UUID, user: CurrentUser, db: DbDep) -> BacktestResponse:
    run_row = await db.get(BacktestRun, run_id)
    if run_row is None or run_row.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such run.")
    return BacktestResponse.model_validate(run_row)


@backtests_router.get("/{run_id}/trades.csv")
async def export_trades(run_id: uuid.UUID, user: CurrentUser, db: DbDep) -> Response:
    """The list of trades as CSV (SPEC §3.3)."""
    run_row = await db.get(BacktestRun, run_id)
    if run_row is None or run_row.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such run.")

    csv_text = backtest_service.trades_to_csv(run_row.trades)
    filename = f"quanta-{run_row.symbol}-{run_row.interval}-{run_row.strategy_version[:8]}.csv"
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
