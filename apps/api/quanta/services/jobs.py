"""Background jobs with progress (SPEC §3.2 and D8).

A Discover search over the reference case runs half a million tests and
takes about half a minute. That is too long for a request to hold open:
the browser gives up, a proxy gives up, and the user has no idea whether
anything is happening. So the search becomes a job — started, polled,
cancellable — and the rail's Jobs ring reads its progress.

Jobs live in the process, not the database. That is the honest scope for
now: a restart loses running work, which is correct behaviour for a
computation that can simply be re-run, and pretending otherwise would mean
writing checkpoints nothing yet reads.

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


def progress_reporter(job: Job) -> Callable[[int, int], None]:
    """A callback the engine can call, which also honours cancellation."""

    def report(done: int, total: int) -> None:
        if job._cancel:
            raise JobCancelledError
        job.done = done
        job.total = total

    return report
