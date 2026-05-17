"""
core/evaluator.py

Deterministic policy evaluator with monotonic escalation resolution.

The evaluator:
1. Runs every policy in POLICY_REGISTRY against the frame.
2. Collects all PolicySignals.
3. Resolves the final verdict by taking the maximum (highest ordinal).
4. Returns a Verdict — the canonical, hashable record of the decision.

Monotonicity invariant:
  Once a higher verdict is observed, no lower verdict can reduce it.
  max() over {PROCEED=0, EXPLORE=1, GATE=2, REFUSE=3} is sufficient.

No probabilities. No embeddings. No LLM calls. No async. No state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from core.policy import (
    POLICY_REGISTRY,
    PolicySignal,
    VERDICT_NAMES,
    PROCEED,
)


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Verdict:
    """
    The authoritative output of one frame evaluation.

    Fields
    ------
    frame_id          : ID of the frame that was evaluated.
    final_verdict     : The dominant verdict integer (0-3).
    dominant_signal   : The PolicySignal that produced the final verdict.
                        If two signals tie, the first encountered wins
                        (registry order is the tiebreaker — deterministic).
    all_signals       : All signals emitted, in evaluation order.
    frame_hash        : SHA-256 of the canonical frame bytes (computed by caller
                        or by evaluate(); confirms what was evaluated).
    """
    frame_id:         str
    final_verdict:    int
    dominant_signal:  PolicySignal
    all_signals:      tuple[PolicySignal, ...]
    frame_hash:       str

    def verdict_name(self) -> str:
        return VERDICT_NAMES[self.final_verdict]

    def to_dict(self) -> dict:
        return {
            "frame_id":       self.frame_id,
            "final_verdict":  self.final_verdict,
            "verdict_name":   self.verdict_name(),
            "dominant_signal": self.dominant_signal.to_dict(),
            "all_signals":    [s.to_dict() for s in self.all_signals],
            "frame_hash":     self.frame_hash,
        }


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

def evaluate(frame, *, frame_hash: str = "") -> Verdict:
    """
    Evaluate a MachineTraceFrame against the full policy registry.

    Parameters
    ----------
    frame       : A MachineTraceFrame instance.
    frame_hash  : Pre-computed canonical hash of the frame (optional but
                  recommended for replay verification). If empty string,
                  evaluation proceeds without hash binding.

    Returns
    -------
    Verdict with the monotonically resolved final decision.

    Raises
    ------
    RuntimeError if POLICY_REGISTRY is empty (should not happen in production).
    """
    if not POLICY_REGISTRY:
        raise RuntimeError("POLICY_REGISTRY is empty — no policies loaded.")

    signals: list[PolicySignal] = []

    for policy_fn in POLICY_REGISTRY:
        signal = policy_fn(frame)
        if not isinstance(signal, PolicySignal):
            raise TypeError(
                f"Policy {policy_fn.__name__} returned {type(signal).__name__}, "
                f"expected PolicySignal."
            )
        signals.append(signal)

    # Monotonic resolution: highest verdict wins.
    # Tiebreaker: first signal with the maximum verdict (registry order).
    dominant = max(signals, key=lambda s: s.verdict)

    return Verdict(
        frame_id=frame.frame_id,
        final_verdict=dominant.verdict,
        dominant_signal=dominant,
        all_signals=tuple(signals),
        frame_hash=frame_hash,
    )


def evaluate_with_hash(frame) -> tuple[Verdict, str]:
    """
    Convenience wrapper that computes the canonical hash before evaluating.
    Returns (Verdict, frame_hash_hex).

    Use this as the standard path so every verdict is bound to a frame hash.
    """
    from core.canonicalizer import canonicalise
    from core.hashes import hash_canonical

    canonical_bytes = canonicalise(frame.to_dict())
    frame_hash = hash_canonical(canonical_bytes)
    verdict = evaluate(frame, frame_hash=frame_hash)
    return verdict, frame_hash
