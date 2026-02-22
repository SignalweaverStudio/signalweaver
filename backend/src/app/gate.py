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


def decide(state: UserState, conflicted_anchor_ids: List[int], max_level_conflict: int) -> GateDecision:
    """
    Minimal v1.2 Gate logic with UI-ready next actions.
    """

    if max_level_conflict >= 3:
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

    if conflicted_anchor_ids:
        return GateDecision(
            decision="proceed",
            reason="low_level_conflict",
            conflicted_anchor_ids=conflicted_anchor_ids,
            interpretation="Minor conflicts detected, but nothing high-priority was violated.",
            suggestion="Proceed, but tighten wording to avoid drift.",
            next_actions=["proceed", "tighten_wording", "view_conflicts"],
        )

    return GateDecision(
        decision="proceed",
        reason="no_high_conflict",
        conflicted_anchor_ids=[],
        interpretation="No conflicts detected against active anchors.",
        suggestion="Proceed normally.",
        next_actions=["proceed"],
    )
