"""
examples/treasury_airlock.py

Treasury Airlock — reference scenario for the SignalWeaver governance substrate.

Scenario
--------
An automated treasury system attempts a series of outbound transfers.
SignalWeaver sits between the system's intent and its execution, evaluating
each frame against the static policy pack and emitting a deterministic trace.

Three frames are submitted:

  Frame 1 — Normal transfer (£500). Expect PROCEED.
  Frame 2 — Large transfer (£25,000) with velocity anomaly (6 transfers/h).
             Expect GATE (both POL-100 and POL-101 fire; GATE dominates).
  Frame 3 — Massive transfer (£150,000).
             Expect REFUSE (POL-100 hard refusal).

After all frames are processed, the trace log is replayed from cold boot and
all verdicts are verified bitwise-identical.

Run with:
    python -m examples.treasury_airlock
or:
    python examples/treasury_airlock.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Allow running from repo root without installation
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.frame import MachineTraceFrame
from core.evaluator import evaluate_with_hash
from core.replay import TraceLog, replay_from_log
from core.policy import VERDICT_NAMES


# ---------------------------------------------------------------------------
# Scenario frames
# ---------------------------------------------------------------------------

FRAMES = [
    MachineTraceFrame.build(
        frame_id="treasury-001",
        timestamp_ms=1_700_000_001_000,
        actor="actor:treasury:automated",
        action="transfer.outbound",
        payload={
            "amount_pence":          50_000,       # £500 — well within threshold
            "destination":           "acc:supplier:acme",
            "velocity_transfers_1h": 1,
        },
        tags=["treasury", "outbound"],
    ),
    MachineTraceFrame.build(
        frame_id="treasury-002",
        timestamp_ms=1_700_000_002_000,
        actor="actor:treasury:automated",
        action="transfer.outbound",
        payload={
            "amount_pence":          2_500_000,    # £25,000 — exceeds GATE threshold
            "destination":           "acc:supplier:beta",
            "velocity_transfers_1h": 6,            # velocity anomaly: >=5
        },
        tags=["treasury", "outbound", "sensitive", "unreviewed"],
        parent_frame_id="treasury-001",
    ),
    MachineTraceFrame.build(
        frame_id="treasury-003",
        timestamp_ms=1_700_000_003_000,
        actor="actor:treasury:automated",
        action="transfer.outbound",
        payload={
            "amount_pence":          15_000_000,   # £150,000 — exceeds REFUSE threshold
            "destination":           "acc:unknown:offshore",
            "velocity_transfers_1h": 2,
        },
        tags=["treasury", "outbound"],
        parent_frame_id="treasury-002",
    ),
]

EXPECTED_VERDICTS = [0, 2, 3]   # PROCEED, GATE, REFUSE


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def run(trace_path: str | None = None) -> None:
    """
    Execute the Treasury Airlock scenario.

    Parameters
    ----------
    trace_path : Path for the trace log file. If None, uses a temp file that
                 is printed to stdout and left on disk for inspection.
    """
    if trace_path is None:
        trace_path = os.path.join(tempfile.gettempdir(), "sw_treasury_airlock.trace")

    trace_log = TraceLog(trace_path)
    trace_log.clear()   # start fresh

    print("=" * 60)
    print("SIGNALWEAVER — Treasury Airlock Scenario")
    print("=" * 60)
    print()

    results = []

    for frame in FRAMES:
        verdict, frame_hash = evaluate_with_hash(frame)
        entry = trace_log.emit(frame, verdict)
        results.append((frame, verdict, frame_hash, entry))

        print(f"  Frame   : {frame.frame_id}")
        print(f"  Action  : {frame.action}")
        print(f"  Amount  : {frame.payload.get('amount_pence', 'n/a')} pence")
        print(f"  Velocity: {frame.payload.get('velocity_transfers_1h', 'n/a')} /h")
        print(f"  Tags    : {list(frame.tags)}")
        print(f"  Hash    : {frame_hash[:16]}…")
        print(f"  Verdict : {verdict.verdict_name()}  ({verdict.final_verdict})")
        print(f"  Reason  : {verdict.dominant_signal.reason}")
        print(f"  Policy  : {verdict.dominant_signal.policy_id}")
        print()

    # Verify expected verdicts
    print("-" * 60)
    print("Verdict assertions:")
    all_ok = True
    for (frame, verdict, _, _), expected in zip(results, EXPECTED_VERDICTS):
        ok = verdict.final_verdict == expected
        status = "PASS" if ok else "FAIL"
        print(
            f"  [{status}] {frame.frame_id}: "
            f"expected {VERDICT_NAMES[expected]}, "
            f"got {verdict.verdict_name()}"
        )
        if not ok:
            all_ok = False

    print()

    # Cold-boot replay
    print("-" * 60)
    print("Replaying from cold boot …")
    replay_result = replay_from_log(trace_log, raise_on_violation=True)
    print(
        f"  Replayed {replay_result.total_entries} entries: "
        f"{replay_result.passed} passed, "
        f"{replay_result.failed} failed."
    )
    if replay_result.is_clean:
        print("  REPLAY INVARIANT: VERIFIED — bitwise identical.")
    else:
        print("  REPLAY INVARIANT: VIOLATED — see violations above.")
        all_ok = False

    print()
    print(f"Trace log: {trace_path}")
    print()

    if all_ok:
        print("ALL CHECKS PASSED.")
    else:
        print("ONE OR MORE CHECKS FAILED.")
        sys.exit(1)


if __name__ == "__main__":
    run()
