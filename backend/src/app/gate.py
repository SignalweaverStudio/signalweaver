from dataclasses import dataclass
from typing import List


@dataclass
class UserState:
    arousal: str       # low/med/high/unknown
    dominance: str     # low/med/high/unknown


@dataclass
class GateDecision:
    decision: str      # proceed | gate | refuse
    reason: str
    conflicted_anchor_ids: List[int]
    interpretation: str
    suggestion: str
    next_actions: List[str]   # UI-ready actions


def decide(
    state: UserState,
    conflicted_anchor_ids: List[int],
    max_level_conflict: int,
    num_l3_conflicts: int = 0,
) -> GateDecision:
    """
    Gate decision logic (v1.3).

    Decision priority (highest → lowest):
      1. multi_l3_conflict                 num_l3_conflicts > 1          → refuse
      2. state_mismatch_with_l3_anchor     L3 + high-arousal/low-control → gate
      3. l3_anchor_conflict                any single L3 conflict        → gate
      4. state_mismatch_with_l2_anchor     L2 + high-arousal/low-control → gate (soft)
      5. l2_anchor_conflict                any L2 conflict               → gate (soft)
      6. l1_advisory_conflict              L1 conflicts only             → proceed (advisory)
      7. no_conflict                       no conflicts at all           → proceed
    """

    # --- Level 3: hard gate ---
    if max_level_conflict >= 3:

        # Refuse: multiple L3 anchors fire simultaneously — too severe to reframe.
        if num_l3_conflicts > 1:
            return GateDecision(
                decision="refuse",
                reason="multi_l3_conflict",
                conflicted_anchor_ids=conflicted_anchor_ids,
                interpretation="Multiple level-3 boundaries conflict with this request simultaneously.",
                suggestion="This request cannot be reframed. Review the active L3 anchors or seek guidance.",
                next_actions=["view_conflicts", "cancel"],
            )

        # Gate: single L3 conflict while in a dysregulated state.
        if state.arousal == "high" and state.dominance == "low":
            return GateDecision(
                decision="gate",
                reason="state_mismatch_with_l3_anchor",
                conflicted_anchor_ids=conflicted_anchor_ids,
                interpretation="This conflicts with a level-3 boundary while your state reads high-arousal / low-control.",
                suggestion="Pause, then reframe the intent to align with the boundary.",
                next_actions=["pause", "reframe", "view_conflicts"],
            )
        return GateDecision(
            decision="gate",
            reason="l3_anchor_conflict",
            conflicted_anchor_ids=conflicted_anchor_ids,
            interpretation="This conflicts with a level-3 boundary (protected constraint).",
            suggestion="Rephrase the request so it stays within the boundary.",
            next_actions=["reframe", "view_conflicts", "cancel"],
        )

    # --- Level 2: soft gate ---
    if max_level_conflict == 2:
        if state.arousal == "high" and state.dominance == "low":
            return GateDecision(
                decision="gate",
                reason="state_mismatch_with_l2_anchor",
                conflicted_anchor_ids=conflicted_anchor_ids,
                interpretation="This conflicts with a level-2 policy while your state reads high-arousal / low-control.",
                suggestion="Consider pausing. You can reframe or proceed with acknowledgement.",
                next_actions=["pause", "reframe", "proceed_acknowledged", "view_conflicts"],
            )
        return GateDecision(
            decision="gate",
            reason="l2_anchor_conflict",
            conflicted_anchor_ids=conflicted_anchor_ids,
            interpretation="This conflicts with a level-2 policy constraint.",
            suggestion="Reframe the request to stay within the boundary, or proceed with acknowledgement.",
            next_actions=["reframe", "proceed_acknowledged", "view_conflicts"],
        )

    # --- Level 1: advisory (proceed with warning) ---
    if max_level_conflict == 1:
        return GateDecision(
            decision="proceed",
            reason="l1_advisory_conflict",
            conflicted_anchor_ids=conflicted_anchor_ids,
            interpretation="A low-priority advisory constraint was noted. No block applied.",
            suggestion="Proceed, but review the flagged anchor for alignment.",
            next_actions=["proceed", "view_conflicts"],
        )

    # --- No conflict ---
    return GateDecision(
        decision="proceed",
        reason="no_conflict",
        conflicted_anchor_ids=[],
        interpretation="No conflicts detected against active anchors.",
        suggestion="Proceed normally.",
        next_actions=["proceed"],
    )