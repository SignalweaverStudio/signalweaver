from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal


GateDecisionKind = Literal["proceed", "gate", "refuse"]


@dataclass
class UserState:
    """
    arousal/dominance are categorical strings:
      'low' | 'med' | 'high' | 'unknown'
    request is optional (used by replay/trace paths).
    """
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


def decide(
    state: UserState,
    conflicted_anchor_ids: List[int],
    max_level_conflict: int,
    l3_count: int = 0,
) -> GateDecision:
    """
    Minimal v1.x Gate logic with UI-ready next actions.
    """

    # Multiple L3 conflicts: hard refuse — intent must change, not wording
    if max_level_conflict >= 3 and l3_count >= 2:
        return GateDecision(
            decision="refuse",
            reason="multi_l3_conflict",
            conflicted_anchor_ids=conflicted_anchor_ids,
            interpretation=(
                "Multiple protected constraints are violated simultaneously. "
                "This action cannot proceed under any framing."
            ),
            suggestion="The intent itself conflicts with core policy. Redesign the action, not the wording.",
            next_actions=["cancel", "view_conflicts"],
        )

    # Single L3 conflict: gate for review
    if max_level_conflict >= 3:
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
            )

        return GateDecision(
            decision="gate",
            reason="l3_anchor_conflict",
            conflicted_anchor_ids=conflicted_anchor_ids,
            interpretation="This conflicts with a level-3 boundary (protected constraint).",
            suggestion="Rephrase the request so it stays within the boundary.",
            next_actions=["reframe", "view_conflicts", "cancel"],
        )

    # Lower-level conflicts: proceed, but warn
    if conflicted_anchor_ids:
        return GateDecision(
            decision="proceed",
            reason="low_level_conflict",
            conflicted_anchor_ids=conflicted_anchor_ids,
            interpretation="Minor conflicts detected, but nothing high-priority was violated.",
            suggestion="Proceed, but tighten wording to avoid drift.",
            next_actions=["proceed", "tighten_wording", "view_conflicts"],
        )

    # No conflicts
    return GateDecision(
        decision="proceed",
        reason="no_high_conflict",
        conflicted_anchor_ids=[],
        interpretation="No conflicts detected against active anchors.",
        suggestion="Proceed normally.",
        next_actions=["proceed"],
    )
