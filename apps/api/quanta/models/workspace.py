"""Autosaved workspace state and its version history.

SPEC §2 / DECISIONS: everything the user touches is autosaved — drawings per
symbol and timeframe, indicators, panes, layouts, settings, UI state. Storage
is local-first (IndexedDB in the browser) and synced here. The History tab
reads :class:`WorkspaceRevision`: 90 days of automatic revisions, named ones
kept forever.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from quanta.db.base import Base, Timestamped, UUIDPrimaryKey

if TYPE_CHECKING:
    from quanta.models.user import User

# Document kinds the History tab can filter by.
DOCUMENT_KINDS = ("chart", "strategy", "research", "settings", "layout", "ui")


class WorkspaceDocument(UUIDPrimaryKey, Timestamped, Base):
    """The current state of one autosaved document.

    ``scope_key`` namespaces a document inside its kind — for chart drawings
    that is ``"BTCUSDT:15m"``, for settings it is just ``"default"``.
    """

    __tablename__ = "workspace_documents"
    __table_args__ = (
        UniqueConstraint("user_id", "kind", "scope_key", name="uq_workspace_document_scope"),
        Index("ix_workspace_documents_user_kind", "user_id", "kind"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(160), nullable=False, default="default")

    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # Monotonic per document. The client sends the revision it based its edit
    # on; a mismatch is reported as a conflict instead of silently overwriting.
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    # Which device wrote the current revision, for the History tab.
    device_label: Mapped[str | None] = mapped_column(String(120), nullable=True)

    user: Mapped[User] = relationship(back_populates="documents")
    revisions: Mapped[list[WorkspaceRevision]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        lazy="raise",
        order_by="WorkspaceRevision.revision.desc()",
    )


class WorkspaceRevision(UUIDPrimaryKey, Base):
    """One historical version of a document."""

    __tablename__ = "workspace_revisions"
    __table_args__ = (
        UniqueConstraint("document_id", "revision", name="uq_workspace_revision_number"),
        Index("ix_workspace_revisions_document_created", "document_id", "created_at"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("workspace_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # A named revision is kept forever; unnamed ones are pruned after 90 days.
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    device_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    document: Mapped[WorkspaceDocument] = relationship(back_populates="revisions")

    @property
    def is_named(self) -> bool:
        return bool(self.label)
