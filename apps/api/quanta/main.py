"""Quanta API entrypoint."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from quanta.api.router import api_router
from quanta.core.config import get_settings
from quanta.core.logging import configure_logging
from quanta.core.middleware import RequestContextMiddleware, SecurityHeadersMiddleware
from quanta.core.redis_client import close_redis, init_redis
from quanta.db.session import dispose_engine

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    configure_logging(settings)
    logger.info("startup", environment=settings.environment, app=settings.app_name)

    redis = await init_redis()
    if redis is None:
        # Rate limiting degrades open and the market-data fan-out (phase 1)
        # is not wired yet, so this is a warning rather than a hard failure.
        logger.warning("startup_without_redis")

    yield

    await close_redis()
    await dispose_engine()
    logger.info("shutdown")


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
