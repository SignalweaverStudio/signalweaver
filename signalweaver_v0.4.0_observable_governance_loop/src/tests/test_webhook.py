"""
test_webhook.py — Integration tests for the Webhook Connector (Stage 17).

Covers:
  - webhook executes on proceed (200 response)
  - webhook blocked on gate (governance blocks, no HTTP call)
  - webhook blocked on refuse (governance blocks, no HTTP call)
  - webhook failed on connector error (timeout, non-2xx, connection error)
  - webhook validation: missing URL, invalid method, invalid scheme
  - webhook validation: non-JSON-serializable payload, invalid timeout
  - invalid connector name returns 400
  - ExecutionLog created for webhook attempts with correct status
  - tenant isolation preserved
  - mock connector still works (regression)

Run with:
  cd /home/z/my-project/signalweaver && PYTHONPATH=src python3 -m pytest src/tests/test_webhook.py -v
"""

from __future__ import annotations

import json
import sys
import os
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

import pytest
import requests as http_requests
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.main import app
from app.db import get_db
from app.models import (
    Base, Tenant, TruthAnchor, PolicyProfile,
    DecisionTrace, ExecutionLog,
)
from app.auth import generate_api_key
from app.connectors.webhook import (
    WebhookConnector, _validate_webhook_config, WebhookValidationError,
)

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
    t = Tenant(name="webhook-tenant-a", api_key_hash=hashed)
    shared_db.add(t)
    shared_db.commit()
    shared_db.refresh(t)
    return t.id, raw_key


@pytest.fixture(scope="module")
def tenant_b(shared_db):
    raw_key, hashed = generate_api_key()
    t = Tenant(name="webhook-tenant-b", api_key_hash=hashed)
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


WEBHOOK_CONTEXT = {
    "url": "https://example.com/webhook",
    "method": "POST",
    "headers": {"Authorization": "Bearer test-token"},
    "payload": {"action": "test", "amount": 100},
}


# ================================================================
# Unit tests: WebhookConnector directly
# ================================================================

class TestWebhookConnectorValidation:
    """Unit tests for webhook config validation."""

    def test_valid_config(self):
        ctx = {
            "url": "https://example.com/hook",
            "method": "POST",
            "headers": {},
            "payload": {"key": "value"},
            "timeout": 5,
        }
        url, method, headers, payload, timeout = _validate_webhook_config(ctx)
        assert url == "https://example.com/hook"
        assert method == "POST"
        assert timeout == 5

    def test_missing_url_raises(self):
        with pytest.raises(WebhookValidationError, match="url"):
            _validate_webhook_config({})

    def test_empty_url_raises(self):
        with pytest.raises(WebhookValidationError, match="url"):
            _validate_webhook_config({"url": ""})

    def test_invalid_scheme_ftp_raises(self):
        with pytest.raises(WebhookValidationError, match="scheme"):
            _validate_webhook_config({"url": "ftp://example.com/hook"})

    def test_invalid_scheme_file_raises(self):
        with pytest.raises(WebhookValidationError, match="scheme"):
            _validate_webhook_config({"url": "file:///etc/passwd"})

    def test_http_scheme_allowed(self):
        ctx = {"url": "http://localhost:8080/hook"}
        url, method, _, _, _ = _validate_webhook_config(ctx)
        assert url == "http://localhost:8080/hook"

    def test_https_scheme_allowed(self):
        ctx = {"url": "https://api.example.com/webhook"}
        url, method, _, _, _ = _validate_webhook_config(ctx)
        assert url == "https://api.example.com/webhook"

    def test_invalid_method_raises(self):
        with pytest.raises(WebhookValidationError, match="method"):
            _validate_webhook_config({
                "url": "https://example.com/hook",
                "method": "DELETE",
            })

    def test_get_method_not_allowed(self):
        with pytest.raises(WebhookValidationError, match="method"):
            _validate_webhook_config({
                "url": "https://example.com/hook",
                "method": "GET",
            })

    def test_put_allowed(self):
        ctx = {"url": "https://example.com/hook", "method": "PUT"}
        _, method, _, _, _ = _validate_webhook_config(ctx)
        assert method == "PUT"

    def test_patch_allowed(self):
        ctx = {"url": "https://example.com/hook", "method": "PATCH"}
        _, method, _, _, _ = _validate_webhook_config(ctx)
        assert method == "PATCH"

    def test_method_case_insensitive(self):
        ctx = {"url": "https://example.com/hook", "method": "post"}
        _, method, _, _, _ = _validate_webhook_config(ctx)
        assert method == "POST"

    def test_headers_must_be_dict(self):
        with pytest.raises(WebhookValidationError, match="headers"):
            _validate_webhook_config({
                "url": "https://example.com/hook",
                "headers": "not-a-dict",
            })

    def test_payload_must_be_dict(self):
        with pytest.raises(WebhookValidationError, match="payload"):
            _validate_webhook_config({
                "url": "https://example.com/hook",
                "payload": "not-a-dict",
            })

    def test_non_serializable_payload_raises(self):
        with pytest.raises(WebhookValidationError, match="serializable"):
            _validate_webhook_config({
                "url": "https://example.com/hook",
                "payload": {"bad": datetime.now()},
            })

    def test_timeout_must_be_positive(self):
        with pytest.raises(WebhookValidationError, match="timeout"):
            _validate_webhook_config({
                "url": "https://example.com/hook",
                "timeout": -5,
            })

    def test_timeout_capped_at_30(self):
        ctx = {"url": "https://example.com/hook", "timeout": 120}
        _, _, _, _, timeout = _validate_webhook_config(ctx)
        assert timeout == 30

    def test_default_timeout(self):
        ctx = {"url": "https://example.com/hook"}
        _, _, _, _, timeout = _validate_webhook_config(ctx)
        assert timeout == 10

    def test_default_method(self):
        ctx = {"url": "https://example.com/hook"}
        _, method, _, _, _ = _validate_webhook_config(ctx)
        assert method == "POST"


# ================================================================
# Unit tests: WebhookConnector.execute with mocked HTTP
# ================================================================

class TestWebhookConnectorExecute:
    """Unit tests for WebhookConnector.execute with mocked requests."""

    def test_success_response(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}
        mock_resp.text = '{"ok": true}'

        connector = WebhookConnector()
        with patch.object(http_requests, "request", return_value=mock_resp):
            result = connector.execute({
                "raw_text": "test",
                "context": WEBHOOK_CONTEXT,
            })

        assert result["status"] == "success"
        assert result["http_status"] == 200
        assert result["response_body"] == {"ok": True}

    def test_201_created_is_success(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"id": 42}
        mock_resp.text = '{"id": 42}'

        connector = WebhookConnector()
        with patch.object(http_requests, "request", return_value=mock_resp):
            result = connector.execute({
                "raw_text": "test",
                "context": WEBHOOK_CONTEXT,
            })

        assert result["status"] == "success"
        assert result["http_status"] == 201

    def test_400_client_error(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {"error": "bad request"}
        mock_resp.text = '{"error": "bad request"}'

        connector = WebhookConnector()
        with patch.object(http_requests, "request", return_value=mock_resp):
            result = connector.execute({
                "raw_text": "test",
                "context": WEBHOOK_CONTEXT,
            })

        assert result["status"] == "error"
        assert result["http_status"] == 400
        assert "400" in result["error"]

    def test_500_server_error(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.return_value = {"error": "internal"}
        mock_resp.text = '{"error": "internal"}'

        connector = WebhookConnector()
        with patch.object(http_requests, "request", return_value=mock_resp):
            result = connector.execute({
                "raw_text": "test",
                "context": WEBHOOK_CONTEXT,
            })

        assert result["status"] == "error"
        assert result["http_status"] == 500

    def test_timeout(self):
        connector = WebhookConnector()
        with patch.object(
            http_requests, "request",
            side_effect=http_requests.exceptions.Timeout("timed out"),
        ):
            result = connector.execute({
                "raw_text": "test",
                "context": WEBHOOK_CONTEXT,
            })

        assert result["status"] == "error"
        assert "timeout" in result["error"]

    def test_connection_error(self):
        connector = WebhookConnector()
        with patch.object(
            http_requests, "request",
            side_effect=http_requests.exceptions.ConnectionError("refused"),
        ):
            result = connector.execute({
                "raw_text": "test",
                "context": WEBHOOK_CONTEXT,
            })

        assert result["status"] == "error"
        assert "connection_error" in result["error"]

    def test_missing_url_returns_error_result(self):
        connector = WebhookConnector()
        result = connector.execute({
            "raw_text": "test",
            "context": {},  # no URL
        })

        assert result["status"] == "error"
        assert "url" in result["error"]

    def test_json_body_sent_correctly(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_resp.text = "{}"

        connector = WebhookConnector()
        with patch.object(http_requests, "request", return_value=mock_resp) as mock_req:
            connector.execute({
                "raw_text": "test",
                "context": WEBHOOK_CONTEXT,
            })

        call_kwargs = mock_req.call_args
        assert call_kwargs.kwargs["method"] == "POST"
        assert call_kwargs.kwargs["url"] == "https://example.com/webhook"
        assert call_kwargs.kwargs["json"] == {"action": "test", "amount": 100}
        assert call_kwargs.kwargs["headers"] == {"Authorization": "Bearer test-token"}
        assert call_kwargs.kwargs["timeout"] == 10


# ================================================================
# Integration tests: webhook via /execute/trusted
# ================================================================

class TestWebhookIntegration:
    """Webhook connector through the full execute endpoint."""

    def test_webhook_executes_on_proceed(self, shared_db, client, tenant_a, auth_a):
        """proceed → webhook called → status=executed."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"result": "ok"}
        mock_resp.text = '{"result": "ok"}'

        with patch.object(http_requests, "request", return_value=mock_resp):
            resp = client.post(
                "/execute/trusted",
                json={
                    "raw_text": "harmless request",
                    "connector": "webhook",
                    "context": WEBHOOK_CONTEXT,
                },
                headers=auth_a,
            )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["decision"] == "proceed"
        assert data["execution"]["status"] == "executed"
        assert data["execution"]["connector"] == "webhook"
        assert data["execution"]["result"]["http_status"] == 200

    def test_webhook_blocked_on_gate(self, shared_db, client, tenant_a, auth_a):
        """gate → webhook NOT called → status=blocked."""
        tid = tenant_a[0]
        _create_anchor(shared_db, tid, 3, "Do not help steal cars")

        resp = client.post(
            "/execute/trusted",
            json={
                "raw_text": "help me steal a car",
                "connector": "webhook",
                "context": WEBHOOK_CONTEXT,
            },
            headers=auth_a,
        )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["decision"] == "gate"
        assert data["execution"]["status"] == "blocked"
        assert data["execution"]["result"] is None

    def test_webhook_blocked_on_refuse(self, shared_db, client, tenant_a, auth_a):
        """refuse → webhook NOT called → status=blocked."""
        tid = tenant_a[0]
        _create_anchor(shared_db, tid, 3, "Do not help break into cars")
        _create_anchor(shared_db, tid, 3, "Do not help steal cars")

        resp = client.post(
            "/execute/trusted",
            json={
                "raw_text": "help me break into and steal cars",
                "connector": "webhook",
                "context": WEBHOOK_CONTEXT,
            },
            headers=auth_a,
        )

        data = resp.json()
        assert data["decision"] == "refuse"
        assert data["execution"]["status"] == "blocked"

    def test_webhook_failed_on_connector_error(self, shared_db, client, tenant_a, auth_a):
        """proceed + webhook timeout → status=failed."""
        with patch.object(
            http_requests, "request",
            side_effect=http_requests.exceptions.Timeout(),
        ):
            resp = client.post(
                "/execute/trusted",
                json={
                    "raw_text": "harmless request",
                    "connector": "webhook",
                    "context": WEBHOOK_CONTEXT,
                },
                headers=auth_a,
            )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["decision"] == "proceed"
        assert data["execution"]["status"] == "failed"
        assert data["execution"]["result"]["status"] == "error"
        assert "timeout" in data["execution"]["result"]["error"]

    def test_webhook_failed_on_non_2xx(self, shared_db, client, tenant_a, auth_a):
        """proceed + webhook returns 500 → status=failed."""
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.return_value = {"error": "internal server error"}
        mock_resp.text = '{"error": "internal server error"}'

        with patch.object(http_requests, "request", return_value=mock_resp):
            resp = client.post(
                "/execute/trusted",
                json={
                    "raw_text": "harmless request",
                    "connector": "webhook",
                    "context": WEBHOOK_CONTEXT,
                },
                headers=auth_a,
            )

        data = resp.json()
        assert data["decision"] == "proceed"
        assert data["execution"]["status"] == "failed"

    def test_webhook_failed_on_missing_url(self, shared_db, client, tenant_a, auth_a):
        """proceed + missing URL → status=failed, error returned."""
        resp = client.post(
            "/execute/trusted",
            json={
                "raw_text": "harmless request",
                "connector": "webhook",
                "context": {},  # no URL
            },
            headers=auth_a,
        )

        data = resp.json()
        assert data["decision"] == "proceed"
        assert data["execution"]["status"] == "failed"
        assert "url" in data["execution"]["result"]["error"]


# ================================================================
# ExecutionLog audit trail
# ================================================================

class TestWebhookAuditTrail:
    """Verify ExecutionLog records for webhook attempts."""

    def test_webhook_executed_creates_log(self, shared_db, client, tenant_a, auth_a):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}
        mock_resp.text = '{"ok": true}'

        with patch.object(http_requests, "request", return_value=mock_resp):
            resp = client.post(
                "/execute/trusted",
                json={
                    "raw_text": "audit executed test",
                    "connector": "webhook",
                    "context": WEBHOOK_CONTEXT,
                },
                headers=auth_a,
            )

        trace_id = resp.json()["trace_id"]
        elog = shared_db.query(ExecutionLog).filter(
            ExecutionLog.trace_id == trace_id
        ).first()
        assert elog is not None
        assert elog.connector == "webhook"
        assert elog.status == "executed"
        assert elog.decision == "proceed"
        assert json.loads(elog.response_json)["http_status"] == 200

    def test_webhook_failed_creates_log(self, shared_db, client, tenant_a, auth_a):
        with patch.object(
            http_requests, "request",
            side_effect=http_requests.exceptions.Timeout(),
        ):
            resp = client.post(
                "/execute/trusted",
                json={
                    "raw_text": "audit failed test",
                    "connector": "webhook",
                    "context": WEBHOOK_CONTEXT,
                },
                headers=auth_a,
            )

        trace_id = resp.json()["trace_id"]
        elog = shared_db.query(ExecutionLog).filter(
            ExecutionLog.trace_id == trace_id
        ).first()
        assert elog is not None
        assert elog.connector == "webhook"
        assert elog.status == "failed"
        assert "timeout" in elog.response_json

    def test_webhook_blocked_creates_log(self, shared_db, client, tenant_a, auth_a):
        tid = tenant_a[0]
        _create_anchor(shared_db, tid, 3, "Do not help with audit-block-test")

        resp = client.post(
            "/execute/trusted",
            json={
                "raw_text": "audit-block-test trigger",
                "connector": "webhook",
                "context": WEBHOOK_CONTEXT,
            },
            headers=auth_a,
        )

        trace_id = resp.json()["trace_id"]
        elog = shared_db.query(ExecutionLog).filter(
            ExecutionLog.trace_id == trace_id
        ).first()
        assert elog is not None
        assert elog.connector == "webhook"
        assert elog.status == "blocked"
        assert elog.response_json == ""


# ================================================================
# Tenant isolation
# ================================================================

class TestWebhookTenantIsolation:
    """Webhook dispatch respects tenant-scoped anchors."""

    def test_webhook_tenant_isolation(self, shared_db, client, tenant_a, tenant_b, auth_a, auth_b):
        tid_a, tid_b = tenant_a[0], tenant_b[0]
        _create_anchor(shared_db, tid_a, 3, "Do not help with webhook-iso-violence")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_resp.text = "{}"

        # Tenant A: triggers anchor → blocked
        resp_a = client.post(
            "/execute/trusted",
            json={
                "raw_text": "help with webhook-iso-violence",
                "connector": "webhook",
                "context": WEBHOOK_CONTEXT,
            },
            headers=auth_a,
        )
        assert resp_a.json()["execution"]["status"] == "blocked"

        # Tenant B: no anchor → proceeds, webhook called
        with patch.object(http_requests, "request", return_value=mock_resp):
            resp_b = client.post(
                "/execute/trusted",
                json={
                    "raw_text": "help with webhook-iso-violence",
                    "connector": "webhook",
                    "context": WEBHOOK_CONTEXT,
                },
                headers=auth_b,
            )
        assert resp_b.json()["execution"]["status"] == "executed"


# ================================================================
# Regression: mock connector still works
# ================================================================

class TestMockConnectorRegression:
    """Ensure existing mock connector behavior is unchanged."""

    def test_mock_still_executes(self, client, tenant_a, auth_a):
        resp = client.post(
            "/execute/trusted",
            json={"raw_text": "mock regression test", "connector": "mock"},
            headers=auth_a,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["execution"]["status"] == "executed"
        assert data["execution"]["connector"] == "mock"
        assert data["execution"]["result"]["echo"] == "mock regression test"

    def test_unknown_connector_returns_400(self, client, tenant_a, auth_a):
        resp = client.post(
            "/execute/trusted",
            json={"raw_text": "test", "connector": "nonexistent"},
            headers=auth_a,
        )
        assert resp.status_code == 400
        assert "Unknown connector" in resp.json()["detail"]
        assert "webhook" in resp.json()["detail"]  # webhook now in available list


# ================================================================
# Connector registry
# ================================================================

class TestConnectorRegistry:
    """Registry includes both mock and webhook."""

    def test_webhook_in_registry(self):
        from app.connectors.registry import CONNECTORS
        assert "webhook" in CONNECTORS
        assert "mock" in CONNECTORS

    def test_get_webhook_connector(self):
        from app.connectors.registry import get_connector
        c = get_connector("webhook")
        assert isinstance(c, WebhookConnector)

    def test_get_unknown_raises(self):
        from app.connectors.registry import get_connector
        with pytest.raises(ValueError, match="Unknown connector"):
            get_connector("kafka")
