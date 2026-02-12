"""
Simple API key authentication for demo/MVP use.
"""

import os
from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader

# Header definition
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _configured_key() -> str | None:
    # Read environment variable at request time
    return os.getenv("SW_API_KEY")


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
