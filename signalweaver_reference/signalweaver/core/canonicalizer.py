"""
core/canonicalizer.py

SW-CER: SignalWeaver Canonical Encoding Rules.

Guarantees:
- Lexicographic key ordering (recursive)
- UTF-8 encoding, no BOM
- No whitespace variance (compact separators)
- Deterministic array ordering (sorted where type allows)
- Byte-identical output for identical logical content, across runs, processes,
  and Python versions (within 3.11+)

This module contains NO probabilistic logic. It is a pure deterministic
serialisation layer.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def canonicalise(obj: Any) -> bytes:
    """
    Produce the SW-CER canonical byte representation of obj.

    Rules applied (in order):
    1. Recursively normalise: sort dict keys, sort homogeneous lists.
    2. Serialise with json.dumps using:
       - sort_keys=True  (belt-and-suspenders; normalisation already sorted)
       - separators=(',', ':')  — no whitespace
       - ensure_ascii=False  — allow UTF-8 codepoints directly
    3. Encode result as UTF-8 (no BOM).

    The result is a bytes object suitable for hashing, storage, or comparison.
    """
    normalised = _normalise(obj)
    serialised = json.dumps(
        normalised,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return serialised.encode("utf-8")


def canonicalise_frame(frame) -> bytes:
    """
    Convenience wrapper: canonicalise a MachineTraceFrame.
    Accepts any object that exposes .to_dict().
    """
    return canonicalise(frame.to_dict())


def verify_canonical(candidate_bytes: bytes, reference_bytes: bytes) -> bool:
    """
    Bitwise equality check between two canonical byte strings.
    Returns True only if they are identical.
    """
    return candidate_bytes == reference_bytes


# ---------------------------------------------------------------------------
# Internal normalisation
# ---------------------------------------------------------------------------

def _normalise(obj: Any) -> Any:
    """
    Recursively normalise an object to its SW-CER canonical form.

    - dicts:  keys sorted lexicographically, values recursively normalised
    - lists:  elements recursively normalised; sort if homogeneous scalar type
    - scalars: returned as-is (float is not permitted upstream; we do not
               introduce floats here)
    - None:   serialised as JSON null
    """
    if isinstance(obj, dict):
        return {
            k: _normalise(v)
            for k in sorted(obj.keys())       # lexicographic key sort
            for v in [obj[k]]
        }

    if isinstance(obj, (list, tuple)):
        normalised_items = [_normalise(item) for item in obj]
        # Attempt stable sort on homogeneous scalar lists
        try:
            return sorted(normalised_items, key=_canonical_sort_key)
        except TypeError:
            # Mixed types or unhashable — preserve order, still deterministic
            # as long as the upstream producer is deterministic
            return normalised_items

    # Scalars: int, str, bool, None pass through unchanged
    # (Floats are rejected at frame construction; we do not need to handle them)
    return obj


def _canonical_sort_key(value: Any) -> tuple:
    """
    Stable, cross-type sort key for SW-CER list normalisation.

    Encodes type priority so that mixed lists sort predictably:
      None < bool < int < str < list < dict
    """
    if value is None:
        return (0, "")
    if isinstance(value, bool):
        return (1, int(value))
    if isinstance(value, int):
        return (2, value)
    if isinstance(value, str):
        return (3, value)
    if isinstance(value, list):
        return (4, str(value))
    if isinstance(value, dict):
        return (5, str(sorted(value.items())))
    return (9, str(value))


# ---------------------------------------------------------------------------
# Deserialisation
# ---------------------------------------------------------------------------

def deserialise_canonical(raw: bytes) -> Any:
    """
    Decode a SW-CER canonical byte string back to a Python object.

    This does NOT re-normalise on load — the assumption is that stored bytes
    are already canonical. Use this for replay verification only.
    """
    return json.loads(raw.decode("utf-8"))
