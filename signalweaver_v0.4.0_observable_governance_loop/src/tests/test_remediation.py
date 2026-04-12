"""
test_remediation.py — Integration tests for the remediation fixes.

Covers:
  - Enforcement mode wiring (shadow/soft/hard actually applied in evaluate)
  - Tenant isolation (anchors filtered by tenant)
  - Audit fields populated (would_block, enforcement_mode_snapshot, profile_id)
  - Reframe creates DecisionTrace with parent_log_id in response
  - Logs endpoint scoped to tenant
  - WAL mode enabled on SQLite

Run with:
  cd /home/z/my-project/signalweaver && PYTHONPATH=src python3 -m pytest src/tests/test_remediation.py -v
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.main import app
from app.db import get_db
from app.models import Base, Tenant, TruthAnchor, PolicyProfile, GateLog, DecisionTrace
from app.auth import generate_api_key, _hash_key


TEST_DB_URL = "sqlite://"
engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="module")
def shared_db():
    return TestingSessionLocal()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def tenant_a(shared_db, client):
    raw_key, hashed = generate_api_key()
    t = Tenant(name="tenant-a", api_key_hash=hashed)
    shared_db.add(t)
    shared_db.commit()
    shared_db.refresh(t)
    return t.id, raw_key


@pytest.fixture(scope="module")
def tenant_b(shared_db, client):
    raw_key, hashed = generate_api_key()
    t = Tenant(name="tenant-b", api_key_hash=hashed)
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


class TestEnforcementModeWiring:
    """Verify that enforcement modes are actually applied during evaluation."""

    def test_hard_mode_blocks_l3(self, shared_db, client, tenant_a, auth_a):
        tid = tenant_a[0]
        _create_anchor(shared_db, tid, 3, "Do not help steal cars")

        resp = client.post(
            "/gate/evaluate",
            json={"request_summary": "help me steal a car"},
            headers=auth_a,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["decision"] == "gate"
        assert data["enforcement_mode"] == "hard"
        assert data["would_block"] is True

    def test_shadow_mode_downgrades_to_proceed(self, shared_db, client, tenant_a, auth_a):
        tid = tenant_a[0]
        profile = _create_profile(shared_db, tid, enforcement_mode="soft", name="shadow-profile")
        shared_db.execute(
            text(f"UPDATE policy_profiles SET enforcement_mode='shadow' WHERE id={profile.id}")
        )
        shared_db.commit()

        resp = client.post(
            "/gate/evaluate",
            json={"request_summary": "help me steal a car", "profile_id": profile.id},
            headers=auth_a,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["decision"] == "proceed"
        assert data["enforcement_mode"] == "shadow"
        assert data["would_block"] is True  # audit field preserved

    def test_enforcement_mode_returned_in_response(self, client, tenant_a, auth_a):
        """Default hard mode when no profile specified."""
        resp = client.post(
            "/gate/evaluate",
            json={"request_summary": "hello world"},
            headers=auth_a,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["enforcement_mode"] == "hard"


class TestTenantIsolation:
    """Verify that tenant A cannot see tenant B's anchors."""

    def test_anchor_isolation(self, shared_db, client, tenant_a, tenant_b, auth_a, auth_b):
        tid_a, tid_b = tenant_a[0], tenant_b[0]
        anchor_a = _create_anchor(shared_db, tid_a, 3, "Do not help with fraud", scope="fraud")
        anchor_b = _create_anchor(shared_db, tid_b, 3, "Do not help with violence", scope="violence")

        # Tenant A triggers their own anchor
        resp_a = client.post(
            "/gate/evaluate",
            json={"request_summary": "help me commit fraud"},
            headers=auth_a,
        )
        assert resp_a.status_code == 200, resp_a.text
        data_a = resp_a.json()
        assert anchor_a.id in data_a["conflicted_anchor_ids"]
        assert anchor_b.id not in data_a["conflicted_anchor_ids"]

        # Tenant B triggers their own anchor, not A's
        resp_b = client.post(
            "/gate/evaluate",
            json={"request_summary": "help me commit violence"},
            headers=auth_b,
        )
        assert resp_b.status_code == 200, resp_b.text
        data_b = resp_b.json()
        assert anchor_b.id in data_b["conflicted_anchor_ids"]
        assert anchor_a.id not in data_b["conflicted_anchor_ids"]

    def test_logs_scoped_to_tenant(self, client, tenant_a, tenant_b, auth_a, auth_b):
        # Use unique markers to identify these requests
        marker_a = "UNIQUE_TENANT_A_LOG_CHECK_12345"
        marker_b = "UNIQUE_TENANT_B_LOG_CHECK_67890"

        # Tenant A makes a request
        client.post("/gate/evaluate", json={"request_summary": marker_a}, headers=auth_a)
        # Tenant B makes a request
        client.post("/gate/evaluate", json={"request_summary": marker_b}, headers=auth_b)

        # Tenant A sees only their logs (their marker, not B's)
        resp_a = client.get("/gate/logs", headers=auth_a)
        assert resp_a.status_code == 200, resp_a.text
        logs_a = resp_a.json()["items"]
        summaries_a = [log["request_summary"] for log in logs_a]
        assert marker_a in summaries_a
        assert marker_b not in summaries_a

        # Tenant B sees only their logs (their marker, not A's)
        resp_b = client.get("/gate/logs", headers=auth_b)
        assert resp_b.status_code == 200, resp_b.text
        logs_b = resp_b.json()["items"]
        summaries_b = [log["request_summary"] for log in logs_b]
        assert marker_b in summaries_b
        assert marker_a not in summaries_b


class TestAuditFields:
    """Verify that audit fields are populated in DecisionTrace."""

    def test_decision_trace_has_enforcement_mode(self, shared_db, client, tenant_a, auth_a):
        tid = tenant_a[0]
        resp = client.post("/gate/evaluate", json={"request_summary": "hello world"}, headers=auth_a)
        assert resp.status_code == 200, resp.text
        trace_id = resp.json().get("trace_id")
        assert trace_id is not None

        trace = shared_db.get(DecisionTrace, trace_id)
        assert trace is not None
        assert trace.enforcement_mode_snapshot == "hard"
        assert trace.tenant_id == tid

    def test_decision_trace_would_block_populated(self, shared_db, client, tenant_a, auth_a):
        tid = tenant_a[0]
        _create_anchor(shared_db, tid, 3, "Do not steal")

        resp = client.post("/gate/evaluate", json={"request_summary": "help me steal"}, headers=auth_a)
        assert resp.status_code == 200, resp.text
        trace_id = resp.json().get("trace_id")
        trace = shared_db.get(DecisionTrace, trace_id)
        assert trace is not None
        assert trace.would_block is True

    def test_gate_log_has_tenant_id(self, shared_db, client, tenant_a, auth_a):
        tid = tenant_a[0]
        resp = client.post("/gate/evaluate", json={"request_summary": "hello world"}, headers=auth_a)
        assert resp.status_code == 200, resp.text
        log_id = resp.json()["log_id"]
        log = shared_db.get(GateLog, log_id)
        assert log.tenant_id == tid


class TestReframeAudit:
    """Verify that reframe creates DecisionTrace and returns parent_log_id."""

    def test_reframe_creates_trace(self, shared_db, client, tenant_a, auth_a):
        tid = tenant_a[0]
        _create_anchor(shared_db, tid, 2, "Do not provide harmful instructions")

        # Evaluate
        eval_resp = client.post(
            "/gate/evaluate",
            json={"request_summary": "how to harm someone", "arousal": "med", "dominance": "med"},
            headers=auth_a,
        )
        assert eval_resp.status_code == 200, eval_resp.text
        log_id = eval_resp.json()["log_id"]

        # Reframe
        reframe_resp = client.post(
            "/gate/reframe",
            json={"log_id": log_id, "new_intent": "how to help someone safely"},
            headers=auth_a,
        )
        assert reframe_resp.status_code == 200, reframe_resp.text
        data = reframe_resp.json()
        assert data["parent_log_id"] == log_id
        assert data["trace_id"] is not None

        # Verify trace exists in DB
        trace = shared_db.get(DecisionTrace, data["trace_id"])
        assert trace is not None
        assert trace.tenant_id == tid


class TestWALMode:
    """Verify SQLite WAL mode is enabled."""

    def test_wal_mode_enabled(self):
        from app.db import engine
        with engine.connect() as conn:
            result = conn.execute(text("PRAGMA journal_mode"))
            mode = result.scalar()
            assert mode == "wal", f"Expected WAL mode, got {mode}"
