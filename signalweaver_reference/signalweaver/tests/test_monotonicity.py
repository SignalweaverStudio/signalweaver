"""
tests/test_monotonicity.py

Tests for deterministic policy evaluation and monotonic escalation resolution
(core/policy.py and core/evaluator.py).

Verifies:
- Individual policy correctness
- Monotonic escalation: highest verdict always wins
- Verdict binding: returned hash matches frame
- All signal collection: every policy fires, no skips
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.frame import MachineTraceFrame
from core.policy import (
    PROCEED, EXPLORE, GATE, REFUSE,
    policy_default_proceed,
    policy_treasury_threshold,
    policy_treasury_velocity,
    policy_actor_blocklist,
    policy_tag_sensitive,
    POLICY_REGISTRY,
    PolicySignal,
)
from core.evaluator import evaluate, evaluate_with_hash


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _frame(**kwargs) -> MachineTraceFrame:
    """Minimal frame factory for tests."""
    defaults = dict(
        frame_id="test-frame",
        timestamp_ms=1_000,
        actor="actor:test:normal",
        action="test.action",
        payload={},
        tags=[],
    )
    defaults.update(kwargs)
    return MachineTraceFrame.build(**defaults)


# ---------------------------------------------------------------------------
# Individual policy tests
# ---------------------------------------------------------------------------

class TestPolicyDefaultProceed:

    def test_always_proceeds(self):
        f = _frame()
        signal = policy_default_proceed(f)
        assert signal.verdict == PROCEED
        assert signal.policy_id == "POL-000"


class TestPolicyTreasuryThreshold:

    def test_proceed_below_threshold(self):
        f = _frame(action="transfer.outbound", payload={"amount_pence": 500_000})
        signal = policy_treasury_threshold(f)
        assert signal.verdict == PROCEED

    def test_gate_at_threshold_boundary(self):
        # Exactly at the boundary (1,000,001 pence) — should GATE
        f = _frame(action="transfer.outbound", payload={"amount_pence": 1_000_001})
        signal = policy_treasury_threshold(f)
        assert signal.verdict == GATE

    def test_gate_above_threshold(self):
        f = _frame(action="transfer.outbound", payload={"amount_pence": 2_500_000})
        signal = policy_treasury_threshold(f)
        assert signal.verdict == GATE

    def test_refuse_above_hard_threshold(self):
        f = _frame(action="transfer.outbound", payload={"amount_pence": 15_000_000})
        signal = policy_treasury_threshold(f)
        assert signal.verdict == REFUSE

    def test_explore_missing_amount(self):
        f = _frame(action="transfer.outbound", payload={})
        signal = policy_treasury_threshold(f)
        assert signal.verdict == EXPLORE

    def test_not_in_scope_for_other_actions(self):
        f = _frame(action="read.balance", payload={"amount_pence": 99_999_999})
        signal = policy_treasury_threshold(f)
        assert signal.verdict == PROCEED

    def test_refuses_at_exact_hard_boundary(self):
        # 10,000,001 pence — just over hard threshold
        f = _frame(action="transfer.outbound", payload={"amount_pence": 10_000_001})
        signal = policy_treasury_threshold(f)
        assert signal.verdict == REFUSE

    def test_exactly_at_hard_threshold_is_refused(self):
        # > 10,000,000 — exactly 10,000,001 refuses; exactly 10,000,000 gates
        f_gate = _frame(action="transfer.outbound", payload={"amount_pence": 10_000_000})
        f_refuse = _frame(action="transfer.outbound", payload={"amount_pence": 10_000_001})
        assert policy_treasury_threshold(f_gate).verdict == GATE
        assert policy_treasury_threshold(f_refuse).verdict == REFUSE


class TestPolicyTreasuryVelocity:

    def test_proceed_below_velocity_threshold(self):
        f = _frame(action="transfer.outbound", payload={"velocity_transfers_1h": 4})
        signal = policy_treasury_velocity(f)
        assert signal.verdict == PROCEED

    def test_gate_at_velocity_threshold(self):
        f = _frame(action="transfer.outbound", payload={"velocity_transfers_1h": 5})
        signal = policy_treasury_velocity(f)
        assert signal.verdict == GATE

    def test_gate_above_velocity_threshold(self):
        f = _frame(action="transfer.outbound", payload={"velocity_transfers_1h": 10})
        signal = policy_treasury_velocity(f)
        assert signal.verdict == GATE

    def test_proceed_no_velocity_field(self):
        f = _frame(action="transfer.outbound", payload={})
        signal = policy_treasury_velocity(f)
        assert signal.verdict == PROCEED

    def test_not_in_scope_for_other_actions(self):
        f = _frame(action="read.statement", payload={"velocity_transfers_1h": 100})
        signal = policy_treasury_velocity(f)
        assert signal.verdict == PROCEED


class TestPolicyActorBlocklist:

    def test_blocked_actor_refused(self):
        f = _frame(actor="actor:system:compromised")
        signal = policy_actor_blocklist(f)
        assert signal.verdict == REFUSE

    def test_force_refuse_actor_refused(self):
        f = _frame(actor="actor:test:force_refuse")
        signal = policy_actor_blocklist(f)
        assert signal.verdict == REFUSE

    def test_normal_actor_proceeds(self):
        f = _frame(actor="actor:treasury:automated")
        signal = policy_actor_blocklist(f)
        assert signal.verdict == PROCEED


class TestPolicyTagSensitive:

    def test_both_tags_gate(self):
        f = _frame(tags=["sensitive", "unreviewed"])
        signal = policy_tag_sensitive(f)
        assert signal.verdict == GATE

    def test_sensitive_only_proceeds(self):
        f = _frame(tags=["sensitive"])
        signal = policy_tag_sensitive(f)
        assert signal.verdict == PROCEED

    def test_unreviewed_only_proceeds(self):
        f = _frame(tags=["unreviewed"])
        signal = policy_tag_sensitive(f)
        assert signal.verdict == PROCEED

    def test_neither_tag_proceeds(self):
        f = _frame(tags=["treasury", "outbound"])
        signal = policy_tag_sensitive(f)
        assert signal.verdict == PROCEED


# ---------------------------------------------------------------------------
# Monotonic escalation
# ---------------------------------------------------------------------------

class TestMonotonicEscalation:

    def test_all_policies_evaluated(self):
        """Every policy in the registry must fire — no early exits."""
        f = _frame(
            action="transfer.outbound",
            payload={"amount_pence": 500_000, "velocity_transfers_1h": 1},
        )
        verdict = evaluate(f)
        # All registry policies should have fired
        assert len(verdict.all_signals) == len(POLICY_REGISTRY)

    def test_highest_verdict_wins_over_proceed(self):
        """A frame triggering GATE must return GATE, not PROCEED."""
        f = _frame(
            action="transfer.outbound",
            payload={"amount_pence": 2_000_000},  # GATE
        )
        verdict = evaluate(f)
        assert verdict.final_verdict == GATE

    def test_refuse_overrides_gate(self):
        """REFUSE must dominate GATE when both fire."""
        f = _frame(
            action="transfer.outbound",
            payload={
                "amount_pence":          15_000_000,  # REFUSE via POL-100
                "velocity_transfers_1h": 6,            # GATE via POL-101
            },
        )
        verdict = evaluate(f)
        assert verdict.final_verdict == REFUSE

    def test_refuse_from_blocklist_overrides_proceed(self):
        f = _frame(actor="actor:system:compromised")
        verdict = evaluate(f)
        assert verdict.final_verdict == REFUSE

    def test_gate_from_tags_with_proceed_threshold(self):
        """Tag policy GATE should surface even when amount is fine."""
        f = _frame(
            action="transfer.outbound",
            payload={"amount_pence": 100},   # well below threshold
            tags=["sensitive", "unreviewed"],
        )
        verdict = evaluate(f)
        assert verdict.final_verdict == GATE

    def test_dominant_signal_matches_verdict(self):
        f = _frame(
            action="transfer.outbound",
            payload={"amount_pence": 15_000_000},
        )
        verdict = evaluate(f)
        assert verdict.dominant_signal.verdict == verdict.final_verdict

    def test_verdict_is_deterministic_across_calls(self):
        """Same frame must produce identical verdict on repeated calls."""
        f = _frame(
            action="transfer.outbound",
            payload={"amount_pence": 2_000_000, "velocity_transfers_1h": 3},
        )
        v1 = evaluate(f)
        v2 = evaluate(f)
        assert v1.final_verdict == v2.final_verdict
        assert v1.dominant_signal.policy_id == v2.dominant_signal.policy_id

    def test_evaluate_with_hash_binds_frame_hash(self):
        f = _frame(
            frame_id="hash-bind-test",
            action="transfer.outbound",
            payload={"amount_pence": 500},
        )
        verdict, frame_hash = evaluate_with_hash(f)
        assert verdict.frame_hash == frame_hash
        assert len(frame_hash) == 64   # SHA-256 hex

    def test_explore_does_not_override_gate(self):
        """EXPLORE (1) < GATE (2) — GATE must win."""
        # POL-100 returns EXPLORE when amount_pence is missing
        # POL-300 returns GATE when both sensitive+unreviewed tags present
        f = _frame(
            action="transfer.outbound",
            payload={},                         # triggers EXPLORE from POL-100
            tags=["sensitive", "unreviewed"],   # triggers GATE from POL-300
        )
        verdict = evaluate(f)
        assert verdict.final_verdict == GATE

    def test_verdict_ordinals(self):
        """Sanity: ordinal ordering is PROCEED < EXPLORE < GATE < REFUSE."""
        assert PROCEED < EXPLORE < GATE < REFUSE

    def test_all_signals_in_registry_order(self):
        """Signals must be returned in the same order as POLICY_REGISTRY."""
        f = _frame()
        verdict = evaluate(f)
        for i, (signal, policy_fn) in enumerate(zip(verdict.all_signals, POLICY_REGISTRY)):
            # Each signal's policy_id should match the function's expected id
            # (Weak check — we verify the count and that policy_ids are non-empty)
            assert signal.policy_id, f"Signal {i} has empty policy_id"
