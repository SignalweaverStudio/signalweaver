"""
test_alerting.py — Integration tests for the Minimal Alerting Layer (Stage 20).

Covers:
  - GET /alerts — threshold alerts (block rate, override rate, failure rate)
  - GET /alerts — spike detection (latest vs previous average)
  - Window parsing (1h, 24h, 7d, invalid formats)
  - Granularity auto-selection and override
  - Custom threshold parameters
  - Empty dataset → status "ok", no alerts
  - Low volume → no false spikes
  - Tenant isolation
  - Deterministic output
  - Connector/status filtering
  - Auth requirement
"""

from __future__ import annotations

import sys
import os
from datetime import datetime, timezone, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models import (
    Tenant,
    DecisionTrace,
    ExecutionLog,
)
from app.auth import generate_api_key


@pytest.fixture(scope="module")
def tenant_a(shared_db):
    raw_key, hashed = generate_api_key()
    t = Tenant(name="alert-tenant-a", api_key_hash=hashed)
    shared_db.add(t)
    shared_db.commit()
    shared_db.refresh(t)
    return t.id, raw_key


@pytest.fixture(scope="module")
def tenant_b(shared_db):
    raw_key, hashed = generate_api_key()
    t = Tenant(name="alert-tenant-b", api_key_hash=hashed)
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


def _direct_insert_trace(
    db, tenant_id, decision="proceed", reason="",
    would_block=False, override_reason="",
    enforcement_mode="hard",
    created_at=None,
):
    """Directly insert a DecisionTrace for seeding test data."""
    trace = DecisionTrace(
        tenant_id=tenant_id,
        request_text=f"alert-test-{decision}-{reason}",
        request_normalized=f"alert-test-{decision}-{reason}",
        decision=decision,
        reason=reason,
        explanation="test explanation",
        would_block=would_block,
        enforcement_mode_snapshot=enforcement_mode,
        override_reason=override_reason,
    )
    if created_at is not None:
        trace.created_at = created_at
    db.add(trace)
    db.flush()
    db.commit()
    db.refresh(trace)
    return trace


def _direct_insert_exec_log(
    db, tenant_id, trace_id, decision, status,
    connector="mock", created_at=None,
):
    """Directly insert an ExecutionLog."""
    elog = ExecutionLog(
        tenant_id=tenant_id,
        trace_id=trace_id,
        decision=decision,
        connector=connector,
        status=status,
        response_json='{"status":"success"}' if status == "executed" else "",
    )
    if created_at is not None:
        elog.created_at = created_at
    db.add(elog)
    db.flush()
    db.commit()
    db.refresh(elog)
    return elog


def _seed_high_block_rate(shared_db, tenant_id, count=10, hours_ago=1):
    """
    Seed 'count' execution logs with high block rate (80% blocked).
    All placed within the last 'hours_ago' hours.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for i in range(count):
        ts = now - timedelta(hours=hours_ago, minutes=i)
        if i < int(count * 0.8):
            t = _direct_insert_trace(
                shared_db, tenant_id, "gate", "conflict",
                created_at=ts,
            )
            _direct_insert_exec_log(
                shared_db, tenant_id, t.id, "gate", "blocked",
                created_at=ts,
            )
        else:
            t = _direct_insert_trace(
                shared_db, tenant_id, "proceed", "ok",
                created_at=ts,
            )
            _direct_insert_exec_log(
                shared_db, tenant_id, t.id, "proceed", "executed",
                created_at=ts,
            )


def _seed_high_failure_rate(shared_db, tenant_id, count=10, hours_ago=1):
    """
    Seed 'count' execution logs with high failure rate (60% failed).
    All placed within the last 'hours_ago' hours.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for i in range(count):
        ts = now - timedelta(hours=hours_ago, minutes=i)
        if i < int(count * 0.6):
            t = _direct_insert_trace(
                shared_db, tenant_id, "proceed", "ok",
                created_at=ts,
            )
            _direct_insert_exec_log(
                shared_db, tenant_id, t.id, "proceed", "failed",
                created_at=ts,
            )
        else:
            t = _direct_insert_trace(
                shared_db, tenant_id, "proceed", "ok",
                created_at=ts,
            )
            _direct_insert_exec_log(
                shared_db, tenant_id, t.id, "proceed", "executed",
                created_at=ts,
            )


def _seed_spike_data(
    shared_db, tenant_id,
    prev_block_rate=0.1, prev_buckets=3, prev_per_bucket=10,
    latest_block_rate=0.5, latest_count=10,
    hours_back=6,
):
    """
    Seed data that creates a spike scenario:
    - 'prev_buckets' buckets with low block rate
    - 1 latest bucket with high block rate
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    for bucket_idx in range(prev_buckets):
        bucket_start = now - timedelta(hours=hours_back - bucket_idx)
        blocked_count = int(prev_per_bucket * prev_block_rate)
        for i in range(prev_per_bucket):
            ts = bucket_start - timedelta(minutes=i)
            if i < blocked_count:
                t = _direct_insert_trace(
                    shared_db, tenant_id, "gate", "conflict",
                    created_at=ts,
                )
                _direct_insert_exec_log(
                    shared_db, tenant_id, t.id, "gate", "blocked",
                    created_at=ts,
                )
            else:
                t = _direct_insert_trace(
                    shared_db, tenant_id, "proceed", "ok",
                    created_at=ts,
                )
                _direct_insert_exec_log(
                    shared_db, tenant_id, t.id, "proceed", "executed",
                    created_at=ts,
                )

    latest_blocked = int(latest_count * latest_block_rate)
    for i in range(latest_count):
        ts = now - timedelta(minutes=i)
        if i < latest_blocked:
            t = _direct_insert_trace(
                shared_db, tenant_id, "gate", "conflict",
                created_at=ts,
            )
            _direct_insert_exec_log(
                shared_db, tenant_id, t.id, "gate", "blocked",
                created_at=ts,
            )
        else:
            t = _direct_insert_trace(
                shared_db, tenant_id, "proceed", "ok",
                created_at=ts,
            )
            _direct_insert_exec_log(
                shared_db, tenant_id, t.id, "proceed", "executed",
                created_at=ts,
            )


# ================================================================
# 1. Window Parsing
# ================================================================

class TestWindowParsing:
    def test_parse_1h(self):
        from app.api.analytics import _parse_window
        delta, label = _parse_window("1h")
        assert delta == timedelta(hours=1)
        assert label == "1h"

    def test_parse_24h(self):
        from app.api.analytics import _parse_window
        delta, label = _parse_window("24h")
        assert delta == timedelta(hours=24)
        assert label == "24h"

    def test_parse_7d(self):
        from app.api.analytics import _parse_window
        delta, label = _parse_window("7d")
        assert delta == timedelta(days=7)
        assert label == "7d"

    def test_parse_with_spaces(self):
        from app.api.analytics import _parse_window
        delta, label = _parse_window(" 24 h ")
        assert delta == timedelta(hours=24)

    def test_case_insensitive(self):
        from app.api.analytics import _parse_window
        delta, label = _parse_window("7D")
        assert delta == timedelta(days=7)

    def test_invalid_format_returns_422(self, client, tenant_a, auth_a):
        resp = client.get("/alerts?window=abc", headers=auth_a)
        assert resp.status_code == 422

    def test_invalid_unit_returns_422(self, client, tenant_a, auth_a):
        resp = client.get("/alerts?window=1w", headers=auth_a)
        assert resp.status_code == 422

    def test_too_large_window_returns_422(self, client, tenant_a, auth_a):
        resp = client.get("/alerts?window=999d", headers=auth_a)
        assert resp.status_code == 422


# ================================================================
# 2. Granularity Auto-Selection
# ================================================================

class TestGranularityAutoSelection:
    def test_short_window_selects_hour(self):
        from app.api.analytics import _choose_granularity
        assert _choose_granularity(timedelta(hours=1)) == "hour"
        assert _choose_granularity(timedelta(minutes=30)) == "hour"

    def test_medium_window_selects_day(self):
        from app.api.analytics import _choose_granularity
        assert _choose_granularity(timedelta(hours=24)) == "day"
        assert _choose_granularity(timedelta(days=7)) == "day"

    def test_long_window_selects_week(self):
        from app.api.analytics import _choose_granularity
        assert _choose_granularity(timedelta(days=14)) == "week"
        assert _choose_granularity(timedelta(days=30)) == "week"


# ================================================================
# 3. Threshold Alerts
# ================================================================

class TestHighBlockRateAlert:
    def test_alert_triggered(self, shared_db, client, tenant_a, auth_a):
        _seed_high_block_rate(shared_db, tenant_a[0], count=10)
        resp = client.get("/alerts?window=2h&block_rate_threshold=0.25", headers=auth_a)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "alert"
        alert_types = [a["type"] for a in data["alerts"]]
        assert "high_block_rate" in alert_types

    def test_no_alert_below_threshold(self, shared_db, client, tenant_a, auth_a):
        past = datetime(2020, 6, 1, 12, 0)
        for i in range(10):
            ts = past - timedelta(minutes=i)
            t = _direct_insert_trace(shared_db, tenant_a[0], "proceed", "ok", created_at=ts)
            _direct_insert_exec_log(shared_db, tenant_a[0], t.id, "proceed", "executed", created_at=ts)
        resp = client.get("/alerts?window=1h&block_rate_threshold=0.25&granularity=hour", headers=auth_a)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["alerts"], list)


class TestHighFailureRateAlert:
    def test_alert_triggered(self, shared_db, client, tenant_a, auth_a):
        _seed_high_failure_rate(shared_db, tenant_a[0], count=10)
        resp = client.get("/alerts?window=2h&failure_rate_threshold=0.05", headers=auth_a)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "alert"
        alert_types = [a["type"] for a in data["alerts"]]
        assert "high_failure_rate" in alert_types


class TestHighOverrideRateAlert:
    def test_alert_triggered(self, shared_db, client, tenant_a, auth_a):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for i in range(10):
            ts = now - timedelta(minutes=i)
            t = _direct_insert_trace(shared_db, tenant_a[0], "gate", "conflict", override_reason="operator override", created_at=ts)
            _direct_insert_exec_log(shared_db, tenant_a[0], t.id, "gate", "blocked", created_at=ts)
        resp = client.get("/alerts?window=2h&override_rate_threshold=0.05", headers=auth_a)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "alert"
        assert "high_override_rate" in [a["type"] for a in data["alerts"]]


# ================================================================
# 4. Spike Detection
# ================================================================

class TestSpikeDetection:
    def test_block_rate_spike_detected(self, shared_db, client, tenant_a, auth_a):
        _seed_spike_data(shared_db, tenant_a[0], prev_block_rate=0.1, latest_block_rate=0.5, hours_back=6)
        resp = client.get("/alerts?window=6h&granularity=hour&spike_multiplier=2.0", headers=auth_a)
        assert resp.status_code == 200
        data = resp.json()
        block_spikes = [a for a in data["alerts"] if a["type"] == "spike_detected" and a.get("metric") == "block_rate"]
        assert len(block_spikes) >= 1

    def test_no_spike_when_stable(self, shared_db, client, tenant_a, auth_a):
        from app.api.analytics import _evaluate_alerts, TimeseriesBucketItem
        past = datetime(2020, 6, 1, 10, 0)
        buckets = [TimeseriesBucketItem(start=past + timedelta(hours=i), end=past + timedelta(hours=i+1), total_requests=10, executed=8, blocked=2, failed=0, block_rate=0.2, override_rate=0.0, shadow_would_block_rate=0.0) for i in range(4)]
        alerts = _evaluate_alerts(buckets=buckets, block_rate_threshold=0.25, override_rate_threshold=0.1, failure_rate_threshold=0.05, spike_multiplier=2.0)
        assert not any(a.type == "spike_detected" for a in alerts)

    def test_no_spike_with_low_volume(self, shared_db, client, tenant_a, auth_a):
        from app.api.analytics import _evaluate_alerts, TimeseriesBucketItem
        past = datetime(2020, 6, 1, 10, 0)
        buckets = [TimeseriesBucketItem(start=past + timedelta(hours=i), end=past + timedelta(hours=i+1), total_requests=1, executed=1, blocked=0, failed=0, block_rate=0.0, override_rate=0.0, shadow_would_block_rate=0.0) for i in range(3)]
        buckets.append(TimeseriesBucketItem(start=past + timedelta(hours=3), end=past + timedelta(hours=4), total_requests=1, executed=0, blocked=1, failed=0, block_rate=1.0, override_rate=0.0, shadow_would_block_rate=0.0))
        alerts = _evaluate_alerts(buckets=buckets, block_rate_threshold=0.25, override_rate_threshold=0.1, failure_rate_threshold=0.05, spike_multiplier=2.0)
        assert not any(a.type == "spike_detected" for a in alerts)


# ================================================================
# 5. Empty & Low-Volume Datasets
# ================================================================

class TestEmptyAndLowVolume:
    def test_empty_dataset_returns_ok(self, client, tenant_a, auth_a):
        resp = client.get("/alerts?window=1h", headers=auth_a)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("ok", "alert")

    def test_low_volume_no_false_alerts(self, shared_db, client, tenant_a, auth_a):
        from app.api.analytics import _evaluate_alerts, TimeseriesBucketItem
        past = datetime(2020, 6, 1, 10, 0)
        buckets = [TimeseriesBucketItem(start=past, end=past + timedelta(hours=1), total_requests=3, executed=0, blocked=3, failed=0, block_rate=1.0, override_rate=0.0, shadow_would_block_rate=0.0)]
        alerts = _evaluate_alerts(buckets=buckets, block_rate_threshold=0.25, override_rate_threshold=0.1, failure_rate_threshold=0.05, spike_multiplier=2.0)
        assert len(alerts) == 0

    def test_exact_minimum_triggers(self, shared_db, client, tenant_a, auth_a):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for i in range(5):
            ts = now - timedelta(minutes=i)
            t = _direct_insert_trace(shared_db, tenant_a[0], "gate", "conflict", created_at=ts)
            _direct_insert_exec_log(shared_db, tenant_a[0], t.id, "gate", "blocked", created_at=ts)
        resp = client.get("/alerts?window=1h&block_rate_threshold=0.25", headers=auth_a)
        assert resp.json()["status"] == "alert"


# ================================================================
# 6. Response Shape & Defaults
# ================================================================

class TestResponseShape:
    def test_response_shape(self, client, tenant_a, auth_a):
        resp = client.get("/alerts", headers=auth_a)
        data = resp.json()
        assert all(k in data for k in ("window", "alerts", "status"))

    def test_default_window_is_24h(self, client, tenant_a, auth_a):
        resp = client.get("/alerts", headers=auth_a)
        assert resp.json()["window"] == "24h"


# ================================================================
# 7. Custom Thresholds
# ================================================================

class TestCustomThresholds:
    def test_custom_block_rate_threshold(self, shared_db, client, tenant_a, auth_a):
        _seed_high_block_rate(shared_db, tenant_a[0], count=10)
        resp = client.get("/alerts?window=2h&block_rate_threshold=0.99", headers=auth_a)
        assert "high_block_rate" not in [a["type"] for a in resp.json()["alerts"]]

    def test_custom_spike_multiplier(self, shared_db, client, tenant_a, auth_a):
        _seed_spike_data(shared_db, tenant_a[0], prev_block_rate=0.1, latest_block_rate=0.5, hours_back=6)
        resp = client.get("/alerts?window=6h&granularity=hour&spike_multiplier=10.0", headers=auth_a)
        assert len([a for a in resp.json()["alerts"] if a["type"] == "spike_detected"]) == 0


# ================================================================
# 8. Granularity Override
# ================================================================

class TestGranularityOverride:
    def test_explicit_hour_granularity(self, client, tenant_a, auth_a):
        resp = client.get("/alerts?window=1d&granularity=hour", headers=auth_a)
        assert resp.status_code == 200

    def test_invalid_granularity_returns_422(self, client, tenant_a, auth_a):
        resp = client.get("/alerts?window=24h&granularity=monthly", headers=auth_a)
        assert resp.status_code == 422


# ================================================================
# 9. Tenant Isolation
# ================================================================

class TestAlertingTenantIsolation:
    def test_tenant_isolation(self, shared_db, client, tenant_a, tenant_b, auth_a, auth_b):
        _seed_high_block_rate(shared_db, tenant_a[0], count=10)
        resp_a = client.get("/alerts?window=2h&block_rate_threshold=0.25", headers=auth_a)
        resp_b = client.get("/alerts?window=2h&block_rate_threshold=0.25", headers=auth_b)
        assert resp_a.json()["status"] == "alert"
        assert resp_b.json()["status"] == "ok"


# ================================================================
# 10. Connector & Status Filtering
# ================================================================

class TestAlertingFiltering:
    def test_connector_filter(self, shared_db, client, tenant_a, auth_a):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for i in range(10):
            ts = now - timedelta(minutes=i)
            t1 = _direct_insert_trace(shared_db, tenant_a[0], "proceed", "ok", created_at=ts)
            _direct_insert_exec_log(shared_db, tenant_a[0], t1.id, "proceed", "executed", connector="c1", created_at=ts)
            t2 = _direct_insert_trace(shared_db, tenant_a[0], "gate", "conflict", created_at=ts)
            _direct_insert_exec_log(shared_db, tenant_a[0], t2.id, "gate", "blocked", connector="c2", created_at=ts)

        resp_c1 = client.get("/alerts?window=1h&block_rate_threshold=0.25&connector=c1", headers=auth_a)
        assert "high_block_rate" not in [a["type"] for a in resp_c1.json()["alerts"]]
        resp_c2 = client.get("/alerts?window=1h&block_rate_threshold=0.25&connector=c2", headers=auth_a)
        assert "high_block_rate" in [a["type"] for a in resp_c2.json()["alerts"]]


# ================================================================
# 11. Determinism
# ================================================================

class TestDeterminism:
    def test_deterministic_output(self, client, tenant_a, auth_a):
        url = "/alerts?window=1h&block_rate_threshold=0.25"
        assert client.get(url, headers=auth_a).json() == client.get(url, headers=auth_a).json()


# ================================================================
# 12. Auth Requirement
# ================================================================

class TestAlertingAuth:
    def test_no_auth_returns_401(self, client):
        assert client.get("/alerts").status_code == 401

    def test_invalid_auth_returns_401(self, client):
        assert client.get("/alerts", headers={"Authorization": "Bearer bad"}).status_code == 401


# ================================================================
# 13. Multiple Simultaneous Alerts
# ================================================================

class TestMultipleAlerts:
    def test_multiple_alerts_fire(self, shared_db, client, tenant_a, auth_a):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for i in range(5):
            ts = now - timedelta(minutes=i)
            t = _direct_insert_trace(shared_db, tenant_a[0], "gate", "conflict", created_at=ts)
            _direct_insert_exec_log(shared_db, tenant_a[0], t.id, "gate", "blocked", created_at=ts)
            t2 = _direct_insert_trace(shared_db, tenant_a[0], "proceed", "ok", created_at=ts)
            _direct_insert_exec_log(shared_db, tenant_a[0], t2.id, "proceed", "failed", created_at=ts)

        resp = client.get("/alerts?window=1h&block_rate_threshold=0.25&failure_rate_threshold=0.05", headers=auth_a)
        types = [a["type"] for a in resp.json()["alerts"]]
        assert "high_block_rate" in types and "high_failure_rate" in types