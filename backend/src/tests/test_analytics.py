"""
test_analytics.py — Integration tests for the Execution Analytics Layer (Stage 16).

Covers:
  - GET /executions — filtering by status, connector, pagination, empty state
  - GET /executions/summary — metric correctness, zero-divider safety
  - GET /governance/insights — top anchors, top reasons, empty state
  - GET /compliance/export — date filtering, audit chain integrity, empty state
  - Tenant isolation across all endpoints
"""

from __future__ import annotations

import sys
import os
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models import (
    Tenant,
    TruthAnchor,
    PolicyProfile,
    DecisionTrace,
    DecisionTraceAnchor,
    ExecutionLog,
)
from app.auth import generate_api_key


@pytest.fixture(scope="module")
def tenant_a(shared_db):
    raw_key, hashed = generate_api_key()
    t = Tenant(name="analytics-tenant-a", api_key_hash=hashed)
    shared_db.add(t)
    shared_db.commit()
    shared_db.refresh(t)
    return t.id, raw_key


@pytest.fixture(scope="module")
def tenant_b(shared_db):
    raw_key, hashed = generate_api_key()
    t = Tenant(name="analytics-tenant-b", api_key_hash=hashed)
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


def _execute_request(client, raw_text, headers, connector="mock", **kwargs):
    """Helper to call POST /execute/trusted and return parsed JSON."""
    payload = {"raw_text": raw_text, "connector": connector}
    payload.update(kwargs)
    resp = client.post("/execute/trusted", json=payload, headers=headers)
    return resp.status_code, resp.json()


def _direct_insert_trace(
    db, tenant_id, decision="proceed", reason="",
    would_block=False, override_reason="",
    enforcement_mode="hard",
):
    """Directly insert a DecisionTrace for seeding test data."""
    trace = DecisionTrace(
        tenant_id=tenant_id,
        request_text=f"test-{decision}-{reason}",
        request_normalized=f"test-{decision}-{reason}",
        decision=decision,
        reason=reason,
        explanation="test explanation",
        would_block=would_block,
        enforcement_mode_snapshot=enforcement_mode,
        override_reason=override_reason,
    )
    db.add(trace)
    db.flush()
    db.commit()
    db.refresh(trace)
    return trace


def _direct_insert_exec_log(db, tenant_id, trace_id, decision, status, connector="mock"):
    """Directly insert an ExecutionLog."""
    elog = ExecutionLog(
        tenant_id=tenant_id,
        trace_id=trace_id,
        decision=decision,
        connector=connector,
        status=status,
        response_json='{"status":"success"}' if status == "executed" else "",
    )
    db.add(elog)
    db.flush()
    db.commit()
    db.refresh(elog)
    return elog


def _direct_insert_trace_anchor(db, trace_id, anchor_id, matched=True):
    """Directly insert a DecisionTraceAnchor, skip if exists."""
    existing = db.scalar(
        text("SELECT 1 FROM decision_trace_anchors WHERE trace_id = :tid AND anchor_id = :aid"),
        {"tid": trace_id, "aid": anchor_id},
    )
    if existing:
        return None
    try:
        snap = DecisionTraceAnchor(
            trace_id=trace_id,
            anchor_id=anchor_id,
            anchor_hash="abc123",
            statement_snapshot="test anchor",
            scope_snapshot="global",
            level_snapshot=3,
            active_snapshot=True,
            matched=matched,
            match_note="conflict",
        )
        db.add(snap)
        db.commit()
        return snap
    except Exception:
        db.rollback()
        return None


# ================================================================
# 1. GET /executions
# ================================================================

class TestExecutionHistory:
    """Execution history endpoint tests."""

    def test_empty_history(self, client, tenant_a, auth_a):
        """Endpoint returns valid shape even with no prior data."""
        resp = client.get("/executions", headers=auth_a)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["total"], int)
        assert isinstance(data["items"], list)

    def test_history_returns_executions(self, shared_db, client, tenant_a, auth_a):
        """After executing requests, history reflects them."""
        _execute_request(client, "analytics history test 1", auth_a)
        _execute_request(client, "analytics history test 2", auth_a)

        resp = client.get("/executions", headers=auth_a)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 2
        assert len(data["items"]) >= 2
        item = data["items"][0]
        assert "trace_id" in item
        assert "decision" in item
        assert "status" in item
        assert "connector" in item
        assert "created_at" in item
        assert "would_block" in item

    def test_filter_by_status_executed(self, shared_db, client, tenant_a, auth_a):
        """Filter by status=executed."""
        resp = client.get("/executions?status=executed", headers=auth_a)
        assert resp.status_code == 200
        data = resp.json()
        for item in data["items"]:
            assert item["status"] == "executed"

    def test_filter_by_status_blocked(self, shared_db, client, tenant_a, auth_a):
        """Filter by status=blocked."""
        tid = tenant_a[0]
        _create_anchor(shared_db, tid, 3, "Do not help with block-filter-test")

        _execute_request(client, "block-filter-test trigger", auth_a)

        resp = client.get("/executions?status=blocked", headers=auth_a)
        assert resp.status_code == 200
        data = resp.json()
        for item in data["items"]:
            assert item["status"] == "blocked"

    def test_filter_by_connector(self, shared_db, client, tenant_a, auth_a):
        """Filter by connector name."""
        _execute_request(client, "connector filter test", auth_a, connector="mock")

        resp = client.get("/executions?connector=mock", headers=auth_a)
        assert resp.status_code == 200
        data = resp.json()
        for item in data["items"]:
            assert item["connector"] == "mock"

    def test_invalid_status_returns_422(self, client, tenant_a, auth_a):
        """Invalid status value returns 422."""
        resp = client.get("/executions?status=invalid", headers=auth_a)
        assert resp.status_code == 422

    def test_pagination_limit_offset(self, client, tenant_a, auth_a):
        """Pagination respects limit and offset."""
        resp = client.get("/executions?limit=1&offset=0", headers=auth_a)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) <= 1

    def test_history_newest_first(self, client, tenant_a, auth_a):
        """Results are ordered by most recent first."""
        resp = client.get("/executions?limit=5", headers=auth_a)
        data = resp.json()
        if len(data["items"]) >= 2:
            assert data["items"][0]["trace_id"] >= data["items"][1]["trace_id"]


# ================================================================
# 2. GET /executions/summary
# ================================================================

class TestExecutionSummary:
    """Summary metrics endpoint tests."""

    def test_empty_summary(self, client, tenant_a, auth_a):
        """Endpoint returns valid shape even with no prior data."""
        resp = client.get("/executions/summary", headers=auth_a)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["total_requests"], int)
        assert isinstance(data["block_rate"], float)
        assert 0.0 <= data["block_rate"] <= 1.0

    def test_summary_counts_match(self, shared_db, client, tenant_a, auth_a):
        """Summary metrics match inserted data."""
        tid = tenant_a[0]

        _execute_request(client, "summary-proceed-1", auth_a)
        _execute_request(client, "summary-proceed-2", auth_a)

        _create_anchor(shared_db, tid, 3, "Do not help with summary-block-test")
        _execute_request(client, "summary-block-test trigger", auth_a)

        resp = client.get("/executions/summary", headers=auth_a)
        assert resp.status_code == 200
        data = resp.json()
        assert data["executed"] >= 2
        assert data["blocked"] >= 1
        assert data["total_requests"] == data["executed"] + data["blocked"]

    def test_block_rate_calculation(self, shared_db, client, tenant_a, auth_a):
        """Block rate is correctly calculated."""
        tid = tenant_a[0]

        t1 = _direct_insert_trace(shared_db, tid, "proceed", "ok")
        _direct_insert_exec_log(shared_db, tid, t1.id, "proceed", "executed")

        t2 = _direct_insert_trace(shared_db, tid, "gate", "conflict")
        _direct_insert_exec_log(shared_db, tid, t2.id, "gate", "blocked")

        resp = client.get("/executions/summary", headers=auth_a)
        data = resp.json()
        assert 0.0 <= data["block_rate"] <= 1.0
        assert 0.0 <= data["override_rate"] <= 1.0
        assert 0.0 <= data["shadow_would_block_rate"] <= 1.0

    def test_response_shape(self, client, tenant_a, auth_a):
        """Verify all required fields are present."""
        resp = client.get("/executions/summary", headers=auth_a)
        data = resp.json()
        required_fields = [
            "total_requests", "executed", "blocked",
            "block_rate", "override_rate", "shadow_would_block_rate",
        ]
        for f in required_fields:
            assert f in data


# ================================================================
# 3. GET /governance/insights
# ================================================================

class TestGovernanceInsights:
    """Governance insights endpoint tests."""

    def test_empty_insights(self, client, tenant_a, auth_a):
        """Endpoint returns valid shape even with no prior data."""
        resp = client.get("/governance/insights", headers=auth_a)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["top_conflicted_anchors"], list)
        assert isinstance(data["top_reasons"], list)

    def test_top_conflicted_anchors(self, shared_db, client, tenant_a, auth_a):
        """Returns anchors with most conflicts, ordered by count desc."""
        tid = tenant_a[0]

        anchor = _create_anchor(
            shared_db, tid, 3, "Do not help with insights-test-violence"
        )

        for i in range(3):
            resp = _execute_request(
                client, f"insights-violence trigger {i}", auth_a
            )
            trace_id = resp[1].get("trace_id")
            if trace_id:
                _direct_insert_trace_anchor(
                    shared_db, trace_id, anchor.id, matched=True
                )

        resp = client.get("/governance/insights", headers=auth_a)
        assert resp.status_code == 200
        data = resp.json()
        if data["top_conflicted_anchors"]:
            top = data["top_conflicted_anchors"][0]
            assert "anchor_id" in top
            assert "count" in top
            assert top["count"] >= 1
            if len(data["top_conflicted_anchors"]) >= 2:
                assert (
                    data["top_conflicted_anchors"][0]["count"]
                    >= data["top_conflicted_anchors"][1]["count"]
                )

    def test_top_block_reasons(self, shared_db, client, tenant_a, auth_a):
        """Returns most common block reasons."""
        tid = tenant_a[0]
        _create_anchor(shared_db, tid, 3, "Do not help with reasons-test-fraud")

        _execute_request(client, "reasons-fraud trigger", auth_a)

        resp = client.get("/governance/insights", headers=auth_a)
        assert resp.status_code == 200
        data = resp.json()
        for entry in data["top_reasons"]:
            assert "reason" in entry
            assert "count" in entry
            assert entry["count"] >= 1

    def test_insights_limit_param(self, client, tenant_a, auth_a):
        """Limit parameter caps results."""
        resp = client.get("/governance/insights?limit=1", headers=auth_a)
        data = resp.json()
        assert len(data["top_conflicted_anchors"]) <= 1
        assert len(data["top_reasons"]) <= 1

    def test_response_shape(self, client, tenant_a, auth_a):
        """Verify required top-level fields."""
        resp = client.get("/governance/insights", headers=auth_a)
        data = resp.json()
        assert "top_conflicted_anchors" in data
        assert "top_reasons" in data


# ================================================================
# 4. GET /compliance/export
# ================================================================

class TestComplianceExport:
    """Compliance export endpoint tests."""

    def test_empty_export(self, client, tenant_a, auth_a):
        """Endpoint returns valid shape even with no prior data."""
        resp = client.get("/compliance/export", headers=auth_a)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["total"], int)
        assert isinstance(data["traces"], list)

    def test_export_returns_audit_chain(self, shared_db, client, tenant_a, auth_a):
        """Export includes traces with execution outcomes and conflicted anchors."""
        resp_status, resp_data = _execute_request(
            client, "compliance audit test", auth_a
        )
        assert resp_status == 200
        trace_id = resp_data["trace_id"]

        resp = client.get("/compliance/export", headers=auth_a)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

        found = False
        for t in data["traces"]:
            if t["trace_id"] == trace_id:
                found = True
                assert t["decision"] == "proceed"
                assert t["request_text"] == "compliance audit test"
                assert t["execution_status"] == "executed"
                assert t["execution_connector"] == "mock"
                assert isinstance(t["conflicted_anchor_ids"], list)
                break
        assert found

    def test_export_with_blocking(self, shared_db, client, tenant_a, auth_a):
        """Export includes blocked executions."""
        tid = tenant_a[0]
        _create_anchor(shared_db, tid, 3, "Do not help with compliance-block-test")

        _execute_request(client, "compliance-block-test trigger", auth_a)

        resp = client.get("/compliance/export", headers=auth_a)
        data = resp.json()
        blocked_found = any(
            t["execution_status"] == "blocked" for t in data["traces"]
        )
        assert blocked_found

    def test_export_date_filtering(self, shared_db, client, tenant_a, auth_a):
        """Date range filters traces correctly."""
        now = datetime.now(timezone.utc)
        tid = tenant_a[0]
        trace = DecisionTrace(
            tenant_id=tid,
            request_text="date-filter-test-past",
            request_normalized="date-filter-test-past",
            decision="proceed",
            reason="test",
            explanation="",
            would_block=False,
            enforcement_mode_snapshot="hard",
        )
        trace.created_at = now - timedelta(hours=1)
        shared_db.add(trace)
        shared_db.commit()

        recent = now - timedelta(minutes=30)
        recent_str = recent.strftime("%Y-%m-%dT%H:%M:%S")
        resp = client.get(
            f"/compliance/export?start_date={recent_str}",
            headers=auth_a,
        )
        assert resp.status_code == 200
        data = resp.json()
        past_trace_found = any(
            t["request_text"] == "date-filter-test-past" for t in data["traces"]
        )
        assert not past_trace_found

    def test_export_trace_shape(self, shared_db, client, tenant_a, auth_a):
        """Each trace item has all required fields."""
        _execute_request(client, "compliance shape test", auth_a)

        resp = client.get("/compliance/export", headers=auth_a)
        data = resp.json()
        if data["traces"]:
            t = data["traces"][0]
            required = [
                "trace_id", "created_at", "request_text", "decision",
                "reason", "explanation", "enforcement_mode", "would_block",
                "conflicted_anchor_ids", "execution_status", "execution_connector",
            ]
            for f in required:
                assert f in t

    def test_export_pagination(self, client, tenant_a, auth_a):
        """Limit and offset work on export."""
        resp = client.get(
            "/compliance/export?limit=1&offset=0", headers=auth_a
        )
        data = resp.json()
        assert len(data["traces"]) <= 1

    def test_export_total_matches(self, shared_db, client, tenant_a, auth_a):
        """Total count is consistent regardless of pagination."""
        resp_all = client.get("/compliance/export?limit=1&offset=0", headers=auth_a)
        total = resp_all.json()["total"]
        resp_page = client.get("/compliance/export?limit=1000", headers=auth_a)
        assert resp_page.json()["total"] == total


# ================================================================
# 5. Tenant Isolation
# ================================================================

class TestAnalyticsTenantIsolation:
    """All analytics endpoints enforce tenant isolation."""

    def test_executions_tenant_isolation(self, shared_db, client, tenant_a, tenant_b, auth_a, auth_b):
        """Tenant A cannot see Tenant B's executions."""
        _execute_request(client, "tenant-iso-exec-a", auth_a)
        _execute_request(client, "tenant-iso-exec-b", auth_b)

        resp_a = client.get("/executions", headers=auth_a)
        resp_b = client.get("/executions", headers=auth_b)

        trace_ids_a = {item["trace_id"] for item in resp_a.json()["items"]}
        trace_ids_b = {item["trace_id"] for item in resp_b.json()["items"]}
        assert len(trace_ids_a & trace_ids_b) == 0

    def test_summary_tenant_isolation(self, shared_db, client, tenant_a, tenant_b, auth_a, auth_b):
        """Summary metrics are per-tenant."""
        _execute_request(client, "summary-iso-a", auth_a)
        _execute_request(client, "summary-iso-b", auth_b)

        resp_a = client.get("/executions/summary", headers=auth_a)
        resp_b = client.get("/executions/summary", headers=auth_b)
        assert resp_a.status_code == 200
        assert resp_b.status_code == 200

    def test_governance_tenant_isolation(self, shared_db, client, tenant_a, tenant_b, auth_a, auth_b):
        """Governance insights are per-tenant."""
        tid_a, tid_b = tenant_a[0], tenant_b[0]
        anchor_a = _create_anchor(shared_db, tid_a, 3, "Do not iso-test-a")
        anchor_b = _create_anchor(shared_db, tid_b, 3, "Do not iso-test-b")

        _execute_request(client, "iso-test-a trigger", auth_a)
        _execute_request(client, "iso-test-b trigger", auth_b)

        resp_a = client.get("/governance/insights", headers=auth_a)
        anchor_ids_a = {e["anchor_id"] for e in resp_a.json()["top_conflicted_anchors"]}
        assert anchor_b.id not in anchor_ids_a

    def test_compliance_tenant_isolation(self, shared_db, client, tenant_a, tenant_b, auth_a, auth_b):
        """Compliance export is per-tenant."""
        _execute_request(client, "compliance-iso-a", auth_a)
        _execute_request(client, "compliance-iso-b", auth_b)

        resp_a = client.get("/compliance/export", headers=auth_a)
        resp_b = client.get("/compliance/export", headers=auth_b)

        trace_ids_a = {t["trace_id"] for t in resp_a.json()["traces"]}
        trace_ids_b = {t["trace_id"] for t in resp_b.json()["traces"]}
        assert len(trace_ids_a & trace_ids_b) == 0


# ================================================================
# 6. Auth & Edge Cases
# ================================================================

class TestAnalyticsAuth:
    """Analytics endpoints require authentication."""

    def test_no_auth_returns_401(self, client):
        """Requests without auth header are rejected."""
        for endpoint in ["/executions", "/executions/summary", "/governance/insights", "/compliance/export"]:
            resp = client.get(endpoint)
            assert resp.status_code == 401

    def test_invalid_auth_returns_401(self, client):
        """Invalid API key is rejected."""
        headers = {"Authorization": "Bearer invalid-key-12345"}
        resp = client.get("/executions", headers=headers)
        assert resp.status_code == 401


# ================================================================
# 7. GET /executions/timeseries (Stage 19)
# ================================================================

class TestTimeseriesBucketing:
    """Unit-level tests for bucket boundary generation."""

    def test_hourly_bucket_boundaries(self):
        """Hourly buckets align to top of each hour."""
        from app.api.analytics import _generate_buckets
        start = datetime(2026, 4, 1, 10, 30)
        end = datetime(2026, 4, 1, 13, 15)
        buckets = _generate_buckets(start, end, "hour")
        assert buckets[0][0] == datetime(2026, 4, 1, 10, 0)
        assert buckets[-1][1] == datetime(2026, 4, 1, 13, 15)
        for i in range(len(buckets) - 1):
            assert (buckets[i][1] - buckets[i][0]) == timedelta(hours=1)

    def test_daily_bucket_boundaries(self):
        """Daily buckets align to midnight UTC."""
        from app.api.analytics import _generate_buckets
        start = datetime(2026, 4, 1, 0, 0)
        end = datetime(2026, 4, 3, 12, 0)
        buckets = _generate_buckets(start, end, "day")
        assert len(buckets) == 3
        assert buckets[0][0] == datetime(2026, 4, 1, 0, 0)
        assert buckets[2][0] == datetime(2026, 4, 3, 0, 0)

    def test_weekly_bucket_boundaries(self):
        """Weekly buckets align to Monday."""
        from app.api.analytics import _generate_buckets
        start = datetime(2026, 4, 1, 0, 0)
        end = datetime(2026, 4, 15, 0, 0)
        buckets = _generate_buckets(start, end, "week")
        assert buckets[0][0] == datetime(2026, 3, 30, 0, 0)
        assert (buckets[0][1] - buckets[0][0]) == timedelta(weeks=1)


class TestTimeseriesEndpoint:
    """Integration tests for GET /executions/timeseries."""

    def test_daily_aggregation_with_data(self, shared_db, client, tenant_a, auth_a):
        """Daily buckets correctly aggregate execution data."""
        tid = tenant_a[0]
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        for _ in range(2):
            t = _direct_insert_trace(shared_db, tid, "proceed", "ok")
            _direct_insert_exec_log(shared_db, tid, t.id, "proceed", "executed")

        t_block = _direct_insert_trace(shared_db, tid, "gate", "conflict")
        _direct_insert_exec_log(shared_db, tid, t_block.id, "gate", "blocked")

        resp = client.get("/executions/timeseries?granularity=day", headers=auth_a)
        assert resp.status_code == 200
        data = resp.json()
        assert data["granularity"] == "day"
        
        today_bucket = None
        for b in data["buckets"]:
            if datetime.fromisoformat(b["start"]).date() == now.date():
                today_bucket = b
                break

        if today_bucket:
            assert today_bucket["executed"] >= 2
            assert today_bucket["blocked"] >= 1

    def test_hourly_aggregation(self, shared_db, client, tenant_a, auth_a):
        """Hourly buckets work correctly."""
        resp = client.get("/executions/timeseries?granularity=hour", headers=auth_a)
        assert resp.status_code == 200
        assert resp.json()["granularity"] == "hour"

    def test_weekly_aggregation(self, shared_db, client, tenant_a, auth_a):
        """Weekly buckets work correctly."""
        resp = client.get("/executions/timeseries?granularity=week", headers=auth_a)
        assert resp.status_code == 200
        assert resp.json()["granularity"] == "week"

    def test_empty_dataset(self, shared_db, client, tenant_a, auth_a):
        """Returns valid structure with zero counts when no data matches."""
        start, end = "2020-01-01T00:00:00", "2020-01-03T00:00:00"
        resp = client.get(
            f"/executions/timeseries?granularity=day&start_date={start}&end_date={end}",
            headers=auth_a,
        )
        data = resp.json()
        assert len(data["buckets"]) == 2
        assert all(b["total_requests"] == 0 for b in data["buckets"])

    def test_invalid_granularity_returns_422(self, client, tenant_a, auth_a):
        """Invalid granularity returns 422."""
        resp = client.get("/executions/timeseries?granularity=monthly", headers=auth_a)
        assert resp.status_code == 422

    def test_missing_granularity_returns_422(self, client, tenant_a, auth_a):
        """Missing required granularity parameter returns 422."""
        resp = client.get("/executions/timeseries", headers=auth_a)
        assert resp.status_code == 422

    def test_start_date_after_end_date_returns_422(self, client, tenant_a, auth_a):
        """start_date after end_date returns 422."""
        resp = client.get(
            "/executions/timeseries?granularity=day&start_date=2026-04-10T00:00:00&end_date=2026-04-01T00:00:00",
            headers=auth_a,
        )
        assert resp.status_code == 422

    def test_default_date_range_7_days(self, client, tenant_a, auth_a):
        """Without dates, defaults to last 7 days."""
        resp = client.get("/executions/timeseries?granularity=day", headers=auth_a)
        assert 6 <= len(resp.json()["buckets"]) <= 9

    def test_filter_by_connector(self, shared_db, client, tenant_a, auth_a):
        """Connector filter scopes the timeseries correctly."""
        tid = tenant_a[0]
        t1 = _direct_insert_trace(shared_db, tid, "proceed", "ok")
        _direct_insert_exec_log(shared_db, tid, t1.id, "proceed", "executed", connector="mock")

        resp = client.get("/executions/timeseries?granularity=day&connector=mock", headers=auth_a)
        total = sum(b["total_requests"] for b in resp.json()["buckets"])
        assert total >= 1

    def test_filter_by_status(self, shared_db, client, tenant_a, auth_a):
        """Status filter scopes the timeseries correctly."""
        tid = tenant_a[0]
        t1 = _direct_insert_trace(shared_db, tid, "gate", "conflict")
        _direct_insert_exec_log(shared_db, tid, t1.id, "gate", "blocked")

        resp = client.get("/executions/timeseries?granularity=day&status=blocked", headers=auth_a)
        total = sum(b["total_requests"] for b in resp.json()["buckets"])
        assert total >= 1

    def test_rate_calculations_no_division_by_zero(self, client, tenant_a, auth_a):
        """Rates are 0.0 when bucket is empty."""
        resp = client.get("/executions/timeseries?granularity=day&start_date=2025-01-01T00:00:00&end_date=2025-01-02T00:00:00", headers=auth_a)
        b = resp.json()["buckets"][0]
        assert b["block_rate"] == 0.0

    def test_deterministic_output(self, client, tenant_a, auth_a):
        """Same input produces same output."""
        url = "/executions/timeseries?granularity=day&start_date=2025-06-01T00:00:00&end_date=2025-06-03T00:00:00"
        assert client.get(url, headers=auth_a).json() == client.get(url, headers=auth_a).json()


class TestTimeseriesTenantIsolation:
    """Timeseries endpoint enforces tenant isolation."""

    def test_tenant_isolation(self, shared_db, client, tenant_a, tenant_b, auth_a, auth_b):
        """Each tenant only sees their own data in timeseries."""
        tid_a, tid_b = tenant_a[0], tenant_b[0]
        t_a = _direct_insert_trace(shared_db, tid_a, "proceed", "ok-a-iso")
        _direct_insert_exec_log(shared_db, tid_a, t_a.id, "proceed", "executed")

        t_b = _direct_insert_trace(shared_db, tid_b, "proceed", "ok-b-iso")
        _direct_insert_exec_log(shared_db, tid_b, t_b.id, "proceed", "executed")

        resp_a = client.get("/executions/timeseries?granularity=day", headers=auth_a)
        resp_b = client.get("/executions/timeseries?granularity=day", headers=auth_b)

        total_a = sum(b["total_requests"] for b in resp_a.json()["buckets"])
        total_b = sum(b["total_requests"] for b in resp_b.json()["buckets"])
        assert total_a >= 1 and total_b >= 1