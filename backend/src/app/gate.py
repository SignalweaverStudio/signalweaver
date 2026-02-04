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

def decide(state: UserState, conflicted_anchor_ids: List[int], max_level_conflict: int) -> GateDecision:
    """
    Minimal v0 Gate logic:
    - If conflict with L3 anchor -> gate
    - If user is dysregulated (high arousal + low dominance) + L3 conflict -> gate (more specific reason)
    - Otherwise proceed
    """
    if max_level_conflict >= 3:
        if state.arousal == "high" and state.dominance == "low":
            return GateDecision("gate", "state_mismatch_with_l3_anchor", conflicted_anchor_ids)
        return GateDecision("gate", "l3_anchor_conflict", conflicted_anchor_ids)

    return GateDecision("proceed", "no_high_conflict", [])
