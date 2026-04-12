"""
Sensitive field redaction for connector dispatch audit trails.

Recursively walks dicts and lists, replacing values whose keys match
known sensitive patterns with a fixed "[REDACTED]" marker.

This is applied to connector results before they are stored in
ExecutionLog.response_json or returned in API responses.

Design:
  - Minimal, explicit pattern list (not regex-based, not configurable)
  - Case-insensitive key matching
  - Preserves structure: only values change, keys remain
  - Does NOT touch keys or non-sensitive values
  - Recurses into nested dicts and lists
"""

from __future__ import annotations

import copy
from typing import Any

REDACT_MARKER = "[REDACTED]"

# Keys matching any of these patterns (case-insensitive) will have
# their values replaced with REDACT_MARKER.
SENSITIVE_PATTERNS = frozenset({
    "authorization",
    "token",
    "api_key",
    "apikey",
    "secret",
    "password",
    "signature",
    "signing_secret",
})


def _is_sensitive_key(key: str) -> bool:
    """Check if a key matches any known sensitive pattern."""
    return key.strip().lower() in SENSITIVE_PATTERNS


def redact_sensitive(obj: Any) -> Any:
    """
    Recursively redact sensitive values in a structure.

    Traverses dicts (by key) and lists (by index). For each dict key
    that matches a sensitive pattern, replaces the value with
    REDACT_MARKER. Non-container values are returned as-is.

    Returns a deep copy — the original object is never mutated.

    Examples:
        >>> redact_sensitive({"Authorization": "Bearer xyz"})
        {'Authorization': '[REDACTED]'}

        >>> redact_sensitive({"data": {"api_key": "abc", "name": "ok"}})
        {'data': {'api_key': '[REDACTED]', 'name': 'ok'}}

        >>> redact_sensitive([{"token": "t1"}, {"safe": "v1"}])
        [{'token': '[REDACTED]'}, {'safe': 'v1'}]

        >>> redact_sensitive("plain string")
        'plain string'

        >>> redact_sensitive(42)
        42
    """
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if _is_sensitive_key(k):
                out[k] = REDACT_MARKER
            elif isinstance(v, (dict, list)):
                out[k] = redact_sensitive(v)
            else:
                out[k] = v
        return out
    elif isinstance(obj, list):
        return [redact_sensitive(item) for item in obj]
    else:
        # Primitive: str, int, float, bool, None — return as-is
        return obj
