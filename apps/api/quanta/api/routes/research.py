"""Research studies and the Discover search (SPEC §3.2)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status

from quanta.api.deps import CurrentUser, DbDep
from quanta.models.strategy import StrategyRecord
from quanta.schemas.research import (
    DiscoverPlanRequest,
    DiscoverRequest,
    JobResponse,
    JobResultResponse,
    LeverageRequest,
    RobustnessRequest,
    SourceInfo,
    StudyRequest,
)
from quanta.services import discover_service, research_service
from quanta.services.backtest_service import BacktestError
from quanta.services.jobs import JobState, registry

router = APIRouter(prefix="/research", tags=["research"])
jobs_router = APIRouter(prefix="/jobs", tags=["jobs"])


async def _owned(db: DbDep, user: CurrentUser, strategy_id: uuid.UUID) -> StrategyRecord:
    record = await db.get(StrategyRecord, strategy_id)
    if record is None or record.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such strategy.")
    return record


def _fail(exc: BacktestError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


@router.get("/sources", response_model=list[SourceInfo])
async def list_sources(_user: CurrentUser) -> list[SourceInfo]:
    """The indicator chips a Discover search can be built from."""
    return [
        SourceInfo(
            key=key,
            label=str(entry["label"]),
            lines=[line[1] for line in entry["lines"]],
        )
        for key, entry in discover_service.SOURCE_LIBRARY.items()
    ]


@router.post("/{strategy_id}/leverage")
async def leverage(
    strategy_id: uuid.UUID, payload: LeverageRequest, user: CurrentUser, db: DbDep
) -> dict:
    """The margin x leverage surface, with a recommendation."""
    record = await _owned(db, user, strategy_id)
    try:
        return await research_service.leverage_study(
            db,
            record=record,
            symbol=payload.symbol.upper(),
            interval=payload.interval,
            start=payload.start,
            end=payload.end,
            margins=payload.margins,
            leverages=payload.leverages,
            budget_percent=payload.budget_percent,
            config_payload=payload.config.model_dump(),
        )
    except BacktestError as exc:
        raise _fail(exc) from exc


@router.post("/{strategy_id}/trade-risk")
async def trade_risk(
    strategy_id: uuid.UUID, payload: StudyRequest, user: CurrentUser, db: DbDep
) -> dict:
    """MAE scatter and the dip KPIs."""
    record = await _owned(db, user, strategy_id)
    try:
        return await research_service.trade_risk_study(
            db,
            record=record,
            symbol=payload.symbol.upper(),
            interval=payload.interval,
            start=payload.start,
            end=payload.end,
            config_payload=payload.config.model_dump(),
        )
    except BacktestError as exc:
        raise _fail(exc) from exc


@router.post("/{strategy_id}/robustness")
async def robustness(
    strategy_id: uuid.UUID, payload: RobustnessRequest, user: CurrentUser, db: DbDep
) -> dict:
    """Stress cases, reshuffled years, tail risk and the parameter surface."""
    record = await _owned(db, user, strategy_id)
    try:
        return await research_service.robustness_study(
            db,
            record=record,
            symbol=payload.symbol.upper(),
            interval=payload.interval,
            start=payload.start,
            end=payload.end,
            grid=payload.grid,
            config_payload=payload.config.model_dump(),
        )
    except BacktestError as exc:
        raise _fail(exc) from exc


@router.post("/discover/plan")
async def discover_plan(payload: DiscoverPlanRequest, _user: CurrentUser, db: DbDep) -> dict:
    """What a search would cost, before it is started.

    A number like 558,624 tests is the difference between a considered
    click and a surprise, so it is offered before the button.
    """
    try:
        close = await discover_service.load_close(
            db, payload.symbol.upper(), payload.interval, payload.start, payload.end
        )
        return discover_service.plan(payload.sources, close, mix_indicators=payload.mix_indicators)
    except BacktestError as exc:
        raise _fail(exc) from exc


@router.post("/discover", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
async def discover(payload: DiscoverRequest, user: CurrentUser, db: DbDep) -> JobResponse:
    """Start a search. Returns a job to poll, not a result.

    The reference case runs half a million tests in about half a minute.
    Holding a request open for that loses to the first proxy timeout and
    tells the user nothing while it waits.
    """
    try:
        close = await discover_service.load_close(
            db, payload.symbol.upper(), payload.interval, payload.start, payload.end
        )
        planned = discover_service.plan(
            payload.sources, close, mix_indicators=payload.mix_indicators
        )
    except BacktestError as exc:
        raise _fail(exc) from exc

    job = registry.start(
        user_id=user.id,
        kind="discover",
        label=f"Discover · {payload.symbol.upper()} {payload.interval}",
        total=planned["rules"],
        work=discover_service.search_work(
            source_keys=payload.sources,
            close=close,
            cost_percent=payload.cost_percent,
            mix_indicators=payload.mix_indicators,
            max_hits=payload.max_hits,
        ),
    )
    return JobResponse(**job.to_dict())


@jobs_router.get("", response_model=list[JobResponse])
async def list_jobs(user: CurrentUser) -> list[JobResponse]:
    return [JobResponse(**job.to_dict()) for job in registry.list_for(user.id)]


@jobs_router.get("/{job_id}", response_model=JobResultResponse)
async def get_job(job_id: str, user: CurrentUser) -> JobResultResponse:
    job = registry.get(job_id, user.id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such job.")
    # The result rides along only once it exists, so a poll while running
    # stays small however large the finished search is.
    return JobResultResponse(
        **job.to_dict(), result=job.result if job.state is JobState.DONE else None
    )


@jobs_router.delete("/{job_id}", status_code=status.HTTP_202_ACCEPTED)
async def cancel_job(job_id: str, user: CurrentUser) -> dict:
    if registry.get(job_id, user.id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such job.")
    stopped = registry.cancel(job_id, user.id)
    return {"cancelled": stopped}
