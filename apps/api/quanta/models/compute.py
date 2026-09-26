"""Where each feature's work runs (SPEC §3.6, Resources).

Heavy research can run on the server or in the browser. The choice is per
feature rather than global, because the trade-offs differ: a Discover
search is worth sending to a machine with cores to spare, while a chart
redraw belongs where the chart is.

Two features are not a choice at all. Alerts must fire when the browser is
closed, so they only ever run on the server; and SPEC §9 locks bot order
traffic to the server's static IP, because the exchange API key is
whitelisted to it and routing orders anywhere else would both break the
key and, in restricted regions, amount to evading a venue's own rules.
Those locks live here, in the data, rather than only in the UI.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from quanta.db.base import Base, Timestamped, UUIDPrimaryKey

# The features whose compute source can be chosen.
COMPUTE_FEATURES = ("chart_data", "research", "alerts", "ai", "bot")

# Features that may only ever run on the server, and why.
SERVER_ONLY: dict[str, str] = {
    "alerts": "Alerts have to fire when the browser is closed.",
    "bot": (
        "Order traffic is locked to the server's static IP, which the "
        "exchange API key is whitelisted to (SPEC §9)."
    ),
}

COMPUTE_SOURCES = ("server", "local", "auto")

DEFAULT_ROUTING: dict[str, str] = {
    "chart_data": "server",
    "research": "auto",
    "alerts": "server",
    "ai": "server",
    "bot": "server",
}


class ComputePreference(UUIDPrimaryKey, Timestamped, Base):
    """One user's compute choices."""

    __tablename__ = "compute_preferences"
    __table_args__ = (UniqueConstraint("user_id", name="uq_compute_preferences_user"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # {feature: "server" | "local" | "auto"}
    routing: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=lambda: dict(DEFAULT_ROUTING)
    )

    # Share of the local machine a browser job may use. Percentages rather
    # than counts: the browser only reports a core count, and it is a hint.
    cpu_share_percent: Mapped[int] = mapped_column(default=50, nullable=False)
    gpu_duty_percent: Mapped[int] = mapped_column(default=0, nullable=False)
    ram_budget_mb: Mapped[int] = mapped_column(default=1024, nullable=False)

    # What the browser last reported about itself, for the Resources page
    # to show without asking again on every visit.
    local_profile: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    device_label: Mapped[str] = mapped_column(String(120), nullable=False, default="This computer")

    def resolved(self, feature: str) -> str:
        """The source that will actually be used, locks applied."""
        if feature in SERVER_ONLY:
            return "server"
        return str(self.routing.get(feature, DEFAULT_ROUTING.get(feature, "server")))
