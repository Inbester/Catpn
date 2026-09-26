"""WireGuard tunnels and what may be routed through them (SPEC §3.6, §9).

SPEC §3.6 lists four routable features and §9 forbids using the product to
evade a venue's regional restrictions. Those two pull against each other
for exchange traffic specifically: sending market data or orders through a
user-supplied exit, from a region the exchange bars, is the circumvention
§9 rules out. So the routable set here is the features where a tunnel is
about reachability rather than about appearing to be somewhere else —
alert delivery and AI — and exchange traffic stays on the server.

That is narrower than §3.6 reads on its own, and deliberately so: §9 is
the constraint the same document says must be honoured, and a lock is
only meaningful if it is in the code rather than in a paragraph.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from quanta.db.base import Base, Timestamped, UUIDPrimaryKey

# What a tunnel may carry.
ROUTABLE_FEATURES = ("alerts_delivery", "ai")

# What it may not, and why. Each reason is shown next to the lock.
UNROUTABLE: dict[str, str] = {
    "chart_data": (
        "Market data comes from the exchange. Routing it through a personal "
        "exit would be using the product to reach a venue from a region it "
        "restricts, which SPEC §9 rules out."
    ),
    "research_download": (
        "History downloads are exchange traffic, so the same rule applies as for live market data."
    ),
    "bot": (
        "Order traffic is locked to the server's static IP, which the "
        "exchange API key is whitelisted to (SPEC §9)."
    ),
}


class Tunnel(UUIDPrimaryKey, Timestamped, Base):
    """One imported WireGuard configuration."""

    __tablename__ = "tunnels"
    __table_args__ = (Index("ix_tunnels_user_enabled", "user_id", "enabled"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)

    # The private key, encrypted at rest and never returned (SPEC §3.6).
    # Stored separately from the summary so a read path cannot reach it by
    # accident.
    secret: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Endpoint, public key, addresses: what is safe to show.
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Lower goes first when a feature routes through more than one.
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Last test, so the page can show state without re-testing on open.
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class FeatureRoute(UUIDPrimaryKey, Timestamped, Base):
    """Which tunnels a feature uses, in order."""

    __tablename__ = "feature_routes"
    __table_args__ = (Index("ix_feature_routes_user_feature", "user_id", "feature"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    feature: Mapped[str] = mapped_column(String(32), nullable=False)
    # Tunnel ids in failover order. Empty means the server's own route.
    tunnel_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
