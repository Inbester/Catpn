"""What this machine has, and where each feature's work should run."""

from __future__ import annotations

import os
import platform
import shutil
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from quanta.models.compute import (
    COMPUTE_FEATURES,
    COMPUTE_SOURCES,
    DEFAULT_ROUTING,
    SERVER_ONLY,
    ComputePreference,
)


def _meminfo() -> tuple[int, int]:
    """Total and available memory in MB, from /proc where it exists.

    Read rather than taken from a dependency: this is two lines of a file
    on the platform the server runs on, and a container's limits show up
    here the way the kernel sees them.
    """
    try:
        values: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, _, rest = line.partition(":")
            if key in {"MemTotal", "MemAvailable"}:
                values[key] = int(rest.strip().split()[0]) // 1024
        return values.get("MemTotal", 0), values.get("MemAvailable", 0)
    except (OSError, ValueError, IndexError):
        return 0, 0


def server_specs() -> dict[str, Any]:
    """What the server can offer, read live rather than configured.

    A configured number goes stale the first time the box is resized, and
    the whole point of the card is to help someone decide where to send a
    half-hour job.
    """
    total_mb, available_mb = _meminfo()
    disk = shutil.disk_usage("/")
    cores = os.cpu_count() or 1
    try:
        load = os.getloadavg()[0]
    except OSError:
        load = 0.0

    return {
        "platform": f"{platform.system()} {platform.machine()}",
        "cpu_cores": cores,
        # Load over cores: above 1.0 means work is queuing for a core.
        # A point-in-time percentage would need a sampling interval this
        # endpoint should not spend, and the average says more anyway.
        "load_per_core": round(load / cores, 2),
        "memory_total_mb": total_mb,
        "memory_available_mb": available_mb,
        "disk_total_gb": disk.total // (1024**3),
        "disk_free_gb": disk.free // (1024**3),
        # No GPU in the container. Said plainly rather than left blank, so
        # nobody sends GPU work here expecting it to be faster.
        "gpu": None,
    }


async def get_preference(db: AsyncSession, user_id: uuid.UUID) -> ComputePreference:
    """This user's choices, created with the defaults on first use."""
    result = await db.execute(select(ComputePreference).where(ComputePreference.user_id == user_id))
    preference = result.scalar_one_or_none()
    if preference is None:
        preference = ComputePreference(user_id=user_id, routing=dict(DEFAULT_ROUTING))
        db.add(preference)
        await db.flush()
    return preference


class ComputeError(Exception):
    """A routing choice that cannot be honoured, with a reason to show."""


def apply_routing(preference: ComputePreference, routing: dict[str, str]) -> None:
    """Update the routing, refusing what the locks forbid.

    The refusal is explicit rather than a silent correction: someone who
    asked for alerts on their laptop should be told why they cannot have
    it, not quietly given something else.
    """
    merged = dict(preference.routing)
    for feature, source in routing.items():
        if feature not in COMPUTE_FEATURES:
            raise ComputeError(f"Unknown feature {feature!r}.")
        if source not in COMPUTE_SOURCES:
            raise ComputeError(f"{source!r} is not a compute source.")
        if feature in SERVER_ONLY and source != "server":
            raise ComputeError(SERVER_ONLY[feature])
        merged[feature] = source
    preference.routing = merged


def to_dict(preference: ComputePreference) -> dict[str, Any]:
    return {
        "routing": {feature: preference.resolved(feature) for feature in COMPUTE_FEATURES},
        "locked": SERVER_ONLY,
        "cpu_share_percent": preference.cpu_share_percent,
        "gpu_duty_percent": preference.gpu_duty_percent,
        "ram_budget_mb": preference.ram_budget_mb,
        "local_profile": preference.local_profile,
        "device_label": preference.device_label,
    }
