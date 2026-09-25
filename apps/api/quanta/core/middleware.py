"""HTTP middleware: security headers, request ids, CSP nonces.

SPEC §5 asks for a strict nonce-based CSP, COOP/COEP (needed later for
SharedArrayBuffer in the browser compute engine) and HSTS.
"""

from __future__ import annotations

import secrets
import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from quanta.core.config import Settings

logger = structlog.get_logger(__name__)

RequestHandler = Callable[[Request], Awaitable[Response]]


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request id and log request timing."""

    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = request_id
        started = time.perf_counter()

        response = await call_next(request)

        duration_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round(duration_ms, 2),
            request_id=request_id,
        )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Apply the SPEC §5 header set to every response."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        # A per-request nonce, available to any server-rendered HTML and
        # echoed in the CSP so inline scripts must carry it.
        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce

        response = await call_next(request)

        connect_src = ["'self'", *self.settings.cors_origins]
        csp = "; ".join(
            [
                "default-src 'self'",
                f"script-src 'self' 'nonce-{nonce}'",
                # Vite injects styles at runtime in dev; the build emits files.
                "style-src 'self' 'unsafe-inline'",
                "img-src 'self' data: blob:",
                "font-src 'self' data:",
                f"connect-src {' '.join(connect_src)} ws: wss:",
                "worker-src 'self' blob:",
                "frame-ancestors 'none'",
                "object-src 'none'",
                "base-uri 'self'",
                "form-action 'self'",
            ]
        )
        response.headers.setdefault("Content-Security-Policy", csp)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=(), payment=()"
        )

        if self.settings.cross_origin_isolation:
            # Required for SharedArrayBuffer / WASM threads (SPEC §3.6).
            response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
            response.headers.setdefault("Cross-Origin-Embedder-Policy", "require-corp")
            response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")

        if self.settings.is_production:
            response.headers.setdefault(
                "Strict-Transport-Security",
                f"max-age={self.settings.hsts_max_age_seconds}; includeSubDomains; preload",
            )

        return response
