"""
Request signing for webhook dispatch.

Computes an HMAC-SHA256 signature over the outbound JSON payload
and returns the standard headers for target verification.

This is additive: if no signing_secret is provided, dispatch works
without signing. The raw secret is never persisted to logs or
audit records.

Design:
  - Uses only stdlib: hmac, hashlib, json, time
  - SHA-256 HMAC over the exact JSON bytes sent in the body
  - Timestamp header included for replay protection context
  - Simple, deterministic, reviewable
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any


SIGNATURE_HEADER = "X-SignalWeaver-Signature"
TIMESTAMP_HEADER = "X-SignalWeaver-Timestamp"


def sign_payload(payload_bytes: bytes, secret: str) -> str:
    """
    Compute HMAC-SHA256 hex digest over payload bytes.

    Parameters
    ----------
    payload_bytes: bytes
        The exact JSON bytes that will be sent as the request body.
    secret: str
        The signing secret (shared between SignalWeaver and the target).

    Returns
    -------
    str
        Hex-encoded HMAC-SHA256 digest.
    """
    return hmac.new(
        secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()


def build_signed_headers(payload: dict[str, Any], secret: str) -> dict[str, str]:
    """
    Build the signing headers for an outbound webhook request.

    Computes HMAC-SHA256 over the JSON-serialized payload and
    attaches both signature and timestamp headers.

    Parameters
    ----------
    payload: dict
        The payload dict that will be sent as JSON.
    secret: str
        The signing secret.

    Returns
    -------
    dict[str, str]
        Headers dict with X-SignalWeaver-Signature and
        X-SignalWeaver-Timestamp.
    """
    payload_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    signature = sign_payload(payload_bytes, secret)
    timestamp = str(int(time.time()))
    return {
        SIGNATURE_HEADER: f"sha256={signature}",
        TIMESTAMP_HEADER: timestamp,
    }
