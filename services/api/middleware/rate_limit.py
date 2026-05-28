"""
Rate limiter using slowapi.
Uses X-Forwarded-For to identify clients behind Railway's proxy.
Applies default rate limit to all routes.
"""
import time
from collections import defaultdict
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from shared.config import RATE_LIMIT


def _parse_rate(rate_str: str) -> tuple[int, int]:
    """Parse '60/minute' into (max_requests, window_seconds)."""
    parts = rate_str.split("/")
    count = int(parts[0])
    unit = parts[1].lower()
    seconds = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}.get(unit, 60)
    return count, seconds


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_requests: int = 60, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.clients: dict[str, list[float]] = defaultdict(list)

    def _get_client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next):
        client_ip = self._get_client_ip(request)
        now = time.time()
        cutoff = now - self.window_seconds

        timestamps = self.clients[client_ip]
        self.clients[client_ip] = [t for t in timestamps if t > cutoff]

        if len(self.clients[client_ip]) >= self.max_requests:
            return JSONResponse(
                status_code=429,
                content={"detail": f"Rate limit exceeded: {self.max_requests} per {self.window_seconds}s"},
            )

        self.clients[client_ip].append(now)
        return await call_next(request)


def setup_rate_limiting(app: FastAPI) -> None:
    max_req, window = _parse_rate(RATE_LIMIT)
    app.add_middleware(RateLimitMiddleware, max_requests=max_req, window_seconds=window)
