"""
test_alert_dispatch.py — Integration tests for Outbound Alert Delivery (Stage 21).

Covers:
  - POST /alerts/dispatch — no alerts → no dispatch attempted
  - POST /alerts/dispatch — alerts present → webhook dispatch attempted
  - POST /alerts/dispatch — webhook success → dispatch_status=sent
  - POST /alerts/dispatch — webhook failure → dispatch_status=failed
  - Sensitive values redacted in stored audit result
  - Signing works if signing_secret provided
  - Tenant isolation preserved
  - Deterministic response for same input
  - Existing /alerts behavior unchanged
  - Audit log written correctly
  - Outbound payload structure
  - Missing URL in context → handled gracefully
  - Auth requirement

Run with:
  cd /home/z/my-project/signalweaver && PYTHONPATH=src python3 -m pytest src/tests/test_alert_dispatch.py -v
"""

from __future__ import annotations

import json
import sys
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.main import app
from app.db import get_db
from app.models import (
    Base,
    Tenant,
    TruthAnchor,
    PolicyProfile,
    GateLog,
    DecisionTrace,
    DecisionTraceAnchor,
    ExecutionLog,
    AlertDispatchLog,
)
from app.auth import generate_api_key

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
def tenant_a(shared_db):
    raw_key, hashed = generate_api_key()
    t = Tenant(name="dispatch-tenant-a", api_key_hash=hashed)
    shared_db.add(t)
    shared_db.commit()
    shared_db.refresh(t)
    return t.id, raw_key


@pytest.fixture(scope="module")
def tenant_b(shared_db):
    raw_key, hashed = generate_api_key()
    t = Tenant(name="dispatch-tenant-b", api_key_hash=hashed)
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
        request_text=f"dispatch-test-{decision}-{reason}",
        request_normalized=f"dispatch-test-{decision}-{reason}",
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
    """Seed 'count' execution logs with high block rate (80% blocked)."""
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


# ================================================================
# 1. No Alerts → No Dispatch
# ================================================================

class TestNoAlertsNoDispatch:
    """When no alerts are found, dispatch should not be attempted."""

    def test_no_alerts_no_dispatch(self, client, tenant_a, auth_a, shared_db):
        """No data, no alerts → status ok, dispatch_status not_sent."""
        with patch("app.connectors.webhook.http_requests.request") as mock_req:
            resp = client.post(
                "/alerts/dispatch",
                json={
                    "window": "1h",
                    "context": {
                        "url": "https://example.com/alerts",
                        "method": "POST",
                    },
                },
                headers=auth_a,
            )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "ok"
        assert data["alert_count"] == 0
        assert data["dispatch_status"] == "not_sent"
        assert data["connector"] == "webhook"
        assert data["result"] is None

        # Webhook should NOT have been called
        mock_req.assert_not_called()

    def test_audit_log_written_for_no_dispatch(self, client, tenant_a, auth_a, shared_db):
        """Audit log is written even when no dispatch happens."""
        # Clear any existing audit logs for clean count
        shared_db.query(AlertDispatchLog).delete()
        shared_db.commit()

        with patch("app.connectors.webhook.http_requests.request"):
            resp = client.post(
                "/alerts/dispatch",
                json={
                    "window": "1h",
                    "context": {"url": "https://example.com/alerts"},
                },
                headers=auth_a,
            )

        assert resp.status_code == 200

        logs = shared_db.query(AlertDispatchLog).all()
        assert len(logs) >= 1
        latest = logs[-1]
        assert latest.alert_status == "ok"
        assert latest.alert_count == 0
        assert latest.dispatch_status == "not_sent"
        assert latest.tenant_id == tenant_a[0]


# ================================================================
# 2. Alerts Present → Dispatch Attempted
# ================================================================

class TestAlertsDispatchAttempted:
    """When alerts exist, dispatch should be attempted."""

    def _seed_and_dispatch(self, shared_db, tenant_id, auth, client, mock_response=None):
        """Helper: seed data, mock webhook, call dispatch."""
        _seed_high_block_rate(shared_db, tenant_id, count=10)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_response or {"received": True}
        mock_resp.text = '{"received": true}'

        with patch("app.connectors.webhook.http_requests.request", return_value=mock_resp) as mock_req:
            resp = client.post(
                "/alerts/dispatch",
                json={
                    "window": "2h",
                    "context": {
                        "url": "https://example.com/alerts",
                        "method": "POST",
                    },
                    "block_rate_threshold": 0.25,
                },
                headers=auth,
            )

        return resp, mock_req

    def test_dispatch_attempted_with_alerts(self, shared_db, client, tenant_a, auth_a):
        """Alerts present → webhook dispatch attempted."""
        resp, mock_req = self._seed_and_dispatch(
            shared_db, tenant_a[0], auth_a, client,
        )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "alert"
        assert data["alert_count"] > 0

        # Webhook should have been called exactly once
        mock_req.assert_called_once()

    def test_outbound_payload_structure(self, shared_db, client, tenant_a, auth_a):
        """Outbound payload has correct structure."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}
        mock_resp.text = '{"ok": true}'

        _seed_high_block_rate(shared_db, tenant_a[0], count=10)

        with patch("app.connectors.webhook.http_requests.request", return_value=mock_resp) as mock_req:
            client.post(
                "/alerts/dispatch",
                json={
                    "window": "2h",
                    "context": {
                        "url": "https://example.com/alerts",
                        "method": "POST",
                    },
                    "block_rate_threshold": 0.25,
                },
                headers=auth_a,
            )

        # Inspect the call arguments
        call_args = mock_req.call_args
        # The payload should be the alert payload
        sent_payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert sent_payload is not None
        assert "tenant_id" in sent_payload
        assert "window" in sent_payload
        assert "granularity" in sent_payload
        assert "status" in sent_payload
        assert sent_payload["status"] == "alert"
        assert "generated_at" in sent_payload
        assert "alerts" in sent_payload
        assert isinstance(sent_payload["alerts"], list)


# ================================================================
# 3. Webhook Success → dispatch_status=sent
# ================================================================

class TestWebhookSuccess:
    """Webhook returns 2xx → dispatch_status=sent."""

    def test_success_200(self, shared_db, client, tenant_a, auth_a):
        """HTTP 200 → dispatch_status=sent."""
        _seed_high_block_rate(shared_db, tenant_a[0], count=10)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"received": True}
        mock_resp.text = '{"received": true}'

        with patch("app.connectors.webhook.http_requests.request", return_value=mock_resp):
            resp = client.post(
                "/alerts/dispatch",
                json={
                    "window": "2h",
                    "context": {"url": "https://example.com/alerts"},
                    "block_rate_threshold": 0.25,
                },
                headers=auth_a,
            )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["dispatch_status"] == "sent"
        assert data["result"]["status"] == "success"
        assert data["result"]["http_status"] == 200

    def test_success_201(self, shared_db, client, tenant_a, auth_a):
        """HTTP 201 → dispatch_status=sent."""
        _seed_high_block_rate(shared_db, tenant_a[0], count=10)

        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"created": True}
        mock_resp.text = '{"created": true}'

        with patch("app.connectors.webhook.http_requests.request", return_value=mock_resp):
            resp = client.post(
                "/alerts/dispatch",
                json={
                    "window": "2h",
                    "context": {"url": "https://example.com/alerts"},
                    "block_rate_threshold": 0.25,
                },
                headers=auth_a,
            )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["dispatch_status"] == "sent"


# ================================================================
# 4. Webhook Failure → dispatch_status=failed
# ================================================================

class TestWebhookFailure:
    """Webhook returns non-2xx or connection error → dispatch_status=failed."""

    def test_http_500_failure(self, shared_db, client, tenant_a, auth_a):
        """HTTP 500 → dispatch_status=failed."""
        _seed_high_block_rate(shared_db, tenant_a[0], count=10)

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.return_value = {"error": "internal"}
        mock_resp.text = '{"error": "internal"}'

        with patch("app.connectors.webhook.http_requests.request", return_value=mock_resp):
            resp = client.post(
                "/alerts/dispatch",
                json={
                    "window": "2h",
                    "context": {"url": "https://example.com/alerts"},
                    "block_rate_threshold": 0.25,
                },
                headers=auth_a,
            )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["dispatch_status"] == "failed"
        assert data["result"]["status"] == "error"

    def test_connection_error(self, shared_db, client, tenant_a, auth_a):
        """Connection error → dispatch_status=failed."""
        _seed_high_block_rate(shared_db, tenant_a[0], count=10)

        import requests as http_requests

        with patch(
            "app.connectors.webhook.http_requests.request",
            side_effect=http_requests.exceptions.ConnectionError("refused"),
        ):
            resp = client.post(
                "/alerts/dispatch",
                json={
                    "window": "2h",
                    "context": {"url": "https://example.com/alerts"},
                    "block_rate_threshold": 0.25,
                },
                headers=auth_a,
            )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["dispatch_status"] == "failed"
        assert "error" in data["result"]

    def test_timeout(self, shared_db, client, tenant_a, auth_a):
        """Timeout → dispatch_status=failed."""
        _seed_high_block_rate(shared_db, tenant_a[0], count=10)

        import requests as http_requests

        with patch(
            "app.connectors.webhook.http_requests.request",
            side_effect=http_requests.exceptions.Timeout("timed out"),
        ):
            resp = client.post(
                "/alerts/dispatch",
                json={
                    "window": "2h",
                    "context": {"url": "https://example.com/alerts"},
                    "block_rate_threshold": 0.25,
                },
                headers=auth_a,
            )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["dispatch_status"] == "failed"


# ================================================================
# 5. Sensitive Value Redaction
# ================================================================

class TestSensitiveRedaction:
    """Sensitive values are redacted in stored audit results and responses."""

    def test_headers_redacted_in_response(self, shared_db, client, tenant_a, auth_a):
        """Authorization header not leaked in response."""
        _seed_high_block_rate(shared_db, tenant_a[0], count=10)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"received": True}
        mock_resp.text = '{"received": true}'

        with patch("app.connectors.webhook.http_requests.request", return_value=mock_resp):
            resp = client.post(
                "/alerts/dispatch",
                json={
                    "window": "2h",
                    "context": {
                        "url": "https://example.com/alerts",
                        "method": "POST",
                        "headers": {"Authorization": "Bearer secret-token-xyz"},
                    },
                    "block_rate_threshold": 0.25,
                },
                headers=auth_a,
            )

        assert resp.status_code == 200
        data = resp.json()
        # The response result should not contain the raw secret
        result_str = json.dumps(data["result"])
        assert "secret-token-xyz" not in result_str

    def test_signing_secret_redacted_in_audit_log(self, shared_db, client, tenant_a, auth_a):
        """signing_secret not persisted in audit log."""
        _seed_high_block_rate(shared_db, tenant_a[0], count=10)

        shared_db.query(AlertDispatchLog).delete()
        shared_db.commit()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"received": True}
        mock_resp.text = '{"received": true}'

        with patch("app.connectors.webhook.http_requests.request", return_value=mock_resp):
            resp = client.post(
                "/alerts/dispatch",
                json={
                    "window": "2h",
                    "context": {
                        "url": "https://example.com/alerts",
                        "signing_secret": "my-super-secret-key-12345",
                    },
                    "block_rate_threshold": 0.25,
                },
                headers=auth_a,
            )

        assert resp.status_code == 200

        # Check audit log
        logs = shared_db.query(AlertDispatchLog).all()
        assert len(logs) >= 1
        latest = logs[-1]
        assert "my-super-secret-key-12345" not in latest.result_json

    def test_signing_secret_not_in_response(self, shared_db, client, tenant_a, auth_a):
        """signing_secret not leaked in API response."""
        _seed_high_block_rate(shared_db, tenant_a[0], count=10)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"received": True}
        mock_resp.text = '{"received": true}'

        with patch("app.connectors.webhook.http_requests.request", return_value=mock_resp):
            resp = client.post(
                "/alerts/dispatch",
                json={
                    "window": "2h",
                    "context": {
                        "url": "https://example.com/alerts",
                        "signing_secret": "my-super-secret-key-12345",
                    },
                    "block_rate_threshold": 0.25,
                },
                headers=auth_a,
            )

        assert resp.status_code == 200
        resp_str = resp.text
        assert "my-super-secret-key-12345" not in resp_str


# ================================================================
# 6. Signing
# ================================================================

class TestSigning:
    """Signing works when signing_secret is provided."""

    def test_signing_headers_sent(self, shared_db, client, tenant_a, auth_a):
        """X-SignalWeaver-Signature header present when signing_secret provided."""
        _seed_high_block_rate(shared_db, tenant_a[0], count=10)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"received": True}
        mock_resp.text = '{"received": true}'

        with patch("app.connectors.webhook.http_requests.request", return_value=mock_resp) as mock_req:
            resp = client.post(
                "/alerts/dispatch",
                json={
                    "window": "2h",
                    "context": {
                        "url": "https://example.com/alerts",
                        "signing_secret": "test-secret",
                    },
                    "block_rate_threshold": 0.25,
                },
                headers=auth_a,
            )

        assert resp.status_code == 200

        # Check that signing headers were sent
        call_kwargs = mock_req.call_args.kwargs
        sent_headers = call_kwargs.get("headers", {})
        assert "X-SignalWeaver-Signature" in sent_headers
        assert sent_headers["X-SignalWeaver-Signature"].startswith("sha256=")
        assert "X-SignalWeaver-Timestamp" in sent_headers

    def test_no_signing_without_secret(self, shared_db, client, tenant_a, auth_a):
        """No signing headers when signing_secret not provided."""
        _seed_high_block_rate(shared_db, tenant_a[0], count=10)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"received": True}
        mock_resp.text = '{"received": true}'

        with patch("app.connectors.webhook.http_requests.request", return_value=mock_resp) as mock_req:
            resp = client.post(
                "/alerts/dispatch",
                json={
                    "window": "2h",
                    "context": {
                        "url": "https://example.com/alerts",
                    },
                    "block_rate_threshold": 0.25,
                },
                headers=auth_a,
            )

        assert resp.status_code == 200

        call_kwargs = mock_req.call_args.kwargs
        sent_headers = call_kwargs.get("headers", {})
        assert "X-SignalWeaver-Signature" not in sent_headers
        assert "X-SignalWeaver-Timestamp" not in sent_headers


# ================================================================
# 7. Tenant Isolation
# ================================================================

class TestTenantIsolation:
    """Alert dispatch respects tenant boundaries."""

    def test_dispatch_tenant_isolation(self, shared_db, client, tenant_a, tenant_b, auth_a, auth_b):
        """Tenant A's alerts don't affect Tenant B's dispatch."""
        _seed_high_block_rate(shared_db, tenant_a[0], count=10)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"received": True}
        mock_resp.text = '{"received": true}'

        # Tenant A: should have alerts → dispatch attempted
        with patch("app.connectors.webhook.http_requests.request", return_value=mock_resp) as mock_req_a:
            resp_a = client.post(
                "/alerts/dispatch",
                json={
                    "window": "2h",
                    "context": {"url": "https://example.com/alerts"},
                    "block_rate_threshold": 0.25,
                },
                headers=auth_a,
            )

        assert resp_a.status_code == 200
        data_a = resp_a.json()
        assert data_a["status"] == "alert"
        assert data_a["alert_count"] > 0
        mock_req_a.assert_called_once()

        # Tenant B: no data → no dispatch
        with patch("app.connectors.webhook.http_requests.request") as mock_req_b:
            resp_b = client.post(
                "/alerts/dispatch",
                json={
                    "window": "2h",
                    "context": {"url": "https://example.com/alerts"},
                    "block_rate_threshold": 0.25,
                },
                headers=auth_b,
            )

        assert resp_b.status_code == 200
        data_b = resp_b.json()
        assert data_b["status"] == "ok"
        assert data_b["alert_count"] == 0
        assert data_b["dispatch_status"] == "not_sent"
        mock_req_b.assert_not_called()

    def test_audit_log_tenant_scoped(self, shared_db, client, tenant_a, tenant_b, auth_a, auth_b):
        """Audit logs are correctly scoped to tenants."""
        shared_db.query(AlertDispatchLog).delete()
        shared_db.commit()

        _seed_high_block_rate(shared_db, tenant_a[0], count=10)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"received": True}
        mock_resp.text = '{"received": true}'

        with patch("app.connectors.webhook.http_requests.request", return_value=mock_resp):
            client.post(
                "/alerts/dispatch",
                json={
                    "window": "2h",
                    "context": {"url": "https://example.com/alerts"},
                    "block_rate_threshold": 0.25,
                },
                headers=auth_a,
            )
            client.post(
                "/alerts/dispatch",
                json={
                    "window": "2h",
                    "context": {"url": "https://example.com/alerts"},
                    "block_rate_threshold": 0.25,
                },
                headers=auth_b,
            )

        logs = shared_db.query(AlertDispatchLog).all()
        assert len(logs) >= 2

        tenant_a_logs = [l for l in logs if l.tenant_id == tenant_a[0]]
        tenant_b_logs = [l for l in logs if l.tenant_id == tenant_b[0]]

        assert any(l.alert_status == "alert" for l in tenant_a_logs)
        assert all(l.alert_status == "ok" for l in tenant_b_logs)


# ================================================================
# 8. Determinism
# ================================================================

class TestDeterminism:
    """Same input produces same output."""

    def test_deterministic_dispatch_response(self, shared_db, client, tenant_a, auth_a):
        """Repeated dispatch calls with same input return identical results."""
        _seed_high_block_rate(shared_db, tenant_a[0], count=10)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"received": True}
        mock_resp.text = '{"received": true}'

        body = {
            "window": "2h",
            "context": {"url": "https://example.com/alerts"},
            "block_rate_threshold": 0.25,
        }

        results = []
        for _ in range(3):
            with patch("app.connectors.webhook.http_requests.request", return_value=mock_resp):
                resp = client.post("/alerts/dispatch", json=body, headers=auth_a)
            assert resp.status_code == 200
            results.append(resp.json())

        # alert_count, status, dispatch_status, connector should be identical
        for key in ["status", "alert_count", "dispatch_status", "connector"]:
            values = [r[key] for r in results]
            assert all(v == values[0] for v in values), f"Inconsistent {key}: {values}"


# ================================================================
# 9. Existing /alerts Unchanged
# ================================================================

class TestExistingAlertsUnchanged:
    """GET /alerts continues to work exactly as before."""

    def test_get_alerts_still_works(self, client, tenant_a, auth_a):
        """GET /alerts returns expected shape."""
        resp = client.get("/alerts?window=1h", headers=auth_a)
        assert resp.status_code == 200
        data = resp.json()
        assert "window" in data
        assert "alerts" in data
        assert "status" in data
        assert data["status"] in ("ok", "alert")

    def test_get_alerts_default_window(self, client, tenant_a, auth_a):
        """GET /alerts default window is still 24h."""
        resp = client.get("/alerts", headers=auth_a)
        assert resp.status_code == 200
        data = resp.json()
        assert data["window"] == "24h"


# ================================================================
# 10. Audit Log
# ================================================================

class TestAuditLog:
    """Alert dispatch audit records are written correctly."""

    def test_audit_log_on_success(self, shared_db, client, tenant_a, auth_a):
        """Audit log captures successful dispatch."""
        shared_db.query(AlertDispatchLog).delete()
        shared_db.commit()

        _seed_high_block_rate(shared_db, tenant_a[0], count=10)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"received": True}
        mock_resp.text = '{"received": true}'

        with patch("app.connectors.webhook.http_requests.request", return_value=mock_resp):
            resp = client.post(
                "/alerts/dispatch",
                json={
                    "window": "2h",
                    "context": {"url": "https://example.com/alerts"},
                    "block_rate_threshold": 0.25,
                },
                headers=auth_a,
            )

        assert resp.status_code == 200

        logs = shared_db.query(AlertDispatchLog).all()
        assert len(logs) >= 1
        latest = logs[-1]
        assert latest.alert_status == "alert"
        assert latest.alert_count > 0
        assert latest.dispatch_status == "sent"
        assert latest.connector == "webhook"
        assert latest.tenant_id == tenant_a[0]
        assert latest.result_json != ""
        # Verify result is valid JSON
        parsed = json.loads(latest.result_json)
        assert parsed["status"] == "success"

    def test_audit_log_on_failure(self, shared_db, client, tenant_a, auth_a):
        """Audit log captures failed dispatch."""
        shared_db.query(AlertDispatchLog).delete()
        shared_db.commit()

        _seed_high_block_rate(shared_db, tenant_a[0], count=10)

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.return_value = {"error": "server error"}
        mock_resp.text = '{"error": "server error"}'

        with patch("app.connectors.webhook.http_requests.request", return_value=mock_resp):
            resp = client.post(
                "/alerts/dispatch",
                json={
                    "window": "2h",
                    "context": {"url": "https://example.com/alerts"},
                    "block_rate_threshold": 0.25,
                },
                headers=auth_a,
            )

        assert resp.status_code == 200

        logs = shared_db.query(AlertDispatchLog).all()
        assert len(logs) >= 1
        latest = logs[-1]
        assert latest.dispatch_status == "failed"
        parsed = json.loads(latest.result_json)
        assert parsed["status"] == "error"

    def test_audit_log_created_at_populated(self, shared_db, client, tenant_a, auth_a):
        """Audit log has created_at timestamp."""
        shared_db.query(AlertDispatchLog).delete()
        shared_db.commit()

        before = datetime.now(timezone.utc)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"received": True}
        mock_resp.text = '{"received": true}'

        with patch("app.connectors.webhook.http_requests.request", return_value=mock_resp):
            resp = client.post(
                "/alerts/dispatch",
                json={
                    "window": "1h",
                    "context": {"url": "https://example.com/alerts"},
                },
                headers=auth_a,
            )

        assert resp.status_code == 200

        logs = shared_db.query(AlertDispatchLog).all()
        assert len(logs) >= 1
        latest = logs[-1]
        assert latest.created_at is not None


# ================================================================
# 11. Edge Cases
# ================================================================

class TestEdgeCases:
    """Edge cases and error handling."""

    def test_missing_url_in_context_with_data(self, shared_db, client, tenant_a, auth_a):
        """Missing URL in context → connector validation error → dispatch_status=failed.

        This is tested in test_missing_url_in_context above.
        This test is intentionally omitted to avoid duplication.
        """
        pass

    def test_invalid_window_returns_422(self, client, tenant_a, auth_a):
        """Invalid window format returns 422."""
        resp = client.post(
            "/alerts/dispatch",
            json={
                "window": "abc",
                "context": {"url": "https://example.com/alerts"},
            },
            headers=auth_a,
        )
        assert resp.status_code == 422

    def test_invalid_granularity_returns_422(self, client, tenant_a, auth_a):
        """Invalid granularity returns 422."""
        resp = client.post(
            "/alerts/dispatch",
            json={
                "window": "24h",
                "granularity": "monthly",
                "context": {"url": "https://example.com/alerts"},
            },
            headers=auth_a,
        )
        assert resp.status_code == 422

    def test_missing_url_in_context(self, shared_db, client, tenant_a, auth_a):
        """Missing URL → webhook validation error → dispatch_status=failed."""
        _seed_high_block_rate(shared_db, tenant_a[0], count=10)

        # No mock needed — the connector itself handles validation
        # without making any HTTP call
        resp = client.post(
            "/alerts/dispatch",
            json={
                "window": "2h",
                "context": {},  # No URL!
                "block_rate_threshold": 0.25,
            },
            headers=auth_a,
        )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["dispatch_status"] == "failed"
        assert data["result"]["status"] == "error"

    def test_default_thresholds_used(self, shared_db, client, tenant_a, auth_a):
        """Default thresholds are applied when not specified."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"received": True}
        mock_resp.text = '{"received": true}'

        with patch("app.connectors.webhook.http_requests.request", return_value=mock_resp):
            resp = client.post(
                "/alerts/dispatch",
                json={
                    "window": "1h",
                    "context": {"url": "https://example.com/alerts"},
                    # No thresholds specified — use defaults
                },
                headers=auth_a,
            )

        assert resp.status_code == 200


# ================================================================
# 12. Auth Requirement
# ================================================================

class TestDispatchAuth:
    """Dispatch endpoint requires authentication."""

    def test_no_auth_returns_401(self, client):
        """Requests without auth header are rejected."""
        resp = client.post(
            "/alerts/dispatch",
            json={
                "window": "1h",
                "context": {"url": "https://example.com/alerts"},
            },
        )
        assert resp.status_code == 401

    def test_invalid_auth_returns_401(self, client):
        """Invalid API key is rejected."""
        resp = client.post(
            "/alerts/dispatch",
            json={
                "window": "1h",
                "context": {"url": "https://example.com/alerts"},
            },
            headers={"Authorization": "Bearer invalid-key-12345"},
        )
        assert resp.status_code == 401


# ================================================================
# 13. Response Shape
# ================================================================

class TestResponseShape:
    """Verify response structure."""

    def test_response_shape_no_alerts(self, client, tenant_a, auth_a):
        """Response has required fields when no alerts.

        Note: Due to module-scoped fixtures, there may be data from previous tests.
        We verify the response shape regardless of alert status.
        """
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"received": True}
        mock_resp.text = '{"received": true}'

        with patch("app.connectors.webhook.http_requests.request", return_value=mock_resp):
            resp = client.post(
                "/alerts/dispatch",
                json={
                    "window": "1h",
                    "context": {"url": "https://example.com/alerts"},
                },
                headers=auth_a,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "alert_count" in data
        assert "dispatch_status" in data
        assert "connector" in data
        assert "result" in data
        assert data["status"] in ("ok", "alert")
        assert isinstance(data["alert_count"], int)
        assert data["dispatch_status"] in ("not_sent", "sent", "failed")

    def test_response_shape_with_alerts(self, shared_db, client, tenant_a, auth_a):
        """Response has required fields when alerts exist."""
        _seed_high_block_rate(shared_db, tenant_a[0], count=10)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"received": True}
        mock_resp.text = '{"received": true}'

        with patch("app.connectors.webhook.http_requests.request", return_value=mock_resp):
            resp = client.post(
                "/alerts/dispatch",
                json={
                    "window": "2h",
                    "context": {"url": "https://example.com/alerts"},
                    "block_rate_threshold": 0.25,
                },
                headers=auth_a,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "alert"
        assert data["alert_count"] > 0
        assert data["dispatch_status"] == "sent"
        assert data["connector"] == "webhook"
        assert data["result"] is not None
        assert "status" in data["result"]


# ================================================================
# 14. Connector & Status Filtering
# ================================================================

class TestDispatchFiltering:
    """Connector and status filters scope alert evaluation for dispatch."""

    def test_connector_filter_scopes_alerts(self, shared_db, client, tenant_a, auth_a):
        """Dispatch only evaluates alerts for the specified connector."""
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        # Connector A: all executed (no alerts)
        for i in range(10):
            ts = now - timedelta(minutes=i)
            t = _direct_insert_trace(
                shared_db, tenant_a[0], "proceed", "ok", created_at=ts,
            )
            _direct_insert_exec_log(
                shared_db, tenant_a[0], t.id, "proceed", "executed",
                connector="dispatch-filter-exec", created_at=ts,
            )

        # Connector B: all blocked (triggers alerts)
        for i in range(10):
            ts = now - timedelta(minutes=i)
            t = _direct_insert_trace(
                shared_db, tenant_a[0], "gate", "conflict", created_at=ts,
            )
            _direct_insert_exec_log(
                shared_db, tenant_a[0], t.id, "gate", "blocked",
                connector="dispatch-filter-block", created_at=ts,
            )

        # Filter to exec connector → no alerts → no dispatch
        with patch("app.connectors.webhook.http_requests.request") as mock_req:
            resp = client.post(
                "/alerts/dispatch",
                json={
                    "window": "1h",
                    "context": {"url": "https://example.com/alerts"},
                    "block_rate_threshold": 0.25,
                    "connector_filter": "dispatch-filter-exec",
                },
                headers=auth_a,
            )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["dispatch_status"] == "not_sent"
        mock_req.assert_not_called()

        # Filter to block connector → alerts → dispatch attempted
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"received": True}
        mock_resp.text = '{"received": true}'

        with patch("app.connectors.webhook.http_requests.request", return_value=mock_resp) as mock_req:
            resp = client.post(
                "/alerts/dispatch",
                json={
                    "window": "1h",
                    "context": {"url": "https://example.com/alerts"},
                    "block_rate_threshold": 0.25,
                    "connector_filter": "dispatch-filter-block",
                },
                headers=auth_a,
            )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["dispatch_status"] == "sent"
        mock_req.assert_called_once()
