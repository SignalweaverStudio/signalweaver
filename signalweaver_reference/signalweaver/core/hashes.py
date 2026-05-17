"""
core/hashes.py

Deterministic SHA-256 hashing over SW-CER canonical bytes.

All hashes in SignalWeaver are:
- SHA-256 over UTF-8 encoded SW-CER canonical JSON
- Hex-encoded (lowercase, 64 characters)
- Computed from canonical bytes — never from raw Python objects directly

This module is intentionally minimal. It does not cache, index, or interpret
hashes. It only computes and verifies them.
"""

from __future__ import annotations

import hashlib


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def hash_canonical(canonical_bytes: bytes) -> str:
    """
    Compute SHA-256 over already-canonical bytes.
    Returns lowercase hex string (64 chars).

    canonical_bytes must come from canonicalizer.canonicalise() — this function
    does not perform any normalisation itself.
    """
    if not isinstance(canonical_bytes, bytes):
        raise TypeError(f"Expected bytes, got {type(canonical_bytes).__name__}")
    return hashlib.sha256(canonical_bytes).hexdigest()


def hash_frame(frame) -> str:
    """
    Convenience: hash a MachineTraceFrame via its canonical representation.
    Accepts any object with a .to_dict() method.
    """
    from core.canonicalizer import canonicalise
    return hash_canonical(canonicalise(frame.to_dict()))


def hash_verdict(verdict) -> str:
    """
    Convenience: hash a Verdict via its canonical representation.
    Accepts any object with a .to_dict() method.
    """
    from core.canonicalizer import canonicalise
    return hash_canonical(canonicalise(verdict.to_dict()))


def verify_hash(canonical_bytes: bytes, expected_hex: str) -> bool:
    """
    Return True iff SHA-256(canonical_bytes) == expected_hex.
    Both are compared in lowercase.
    """
    computed = hash_canonical(canonical_bytes)
    return computed == expected_hex.lower()
