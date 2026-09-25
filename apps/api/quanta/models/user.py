"""User accounts and their authentication material."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, INET
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from quanta.db.base import Base, Timestamped, UUIDPrimaryKey

if TYPE_CHECKING:
    from quanta.models.workspace import WorkspaceDocument


class User(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # --- 2FA -------------------------------------------------------------
    # The secret is stored only once TOTP is confirmed; `totp_pending_secret`
    # holds the not-yet-verified one during enrolment.
    totp_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    totp_pending_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Recovery codes are stored hashed and removed as they are used.
    recovery_code_hashes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, nullable=False
    )
    # Guards against a replayed TOTP code inside the same 30s step.
    last_totp_counter: Mapped[int | None] = mapped_column(nullable=True)

    # --- Preferences ------------------------------------------------------
    theme: Mapped[str] = mapped_column(String(16), default="graphite", nullable=False)
    locale: Mapped[str] = mapped_column(String(8), default="en", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Tehran", nullable=False)
    calendar: Mapped[str] = mapped_column(String(16), default="gregorian", nullable=False)

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    auth_sessions: Mapped[list[AuthSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    documents: Mapped[list[WorkspaceDocument]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="raise"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User {self.email}>"


class AuthSession(UUIDPrimaryKey, Timestamped, Base):
    """One refresh token = one session = one device.

    The token itself is never stored, only its SHA-256 hash. Rotation replaces
    the row's hash, so a replayed old token finds no match and is rejected.
    """

    __tablename__ = "auth_sessions"
    __table_args__ = (Index("ix_auth_sessions_user_active", "user_id", "revoked_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    # The hash this session held immediately before the last rotation. Two
    # tabs (or React's double-mount in development) can refresh at the same
    # moment; without this the loser presents a token that no longer matches
    # anything and gets signed out. See REFRESH_GRACE_SECONDS.
    previous_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    # Free-form label so the account page can list "Chrome on macOS".
    device_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="auth_sessions")

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None
