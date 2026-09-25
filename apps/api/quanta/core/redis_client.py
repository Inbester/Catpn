"""Shared Redis connection.

Phase 1 reuses this pool for the market-data pub/sub fan-out.
"""

from __future__ import annotations

import structlog
from redis.asyncio import Redis, from_url
from redis.exceptions import RedisError

from quanta.core.config import get_settings

logger = structlog.get_logger(__name__)

_redis: Redis | None = None


async def init_redis() -> Redis | None:
    """Connect to Redis. Returns ``None`` when it is unavailable."""
    global _redis
    if _redis is not None:
        return _redis

    settings = get_settings()
    client: Redis = from_url(str(settings.redis_url), encoding="utf-8", decode_responses=True)
    try:
        await client.ping()
    except (RedisError, OSError) as exc:
        logger.warning("redis_unavailable", error=str(exc))
        await client.aclose()
        return None

    _redis = client
    return _redis


def get_redis() -> Redis | None:
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
