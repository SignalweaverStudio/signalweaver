"""
tests/test_canonicalization.py

Tests for SW-CER canonical serialisation (core/canonicalizer.py)
and MachineTraceFrame construction/serialisation (core/frame.py).

All tests are deterministic and hermetic — no I/O, no external calls.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.frame import MachineTraceFrame
from core.canonicalizer import canonicalise, canonicalise_frame, verify_canonical, deserialise_canonical
from core.hashes import hash_canonical, hash_frame, verify_hash


# ---------------------------------------------------------------------------
# MachineTraceFrame construction
# ---------------------------------------------------------------------------

class TestFrameConstruction:

    def test_build_minimal_frame(self):
        frame = MachineTraceFrame.build(
            frame_id="f-001",
            timestamp_ms=1_000_000,
            actor="actor:test",
            action="test.action",
            payload={},
        )
        assert frame.frame_id == "f-001"
        assert frame.timestamp_ms == 1_000_000
        assert frame.tags == ()
        assert frame.parent_frame_id is None

    def test_tags_are_sorted(self):
        frame = MachineTraceFrame.build(
            frame_id="f-002",
            timestamp_ms=1,
            actor="a",
            action="b",
            payload={},
            tags=["zebra", "alpha", "mango"],
        )
        assert frame.tags == ("alpha", "mango", "zebra")

    def test_tags_are_deduplicated(self):
        frame = MachineTraceFrame.build(
            frame_id="f-003",
            timestamp_ms=1,
            actor="a",
            action="b",
            payload={},
            tags=["x", "x", "y"],
        )
        assert frame.tags == ("x", "y")

    def test_float_in_timestamp_raises(self):
        with pytest.raises(TypeError):
            MachineTraceFrame.build(
                frame_id="f-004",
                timestamp_ms=1.5,   # float — must be rejected
                actor="a",
                action="b",
                payload={},
            )

    def test_float_in_payload_raises(self):
        with pytest.raises(TypeError):
            MachineTraceFrame.build(
                frame_id="f-005",
                timestamp_ms=1,
                actor="a",
                action="b",
                payload={"amount": 1.5},  # float in payload — must be rejected
            )

    def test_float_nested_in_payload_raises(self):
        with pytest.raises(TypeError):
            MachineTraceFrame.build(
                frame_id="f-006",
                timestamp_ms=1,
                actor="a",
                action="b",
                payload={"nested": {"value": 3.14}},
            )

    def test_empty_frame_id_raises(self):
        with pytest.raises(ValueError):
            MachineTraceFrame.build(
                frame_id="",
                timestamp_ms=1,
                actor="a",
                action="b",
                payload={},
            )

    def test_frame_is_frozen(self):
        frame = MachineTraceFrame.build(
            frame_id="f-007",
            timestamp_ms=1,
            actor="a",
            action="b",
            payload={},
        )
        with pytest.raises((AttributeError, TypeError)):
            frame.frame_id = "mutated"  # type: ignore

    def test_roundtrip_from_dict(self):
        frame = MachineTraceFrame.build(
            frame_id="f-008",
            timestamp_ms=9_999,
            actor="actor:roundtrip",
            action="roundtrip.action",
            payload={"key": "value", "count": 3},
            tags=["b", "a"],
            parent_frame_id="f-000",
        )
        reconstructed = MachineTraceFrame.from_dict(frame.to_dict())
        assert reconstructed == frame


# ---------------------------------------------------------------------------
# SW-CER canonicalisation
# ---------------------------------------------------------------------------

class TestCanonicalisation:

    def test_dict_keys_are_sorted(self):
        obj = {"z": 1, "a": 2, "m": 3}
        result = json.loads(canonicalise(obj))
        assert list(result.keys()) == ["a", "m", "z"]

    def test_nested_dict_keys_are_sorted(self):
        obj = {"outer": {"z": 1, "a": 2}}
        result = json.loads(canonicalise(obj))
        assert list(result["outer"].keys()) == ["a", "z"]

    def test_homogeneous_list_is_sorted(self):
        obj = {"tags": ["zebra", "alpha", "mango"]}
        result = json.loads(canonicalise(obj))
        assert result["tags"] == ["alpha", "mango", "zebra"]

    def test_no_whitespace_in_output(self):
        raw = canonicalise({"a": 1, "b": [1, 2]})
        # Should have no spaces or newlines
        assert b" " not in raw
        assert b"\n" not in raw
        assert b"\t" not in raw

    def test_output_is_utf8_bytes(self):
        raw = canonicalise({"k": "v"})
        assert isinstance(raw, bytes)
        raw.decode("utf-8")  # must not raise

    def test_identical_objects_produce_identical_bytes(self):
        obj1 = {"b": 2, "a": 1}
        obj2 = {"a": 1, "b": 2}
        assert canonicalise(obj1) == canonicalise(obj2)

    def test_different_objects_produce_different_bytes(self):
        assert canonicalise({"a": 1}) != canonicalise({"a": 2})

    def test_none_serialises_to_null(self):
        raw = canonicalise(None)
        assert raw == b"null"

    def test_unicode_preserved(self):
        obj = {"name": "naïve café"}
        raw = canonicalise(obj)
        recovered = json.loads(raw.decode("utf-8"))
        assert recovered["name"] == "naïve café"

    def test_frame_canonicalisation_is_stable(self):
        frame = MachineTraceFrame.build(
            frame_id="c-001",
            timestamp_ms=42,
            actor="actor:canon",
            action="canon.test",
            payload={"z": 99, "a": 1},
            tags=["t2", "t1"],
        )
        b1 = canonicalise_frame(frame)
        b2 = canonicalise_frame(frame)
        assert b1 == b2

    def test_verify_canonical_true_for_identical(self):
        b = canonicalise({"x": 1})
        assert verify_canonical(b, b) is True

    def test_verify_canonical_false_for_different(self):
        b1 = canonicalise({"x": 1})
        b2 = canonicalise({"x": 2})
        assert verify_canonical(b1, b2) is False

    def test_deserialise_roundtrip(self):
        obj = {"a": 1, "b": [3, 1, 2]}
        raw = canonicalise(obj)
        recovered = deserialise_canonical(raw)
        # After canonicalise, list is sorted; recovered reflects that
        assert recovered["a"] == 1
        assert recovered["b"] == [1, 2, 3]


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

class TestHashing:

    def test_hash_is_64_hex_chars(self):
        h = hash_canonical(b"hello")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_same_bytes_same_hash(self):
        b = canonicalise({"a": 1})
        assert hash_canonical(b) == hash_canonical(b)

    def test_different_bytes_different_hash(self):
        b1 = canonicalise({"a": 1})
        b2 = canonicalise({"a": 2})
        assert hash_canonical(b1) != hash_canonical(b2)

    def test_hash_frame_stable(self):
        frame = MachineTraceFrame.build(
            frame_id="h-001",
            timestamp_ms=1,
            actor="a",
            action="b",
            payload={"k": 1},
        )
        assert hash_frame(frame) == hash_frame(frame)

    def test_verify_hash_correct(self):
        b = canonicalise({"test": True})
        h = hash_canonical(b)
        assert verify_hash(b, h) is True

    def test_verify_hash_incorrect(self):
        b = canonicalise({"test": True})
        assert verify_hash(b, "0" * 64) is False

    def test_hash_canonical_rejects_non_bytes(self):
        with pytest.raises(TypeError):
            hash_canonical("not bytes")  # type: ignore
