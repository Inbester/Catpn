"""Background jobs with progress (SPEC §3.2 and D8).

A Discover search over the reference case runs half a million tests and
takes about half a minute. That is too long for a request to hold open:
the browser gives up, a proxy gives up, and the user has no idea whether
anything is happening. So the search becomes a job — started, polled,
cancellable — and the rail's Jobs ring reads its progress.

The registry runs the work; the ``jobs`` table remembers it. A restart
loses the running computation — it is pure CPU over data still in the
database, so nothing is destroyed — but losing the record would mean
someone who watched a half-hour search comes back to an empty list unable
to tell whether it ever ran. Jobs left running by a restart are marked
interrupted on the next boot and can be started again from their stored
request.

The work runs in a thread, because the engine is NumPy over the GIL and
would otherwise block the event loop for the whole search — every other
request on the worker, including the poll asking how this one is going.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from quanta.db.session import get_session_factory
from quanta.models.job import JobRecord

logger = structlog.get_logger(__name__)

# Finished jobs are kept so a result can be collected after the fact, but
# not forever: a long session would otherwise accumulate every search it
# ever ran.
MAX_FINISHED_PER_USER = 20


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Job:
    id: str
    user_id: uuid.UUID
    kind: str
    label: str
    state: JobState = JobState.QUEUED
    done: int = 0
    total: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    result: Any = None
    error: str | None = None
    _cancel: bool = False

    @property
    def percent(self) -> float:
        if self.total <= 0:
            return 0.0
        return min(100.0, self.done / self.total * 100.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "state": self.state.value,
            "done": self.done,
            "total": self.total,
            "percent": self.percent,
            "created_at": self.created_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "error": self.error,
        }


class JobCancelledError(Exception):
    """Raised inside the worker when the user stopped the job."""


class JobRegistry:
    """Every job this process is running, by user."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def get(self, job_id: str, user_id: uuid.UUID) -> Job | None:
        job = self._jobs.get(job_id)
        return job if job is not None and job.user_id == user_id else None

    def list_for(self, user_id: uuid.UUID) -> list[Job]:
        jobs = [job for job in self._jobs.values() if job.user_id == user_id]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)

    def cancel(self, job_id: str, user_id: uuid.UUID) -> bool:
        job = self.get(job_id, user_id)
        if job is None or job.state in {JobState.DONE, JobState.FAILED, JobState.CANCELLED}:
            return False
        # The flag is checked by the worker between chunks rather than the
        # task being killed: stopping mid-write would leave the result half
        # built, and there is nothing to gain from being abrupt.
        job._cancel = True
        return True

    def start(
        self,
        *,
        user_id: uuid.UUID,
        kind: str,
        label: str,
        total: int,
        work: Callable[[Job], Any],
        on_finish: Callable[[AsyncSession, Job], Any] | None = None,
    ) -> Job:
        job = Job(id=str(uuid.uuid4()), user_id=user_id, kind=kind, label=label, total=total)
        self._jobs[job.id] = job
        self._trim(user_id)

        async def run() -> None:
            job.state = JobState.RUNNING
            try:
                # to_thread, not the event loop: the engine holds the GIL
                # through long NumPy calls and would starve every other
                # request on this worker, including the progress poll.
                job.result = await asyncio.to_thread(work, job)
                job.state = JobState.DONE
            except JobCancelledError:
                job.state = JobState.CANCELLED
            except Exception as exc:  # a failed search must not kill the worker
                job.state = JobState.FAILED
                job.error = str(exc)
                logger.warning("job_failed", job=job.id, kind=kind, error=str(exc))
            finally:
                job.finished_at = datetime.now(UTC)
                if on_finish is not None:
                    # Its own session: the request that started the job is
                    # long gone by the time a half-hour search ends.
                    try:
                        async with get_session_factory()() as db:
                            await on_finish(db, job)
                    except Exception as exc:  # recording must not mask the run
                        logger.warning("job_record_failed", job=job.id, error=str(exc))

        self._tasks[job.id] = asyncio.create_task(run())
        return job

    def _trim(self, user_id: uuid.UUID) -> None:
        finished = [
            job
            for job in self.list_for(user_id)
            if job.state in {JobState.DONE, JobState.FAILED, JobState.CANCELLED}
        ]
        for job in finished[MAX_FINISHED_PER_USER:]:
            self._jobs.pop(job.id, None)
            self._tasks.pop(job.id, None)


registry = JobRegistry()


async def record_start(
    db: AsyncSession, job: Job, *, request: dict[str, Any], source: str = "server"
) -> None:
    """Write the row that outlives the process."""
    db.add(
        JobRecord(
            id=uuid.UUID(job.id),
            user_id=job.user_id,
            kind=job.kind,
            label=job.label,
            state=job.state.value,
            source=source,
            total=job.total,
            request=request,
            checkpoint={},
        )
    )
    await db.commit()


async def record_finish(db: AsyncSession, job: Job) -> None:
    """Update the row once the work stops, whatever the outcome."""
    record = await db.get(JobRecord, uuid.UUID(job.id))
    if record is None:
        return
    record.state = job.state.value
    record.done = job.done
    record.total = job.total
    record.error = job.error
    record.finished_at = job.finished_at
    # Only a coarse checkpoint: see the module note on why a resume
    # re-runs rather than continuing mid-stream.
    record.checkpoint = {"done": job.done, "total": job.total}
    if job.state is JobState.DONE and isinstance(job.result, dict):
        record.result = job.result
    await db.commit()


async def mark_interrupted(db: AsyncSession) -> int:
    """On boot, close out jobs a previous process left running.

    Without this a restart leaves rows claiming to be running forever, and
    the rail would count progress that nothing is making.
    """
    stale = await db.execute(select(JobRecord).where(JobRecord.state.in_(["queued", "running"])))
    rows = list(stale.scalars().all())
    for row in rows:
        row.state = "interrupted"
        row.finished_at = datetime.now(UTC)
    await db.commit()
    return len(rows)


async def history(db: AsyncSession, user_id: uuid.UUID, limit: int = 50) -> list[JobRecord]:
    result = await db.execute(
        select(JobRecord)
        .where(JobRecord.user_id == user_id)
        .order_by(JobRecord.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


def progress_reporter(job: Job) -> Callable[[int, int], None]:
    """A callback the engine can call, which also honours cancellation."""

    def report(done: int, total: int) -> None:
        if job._cancel:
            raise JobCancelledError
        job.done = done
        job.total = total

    return report
