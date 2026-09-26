"""Jobs that outlive the process that started them (SPEC D8).

The in-process registry is what runs work; this is what remembers it. A
restart loses the running computation — it is pure CPU over data still in
the database, so nothing is destroyed — but losing the *record* would mean
a user watching a half-hour search comes back to an empty list with no way
to tell whether it ever ran.

A resumed job re-runs from its checkpoint rather than continuing
mid-stream. A Discover search's correction needs every test's p-value
before it can decide anything, and keeping half a million of them per
paused job on disk costs more than recomputing them does.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from quanta.db.base import Base, Timestamped, UUIDPrimaryKey

JOB_STATES = ("queued", "running", "done", "failed", "cancelled", "interrupted")


class JobRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_user_created", "user_id", "created_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="server")

    done: Mapped[int] = mapped_column(default=0, nullable=False)
    total: Mapped[int] = mapped_column(default=0, nullable=False)

    # Everything needed to start the job again.
    request: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # Where a resume would pick up. Coarse on purpose; see the module note.
    checkpoint: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
