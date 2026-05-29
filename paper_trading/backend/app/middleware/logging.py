"""
Request logging middleware.

Emits one structured log line per request:
  → METHOD /path  (on receipt)
  ← STATUS METHOD /path  duration_ms  (on completion)

Each request gets a short random ID (X-Request-ID header) so you can grep
a single request across async log output.
"""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("api.access")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        req_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:8]
        method = request.method
        path = request.url.path

        # Skip health-check spam in logs
        if path == "/api/health":
            return await call_next(request)

        logger.debug("[%s] → %s %s", req_id, method, path)
        t0 = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            elapsed = int((time.perf_counter() - t0) * 1000)
            logger.error("[%s] ✗ %s %s  %dms  (unhandled exception)", req_id, method, path, elapsed)
            raise

        elapsed = int((time.perf_counter() - t0) * 1000)
        status = response.status_code
        level = logging.WARNING if status >= 400 else logging.INFO
        logger.log(level, "[%s] ← %d %s %s  %dms", req_id, status, method, path, elapsed)

        response.headers["X-Request-ID"] = req_id
        return response
