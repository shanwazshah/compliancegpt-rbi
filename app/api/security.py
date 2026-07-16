"""API-key auth + a simple in-memory rate limiter (spec §16).

Auth is opt-in: if `settings.api_key` is empty (local dev), requests pass. Set a
key and clients must send it as the `X-API-Key` header.

The rate limiter is a per-client sliding window kept in memory — fine for a
single-process demo. A multi-process/production deploy would move this to Redis.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Header, HTTPException, Request

from app.config import settings

# client-id -> deque of recent request timestamps (monotonic seconds)
_hits: dict[str, deque[float]] = defaultdict(deque)
_WINDOW = 60.0


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Enforce the API key when one is configured."""
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")


def rate_limit(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    """Allow at most rate_limit_per_min requests per client per rolling minute."""
    limit = settings.rate_limit_per_min
    if limit <= 0:
        return
    client = x_api_key or (request.client.host if request.client else "unknown")
    now = time.monotonic()
    window = _hits[client]
    while window and now - window[0] > _WINDOW:
        window.popleft()
    if len(window) >= limit:
        raise HTTPException(status_code=429, detail="rate limit exceeded — try again shortly")
    window.append(now)
