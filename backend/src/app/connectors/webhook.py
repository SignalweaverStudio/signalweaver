"""
Webhook connector — dispatches governed execution requests to configurable HTTP endpoints.

Safety rules:
  - URL must be present and use http:// or https:// only
  - Method restricted to POST, PUT, PATCH
  - Timeout enforced (default 10s, configurable via context.timeout)
  - Payload must be JSON-serializable
  - Response must be structured and predictable
  - Optional request signing (HMAC-SHA256) when signing_secret provided
  - Sensitive fields in response bodies are NOT redacted here; that is
    the caller's responsibility (execute.py applies redaction before
    storage and API response).

Configuration is passed in the request context dict:
  {
      "url": "https://example.com/webhook",
      "method": "POST",
      "headers": {"Authorization": "Bearer x"},
      "payload": {"action": "refund", "amount": 250},
      "timeout": 10,                    (optional, seconds)
      "signing_secret": "shared-secret"  (optional, enables HMAC signing)
  }

Signing behavior:
  - When signing_secret is present in context, computes HMAC-SHA256 over
    the outbound JSON payload and attaches:
      X-SignalWeaver-Signature: sha256=<hex digest>
      X-SignalWeaver-Timestamp: <unix epoch seconds>
  - The signing_secret is never included in the stored result or response.
  - When signing_secret is absent, no signing headers are added.

Returns:
  {"status": "success", "http_status": 200, "response_body": {...}}
  {"status": "error", "error": "<reason>"}
  {"status": "error", "http_status": 500, "response_body": {...}, "error": "HTTP 500"}
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

import requests as http_requests

from app.connectors.base import Connector
from app.connectors.signing import build_signed_headers

ALLOWED_METHODS = {"POST", "PUT", "PATCH"}
DEFAULT_TIMEOUT = 10  # seconds


class WebhookValidationError(Exception):
    """Raised when webhook request config is invalid."""
    pass


def _validate_webhook_config(context: dict[str, Any]) -> tuple[str, str, dict, dict, int]:
    """
    Extract and validate webhook configuration from the context dict.

    Returns:
        (url, method, headers, payload, timeout)

    Raises:
        WebhookValidationError: on invalid config
    """
    url = context.get("url")
    if not url or not isinstance(url, str):
        raise WebhookValidationError("Webhook config requires 'url' in context")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise WebhookValidationError(
            f"Webhook URL scheme must be http or https, got '{parsed.scheme}'"
        )

    method = context.get("method", "POST")
    if not isinstance(method, str) or method.upper() not in ALLOWED_METHODS:
        raise WebhookValidationError(
            f"Webhook method must be one of {sorted(ALLOWED_METHODS)}, got '{method}'"
        )
    method = method.upper()

    headers = context.get("headers")
    if headers is None:
        headers = {}
    if not isinstance(headers, dict):
        raise WebhookValidationError("Webhook 'headers' must be a dict or omitted")

    payload = context.get("payload", {})
    if not isinstance(payload, dict):
        raise WebhookValidationError("Webhook 'payload' must be a dict")

    # Verify payload is JSON-serializable
    try:
        json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        raise WebhookValidationError(f"Webhook payload is not JSON-serializable: {e}")

    timeout = context.get("timeout", DEFAULT_TIMEOUT)
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        raise WebhookValidationError("Webhook 'timeout' must be a positive number")
    # Cap timeout at 30s to prevent abuse
    timeout = min(timeout, 30)

    return url, method, headers, payload, timeout


class WebhookConnector(Connector):
    """
    Real HTTP webhook connector.

    Dispatches governed requests to external HTTP endpoints.
    Governance is handled by the caller (execute.py); this connector
    only validates config and makes the HTTP call.

    Optionally signs requests with HMAC-SHA256 when a signing_secret
    is provided in the context. The secret is never persisted or echoed.
    """

    def execute(self, request: dict[str, Any]) -> dict[str, Any]:
        context = request.get("context", {})
        if not isinstance(context, dict):
            context = {}

        # Validate configuration
        try:
            url, method, headers, payload, timeout = _validate_webhook_config(context)
        except WebhookValidationError as e:
            return {"status": "error", "error": str(e)}

        # --- Request signing (optional, additive) ---
        signing_secret = context.get("signing_secret")
        if signing_secret and isinstance(signing_secret, str):
            # Build signing headers and merge with caller-provided headers.
            # Signing headers are appended; caller headers take precedence
            # if there is a collision (caller controls their own auth).
            signing_headers = build_signed_headers(payload, signing_secret)
            merged_headers = {**signing_headers, **headers}
        else:
            merged_headers = headers

        # Make the HTTP call with real (unredacted) headers
        try:
            resp = http_requests.request(
                method=method,
                url=url,
                json=payload,
                headers=merged_headers,
                timeout=timeout,
            )
        except http_requests.exceptions.Timeout:
            return {"status": "error", "error": "timeout"}
        except http_requests.exceptions.ConnectionError as e:
            return {"status": "error", "error": f"connection_error: {str(e)[:200]}"}
        except Exception as e:
            return {"status": "error", "error": f"request_error: {str(e)[:200]}"}

        # Check response status
        http_status = resp.status_code
        try:
            response_body = resp.json()
        except Exception:
            response_body = resp.text[:2000] if resp.text else ""

        if 200 <= http_status < 300:
            return {
                "status": "success",
                "http_status": http_status,
                "response_body": response_body,
            }
        else:
            return {
                "status": "error",
                "http_status": http_status,
                "error": f"HTTP {http_status}",
                "response_body": response_body,
            }
