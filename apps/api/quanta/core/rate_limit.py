"""Redis-backed fixed-window rate limiting.

SPEC §5 asks for per-user and per-IP limits. The implementation degrades
open: if Redis is unreachable the API keeps serving rather than locking
everyone out, and the failure is logged.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    remaining: int
    limit: int
    retry_after: int


class RateLimiter:
    """Fixed-window counter keyed by ``bucket:identifier:window``."""

    def __init__(self, redis: Redis | None) -> None:
        self._redis = redis

    async def check(
        self, bucket: str, identifier: str, limit: int, window_seconds: int = 60
    ) -> RateLimitResult:
        if self._redis is None:
            return RateLimitResult(True, limit, limit, 0)

        key = f"ratelimit:{bucket}:{identifier}"
        try:
            pipe = self._redis.pipeline()
            pipe.incr(key)
            pipe.ttl(key)
            count, ttl = await pipe.execute()

            if ttl is None or ttl < 0:
                await self._redis.expire(key, window_seconds)
                ttl = window_seconds
        except RedisError as exc:
            # Fail open — a broken cache must not take authentication down.
            logger.warning("rate_limit_unavailable", error=str(exc), bucket=bucket)
            return RateLimitResult(True, limit, limit, 0)

        allowed = int(count) <= limit
        remaining = max(0, limit - int(count))
        return RateLimitResult(allowed, remaining, limit, int(ttl) if not allowed else 0)
