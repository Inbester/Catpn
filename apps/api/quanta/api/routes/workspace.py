"""Autosave sync and the History tab."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException, Query, Response, status

from quanta.api.deps import CurrentUser, DbDep
from quanta.models.workspace import WorkspaceDocument
from quanta.schemas.workspace import (
    MAX_DOCUMENT_BYTES,
    DocumentConflictResponse,
    DocumentPushRequest,
    DocumentResponse,
    RevisionLabelRequest,
    RevisionResponse,
)
from quanta.services import workspace_service
from quanta.services.workspace_service import DocumentConflictError

router = APIRouter(prefix="/workspace", tags=["workspace"])


@router.get("/documents", response_model=list[DocumentResponse])
async def list_documents(
    user: CurrentUser,
    db: DbDep,
    kind: str | None = Query(default=None, max_length=32),
) -> list[DocumentResponse]:
    documents = await workspace_service.list_documents(db, user.id, kind)
    return [DocumentResponse.model_validate(d) for d in documents]


@router.get("/document", response_model=DocumentResponse)
async def get_document(
    user: CurrentUser,
    db: DbDep,
    kind: str = Query(max_length=32),
    scope_key: str = Query(default="default", max_length=160),
) -> DocumentResponse:
    """Fetch one document by its (kind, scope_key) address.

    A query string rather than a path so that a scope_key containing slashes
    — ``BTCUSDT:15m`` today, but nothing stops a future one — cannot collide
    with the ``/documents/{document_id}/...`` routes below.
    """
    document = await workspace_service.get_document(db, user.id, kind, scope_key)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such document.")
    return DocumentResponse.model_validate(document)


@router.put(
    "/documents",
    response_model=DocumentResponse,
    responses={409: {"model": DocumentConflictResponse}},
)
async def push_document(
    payload: DocumentPushRequest, user: CurrentUser, db: DbDep
) -> DocumentResponse:
    """Autosave one document.

    Returns 409 with the server's current copy when another device got there
    first; the client then shows the conflict rather than overwriting.
    """
    encoded = len(json.dumps(payload.data).encode("utf-8"))
    if encoded > MAX_DOCUMENT_BYTES:
        raise HTTPException(
            status_code=413,  # Content Too Large
            detail=f"Document is {encoded} bytes; the limit is {MAX_DOCUMENT_BYTES}.",
        )

    try:
        document = await workspace_service.save_document(
            db,
            user.id,
            payload.kind,
            payload.scope_key,
            payload.data,
            payload.base_revision,
            device_label=payload.device_label,
            label=payload.label,
            summary=payload.summary,
        )
    except DocumentConflictError as exc:
        # exc.snapshot was taken while the object was still live.
        snapshot = exc.snapshot
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "detail": DocumentConflictResponse.model_fields["detail"].default,
                "current": snapshot,
            },
        ) from exc

    await db.commit()
    await db.refresh(document)
    return DocumentResponse.model_validate(document)


@router.get("/documents/{document_id}/revisions", response_model=list[RevisionResponse])
async def list_revisions(
    document_id: uuid.UUID,
    user: CurrentUser,
    db: DbDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[RevisionResponse]:
    """History for one document."""
    document = await db.get(WorkspaceDocument, document_id)
    if document is None or document.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such document.")

    revisions = await workspace_service.list_revisions(db, document_id, limit)
    return [RevisionResponse.model_validate(r) for r in revisions]


@router.post(
    "/documents/{document_id}/revisions/{revision_id}/restore",
    response_model=DocumentResponse,
)
async def restore_revision(
    document_id: uuid.UUID, revision_id: uuid.UUID, user: CurrentUser, db: DbDep
) -> DocumentResponse:
    """Restore a revision, recorded as a new revision on top.

    Returns the document's new current state, so the client can swap its
    local copy without a second round trip.
    """
    document = await db.get(WorkspaceDocument, document_id)
    if document is None or document.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such document.")

    revision = await workspace_service.get_revision(db, document_id, revision_id)
    if revision is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such revision.")

    await workspace_service.restore_revision(db, document, revision)
    await db.commit()
    await db.refresh(document)
    return DocumentResponse.model_validate(document)


@router.patch("/documents/{document_id}/revisions/{revision_id}", response_model=RevisionResponse)
async def label_revision(
    document_id: uuid.UUID,
    revision_id: uuid.UUID,
    payload: RevisionLabelRequest,
    user: CurrentUser,
    db: DbDep,
) -> RevisionResponse:
    """Name a revision so it survives the 90-day prune (or clear the name)."""
    document = await db.get(WorkspaceDocument, document_id)
    if document is None or document.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such document.")

    revision = await workspace_service.get_revision(db, document_id, revision_id)
    if revision is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such revision.")

    revision.label = payload.label
    await db.commit()
    await db.refresh(revision)
    return RevisionResponse.model_validate(revision)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID, user: CurrentUser, db: DbDep, response: Response
) -> Response:
    document = await db.get(WorkspaceDocument, document_id)
    if document is None or document.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such document.")

    await db.delete(document)
    await db.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
