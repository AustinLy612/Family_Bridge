"""Request-id and security-header middleware (Plan Phase 0 task 2; §5.12)."""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import get_logger, request_id_var

REQUEST_ID_HEADER = "X-Request-ID"
# Accept a caller-supplied id only if it is short and harmless; otherwise mint one.
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

_DOCS_PATHS = frozenset({"/docs", "/redoc", "/docs/oauth2-redirect"})

log = get_logger("http")


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        rid = incoming if _SAFE_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(rid)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        # Re-set for the log line (reset above restores the outer context).
        token = request_id_var.set(rid)
        try:
            log.info(
                "request",
                method=request.method,
                path=request.url.path,  # path only — never query strings (may carry data)
                status=response.status_code,
                duration_ms=round((time.perf_counter() - start) * 1000, 1),
            )
        finally:
            request_id_var.reset(token)
        response.headers[REQUEST_ID_HEADER] = rid
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline secure headers. HSTS only outside development (TLS terminates upstream)."""

    def __init__(self, app: object, *, hsts: bool) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.hsts = hsts

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "no-referrer")
        h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if request.url.path not in _DOCS_PATHS:
            # The API serves JSON only. Interactive docs (dev only) need scripts, so they skip it.
            h.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        if self.hsts:
            h.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
        return response
