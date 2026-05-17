"""
core/frame.py

MachineTraceFrame: the atomic unit of observable machine behaviour.

Rules:
- Frozen dataclass (immutable after construction)
- No floats anywhere
- All arrays normalised to sorted tuples at construction time
- JSON serialisation must be byte-stable across runs
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import FrozenSet, Tuple


# ---------------------------------------------------------------------------
# Field-level constraints
# ---------------------------------------------------------------------------

def _validate_no_floats(value: object, path: str = "") -> None:
    """Recursively assert that no float values exist in the payload."""
    if isinstance(value, float):
        raise TypeError(f"Floats are not permitted in MachineTraceFrame. Found at: {path!r}")
    if isinstance(value, dict):
        for k, v in value.items():
            _validate_no_floats(v, path=f"{path}.{k}")
    if isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _validate_no_floats(v, path=f"{path}[{i}]")


def _normalise_tags(tags: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    """Sort and deduplicate tags; return as sorted tuple."""
    if tags is None:
        return ()
    return tuple(sorted(set(str(t) for t in tags)))


# ---------------------------------------------------------------------------
# MachineTraceFrame
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MachineTraceFrame:
    """
    Immutable record of a single observed machine action.

    Fields
    ------
    frame_id        : Unique identifier for this frame (string, caller-assigned).
    timestamp_ms    : Wall-clock time in integer milliseconds since epoch.
                      Integer only — no floats.
    actor           : The identity of the entity performing the action.
    action          : The action being attempted (verb-noun convention, e.g. "transfer.outbound").
    payload         : Arbitrary key-value context. No floats allowed.
    tags            : Sorted, deduplicated classification labels.
    parent_frame_id : Optional link to the preceding frame in a causal chain.
    """

    frame_id:        str
    timestamp_ms:    int
    actor:           str
    action:          str
    payload:         dict                        # str -> int | str | bool | list | dict
    tags:            tuple[str, ...]             # always sorted
    parent_frame_id: str | None = field(default=None)

    # ------------------------------------------------------------------
    # Post-init validation — enforced even though the class is frozen
    # ------------------------------------------------------------------

    def __post_init__(self) -> None:
        # Type guards
        if not isinstance(self.frame_id, str) or not self.frame_id:
            raise ValueError("frame_id must be a non-empty string")
        if not isinstance(self.timestamp_ms, int):
            raise TypeError("timestamp_ms must be int, not float or other type")
        if not isinstance(self.actor, str) or not self.actor:
            raise ValueError("actor must be a non-empty string")
        if not isinstance(self.action, str) or not self.action:
            raise ValueError("action must be a non-empty string")
        if not isinstance(self.payload, dict):
            raise TypeError("payload must be a dict")
        if not isinstance(self.tags, tuple):
            raise TypeError("tags must be a tuple (use MachineTraceFrame.build())")

        # No floats anywhere
        _validate_no_floats(self.timestamp_ms, "timestamp_ms")
        _validate_no_floats(self.payload, "payload")

        # Tags must already be sorted (invariant)
        if list(self.tags) != sorted(self.tags):
            raise ValueError("tags must be pre-sorted — use MachineTraceFrame.build()")

    # ------------------------------------------------------------------
    # Factory — preferred construction path
    # ------------------------------------------------------------------

    @classmethod
    def build(
        cls,
        *,
        frame_id: str,
        timestamp_ms: int,
        actor: str,
        action: str,
        payload: dict,
        tags: list[str] | tuple[str, ...] | None = None,
        parent_frame_id: str | None = None,
    ) -> "MachineTraceFrame":
        """
        Normalising constructor.
        Sorts tags, validates no floats, then constructs the frozen instance.
        """
        normalised_tags = _normalise_tags(tags)
        _validate_no_floats(payload, "payload")
        if not isinstance(timestamp_ms, int):
            raise TypeError("timestamp_ms must be int")

        return cls(
            frame_id=frame_id,
            timestamp_ms=timestamp_ms,
            actor=actor,
            action=action,
            payload=payload,
            tags=normalised_tags,
            parent_frame_id=parent_frame_id,
        )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """
        Return a plain dict suitable for canonical serialisation.
        Arrays (tags, payload lists) are sorted to ensure determinism.
        """
        return {
            "frame_id":        self.frame_id,
            "timestamp_ms":    self.timestamp_ms,
            "actor":           self.actor,
            "action":          self.action,
            "payload":         _sort_payload(self.payload),
            "tags":            list(self.tags),          # already sorted
            "parent_frame_id": self.parent_frame_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MachineTraceFrame":
        """Reconstruct from a plain dict (e.g. loaded from a trace log)."""
        return cls.build(
            frame_id=d["frame_id"],
            timestamp_ms=d["timestamp_ms"],
            actor=d["actor"],
            action=d["action"],
            payload=d["payload"],
            tags=d.get("tags", []),
            parent_frame_id=d.get("parent_frame_id"),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sort_payload(obj: object) -> object:
    """
    Recursively sort dict keys and list elements where the element type
    supports ordering. This keeps payload serialisation byte-stable.
    """
    if isinstance(obj, dict):
        return {k: _sort_payload(v) for k in sorted(obj.keys()) for v in [obj[k]]}
    if isinstance(obj, list):
        # Sort lists of scalars; leave lists of dicts/mixed in original order
        # (mixed-type ordering is undefined in Python 3 — sort only homogeneous)
        try:
            return sorted(_sort_payload(v) for v in obj)
        except TypeError:
            return [_sort_payload(v) for v in obj]
    return obj
