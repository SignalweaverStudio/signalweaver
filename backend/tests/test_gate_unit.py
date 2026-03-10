"""
Unit tests for app.gate.decide()

These tests are pure (no DB, no HTTP) — run with:
    pytest tests/test_gate_unit.py
from the backend/src directory (or set PYTHONPATH=src).
"""
import sys
import os

# Ensure the src package is importable when running from the backend root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from app.gate import UserState, GateDecision, decide


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _state(arousal: str = "unknown", dominance: str = "unknown") -> UserState:
    return UserState(arousal=arousal, dominance=dominance)


# ---------------------------------------------------------------------------
# No-conflict cases
# ---------------------------------------------------------------------------

def test_no_conflicts_proceeds():
    result = decide(_state(), [], 0)
    assert result.decision == "proceed"
    assert result.reason == "no_high_conflict"
    assert result.conflicted_anchor_ids == []
    assert result.next_actions == ["proceed"]


def test_no_conflicts_any_state_proceeds():
    for arousal in ("low", "med", "high", "unknown"):
        for dominance in ("low", "med", "high", "unknown"):
            result = decide(_state(arousal, dominance), [], 0)
            assert result.decision == "proceed", f"Expected proceed for {arousal}/{dominance}"


# ---------------------------------------------------------------------------
# Low-level conflict (L1/L2) — advisory proceed
# ---------------------------------------------------------------------------

def test_low_level_conflict_proceeds():
    result = decide(_state(), [1, 2], 2)
    assert result.decision == "proceed"
    assert result.reason == "low_level_conflict"
    assert result.conflicted_anchor_ids == [1, 2]


def test_low_level_conflict_has_next_actions():
    result = decide(_state(), [5], 1)
    assert "proceed" in result.next_actions
    assert "view_conflicts" in result.next_actions


def test_low_level_conflict_max_level_2_proceeds():
    # State does not affect L1/L2 outcome; high/low state only matters at L3.
    result = decide(_state("high", "low"), [10], 2)
    assert result.decision == "proceed"


# ---------------------------------------------------------------------------
# L3 conflict — standard gate (single L3)
# ---------------------------------------------------------------------------

def test_l3_conflict_gates():
    result = decide(_state(), [3], 3, num_l3_conflicts=1)
    assert result.decision == "gate"
    assert result.reason == "l3_anchor_conflict"
    assert 3 in result.conflicted_anchor_ids


def test_l3_conflict_has_reframe_action():
    result = decide(_state(), [3], 3, num_l3_conflicts=1)
    assert "reframe" in result.next_actions
    assert "view_conflicts" in result.next_actions


def test_l3_conflict_includes_suggestion():
    result = decide(_state(), [3], 3, num_l3_conflicts=1)
    assert result.suggestion
    assert result.interpretation


def test_l3_conflict_neutral_state_uses_generic_reason():
    result = decide(_state("low", "high"), [3], 3, num_l3_conflicts=1)
    assert result.reason == "l3_anchor_conflict"


# ---------------------------------------------------------------------------
# L3 conflict — state mismatch (high arousal + low dominance, single L3)
# ---------------------------------------------------------------------------

def test_l3_state_mismatch_gates_with_specific_reason():
    result = decide(_state(arousal="high", dominance="low"), [3], 3, num_l3_conflicts=1)
    assert result.decision == "gate"
    assert result.reason == "state_mismatch_with_l3_anchor"


def test_l3_state_mismatch_suggests_pause():
    result = decide(_state(arousal="high", dominance="low"), [3], 3, num_l3_conflicts=1)
    assert "pause" in result.next_actions
    assert "reframe" in result.next_actions


def test_l3_state_mismatch_only_on_high_arousal_low_dominance():
    """Only the exact high/low combination triggers the mismatch path."""
    for arousal, dominance in [
        ("high", "high"),
        ("high", "med"),
        ("med", "low"),
        ("low", "low"),
        ("unknown", "unknown"),
    ]:
        result = decide(_state(arousal, dominance), [3], 3, num_l3_conflicts=1)
        assert result.reason == "l3_anchor_conflict", (
            f"Expected l3_anchor_conflict for {arousal}/{dominance}, got {result.reason}"
        )


# ---------------------------------------------------------------------------
# Multi-L3 conflict — refuse
# ---------------------------------------------------------------------------

def test_multi_l3_refuses():
    result = decide(_state(), [3, 7], 3, num_l3_conflicts=2)
    assert result.decision == "refuse"


def test_multi_l3_refuse_reason():
    result = decide(_state(), [3, 7], 3, num_l3_conflicts=2)
    assert result.reason == "multi_l3_conflict"


def test_multi_l3_refuse_carries_all_conflict_ids():
    result = decide(_state(), [3, 7, 12], 3, num_l3_conflicts=3)
    assert result.decision == "refuse"
    assert result.conflicted_anchor_ids == [3, 7, 12]


def test_multi_l3_refuse_has_interpretation_and_suggestion():
    result = decide(_state(), [3, 7], 3, num_l3_conflicts=2)
    assert result.interpretation
    assert result.suggestion


def test_multi_l3_refuse_next_actions_no_reframe():
    """Refuse is final — reframe should not be offered."""
    result = decide(_state(), [3, 7], 3, num_l3_conflicts=2)
    assert "reframe" not in result.next_actions
    assert "cancel" in result.next_actions
    assert "view_conflicts" in result.next_actions


def test_multi_l3_boundary_exactly_two_refuses():
    result = decide(_state(), [3, 7], 3, num_l3_conflicts=2)
    assert result.decision == "refuse"


def test_single_l3_does_not_refuse():
    """num_l3_conflicts=1 must gate, not refuse."""
    result = decide(_state(), [3], 3, num_l3_conflicts=1)
    assert result.decision == "gate"
    assert result.decision != "refuse"


def test_multi_l3_takes_priority_over_state_mismatch():
    """Multi-L3 refuse should fire before the state-mismatch gate check."""
    result = decide(_state(arousal="high", dominance="low"), [3, 7], 3, num_l3_conflicts=2)
    assert result.decision == "refuse"
    assert result.reason == "multi_l3_conflict"


def test_multi_l3_takes_priority_across_all_states():
    """All state combinations yield refuse when num_l3_conflicts > 1."""
    for arousal in ("low", "med", "high", "unknown"):
        for dominance in ("low", "med", "high", "unknown"):
            result = decide(_state(arousal, dominance), [3, 7], 3, num_l3_conflicts=2)
            assert result.decision == "refuse", (
                f"Expected refuse for {arousal}/{dominance}, got {result.decision}"
            )


# ---------------------------------------------------------------------------
# max_level_conflict boundary (num_l3_conflicts=0 used deliberately to test
# the level check in isolation — real callers always pass the correct count)
# ---------------------------------------------------------------------------

def test_max_level_exactly_3_triggers_l3_block():
    result = decide(_state(), [1], 3, num_l3_conflicts=0)
    assert result.decision == "gate"


def test_max_level_above_3_triggers_l3_block():
    # Shouldn't happen in practice (levels are 1–3), but the guard is >=3
    result = decide(_state(), [1], 5, num_l3_conflicts=0)
    assert result.decision == "gate"


def test_max_level_2_with_conflicts_proceeds():
    result = decide(_state(), [1, 2], 2)
    assert result.decision == "proceed"


# ---------------------------------------------------------------------------
# Return type / shape
# ---------------------------------------------------------------------------

def test_decide_always_returns_gate_decision():
    cases = [
        ([], 0, 0),
        ([1], 1, 0),
        ([2], 3, 1),    # single L3 → gate
        ([3, 7], 3, 2), # multi-L3 → refuse
    ]
    for ids, level, num_l3 in cases:
        result = decide(_state(), ids, level, num_l3_conflicts=num_l3)
        assert isinstance(result, GateDecision)


def test_next_actions_always_list():
    cases = [
        ([], 0, 0),
        ([1], 1, 0),
        ([2], 3, 1),
        ([3, 7], 3, 2),
    ]
    for ids, level, num_l3 in cases:
        result = decide(_state(), ids, level, num_l3_conflicts=num_l3)
        assert isinstance(result.next_actions, list)
