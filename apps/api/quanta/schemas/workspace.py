"""Request and response bodies for the autosave / workspace routes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from quanta.models.workspace import DOCUMENT_KINDS

# A single autosaved document is UI state, not a dataset. Anything larger is
# a bug on the client side, and the cap keeps one tab from filling the table.
MAX_DOCUMENT_BYTES = 1_000_000


class DocumentPushRequest(BaseModel):
    """Client → server autosave."""

    kind: str = Field(max_length=32)
    scope_key: str = Field(default="default", max_length=160)
    data: dict[str, Any]
    # The revision the client based this edit on. ``0`` means "new document".
    base_revision: int = Field(default=0, ge=0)
    device_label: str | None = Field(default=None, max_length=120)
    label: str | None = Field(default=None, max_length=120)
    summary: str | None = Field(default=None, max_length=500)

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, value: str) -> str:
        if value not in DOCUMENT_KINDS:
            raise ValueError(f"kind must be one of {', '.join(DOCUMENT_KINDS)}")
        return value


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    scope_key: str
    data: dict[str, Any]
    revision: int
    device_label: str | None
    updated_at: datetime


class DocumentConflictResponse(BaseModel):
    """Returned with 409 when two devices edited the same document.

    ``current`` is ``None`` when the client tried to update a document that no
    longer exists on the server at all.
    """

    detail: str = "Document changed on the server since this edit started."
    current: DocumentResponse | None = None


class RevisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    revision: int
    label: str | None
    summary: str | None
    device_label: str | None
    created_at: datetime


class RevisionDetailResponse(RevisionResponse):
    data: dict[str, Any]


class RevisionLabelRequest(BaseModel):
    """Naming a revision keeps it past the 90-day prune."""

    label: str | None = Field(default=None, max_length=120)
