"""Shared FastAPI dependencies: current user, CSRF, rate limiting."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from quanta.core.config import Settings, get_settings
from quanta.core.rate_limit import RateLimiter
from quanta.core.redis_client import get_redis
from quanta.core.security import TokenError, constant_time_compare, decode_token
from quanta.db.session import get_db
from quanta.models.user import User

# auto_error=False so a missing header yields our own 401 shape.
bearer_scheme = HTTPBearer(auto_error=False)

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[AsyncSession, Depends(get_db)]


def client_ip(request: Request) -> str | None:
    """Best-effort client IP.

    ``X-Forwarded-For`` is only trusted because the deployment puts a CDN/WAF
    in front (SPEC §4); without that proxy it is client-controlled.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def get_rate_limiter() -> RateLimiter:
    return RateLimiter(get_redis())


RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]


async def enforce_rate_limit(
    request: Request,
    bucket: str,
    limit: int,
    limiter: RateLimiter,
) -> None:
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return

    identifier = client_ip(request) or "unknown"
    result = await limiter.check(bucket, identifier, limit)
    if not result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please slow down.",
            headers={"Retry-After": str(result.retry_after or 60)},
        )


async def auth_rate_limit(request: Request, limiter: RateLimiterDep, settings: SettingsDep) -> None:
    """Tight per-IP budget for credential endpoints."""
    await enforce_rate_limit(request, "auth", settings.rate_limit_auth_per_minute, limiter)


async def get_current_user(
    db: DbDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    """Resolve the bearer access token to an active user."""
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or not credentials.credentials:
        raise unauthorized

    try:
        payload = decode_token(credentials.credentials, "access")
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise unauthorized from exc

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def verify_csrf(
    request: Request,
    settings: SettingsDep,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> None:
    """Double-submit CSRF check for cookie-authenticated routes.

    The refresh cookie is ``SameSite=strict``, which already blocks the
    cross-site case; this is the second layer SPEC §5 asks for.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return

    cookie_value = request.cookies.get(settings.csrf_cookie_name)
    if not cookie_value or not csrf_header:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing CSRF token.")
    if not constant_time_compare(cookie_value, csrf_header):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")
