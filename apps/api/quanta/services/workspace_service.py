"""Autosave document storage with optimistic concurrency and history."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from quanta.models.workspace import WorkspaceDocument, WorkspaceRevision

# Unnamed revisions are pruned after this long; named ones are kept forever.
REVISION_RETENTION_DAYS = 90
# Hard ceiling on unnamed revisions per document, so a chatty client cannot
# grow one document's history without bound inside the retention window.
MAX_UNNAMED_REVISIONS = 200


def document_snapshot(document: WorkspaceDocument) -> dict[str, Any]:
    """A JSON-safe copy of a document, detached from the session."""
    return {
        "id": str(document.id),
        "kind": document.kind,
        "scope_key": document.scope_key,
        "data": document.data,
        "revision": document.revision,
        "device_label": document.device_label,
        "updated_at": document.updated_at.isoformat() if document.updated_at else None,
    }


class DocumentConflictError(Exception):
    """Raised when the client's ``base_revision`` is stale.

    The server's current state is captured as a plain dict up front: the route
    rolls the transaction back before answering, which would expire a live ORM
    object and make reading its columns raise.
    """

    def __init__(self, current: WorkspaceDocument | None) -> None:
        super().__init__("Document changed on the server.")
        self.snapshot: dict[str, Any] | None = (
            document_snapshot(current) if current is not None else None
        )


async def get_document(
    db: AsyncSession, user_id: uuid.UUID, kind: str, scope_key: str
) -> WorkspaceDocument | None:
    result = await db.execute(
        select(WorkspaceDocument).where(
            WorkspaceDocument.user_id == user_id,
            WorkspaceDocument.kind == kind,
            WorkspaceDocument.scope_key == scope_key,
        )
    )
    return result.scalar_one_or_none()


async def list_documents(
    db: AsyncSession, user_id: uuid.UUID, kind: str | None = None
) -> list[WorkspaceDocument]:
    stmt = select(WorkspaceDocument).where(WorkspaceDocument.user_id == user_id)
    if kind:
        stmt = stmt.where(WorkspaceDocument.kind == kind)
    result = await db.execute(stmt.order_by(WorkspaceDocument.updated_at.desc()))
    return list(result.scalars().all())


async def save_document(
    db: AsyncSession,
    user_id: uuid.UUID,
    kind: str,
    scope_key: str,
    data: dict,
    base_revision: int,
    *,
    device_label: str | None = None,
    label: str | None = None,
    summary: str | None = None,
) -> WorkspaceDocument:
    """Create or update a document, snapshotting the previous state.

    ``base_revision`` is the revision the client edited. If the stored
    document has moved on, :class:`DocumentConflictError` is raised so the UI can
    offer the History tab instead of silently losing one device's work.
    """
    document = await get_document(db, user_id, kind, scope_key)

    if document is None:
        if base_revision not in (0, 1):
            # The client thinks it is updating something that is not here.
            raise DocumentConflictError(None)
        document = WorkspaceDocument(
            user_id=user_id,
            kind=kind,
            scope_key=scope_key,
            data=data,
            revision=1,
            device_label=device_label,
        )
        db.add(document)
        await db.flush()
        await _snapshot(db, document, label=label, summary=summary)
        return document

    if base_revision != document.revision:
        raise DocumentConflictError(document)

    document.data = data
    document.revision += 1
    document.device_label = device_label
    await db.flush()
    await _snapshot(db, document, label=label, summary=summary)
    await _prune(db, document.id)
    return document


async def _snapshot(
    db: AsyncSession,
    document: WorkspaceDocument,
    *,
    label: str | None,
    summary: str | None,
) -> None:
    db.add(
        WorkspaceRevision(
            document_id=document.id,
            revision=document.revision,
            data=document.data,
            label=label,
            summary=summary,
            device_label=document.device_label,
            created_at=datetime.now(UTC),
        )
    )


async def _prune(db: AsyncSession, document_id: uuid.UUID) -> None:
    """Drop unnamed revisions past the retention window or the count cap."""
    cutoff = datetime.now(UTC) - timedelta(days=REVISION_RETENTION_DAYS)
    await db.execute(
        delete(WorkspaceRevision).where(
            WorkspaceRevision.document_id == document_id,
            WorkspaceRevision.label.is_(None),
            WorkspaceRevision.created_at < cutoff,
        )
    )

    keep = await db.execute(
        select(WorkspaceRevision.id)
        .where(
            WorkspaceRevision.document_id == document_id,
            WorkspaceRevision.label.is_(None),
        )
        .order_by(WorkspaceRevision.revision.desc())
        .limit(MAX_UNNAMED_REVISIONS)
    )
    keep_ids = list(keep.scalars().all())
    if len(keep_ids) == MAX_UNNAMED_REVISIONS:
        await db.execute(
            delete(WorkspaceRevision).where(
                WorkspaceRevision.document_id == document_id,
                WorkspaceRevision.label.is_(None),
                WorkspaceRevision.id.notin_(keep_ids),
            )
        )


async def list_revisions(
    db: AsyncSession, document_id: uuid.UUID, limit: int = 50
) -> list[WorkspaceRevision]:
    result = await db.execute(
        select(WorkspaceRevision)
        .where(WorkspaceRevision.document_id == document_id)
        .order_by(WorkspaceRevision.revision.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_revision(
    db: AsyncSession, document_id: uuid.UUID, revision_id: uuid.UUID
) -> WorkspaceRevision | None:
    result = await db.execute(
        select(WorkspaceRevision).where(
            WorkspaceRevision.id == revision_id,
            WorkspaceRevision.document_id == document_id,
        )
    )
    return result.scalar_one_or_none()


async def restore_revision(
    db: AsyncSession, document: WorkspaceDocument, revision: WorkspaceRevision
) -> WorkspaceDocument:
    """Restore old content as a *new* revision, so the undo itself is undoable."""
    document.data = revision.data
    document.revision += 1
    await db.flush()
    await _snapshot(
        db,
        document,
        label=None,
        summary=f"Restored revision {revision.revision}",
    )
    return document
