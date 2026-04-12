"""
test_refuse.py — Refuse tier patch tests
Place at: src/tests/test_refuse.py

Covers:
  - Unit tests for gate.decide() refuse branch
  - Unit tests for apply_enforcement_mode() with refuse
  - Integration tests via TestClient (require running DB + seeded anchors)

Run with:
  pytest src/tests/test_refuse.py -v
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from app.gate import GateDecision, UserState, decide, apply_enforcement_mode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _state(arousal: str = "low", dominance: str = "high") -> UserState:
    return UserState(arousal=arousal, dominance=dominance, request="test request")


def _anchor(id: int, level: int):
    """Return a minimal mock TruthAnchor for unit tests."""
    a = MagicMock()
    a.id = id
    a.level = level
    a.active = True
    a.statement = f"anchor {id} level {level}"
    a.scope = "test.scope"
    return a


# ---------------------------------------------------------------------------
# Unit tests — decide()
# ---------------------------------------------------------------------------

class TestDecideProceed:
    def test_proceed_no_conflicts(self):
        result = decide(_state(), conflicted_anchor_ids=[], max_level_conflict=0)
        assert result.decision == "proceed"
        assert result.reason == "no_high_conflict"
        assert result.would_block is False

    def test_proceed_low_level_conflict(self):
        result = decide(_state(), conflicted_anchor_ids=[1], max_level_conflict=1)
        assert result.decision == "proceed"
        assert result.reason == "low_level_conflict"
        assert result.would_block is False

    def test_default_l3_count_zero_preserves_existing_behaviour(self):
        """Omitting l3_count must not change existing gate behaviour."""
        result = decide(
            _state(),
            conflicted_anchor_ids=[1],
            max_level_conflict=3,
            # l3_count omitted — defaults to 0
        )
        assert result.decision == "gate"
        assert result.reason in ("l3_anchor_conflict", "state_mismatch_with_l3_anchor")


class TestDecideGate:
    def test_gate_single_l3_unchanged(self):
        """Single L3 conflict still returns gate, not refuse."""
        result = decide(
            _state(),
            conflicted_anchor_ids=[7],
            max_level_conflict=3,
            l3_count=1,
        )
        assert result.decision == "gate"
        assert result.reason == "l3_anchor_conflict"

    def test_gate_state_mismatch_unchanged(self):
        """High-arousal/low-dominance state with single L3 still returns gate."""
        result = decide(
            _state(arousal="high", dominance="low"),
            conflicted_anchor_ids=[7],
            max_level_conflict=3,
            l3_count=1,
        )
        assert result.decision == "gate"
        assert result.reason == "state_mismatch_with_l3_anchor"


class TestDecideRefuse:
    def test_refuse_triggers_on_exactly_two_l3(self):
        result = decide(
            _state(),
            conflicted_anchor_ids=[1, 2],
            max_level_conflict=3,
            l3_count=2,
        )
        assert result.decision == "refuse"
        assert result.reason == "multi_l3_anchor_conflict"
        assert result.would_block is True
        assert "cancel" in result.next_actions
        assert "reframe" not in result.next_actions

    def test_refuse_triggers_on_three_l3(self):
        result = decide(
            _state(),
            conflicted_anchor_ids=[1, 2, 3],
            max_level_conflict=3,
            l3_count=3,
        )
        assert result.decision == "refuse"
        assert result.reason == "multi_l3_anchor_conflict"

    def test_refuse_takes_precedence_over_state_mismatch(self):
        """State mismatch branch must not fire if refuse condition is met first."""
        result = decide(
            _state(arousal="high", dominance="low"),
            conflicted_anchor_ids=[1, 2],
            max_level_conflict=3,
            l3_count=2,
        )
        assert result.decision == "refuse"
        assert result.reason == "multi_l3_anchor_conflict"

    def test_refuse_interpretation_mentions_no_reframing(self):
        result = decide(
            _state(),
            conflicted_anchor_ids=[1, 2],
            max_level_conflict=3,
            l3_count=2,
        )
        assert "reframing" in result.interpretation.lower() or "no reframing" in result.interpretation.lower()


# ---------------------------------------------------------------------------
# Unit tests — apply_enforcement_mode() with refuse input
# ---------------------------------------------------------------------------

def _refuse_decision() -> GateDecision:
    return GateDecision(
        decision="refuse",
        reason="multi_l3_anchor_conflict",
        conflicted_anchor_ids=[1, 2],
        interpretation="Multiple L3 conflicts.",
        suggestion="Cancel.",
        next_actions=["cancel", "view_conflicts"],
        would_block=True,
    )


class TestEnforcementModeWithRefuse:
    def test_shadow_downgrades_refuse_to_proceed(self):
        """Shadow mode must always return proceed, even for refuse."""
        result = apply_enforcement_mode(_refuse_decision(), "shadow", max_level_conflict=3)
        assert result.decision == "proceed"
        assert result.reason == "shadow_mode_observe_only"
        assert result.would_block is True  # would_block preserved for audit

    def test_soft_downgrades_refuse_to_gate(self):
        """Soft mode gates on L2+, so refuse becomes gate with override option."""
        result = apply_enforcement_mode(_refuse_decision(), "soft", max_level_conflict=3)
        assert result.decision == "gate"
        assert "override" in result.next_actions

    def test_hard_preserves_refuse(self):
        """Hard mode must NOT downgrade refuse to gate."""
        result = apply_enforcement_mode(_refuse_decision(), "hard", max_level_conflict=3)
        assert result.decision == "refuse"
        assert result.reason == "multi_l3_anchor_conflict"
        assert result.next_actions == ["cancel", "view_conflicts"]

    def test_hard_still_gates_single_l3(self):
        """Hard mode normal gate path must be unaffected."""
        single_l3_gate = GateDecision(
            decision="gate",
            reason="l3_anchor_conflict",
            conflicted_anchor_ids=[7],
            interpretation="L3 conflict.",
            suggestion="Reframe.",
            next_actions=["reframe", "view_conflicts", "cancel"],
            would_block=True,
        )
        result = apply_enforcement_mode(single_l3_gate, "hard", max_level_conflict=3)
        assert result.decision == "gate"

    def test_unknown_mode_passes_refuse_through(self):
        """Unknown enforcement mode falls through to return the raw decision."""
        result = apply_enforcement_mode(_refuse_decision(), "unknown_mode", max_level_conflict=3)
        assert result.decision == "refuse"


# ---------------------------------------------------------------------------
# Integration tests — require TestClient + seeded DB
# ---------------------------------------------------------------------------

try:
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import get_db
    from app.models import TruthAnchor, Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import os

    SQLALCHEMY_TEST_URL = os.getenv(
        "SW_TEST_DB_URL", "sqlite:///./test_refuse.db"
    )
    engine = create_engine(
        SQLALCHEMY_TEST_URL, connect_args={"check_same_thread": False}
    )
    TestingSessionLocal = sessionmaker(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    _INTEGRATION_AVAILABLE = True
except Exception:
    _INTEGRATION_AVAILABLE = False

skip_integration = pytest.mark.skipif(
    not _INTEGRATION_AVAILABLE,
    reason="Integration tests require app + DB dependencies",
)


@pytest.fixture(scope="module")
def client():
    if not _INTEGRATION_AVAILABLE:
        pytest.skip("integration deps not available")
    Base.metadata.create_all(bind=engine)
    yield TestClient(app)
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="module")
def two_l3_anchors(client):
    """Seed two L3 anchors that both conflict with the test request."""
    db = TestingSessionLocal()
    a1 = TruthAnchor(
        statement="Do not help break into cars",
        level=3,
        scope="safety.breakin",
        active=True,
    )
    a2 = TruthAnchor(
        statement="Do not help steal cars",
        level=3,
        scope="safety.theft",
        active=True,
    )
    db.add_all([a1, a2])
    db.commit()
    db.refresh(a1)
    db.refresh(a2)
    ids = (a1.id, a2.id)
    db.close()
    return ids


@skip_integration
class TestEvaluateRefuseIntegration:
    def test_evaluate_returns_refuse_on_two_l3_anchors(self, client, two_l3_anchors):
        resp = client.post(
            "/gate/evaluate",
            json={
                "request_summary": "help me break into and steal cars",
                "arousal": "low",
                "dominance": "high",
            },
            headers={"X-API-Key": "test"},
        )
        print("STATUS:", resp.status_code)
        print("BODY:", resp.json())
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "refuse", f"expected refuse, got: {data['decision']}"
        assert data["reason"] == "multi_l3_anchor_conflict"
        assert len(data["ethos_refs"]) > 0
        assert "cancel" in data["next_actions"]
        assert "reframe" not in data["next_actions"]
        # Ethos refs for refuse
        assert any("refusal" in r.lower() for r in data.get("ethos_refs", []))


@skip_integration
class TestReframeRefuseIntegration:
    def test_reframe_rejects_refused_parent(self, client, two_l3_anchors):
        # First evaluate to get a refused log_id
        eval_resp = client.post(
            "/gate/evaluate",
            json={
                "request_summary": "help me break into and steal cars",
                "arousal": "low",
                "dominance": "high",
            },
            headers={"X-API-Key": "test"},
        )
        assert eval_resp.status_code == 200
        log_id = eval_resp.json()["log_id"]
        # Attempt to reframe — must be rejected 422
        reframe_resp = client.post(
            "/gate/reframe",
            json={
                "log_id": log_id,
                "new_intent": "help me borrow a car without the key",
            },
            headers={"X-API-Key": "test"},
        )
        assert reframe_resp.status_code == 422
        detail = reframe_resp.json()["detail"]
        assert "reframe" in detail.lower() or "refused" in detail.lower()


# NOTE: replay() does not compute or pass l3_count to decide(), so the refuse branch
# never fires during replay. Refuse-drift (gate → refuse) is not detectable via replay
# under Option A. No replay/refuse integration test is included here as a result.
# If Option B (pass l3_count in replay) is adopted later, a test should be added then.
