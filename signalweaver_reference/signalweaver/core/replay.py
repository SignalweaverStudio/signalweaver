"""
core/replay.py

Trace emission and cold-boot replay.

The trace log is a newline-delimited file of SW-CER canonical JSON records.
Each line is one TraceEntry: the canonical frame bytes + the verdict.

Replay invariant:
  Given the same trace file on cold boot, re-evaluating every frame must
  produce identical verdicts and identical hashes.

  If any verdict or hash diverges, replay raises ReplayInvariantViolation.

No state is retained between calls. The trace file is the only persistence.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List

from core.canonicalizer import canonicalise, deserialise_canonical
from core.evaluator import evaluate, Verdict
from core.frame import MachineTraceFrame
from core.hashes import hash_canonical, verify_hash


# ---------------------------------------------------------------------------
# TraceEntry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TraceEntry:
    """
    One record in the trace log.

    Stores:
    - canonical_bytes  : The SW-CER canonical serialisation of the frame.
    - frame_hash       : SHA-256 hex of canonical_bytes.
    - verdict_dict     : The Verdict serialised as a plain dict.
    - verdict_hash     : SHA-256 hex of the canonical verdict bytes.
    """
    canonical_bytes: bytes
    frame_hash:      str
    verdict_dict:    dict
    verdict_hash:    str

    def to_log_line(self) -> str:
        """
        Serialise to a single newline-free JSON string for the trace log.

        Structure:
        {
          "frame_canonical": "<hex-encoded canonical bytes>",
          "frame_hash":      "<sha256 hex>",
          "verdict":         { ... verdict dict ... },
          "verdict_hash":    "<sha256 hex>"
        }

        canonical_bytes are hex-encoded so the log stays pure ASCII/UTF-8.
        """
        record = {
            "frame_canonical": self.canonical_bytes.hex(),
            "frame_hash":      self.frame_hash,
            "verdict":         self.verdict_dict,
            "verdict_hash":    self.verdict_hash,
        }
        # Canonical serialisation of the log line itself
        return json.dumps(record, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_log_line(cls, line: str) -> "TraceEntry":
        """Parse one log line back to a TraceEntry."""
        record = json.loads(line.strip())
        return cls(
            canonical_bytes=bytes.fromhex(record["frame_canonical"]),
            frame_hash=record["frame_hash"],
            verdict_dict=record["verdict"],
            verdict_hash=record["verdict_hash"],
        )


# ---------------------------------------------------------------------------
# Trace emitter
# ---------------------------------------------------------------------------

class TraceLog:
    """
    Append-only trace log backed by a flat file.

    Each write appends one TraceEntry line.
    Reads scan from the beginning.
    No indexing, no database.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, frame: MachineTraceFrame, verdict: Verdict) -> TraceEntry:
        """
        Serialise frame + verdict to a TraceEntry and append to log.
        Returns the TraceEntry for caller inspection.
        """
        from core.canonicalizer import canonicalise
        from core.hashes import hash_canonical

        # Canonical bytes for the frame
        frame_bytes = canonicalise(frame.to_dict())
        frame_hash  = hash_canonical(frame_bytes)

        # Canonical bytes for the verdict
        verdict_dict  = verdict.to_dict()
        verdict_bytes = canonicalise(verdict_dict)
        verdict_hash  = hash_canonical(verdict_bytes)

        entry = TraceEntry(
            canonical_bytes=frame_bytes,
            frame_hash=frame_hash,
            verdict_dict=verdict_dict,
            verdict_hash=verdict_hash,
        )

        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(entry.to_log_line() + "\n")

        return entry

    def iter_entries(self) -> Iterator[TraceEntry]:
        """Yield each TraceEntry from the log in emission order."""
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield TraceEntry.from_log_line(line)

    def clear(self) -> None:
        """Wipe the trace log. Useful for test isolation."""
        if self.path.exists():
            self.path.unlink()


# ---------------------------------------------------------------------------
# Replay engine
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReplayResult:
    """
    Summary of one replay run.

    Fields
    ------
    total_entries    : Number of entries replayed.
    passed           : Entries where verdict and hash matched.
    failed           : Entries where anything diverged (should be zero).
    violations       : List of ReplayViolation records (empty on clean replay).
    """
    total_entries: int
    passed:        int
    failed:        int
    violations:    tuple  # tuple[ReplayViolation, ...]

    @property
    def is_clean(self) -> bool:
        return self.failed == 0


@dataclass(frozen=True)
class ReplayViolation:
    """
    Records a divergence found during replay.
    """
    entry_index:            int
    frame_id:               str
    stored_frame_hash:      str
    replayed_frame_hash:    str
    stored_verdict:         int
    replayed_verdict:       int
    stored_verdict_hash:    str
    replayed_verdict_hash:  str
    description:            str


class ReplayInvariantViolation(Exception):
    """Raised when replay produces a divergent result."""
    pass


def replay_from_log(
    trace_log: TraceLog,
    *,
    raise_on_violation: bool = True,
) -> ReplayResult:
    """
    Cold-boot replay: re-evaluate every frame in the trace log and verify
    that verdicts and hashes are bitwise identical to stored values.

    Parameters
    ----------
    trace_log           : The TraceLog to replay.
    raise_on_violation  : If True (default), raise ReplayInvariantViolation
                          on first divergence. If False, collect all violations
                          and return them in ReplayResult.

    Returns
    -------
    ReplayResult summarising the replay run.
    """
    from core.canonicalizer import canonicalise
    from core.hashes import hash_canonical

    violations: list[ReplayViolation] = []
    passed = 0

    for i, entry in enumerate(trace_log.iter_entries()):

        # 1. Verify stored frame hash matches stored canonical bytes
        recomputed_frame_hash = hash_canonical(entry.canonical_bytes)
        if recomputed_frame_hash != entry.frame_hash:
            v = ReplayViolation(
                entry_index=i,
                frame_id=entry.verdict_dict.get("frame_id", "?"),
                stored_frame_hash=entry.frame_hash,
                replayed_frame_hash=recomputed_frame_hash,
                stored_verdict=entry.verdict_dict.get("final_verdict", -1),
                replayed_verdict=-1,
                stored_verdict_hash=entry.verdict_hash,
                replayed_verdict_hash="",
                description="Frame canonical bytes do not match stored frame_hash.",
            )
            violations.append(v)
            if raise_on_violation:
                raise ReplayInvariantViolation(v.description)
            continue

        # 2. Reconstruct frame from canonical bytes
        frame_dict = deserialise_canonical(entry.canonical_bytes)
        frame = MachineTraceFrame.from_dict(frame_dict)

        # 3. Re-evaluate
        replayed_verdict = evaluate(frame, frame_hash=recomputed_frame_hash)

        # 4. Re-canonicalise and hash the replayed verdict
        replayed_verdict_bytes = canonicalise(replayed_verdict.to_dict())
        replayed_verdict_hash  = hash_canonical(replayed_verdict_bytes)

        # 5. Compare stored vs replayed
        stored_verdict_int   = entry.verdict_dict.get("final_verdict", -1)
        replayed_verdict_int = replayed_verdict.final_verdict

        frame_hash_ok   = (recomputed_frame_hash == entry.frame_hash)
        verdict_int_ok  = (replayed_verdict_int == stored_verdict_int)
        verdict_hash_ok = (replayed_verdict_hash == entry.verdict_hash)

        if not (frame_hash_ok and verdict_int_ok and verdict_hash_ok):
            v = ReplayViolation(
                entry_index=i,
                frame_id=frame.frame_id,
                stored_frame_hash=entry.frame_hash,
                replayed_frame_hash=recomputed_frame_hash,
                stored_verdict=stored_verdict_int,
                replayed_verdict=replayed_verdict_int,
                stored_verdict_hash=entry.verdict_hash,
                replayed_verdict_hash=replayed_verdict_hash,
                description=(
                    f"Divergence at entry {i} (frame {frame.frame_id!r}): "
                    f"verdict_int_ok={verdict_int_ok}, "
                    f"verdict_hash_ok={verdict_hash_ok}"
                ),
            )
            violations.append(v)
            if raise_on_violation:
                raise ReplayInvariantViolation(v.description)
        else:
            passed += 1

    return ReplayResult(
        total_entries=passed + len(violations),
        passed=passed,
        failed=len(violations),
        violations=tuple(violations),
    )
