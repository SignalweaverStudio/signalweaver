"""
test_secure_dispatch.py — Tests for Stage 18: Secure Dispatch Layer.

Covers:
  1. Redaction unit tests
  2. Signing unit tests
  3. Webhook connector signing integration
  4. Storage safety (via /execute/trusted integration)
  5. Regression
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
import os
from unittest.mock import patch, MagicMock

import pytest
import requests as http_requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models import Tenant, TruthAnchor, ExecutionLog
from app.auth import generate_api_key
from app.connectors.webhook import WebhookConnector
from app.connectors.redaction import redact_sensitive, REDACT_MARKER
from app.connectors.signing import sign_payload, build_signed_headers, SIGNATURE_HEADER, TIMESTAMP_HEADER


@pytest.fixture(scope="module")
def tenant_a(shared_db):
    raw_key, hashed = generate_api_key()
    t = Tenant(name="secure-tenant-a", api_key_hash=hashed)
    shared_db.add(t)
    shared_db.commit()
    shared_db.refresh(t)
    return t.id, raw_key


@pytest.fixture(scope="module")
def auth_a(tenant_a):
    return {"Authorization": f"Bearer {tenant_a[1]}"}


def _create_anchor(db, tenant_id, level, statement, scope="global"):
    a = TruthAnchor(
        level=level, statement=statement, scope=scope,
        active=True, tenant_id=tenant_id,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


# ================================================================
# 1. Redaction unit tests
# ================================================================

class TestRedaction:
    """Unit tests for redact_sensitive()."""

    def test_authorization_header_redacted(self):
        result = redact_sensitive({"Authorization": "Bearer secret-token-123"})
        assert result["Authorization"] == REDACT_MARKER

    def test_token_field_redacted(self):
        result = redact_sensitive({"token": "abc123"})
        assert result["token"] == REDACT_MARKER

    def test_api_key_field_redacted(self):
        result = redact_sensitive({"api_key": "sk-xyz"})
        assert result["api_key"] == REDACT_MARKER

    def test_apikey_field_redacted(self):
        result = redact_sensitive({"apikey": "key-456"})
        assert result["apikey"] == REDACT_MARKER

    def test_password_field_redacted(self):
        result = redact_sensitive({"password": "p@ssw0rd"})
        assert result["password"] == REDACT_MARKER

    def test_signature_field_redacted(self):
        result = redact_sensitive({"signature": "sig-abc"})
        assert result["signature"] == REDACT_MARKER

    def test_signing_secret_field_redacted(self):
        result = redact_sensitive({"signing_secret": "my-secret"})
        assert result["signing_secret"] == REDACT_MARKER

    def test_case_insensitive_key_matching(self):
        """Keys should be matched case-insensitively."""
        result = redact_sensitive({
            "AUTHORIZATION": "Bearer x",
            "Token": "t",
            "API_KEY": "k",
            "Apikey": "k2",
            "SECRET": "s",
            "Password": "p",
            "SIGNATURE": "sig",
        })
        for key in ["AUTHORIZATION", "Token", "API_KEY", "Apikey", "SECRET", "Password", "SIGNATURE"]:
            assert result[key] == REDACT_MARKER, f"Expected {key} to be redacted"

    def test_non_sensitive_fields_preserved(self):
        data = {
            "name": "test",
            "action": "refund",
            "amount": 250,
            "url": "https://example.com",
            "status": "success",
        }
        result = redact_sensitive(data)
        assert result == data

    def test_nested_sensitive_fields_redacted(self):
        data = {
            "response_body": {
                "api_key": "secret-key",
                "user": {"name": "Alice", "token": "t-123"},
            }
        }
        result = redact_sensitive(data)
        assert result["response_body"]["api_key"] == REDACT_MARKER
        assert result["response_body"]["user"]["name"] == "Alice"
        assert result["response_body"]["user"]["token"] == REDACT_MARKER

    def test_list_wrapped_sensitive_fields_redacted(self):
        data = [
            {"token": "t1", "safe": "v1"},
            {"Authorization": "Bearer x", "safe": "v2"},
        ]
        result = redact_sensitive(data)
        assert result[0]["token"] == REDACT_MARKER
        assert result[0]["safe"] == "v1"
        assert result[1]["Authorization"] == REDACT_MARKER
        assert result[1]["safe"] == "v2"

    def test_deeply_nested_redaction(self):
        data = {"a": {"b": {"c": {"secret": "deep-secret"}}}}
        result = redact_sensitive(data)
        assert result["a"]["b"]["c"]["secret"] == REDACT_MARKER

    def test_string_primitive_unchanged(self):
        assert redact_sensitive("plain string") == "plain string"

    def test_integer_primitive_unchanged(self):
        assert redact_sensitive(42) == 42

    def test_none_unchanged(self):
        assert redact_sensitive(None) is None

    def test_bool_unchanged(self):
        assert redact_sensitive(True) is True

    def test_empty_dict(self):
        assert redact_sensitive({}) == {}

    def test_empty_list(self):
        assert redact_sensitive([]) == []

    def test_mixed_nested_structure(self):
        data = {
            "items": [
                {"name": "item1", "api_key": "key1"},
                {"name": "item2"},
            ],
            "meta": {"total": 2, "token": "t"},
            "status": "ok",
        }
        result = redact_sensitive(data)
        assert result["items"][0]["name"] == "item1"
        assert result["items"][0]["api_key"] == REDACT_MARKER
        assert result["items"][1]["name"] == "item2"
        assert result["meta"]["total"] == 2
        assert result["meta"]["token"] == REDACT_MARKER
        assert result["status"] == "ok"

    def test_does_not_mutate_original(self):
        original = {"Authorization": "Bearer x", "safe": "val"}
        original_list = [original]
        result = redact_sensitive(original_list)
        assert original["Authorization"] == "Bearer x"
        assert result[0]["Authorization"] == REDACT_MARKER

    def test_sensitive_key_with_whitespace_trimmed(self):
        result = redact_sensitive({"  token  ": "val"})
        assert result["  token  "] == REDACT_MARKER


# ================================================================
# 2. Signing unit tests
# ================================================================

class TestSigning:
    """Unit tests for request signing."""

    def test_sign_payload_returns_hex_digest(self):
        payload = b'{"action":"test"}'
        secret = "my-secret"
        sig = sign_payload(payload, secret)
        assert isinstance(sig, str)
        assert len(sig) == 64
        int(sig, 16)

    def test_sign_payload_deterministic(self):
        payload = b'{"action":"test"}'
        secret = "my-secret"
        sig1 = sign_payload(payload, secret)
        sig2 = sign_payload(payload, secret)
        assert sig1 == sig2

    def test_sign_payload_different_secrets_differ(self):
        payload = b'{"action":"test"}'
        sig1 = sign_payload(payload, "secret-a")
        sig2 = sign_payload(payload, "secret-b")
        assert sig1 != sig2

    def test_sign_payload_matches_stdlib_hmac(self):
        payload = b'{"action":"refund","amount":250}'
        secret = "shared-secret-xyz"
        expected = hmac.new(
            secret.encode("utf-8"), payload, hashlib.sha256
        ).hexdigest()
        assert sign_payload(payload, secret) == expected

    def test_build_signed_headers_has_signature(self):
        headers = build_signed_headers({"action": "test"}, "secret")
        assert SIGNATURE_HEADER in headers
        assert headers[SIGNATURE_HEADER].startswith("sha256=")

    def test_build_signed_headers_has_timestamp(self):
        headers = build_signed_headers({"action": "test"}, "secret")
        assert TIMESTAMP_HEADER in headers
        int(headers[TIMESTAMP_HEADER])

    def test_build_signed_headers_signature_correct(self):
        payload = {"action": "test"}
        secret = "my-signing-secret"
        headers = build_signed_headers(payload, secret)
        sig_value = headers[SIGNATURE_HEADER].replace("sha256=", "")
        payload_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        expected = hmac.new(
            secret.encode("utf-8"), payload_bytes, hashlib.sha256
        ).hexdigest()
        assert sig_value == expected

    def test_build_signed_headers_has_exactly_two_keys(self):
        headers = build_signed_headers({"data": 1}, "s")
        assert len(headers) == 2
        assert SIGNATURE_HEADER in headers
        assert TIMESTAMP_HEADER in headers


# ================================================================
# 3. Webhook connector signing integration
# ================================================================

class TestWebhookSigning:
    """Webhook connector signing via mocked HTTP."""

    def test_signed_request_includes_signature_header(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}
        mock_resp.text = '{"ok": true}'

        ctx = {
            "url": "https://example.com/webhook",
            "method": "POST",
            "headers": {"Content-Type": "application/json"},
            "payload": {"action": "test"},
            "signing_secret": "my-secret",
        }

        connector = WebhookConnector()
        with patch.object(http_requests, "request", return_value=mock_resp) as mock_req:
            result = connector.execute({"raw_text": "test", "context": ctx})

        assert result["status"] == "success"
        call_kwargs = mock_req.call_args.kwargs
        sent_headers = call_kwargs["headers"]
        assert SIGNATURE_HEADER in sent_headers
        assert sent_headers[SIGNATURE_HEADER].startswith("sha256=")

    def test_signed_request_includes_timestamp_header(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_resp.text = "{}"

        ctx = {
            "url": "https://example.com/webhook",
            "payload": {"data": 1},
            "signing_secret": "secret",
        }

        connector = WebhookConnector()
        with patch.object(http_requests, "request", return_value=mock_resp) as mock_req:
            connector.execute({"raw_text": "test", "context": ctx})

        sent_headers = mock_req.call_args.kwargs["headers"]
        assert TIMESTAMP_HEADER in sent_headers
        int(sent_headers[TIMESTAMP_HEADER])

    def test_unsigned_request_no_signing_headers(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_resp.text = "{}"

        ctx = {
            "url": "https://example.com/webhook",
            "payload": {"data": 1},
        }

        connector = WebhookConnector()
        with patch.object(http_requests, "request", return_value=mock_resp) as mock_req:
            connector.execute({"raw_text": "test", "context": ctx})

        sent_headers = mock_req.call_args.kwargs["headers"]
        assert SIGNATURE_HEADER not in sent_headers
        assert TIMESTAMP_HEADER not in sent_headers

    def test_signing_secret_not_in_result(self):
        """The signing_secret must never appear in the connector result."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_resp.text = "{}"

        ctx = {
            "url": "https://example.com/webhook",
            "payload": {"data": 1},
            "signing_secret": "super-secret-value",
        }

        connector = WebhookConnector()
        with patch.object(http_requests, "request", return_value=mock_resp):
            result = connector.execute({"raw_text": "test", "context": ctx})

        result_str = json.dumps(result)
        assert "super-secret-value" not in result_str

    def test_caller_headers_preserved_with_signing(self):
        """Caller-provided headers are preserved alongside signing headers."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_resp.text = "{}"

        ctx = {
            "url": "https://example.com/webhook",
            "headers": {"X-Custom": "value", "Authorization": "Bearer token"},
            "payload": {"data": 1},
            "signing_secret": "secret",
        }

        connector = WebhookConnector()
        with patch.object(http_requests, "request", return_value=mock_resp) as mock_req:
            connector.execute({"raw_text": "test", "context": ctx})

        sent_headers = mock_req.call_args.kwargs["headers"]
        assert sent_headers["X-Custom"] == "value"
        assert sent_headers["Authorization"] == "Bearer token"
        assert SIGNATURE_HEADER in sent_headers

    def test_non_string_signing_secret_ignored(self):
        """Non-string signing_secret should be ignored (no signing applied)."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_resp.text = "{}"

        ctx = {
            "url": "https://example.com/webhook",
            "payload": {"data": 1},
            "signing_secret": 12345,
        }

        connector = WebhookConnector()
        with patch.object(http_requests, "request", return_value=mock_resp) as mock_req:
            connector.execute({"raw_text": "test", "context": ctx})

        sent_headers = mock_req.call_args.kwargs["headers"]
        assert SIGNATURE_HEADER not in sent_headers


# ================================================================
# 4. Storage safety (integration via /execute/trusted)
# ================================================================

class TestStorageSafety:
    """Verify that secrets are redacted in ExecutionLog.response_json and API responses."""

    def test_webhook_response_with_sensitive_fields_redacted_in_db(self, shared_db, client, tenant_a, auth_a):
        """Target echoes back sensitive fields → stored redacted."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "result": "ok",
            "api_key": "leaked-key-123",
            "user_token": "leaked-token",
            "auth": "leaked-auth",
        }
        mock_resp.text = '{"result":"ok","api_key":"leaked-key-123"}'

        ctx = {
            "url": "https://example.com/webhook",
            "method": "POST",
            "payload": {"action": "test"},
        }

        with patch.object(http_requests, "request", return_value=mock_resp):
            resp = client.post(
                "/execute/trusted",
                json={
                    "raw_text": "storage safety test 1",
                    "connector": "webhook",
                    "context": ctx,
                },
                headers=auth_a,
            )

        assert resp.status_code == 200
        trace_id = resp.json()["trace_id"]

        elog = shared_db.query(ExecutionLog).filter(
            ExecutionLog.trace_id == trace_id
        ).first()
        assert elog is not None
        stored = json.loads(elog.response_json)
        assert stored["response_body"]["api_key"] == REDACT_MARKER
        assert stored["response_body"]["user_token"] == "leaked-token"
        assert stored["response_body"]["auth"] == "leaked-auth"
        assert stored["response_body"]["result"] == "ok"

    def test_api_response_redacts_sensitive_fields(self, client, tenant_a, auth_a):
        """API response also contains redacted data."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "ok",
            "token": "should-not-appear-in-response",
        }
        mock_resp.text = '{"status":"ok","token":"secret"}'

        ctx = {
            "url": "https://example.com/webhook",
            "payload": {},
        }

        with patch.object(http_requests, "request", return_value=mock_resp):
            resp = client.post(
                "/execute/trusted",
                json={
                    "raw_text": "api response safety test",
                    "connector": "webhook",
                    "context": ctx,
                },
                headers=auth_a,
            )

        data = resp.json()
        result = data["execution"]["result"]
        assert result["response_body"]["token"] == REDACT_MARKER
        assert "should-not-appear-in-response" not in json.dumps(data)

    def test_mock_connector_context_redacted_in_db(self, shared_db, client, tenant_a, auth_a):
        """MockConnector echoes context → sensitive context fields redacted in storage."""
        resp = client.post(
            "/execute/trusted",
            json={
                "raw_text": "mock context safety test",
                "connector": "mock",
                "context": {
                    "api_key": "mock-leaked-key",
                    "password": "mock-leaked-pass",
                    "safe_field": "visible",
                },
            },
            headers=auth_a,
        )

        assert resp.status_code == 200
        trace_id = resp.json()["trace_id"]

        elog = shared_db.query(ExecutionLog).filter(
            ExecutionLog.trace_id == trace_id
        ).first()
        assert elog is not None
        stored = json.loads(elog.response_json)
        assert stored["context"]["api_key"] == REDACT_MARKER
        assert stored["context"]["password"] == REDACT_MARKER
        assert stored["context"]["safe_field"] == "visible"

    def test_mock_connector_context_redacted_in_api_response(self, client, tenant_a, auth_a):
        """MockConnector API response also has redacted context."""
        resp = client.post(
            "/execute/trusted",
            json={
                "raw_text": "mock api safety test",
                "connector": "mock",
                "context": {
                    "secret": "should-be-redacted",
                    "normal": "visible",
                },
            },
            headers=auth_a,
        )

        data = resp.json()
        context = data["execution"]["result"]["context"]
        assert context["secret"] == REDACT_MARKER
        assert context["normal"] == "visible"

    def test_webhook_failure_stored_safely(self, shared_db, client, tenant_a, auth_a):
        """Webhook failure result stored safely (no sensitive leakage in error messages)."""
        ctx = {
            "url": "https://example.com/webhook",
            "payload": {"token": "t"},
        }

        with patch.object(
            http_requests, "request",
            side_effect=http_requests.exceptions.Timeout(),
        ):
            resp = client.post(
                "/execute/trusted",
                json={
                    "raw_text": "failure safety test",
                    "connector": "webhook",
                    "context": ctx,
                },
                headers=auth_a,
            )

        trace_id = resp.json()["trace_id"]
        elog = shared_db.query(ExecutionLog).filter(
            ExecutionLog.trace_id == trace_id
        ).first()
        assert elog is not None
        stored = json.loads(elog.response_json)
        assert stored["status"] == "error"
        assert "timeout" in stored["error"]

    def test_blocked_execution_no_connector_result_stored(self, shared_db, client, tenant_a, auth_a):
        """Blocked execution: response_json should be empty (no result to redact)."""
        tid = tenant_a[0]
        _create_anchor(shared_db, tid, 3, "Do not help with secure-block-test")

        resp = client.post(
            "/execute/trusted",
            json={
                "raw_text": "secure-block-test trigger",
                "connector": "webhook",
                "context": {"url": "https://x.com/hook", "payload": {"api_key": "secret"}},
            },
            headers=auth_a,
        )

        trace_id = resp.json()["trace_id"]
        elog = shared_db.query(ExecutionLog).filter(
            ExecutionLog.trace_id == trace_id
        ).first()
        assert elog is not None
        assert elog.status == "blocked"
        assert elog.response_json == ""

    def test_webhook_signing_secret_never_persisted(self, shared_db, client, tenant_a, auth_a):
        """signing_secret from context must never appear in ExecutionLog."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}
        mock_resp.text = '{"ok": true}'

        secret_value = "my-precious-signing-secret-789"
        ctx = {
            "url": "https://example.com/webhook",
            "payload": {"data": 1},
            "signing_secret": secret_value,
        }

        with patch.object(http_requests, "request", return_value=mock_resp):
            resp = client.post(
                "/execute/trusted",
                json={
                    "raw_text": "signing secret persistence test",
                    "connector": "webhook",
                    "context": ctx,
                },
                headers=auth_a,
            )

        trace_id = resp.json()["trace_id"]
        elog = shared_db.query(ExecutionLog).filter(
            ExecutionLog.trace_id == trace_id
        ).first()
        assert elog is not None
        assert secret_value not in elog.response_json
        assert secret_value not in resp.text


# ================================================================
# 5. Regression: existing semantics unchanged
# ================================================================

class TestRegression:
    """Ensure existing behavior is preserved after security changes."""

    def test_mock_connector_still_works(self, client, tenant_a, auth_a):
        resp = client.post(
            "/execute/trusted",
            json={"raw_text": "regression mock test", "connector": "mock"},
            headers=auth_a,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["execution"]["status"] == "executed"
        assert data["execution"]["connector"] == "mock"
        assert data["execution"]["result"]["echo"] == "regression mock test"

    def test_webhook_still_dispatches(self, client, tenant_a, auth_a):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"result": "ok"}
        mock_resp.text = '{"result": "ok"}'

        ctx = {
            "url": "https://example.com/webhook",
            "payload": {"action": "test"},
        }

        with patch.object(http_requests, "request", return_value=mock_resp):
            resp = client.post(
                "/execute/trusted",
                json={
                    "raw_text": "regression webhook test",
                    "connector": "webhook",
                    "context": ctx,
                },
                headers=auth_a,
            )

        data = resp.json()
        assert data["decision"] == "proceed"
        assert data["execution"]["status"] == "executed"
        assert data["execution"]["connector"] == "webhook"
        assert data["execution"]["result"]["http_status"] == 200

    def test_blocked_decision_still_blocks(self, shared_db, client, tenant_a, auth_a):
        tid = tenant_a[0]
        _create_anchor(shared_db, tid, 3, "Do not help with regression-block")

        resp = client.post(
            "/execute/trusted",
            json={"raw_text": "regression-block trigger", "connector": "webhook"},
            headers=auth_a,
        )

        data = resp.json()
        assert data["execution"]["status"] == "blocked"
        assert data["execution"]["result"] is None

    def test_failed_webhook_still_marks_failed(self, client, tenant_a, auth_a):
        with patch.object(
            http_requests, "request",
            side_effect=http_requests.exceptions.ConnectionError("refused"),
        ):
            resp = client.post(
                "/execute/trusted",
                json={
                    "raw_text": "regression fail test",
                    "connector": "webhook",
                    "context": {
                        "url": "https://example.com/webhook",
                        "payload": {},
                    },
                },
                headers=auth_a,
            )

        data = resp.json()
        assert data["execution"]["status"] == "failed"

    def test_non_2xx_still_marks_failed(self, client, tenant_a, auth_a):
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_resp.json.return_value = {"error": "unavailable"}
        mock_resp.text = '{"error": "unavailable"}'

        with patch.object(http_requests, "request", return_value=mock_resp):
            resp = client.post(
                "/execute/trusted",
                json={
                    "raw_text": "regression 503 test",
                    "connector": "webhook",
                    "context": {
                        "url": "https://example.com/webhook",
                        "payload": {},
                    },
                },
                headers=auth_a,
            )

        data = resp.json()
        assert data["execution"]["status"] == "failed"

    def test_execution_log_still_created(self, shared_db, client, tenant_a, auth_a):
        resp = client.post(
            "/execute/trusted",
            json={"raw_text": "regression log test", "connector": "mock"},
            headers=auth_a,
        )

        trace_id = resp.json()["trace_id"]
        elog = shared_db.query(ExecutionLog).filter(
            ExecutionLog.trace_id == trace_id
        ).first()
        assert elog is not None
        assert elog.connector == "mock"
        assert elog.status == "executed"