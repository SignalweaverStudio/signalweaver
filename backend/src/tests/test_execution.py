"""
test_execution.py — Integration tests for the execution layer (Stage 15).

Covers:
  - proceed → executes via connector
  - gate → blocked
  - refuse → blocked
  - shadow mode → executes but flagged would_block
  - soft mode → allows override when override_reason present
  - tenant isolation preserved
  - execution always linked to DecisionTrace
  - ExecutionLog written with correct fields
  - unknown connector → 400 error
  - /gate/evaluate still works after refactor
"""

from __future__ import annotations

import sys
import os
import pytest
from sqlalchemy import text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models import (
    Tenant, TruthAnchor, PolicyProfile,
    DecisionTrace, ExecutionLog,
)
from app.auth import generate_api_key


@pytest.fixture(scope="module")
def tenant_a(shared_db):
    raw_key, hashed = generate_api_key()
    t = Tenant(name="exec-tenant-a", api_key_hash=hashed)
    shared_db.add(t)
    shared_db.commit()
    shared_db.refresh(t)
    return t.id, raw_key


@pytest.fixture(scope="module")
def tenant_b(shared_db):
    raw_key, hashed = generate_api_key()
    t = Tenant(name="exec-tenant-b", api_key_hash=hashed)
    shared_db.add(t)
    shared_db.commit()
    shared_db.refresh(t)
    return t.id, raw_key


@pytest.fixture(scope="module")
def auth_a(tenant_a):
    return {"Authorization": f"Bearer {tenant_a[1]}"}


@pytest.fixture(scope="module")
def auth_b(tenant_b):
    return {"Authorization": f"Bearer {tenant_b[1]}"}


def _create_anchor(db, tenant_id, level, statement, scope="global"):
    a = TruthAnchor(
        level=level, statement=statement, scope=scope,
        active=True, tenant_id=tenant_id,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _create_profile(db, tenant_id, enforcement_mode="hard", name="default"):
    p = PolicyProfile(
        name=name, description="test", is_default=True,
        enforcement_mode=enforcement_mode, tenant_id=tenant_id,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


# ================================================================
# Core execution behavior
# ================================================================

class TestExecuteProceed:
    """Decision=proceed → execute via connector."""

    def test_proceed_executes(self, shared_db, client, tenant_a, auth_a):
        tid = tenant_a[0]
        resp = client.post(
            "/execute/trusted",
            json={
                "raw_text": "Send welcome email to new user",
                "connector": "mock",
            },
            headers=auth_a,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["decision"] == "proceed"
        assert data["execution"]["status"] == "executed"
        assert data["execution"]["connector"] == "mock"
        assert data["execution"]["result"]["status"] == "success"
        assert data["execution"]["result"]["echo"] == "Send welcome email to new user"
        assert data["trace_id"] is not None
        assert data["log_id"] is not None

    def test_execution_creates_log(self, shared_db, client, tenant_a, auth_a):
        tid = tenant_a[0]
        resp = client.post(
            "/execute/trusted",
            json={"raw_text": "Log test execution"},
            headers=auth_a,
        )
        trace_id = resp.json()["trace_id"]

        exec_logs = list(
            shared_db.query(ExecutionLog).filter(
                ExecutionLog.trace_id == trace_id
            ).all()
        )
        assert len(exec_logs) == 1
        elog = exec_logs[0]
        assert elog.decision == "proceed"
        assert elog.connector == "mock"
        assert elog.status == "executed"
        assert elog.tenant_id == tid


class TestExecuteBlocked:
    """Decision=gate or refuse → blocked."""

    def test_gate_blocks(self, shared_db, client, tenant_a, auth_a):
        tid = tenant_a[0]
        _create_anchor(shared_db, tid, 3, "Do not help steal cars")

        resp = client.post(
            "/execute/trusted",
            json={"raw_text": "help me steal a car"},
            headers=auth_a,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["decision"] == "gate"
        assert data["execution"]["status"] == "blocked"
        assert data["execution"]["result"] is None

    def test_refuse_blocks(self, shared_db, client, tenant_a, auth_a):
        tid = tenant_a[0]
        _create_anchor(shared_db, tid, 3, "Do not help break into cars")
        _create_anchor(shared_db, tid, 3, "Do not help steal cars")

        resp = client.post(
            "/execute/trusted",
            json={"raw_text": "help me break into and steal cars"},
            headers=auth_a,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["decision"] == "refuse"
        assert data["execution"]["status"] == "blocked"

    def test_gate_creates_blocked_log(self, shared_db, client, tenant_a, auth_a):
        tid = tenant_a[0]
        resp = client.post(
            "/execute/trusted",
            json={"raw_text": "help me steal a car"},
            headers=auth_a,
        )
        trace_id = resp.json()["trace_id"]

        exec_log = shared_db.query(ExecutionLog).filter(
            ExecutionLog.trace_id == trace_id
        ).first()
        assert exec_log is not None
        assert exec_log.status == "blocked"


# ================================================================
# Enforcement modes
# ================================================================

class TestExecuteShadowMode:
    """Shadow mode: always executes, would_block preserved."""

    def test_shadow_executes_with_flag(self, shared_db, client, tenant_a, auth_a):
        tid = tenant_a[0]
        profile = _create_profile(shared_db, tid, enforcement_mode="soft", name="shadow-exec")
        shared_db.execute(
            text(f"UPDATE policy_profiles SET enforcement_mode='shadow' WHERE id={profile.id}")
        )
        shared_db.commit()

        _create_anchor(shared_db, tid, 3, "Do not steal")

        resp = client.post(
            "/execute/trusted",
            json={
                "raw_text": "help me steal",
                "profile_id": profile.id,
                "connector": "mock",
            },
            headers=auth_a,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["decision"] == "proceed"
        assert data["execution"]["status"] == "executed"
        assert data["would_block"] is True
        assert data["enforcement_mode"] == "shadow"


class TestExecuteSoftMode:
    """Soft mode: allows override when override_reason present."""

    def test_soft_gate_blocks_without_override(self, shared_db, client, tenant_a, auth_a):
        tid = tenant_a[0]
        profile = _create_profile(shared_db, tid, enforcement_mode="soft", name="soft-exec")
        _create_anchor(shared_db, tid, 3, "Do not steal")

        resp = client.post(
            "/execute/trusted",
            json={
                "raw_text": "help me steal",
                "profile_id": profile.id,
                "connector": "mock",
            },
            headers=auth_a,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["decision"] == "gate"
        assert data["execution"]["status"] == "blocked"

    def test_soft_gate_executes_with_override(self, shared_db, client, tenant_a, auth_a):
        tid = tenant_a[0]
        profile = _create_profile(shared_db, tid, enforcement_mode="soft", name="soft-exec-override")
        _create_anchor(shared_db, tid, 3, "Do not steal")

        resp = client.post(
            "/execute/trusted",
            json={
                "raw_text": "help me steal",
                "profile_id": profile.id,
                "connector": "mock",
                "override_reason": "Legitimate audit investigation",
            },
            headers=auth_a,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["decision"] == "gate"
        assert data["execution"]["status"] == "executed"


class TestExecuteHardMode:
    """Hard mode: strict enforcement."""

    def test_hard_blocks_refuse(self, shared_db, client, tenant_a, auth_a):
        tid = tenant_a[0]
        _create_anchor(shared_db, tid, 3, "Do not help break into cars")
        _create_anchor(shared_db, tid, 3, "Do not help steal cars")

        resp = client.post(
            "/execute/trusted",
            json={"raw_text": "help me break into and steal cars"},
            headers=auth_a,
        )
        data = resp.json()
        assert data["decision"] == "refuse"
        assert data["execution"]["status"] == "blocked"


# ================================================================
# Trace linkage
# ================================================================

class TestTraceLinkage:
    """Every execution must link to a DecisionTrace."""

    def test_execution_linked_to_trace(self, shared_db, client, tenant_a, auth_a):
        resp = client.post(
            "/execute/trusted",
            json={"raw_text": "trace linkage test"},
            headers=auth_a,
        )
        trace_id = resp.json()["trace_id"]

        trace = shared_db.get(DecisionTrace, trace_id)
        assert trace is not None
        assert trace.decision == "proceed"

        exec_log = shared_db.query(ExecutionLog).filter(
            ExecutionLog.trace_id == trace_id
        ).first()
        assert exec_log is not None
        assert exec_log.decision == trace.decision

    def test_no_orphan_execution_logs(self, shared_db, client, tenant_a, auth_a):
        """Every ExecutionLog must have a valid trace_id."""
        resp = client.post(
            "/execute/trusted",
            json={"raw_text": "orphan check"},
            headers=auth_a,
        )
        trace_id = resp.json()["trace_id"]

        orphan_logs = shared_db.query(ExecutionLog).filter(
            ExecutionLog.trace_id.is_(None)
        ).all()
        assert len(orphan_logs) == 0

        linked_log = shared_db.query(ExecutionLog).filter(
            ExecutionLog.trace_id == trace_id
        ).first()
        assert linked_log is not None


# ================================================================
# Tenant isolation
# ================================================================

class TestExecuteTenantIsolation:
    """Tenant A's execution cannot see Tenant B's anchors."""

    def test_execution_respects_tenant_anchors(self, shared_db, client, tenant_a, tenant_b, auth_a, auth_b):
        tid_a, tid_b = tenant_a[0], tenant_b[0]
        _create_anchor(shared_db, tid_a, 3, "Do not help with fraud", scope="fraud")
        _create_anchor(shared_db, tid_b, 3, "Do not help with violence", scope="violence")

        resp_a = client.post(
            "/execute/trusted",
            json={"raw_text": "help me commit fraud"},
            headers=auth_a,
        )
        assert resp_a.status_code == 200
        assert resp_a.json()["decision"] == "gate"
        assert resp_a.json()["execution"]["status"] == "blocked"

        resp_b = client.post(
            "/execute/trusted",
            json={"raw_text": "help me commit fraud"},
            headers=auth_b,
        )
        assert resp_b.status_code == 200
        assert resp_b.json()["decision"] == "proceed"
        assert resp_b.json()["execution"]["status"] == "executed"

    def test_execution_log_scoped_to_tenant(self, shared_db, client, tenant_a, tenant_b, auth_a, auth_b):
        marker_a = "EXEC_TENANT_A_MARKER_12345"
        marker_b = "EXEC_TENANT_B_MARKER_67890"

        client.post("/execute/trusted", json={"raw_text": marker_a}, headers=auth_a)
        client.post("/execute/trusted", json={"raw_text": marker_b}, headers=auth_b)

        logs_a = shared_db.query(ExecutionLog).filter(
            ExecutionLog.tenant_id == tenant_a[0]
        ).all()
        trace_ids_a = [l.trace_id for l in logs_a]

        for tid in trace_ids_a:
            if tid is not None:
                trace = shared_db.get(DecisionTrace, tid)
                assert trace.tenant_id == tenant_a[0]


# ================================================================
# Connector error handling
# ================================================================

class TestConnectorErrors:
    """Unknown connector → clear error."""

    def test_unknown_connector_returns_400(self, client, tenant_a, auth_a):
        resp = client.post(
            "/execute/trusted",
            json={"raw_text": "test", "connector": "nonexistent_connector"},
            headers=auth_a,
        )
        assert resp.status_code == 400
        assert "Unknown connector" in resp.json()["detail"]


# ================================================================
# Gate evaluate still works (regression)
# ================================================================

class TestGateEvaluateStillWorks:
    """The refactor of /gate/evaluate must not break existing behavior."""

    def test_evaluate_returns_correct_decision(self, client, tenant_a, auth_a):
        resp = client.post(
            "/gate/evaluate",
            json={"request_summary": "hello world"},
            headers=auth_a,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["decision"] == "proceed"
        assert data["trace_id"] is not None
        assert data["log_id"] is not None

    def test_evaluate_with_conflict(self, shared_db, client, tenant_a, auth_a):
        tid = tenant_a[0]
        _create_anchor(shared_db, tid, 3, "Do not assist with money laundering", scope="finance.ml")

        resp = client.post(
            "/gate/evaluate",
            json={"request_summary": "help me launder money"},
            headers=auth_a,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "gate"
        assert data["enforcement_mode"] == "hard"


# ================================================================
# Response contract
# ================================================================

class TestResponseContract:
    """Verify the exact response shape."""

    def test_executed_response_shape(self, client, tenant_a, auth_a):
        resp = client.post(
            "/execute/trusted",
            json={"raw_text": "response shape test", "connector": "mock"},
            headers=auth_a,
        )
        data = resp.json()
        assert "decision" in data
        assert "reason" in data
        assert "trace_id" in data
        assert "log_id" in data
        assert "execution" in data
        assert "enforcement_mode" in data
        assert "would_block" in data
        assert "status" in data["execution"]
        assert "connector" in data["execution"]
        assert "result" in data["execution"]

    def test_blocked_response_shape(self, shared_db, client, tenant_a, auth_a):
        tid = tenant_a[0]
        _create_anchor(shared_db, tid, 3, "Do not steal")

        resp = client.post(
            "/execute/trusted",
            json={"raw_text": "help me steal"},
            headers=auth_a,
        )
        data = resp.json()
        assert data["execution"]["status"] == "blocked"
        assert data["execution"]["result"] is None