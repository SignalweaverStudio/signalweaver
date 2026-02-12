"""
Simple API key authentication for demo/MVP use.
"""

import os
from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader
import time
from collections import defaultdict, deque
from fastapi import Request

# Header definition
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _configured_key() -> str | None:
    # Read environment variable at request time
    return os.getenv("SW_API_KEY")

# ---- Demo-grade in-memory rate limit ----
# ip -> deque[timestamps]
_hits: dict[str, deque[float]] = defaultdict(deque)

def rate_limit(request: Request, limit: int = 60, window_s: int = 60) -> None:
    """
    Simple per-IP rate limiter.

    - limit: max requests within window_s seconds
    - window_s: rolling window size in seconds

    Demo-safe: in-memory, per-process.
    """
    ip = request.client.host if request.client else "unknown"
    now = time.time()

    q = _hits[ip]

    # Drop old hits
    cutoff = now - window_s
    while q and q[0] < cutoff:
        q.popleft()

    # Enforce limit
    if len(q) >= limit:
        raise HTTPException(
    status_code=429,
    detail="Too many requests",
    headers={"Retry-After": str(window_s)},
)


    q.append(now)

async def verify_api_key(api_key: str | None = Security(api_key_header)) -> None:
    """
    Demo-grade API key check.

    - If SW_API_KEY not set → allow all (dev mode)
    - If set → require matching X-API-Key header
    """
    expected = _configured_key()

    if not expected:
        return  # dev mode — open access

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-API-Key header required",
        )

    if api_key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
