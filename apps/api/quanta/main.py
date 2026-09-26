"""Quanta API entrypoint."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from quanta.api.market_runtime import set_market_service
from quanta.api.router import api_router
from quanta.core.config import Settings, get_settings
from quanta.core.logging import configure_logging
from quanta.core.middleware import RequestContextMiddleware, SecurityHeadersMiddleware
from quanta.core.redis_client import close_redis, init_redis
from quanta.db.session import dispose_engine, get_session_factory
from quanta.exchanges.base import Interval
from quanta.exchanges.bitunix import BitunixAdapter
from quanta.services import jobs
from quanta.services.market_data import MarketDataService

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    configure_logging(settings)
    logger.info("startup", environment=settings.environment, app=settings.app_name)

    redis = await init_redis()
    if redis is None:
        # Rate limiting degrades open; the live chart stream needs Redis and
        # reports itself unavailable rather than failing the whole boot.
        logger.warning("startup_without_redis")

    # A previous process may have died mid-job. Those rows would otherwise
    # claim to be running forever.
    try:
        async with get_session_factory()() as db:
            stale = await jobs.mark_interrupted(db)
        if stale:
            logger.info("jobs_interrupted_by_restart", count=stale)
    except Exception as exc:  # a database hiccup must not stop the boot
        logger.warning("job_cleanup_failed", error=str(exc))

    market = await _start_market_data(settings, redis)

    yield

    if market is not None:
        await market.stop()
    set_market_service(None)
    await close_redis()
    await dispose_engine()
    logger.info("shutdown")


async def _start_market_data(settings: Settings, redis: Redis | None) -> MarketDataService | None:
    """Open the one shared exchange connection and warm the chart's history.

    Failures here are logged, not fatal: the app must still serve sign-in
    and the shell when the venue is unreachable — which SPEC §9 says is the
    normal case in restricted regions.
    """
    if not settings.market_data_enabled:
        return None

    adapter = BitunixAdapter(rest_url=settings.exchange_rest_url, ws_url=settings.exchange_ws_url)
    service = MarketDataService(adapter, get_session_factory(), redis)
    set_market_service(service)

    async def warm() -> None:
        try:
            await service.refresh_instruments()
            for symbol in settings.market_warm_symbols:
                for raw_interval in settings.market_warm_intervals:
                    interval = Interval(raw_interval)
                    await service.ensure_history(symbol, interval, bars=settings.market_warm_bars)
                    await service.fill_gaps(symbol, interval)
                    service.subscribe(symbol, interval)
                await service.refresh_funding(symbol)
            logger.info("market_data_warm", symbols=settings.market_warm_symbols)
        except Exception as exc:  # the app stays up when the venue is unreachable
            logger.warning("market_data_warm_failed", error=str(exc))

    await service.start()
    # Warming runs in the background so boot is not blocked on the exchange.
    asyncio.create_task(warm())  # noqa: RUF006 - lives for the process
    return service


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=f"{settings.app_name} API",
        version="0.1.0",
        description=(
            "Crypto charting, research and trading platform. "
            "Phase 0: auth, workspace autosave and the app shell."
        ),
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    # Order matters: the outermost middleware is added last.
    app.add_middleware(SecurityHeadersMiddleware, settings=settings)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", settings.csrf_header_name],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )

    app.include_router(api_router, prefix=settings.api_prefix)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Log the detail, return a generic message.

        Stack traces and driver errors must never reach the client.
        """
        logger.exception(
            "unhandled_exception",
            path=request.url.path,
            request_id=getattr(request.state, "request_id", None),
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error."},
        )

    return app


app = create_app()
