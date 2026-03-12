from __future__ import annotations
from dataclasses import dataclass
from typing import List, Literal

# PATCH: added "refuse" to the decision kind literal
GateDecisionKind = Literal["proceed", "gate", "refuse"]

@dataclass
class UserState:
    arousal: str
    dominance: str
    request: str = ""

@dataclass
class GateDecision:
    decision: GateDecisionKind
    reason: str
    conflicted_anchor_ids: List[int]
    interpretation: str
    suggestion: str
    next_actions: List[str]
    would_block: bool = False

def decide(
    state: UserState,
    conflicted_anchor_ids: List[int],
    max_level_conflict: int,
    l3_count: int = 0,  # PATCH: count of L3 anchors in the conflict set
) -> GateDecision:
    """
    Core deterministic gate logic. Unchanged from v1.x.
    This function is enforcement-mode-agnostic.

    l3_count: number of conflicting anchors at level >= 3.
    When l3_count >= 2, the request is refused outright — no reframing path exists.
    """
    if max_level_conflict >= 3:
        # PATCH: refuse when two or more L3 anchors conflict simultaneously
        if l3_count >= 2:
            return GateDecision(
                decision="refuse",
                reason="multi_l3_anchor_conflict",
                conflicted_anchor_ids=conflicted_anchor_ids,
                interpretation=(
                    "This request conflicts with multiple level-3 boundaries simultaneously. "
                    "No reframing path is available."
                ),
                suggestion="Cancel this action and reconsider the intent entirely.",
                next_actions=["cancel", "view_conflicts"],
                would_block=True,
            )
        if state.arousal == "high" and state.dominance == "low":
            return GateDecision(
                decision="gate",
                reason="state_mismatch_with_l3_anchor",
                conflicted_anchor_ids=conflicted_anchor_ids,
                interpretation=(
                    "This conflicts with a level-3 boundary while your state reads "
                    "high-arousal / low-control."
                ),
                suggestion="Pause, then reframe the intent to align with the boundary.",
                next_actions=["pause", "reframe", "view_conflicts"],
                would_block=True,
            )
        return GateDecision(
            decision="gate",
            reason="l3_anchor_conflict",
            conflicted_anchor_ids=conflicted_anchor_ids,
            interpretation="This conflicts with a level-3 boundary (protected constraint).",
            suggestion="Rephrase the request so it stays within the boundary.",
            next_actions=["reframe", "view_conflicts", "cancel"],
            would_block=True,
        )
    if conflicted_anchor_ids:
        return GateDecision(
            decision="proceed",
            reason="low_level_conflict",
            conflicted_anchor_ids=conflicted_anchor_ids,
            interpretation="Minor conflicts detected, but nothing high-priority was violated.",
            suggestion="Proceed, but tighten wording to avoid drift.",
            next_actions=["proceed", "tighten_wording", "view_conflicts"],
            would_block=False,
        )
    return GateDecision(
        decision="proceed",
        reason="no_high_conflict",
        conflicted_anchor_ids=[],
        interpretation="No conflicts detected against active anchors.",
        suggestion="Proceed normally.",
        next_actions=["proceed"],
        would_block=False,
    )

def apply_enforcement_mode(
    decision: GateDecision,
    enforcement_mode: str,
    max_level_conflict: int,
) -> GateDecision:
    """
    Applies the governance spectrum on top of the raw gate decision.
    Does NOT mutate the original decision – returns a new one.
    shadow: always return proceed, log would_block
    soft:   gate on L2 and L3, allow override
    hard:   gate on L3 automatically, L2 behaves as soft gate
    """
    mode = enforcement_mode.lower()
    # --- Shadow mode: observe only, never block ---
    if mode == "shadow":
        return GateDecision(
            decision="proceed",
            reason="shadow_mode_observe_only",
            conflicted_anchor_ids=decision.conflicted_anchor_ids,
            interpretation=decision.interpretation,
            suggestion=decision.suggestion,
            next_actions=["proceed"],
            would_block=decision.would_block,
        )
    # --- Soft mode: L2 and L3 both gate, override allowed ---
    if mode == "soft":
        if max_level_conflict >= 2:
            return GateDecision(
                decision="gate",
                reason=decision.reason,
                conflicted_anchor_ids=decision.conflicted_anchor_ids,
                interpretation=decision.interpretation,
                suggestion=decision.suggestion,
                next_actions=["override", "reframe", "view_conflicts"],
                would_block=decision.would_block,
            )
        return decision
    # --- Hard mode: L3 auto-blocks, L2 is soft gate ---
    if mode == "hard":
        if max_level_conflict >= 3:
            # PATCH: refuse decisions pass through hard mode unchanged — do not downgrade to gate
            if decision.decision == "refuse":
                return decision
            return GateDecision(
                decision="gate",
                reason=decision.reason,
                conflicted_anchor_ids=decision.conflicted_anchor_ids,
                interpretation=decision.interpretation,
                suggestion=decision.suggestion,
                next_actions=["reframe", "view_conflicts", "cancel"],
                would_block=True,
            )
        if max_level_conflict == 2:
            return GateDecision(
                decision="gate",
                reason=decision.reason,
                conflicted_anchor_ids=decision.conflicted_anchor_ids,
                interpretation=decision.interpretation,
                suggestion=decision.suggestion,
                next_actions=["override", "reframe", "view_conflicts"],
                would_block=decision.would_block,
            )
        return decision
    # Fallback: treat unknown mode as hard
    return decision
