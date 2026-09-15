"""Optional API authentication and a bounded, thread-safe per-client limiter."""

from __future__ import annotations

import hmac
import time
from collections import OrderedDict, deque
from threading import Lock

from fastapi import Header, HTTPException, Request

from app.config import settings

_hits: OrderedDict[str, deque[float]] = OrderedDict()
_lock = Lock()
_WINDOW = 60.0
_MAX_CLIENTS = 10000


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if settings.api_key and not hmac.compare_digest(
        (x_api_key or "").encode(), settings.api_key.encode()
    ):
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")


def rate_limit(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    limit = settings.rate_limit_per_min
    if limit <= 0:
        return
    # Never trust an arbitrary header as a client identity in anonymous mode.
    authenticated = settings.api_key and hmac.compare_digest(
        (x_api_key or "").encode(), settings.api_key.encode()
    )
    client = (
        "authenticated" if authenticated else (request.client.host if request.client else "unknown")
    )
    now = time.monotonic()
    with _lock:
        # Ordered by last use: expire idle identities without an unbounded dictionary.
        while _hits:
            oldest = next(iter(_hits))
            if _hits[oldest] and now - _hits[oldest][-1] <= _WINDOW:
                break
            _hits.popitem(last=False)
        if client not in _hits and len(_hits) >= _MAX_CLIENTS:
            raise HTTPException(status_code=429, detail="rate limiter capacity reached")
        window = _hits.setdefault(client, deque())
        _hits.move_to_end(client)
        while window and now - window[0] > _WINDOW:
            window.popleft()
        if len(window) >= limit:
            raise HTTPException(status_code=429, detail="rate limit exceeded")
        window.append(now)
