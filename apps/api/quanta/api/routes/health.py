"""Liveness and readiness probes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from quanta.api.deps import DbDep
from quanta.core.redis_client import get_redis

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness: the process is up."""
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness(db: DbDep) -> dict[str, Any]:
    """Readiness: dependencies are reachable."""
    checks: dict[str, str] = {}

    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except SQLAlchemyError as exc:
        checks["database"] = f"error: {type(exc).__name__}"

    redis = get_redis()
    if redis is None:
        checks["redis"] = "unavailable"
    else:
        try:
            await redis.ping()
            checks["redis"] = "ok"
        except RedisError as exc:
            checks["redis"] = f"error: {type(exc).__name__}"

    healthy = all(v == "ok" for v in checks.values())
    return {"status": "ok" if healthy else "degraded", "checks": checks}
