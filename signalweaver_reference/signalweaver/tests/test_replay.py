"""
tests/test_replay.py

Tests for trace emission and cold-boot replay invariance
(core/replay.py).

Verifies:
- TraceEntry serialises and deserialises correctly
- TraceLog emits and reads back correctly
- Replay produces identical verdicts and hashes (bitwise invariance)
- Replay raises on corrupted trace data
- Empty log replays cleanly
"""

from __future__ import annotations

import json
import sys
import tempfile
import os
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.frame import MachineTraceFrame
from core.evaluator import evaluate_with_hash
from core.replay import (
    TraceEntry,
    TraceLog,
    replay_from_log,
    ReplayResult,
    ReplayInvariantViolation,
)
from core.canonicalizer import canonicalise
from core.hashes import hash_canonical


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _frame(frame_id: str, amount: int = 500_000, velocity: int = 1) -> MachineTraceFrame:
    return MachineTraceFrame.build(
        frame_id=frame_id,
        timestamp_ms=1_000_000 + hash(frame_id) % 1_000,  # deterministic offset
        actor="actor:replay:test",
        action="transfer.outbound",
        payload={"amount_pence": amount, "velocity_transfers_1h": velocity},
        tags=["replay", "test"],
    )


def _tmp_log() -> TraceLog:
    """Create a TraceLog backed by a fresh temp file."""
    fd, path = tempfile.mkstemp(suffix=".trace")
    os.close(fd)
    log = TraceLog(path)
    log.clear()
    return log


# ---------------------------------------------------------------------------
# TraceEntry serialisation
# ---------------------------------------------------------------------------

class TestTraceEntry:

    def test_roundtrip_log_line(self):
        frame = _frame("entry-001")
        verdict, frame_hash = evaluate_with_hash(frame)

        frame_bytes   = canonicalise(frame.to_dict())
        verdict_bytes = canonicalise(verdict.to_dict())
        verdict_hash  = hash_canonical(verdict_bytes)

        entry = TraceEntry(
            canonical_bytes=frame_bytes,
            frame_hash=frame_hash,
            verdict_dict=verdict.to_dict(),
            verdict_hash=verdict_hash,
        )

        line = entry.to_log_line()
        recovered = TraceEntry.from_log_line(line)

        assert recovered.canonical_bytes == entry.canonical_bytes
        assert recovered.frame_hash      == entry.frame_hash
        assert recovered.verdict_dict    == entry.verdict_dict
        assert recovered.verdict_hash    == entry.verdict_hash

    def test_log_line_is_single_line(self):
        frame = _frame("entry-002")
        verdict, frame_hash = evaluate_with_hash(frame)
        frame_bytes   = canonicalise(frame.to_dict())
        verdict_bytes = canonicalise(verdict.to_dict())

        entry = TraceEntry(
            canonical_bytes=frame_bytes,
            frame_hash=frame_hash,
            verdict_dict=verdict.to_dict(),
            verdict_hash=hash_canonical(verdict_bytes),
        )
        line = entry.to_log_line()
        assert "\n" not in line
        # Must be valid JSON
        json.loads(line)

    def test_canonical_bytes_hex_encoded_in_line(self):
        frame = _frame("entry-003")
        verdict, frame_hash = evaluate_with_hash(frame)
        frame_bytes   = canonicalise(frame.to_dict())
        verdict_bytes = canonicalise(verdict.to_dict())

        entry = TraceEntry(
            canonical_bytes=frame_bytes,
            frame_hash=frame_hash,
            verdict_dict=verdict.to_dict(),
            verdict_hash=hash_canonical(verdict_bytes),
        )
        record = json.loads(entry.to_log_line())
        assert record["frame_canonical"] == frame_bytes.hex()


# ---------------------------------------------------------------------------
# TraceLog emit and iterate
# ---------------------------------------------------------------------------

class TestTraceLog:

    def test_emit_creates_file(self):
        log = _tmp_log()
        frame = _frame("log-001")
        verdict, _ = evaluate_with_hash(frame)
        log.emit(frame, verdict)
        assert log.path.exists()

    def test_emit_and_iterate(self):
        log = _tmp_log()
        frames = [_frame(f"log-{i:03d}") for i in range(3)]
        for f in frames:
            v, _ = evaluate_with_hash(f)
            log.emit(f, v)

        entries = list(log.iter_entries())
        assert len(entries) == 3

    def test_iterate_empty_log(self):
        log = _tmp_log()
        entries = list(log.iter_entries())
        assert entries == []

    def test_emit_order_preserved(self):
        log = _tmp_log()
        frame_ids = ["alpha", "beta", "gamma"]
        for fid in frame_ids:
            f = _frame(fid)
            v, _ = evaluate_with_hash(f)
            log.emit(f, v)

        entries = list(log.iter_entries())
        stored_ids = [e.verdict_dict["frame_id"] for e in entries]
        assert stored_ids == frame_ids

    def test_clear_removes_entries(self):
        log = _tmp_log()
        f = _frame("clear-001")
        v, _ = evaluate_with_hash(f)
        log.emit(f, v)
        log.clear()
        assert list(log.iter_entries()) == []

    def test_frame_hash_in_entry_matches_canonical(self):
        log = _tmp_log()
        frame = _frame("hash-check")
        verdict, frame_hash = evaluate_with_hash(frame)
        entry = log.emit(frame, verdict)
        assert entry.frame_hash == frame_hash


# ---------------------------------------------------------------------------
# Replay invariance
# ---------------------------------------------------------------------------

class TestReplayInvariance:

    def test_clean_replay_single_frame(self):
        log = _tmp_log()
        f = _frame("replay-001")
        v, _ = evaluate_with_hash(f)
        log.emit(f, v)

        result = replay_from_log(log)
        assert result.is_clean
        assert result.total_entries == 1
        assert result.passed == 1
        assert result.failed == 0

    def test_clean_replay_multiple_frames(self):
        log = _tmp_log()
        test_cases = [
            ("r-001", 500_000,   1),   # PROCEED
            ("r-002", 2_000_000, 1),   # GATE (amount)
            ("r-003", 2_000_000, 6),   # GATE (amount + velocity)
            ("r-004", 15_000_000, 1),  # REFUSE
        ]
        for fid, amount, vel in test_cases:
            f = _frame(fid, amount=amount, velocity=vel)
            v, _ = evaluate_with_hash(f)
            log.emit(f, v)

        result = replay_from_log(log)
        assert result.is_clean
        assert result.total_entries == 4

    def test_replay_empty_log_is_clean(self):
        log = _tmp_log()
        result = replay_from_log(log)
        assert result.is_clean
        assert result.total_entries == 0

    def test_replay_produces_identical_verdict_integers(self):
        """
        Re-evaluation of every replayed frame must return the same final_verdict
        integer as the originally stored verdict.
        """
        log = _tmp_log()
        original_verdicts = []

        for i in range(5):
            amounts = [100_000, 2_000_000, 15_000_000, 500_000, 3_000_000]
            f = _frame(f"inv-{i:03d}", amount=amounts[i])
            v, _ = evaluate_with_hash(f)
            original_verdicts.append(v.final_verdict)
            log.emit(f, v)

        # Replay and manually compare
        for entry, expected_verdict in zip(log.iter_entries(), original_verdicts):
            stored_verdict = entry.verdict_dict["final_verdict"]
            assert stored_verdict == expected_verdict

        # Full replay must be clean
        result = replay_from_log(log)
        assert result.is_clean

    def test_replay_raises_on_corrupted_frame_hash(self):
        """
        If we corrupt the stored frame_hash in the log, replay must raise.
        """
        log = _tmp_log()
        f = _frame("corrupt-001")
        v, _ = evaluate_with_hash(f)
        log.emit(f, v)

        # Read the log line, corrupt the hash, rewrite
        lines = log.path.read_text(encoding="utf-8").splitlines()
        record = json.loads(lines[0])
        record["frame_hash"] = "0" * 64   # corrupt
        corrupted_line = json.dumps(record, sort_keys=True, separators=(",", ":"))
        log.path.write_text(corrupted_line + "\n", encoding="utf-8")

        with pytest.raises(ReplayInvariantViolation):
            replay_from_log(log, raise_on_violation=True)

    def test_replay_collects_violations_without_raising(self):
        """
        With raise_on_violation=False, all violations should be collected.
        """
        log = _tmp_log()
        f = _frame("corrupt-002")
        v, _ = evaluate_with_hash(f)
        log.emit(f, v)

        # Corrupt the stored frame hash
        lines = log.path.read_text(encoding="utf-8").splitlines()
        record = json.loads(lines[0])
        record["frame_hash"] = "a" * 64
        corrupted_line = json.dumps(record, sort_keys=True, separators=(",", ":"))
        log.path.write_text(corrupted_line + "\n", encoding="utf-8")

        result = replay_from_log(log, raise_on_violation=False)
        assert not result.is_clean
        assert result.failed == 1
        assert len(result.violations) == 1

    def test_bitwise_hash_invariance(self):
        """
        The SHA-256 of the canonical frame must be identical whether computed
        at emit time or at replay time.
        """
        log = _tmp_log()
        frame = _frame("bitwise-001", amount=1_234_567)
        verdict, emit_frame_hash = evaluate_with_hash(frame)
        entry = log.emit(frame, verdict)

        # Hash stored in the entry
        assert entry.frame_hash == emit_frame_hash

        # Hash recomputed from canonical_bytes stored in the entry
        recomputed = hash_canonical(entry.canonical_bytes)
        assert recomputed == emit_frame_hash

    def test_replay_verdict_hash_invariance(self):
        """
        Verdict hash stored at emit time must equal verdict hash recomputed
        at replay time.
        """
        log = _tmp_log()
        frame = _frame("vhash-001")
        verdict, _ = evaluate_with_hash(frame)
        entry = log.emit(frame, verdict)

        # Recompute verdict hash from the stored verdict_dict
        verdict_bytes = canonicalise(entry.verdict_dict)
        recomputed_verdict_hash = hash_canonical(verdict_bytes)
        assert recomputed_verdict_hash == entry.verdict_hash
