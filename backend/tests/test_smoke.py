"""
Smoke / integration tests — require a running server at BASE_URL.

Start the server first:
    cd backend/src
    python -m uvicorn app.main:app --reload

Then run:
    pytest tests/test_smoke.py
"""
import uuid
import httpx
import pytest

BASE_URL = "http://127.0.0.1:8000"


def _unique(prefix: str) -> str:
    return f"{prefix} [{uuid.uuid4().hex[:8]}]"


def _create_anchor(statement: str, level: int = 1, headers: dict = None) -> dict:
    r = httpx.post(f"{BASE_URL}/anchors/", json={"level": level, "statement": statement}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _archive_anchor(anchor_id: int, headers: dict = None) -> None:
    httpx.post(f"{BASE_URL}/anchors/{anchor_id}/archive", headers=headers)


def test_health_ok():
    r = httpx.get(f"{BASE_URL}/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_create_and_list_anchor(auth_headers):
    statement = _unique("pytest anchor")
    created = _create_anchor(statement, headers=auth_headers)
    assert created["statement"] == statement
    assert "id" in created
    r2 = httpx.get(f"{BASE_URL}/anchors/", headers=auth_headers)
    assert r2.status_code == 200
    ids = [a["id"] for a in r2.json()]
    assert created["id"] in ids
    _archive_anchor(created["id"], headers=auth_headers)


def test_get_anchor_by_id(auth_headers):
    statement = _unique("pytest get-by-id anchor")
    created = _create_anchor(statement, headers=auth_headers)
    anchor_id = created["id"]
    r = httpx.get(f"{BASE_URL}/anchors/{anchor_id}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["id"] == anchor_id
    _archive_anchor(anchor_id, headers=auth_headers)


def test_get_anchor_not_found(auth_headers):
    r = httpx.get(f"{BASE_URL}/anchors/999999999", headers=auth_headers)
    assert r.status_code == 404


def test_archive_anchor(auth_headers):
    statement = _unique("pytest anchor to archive")
    created = _create_anchor(statement, headers=auth_headers)
    anchor_id = created["id"]
    r2 = httpx.post(f"{BASE_URL}/anchors/{anchor_id}/archive", headers=auth_headers)
    assert r2.status_code == 200
    assert r2.json().get("active") in (False, 0)
    r3 = httpx.get(f"{BASE_URL}/anchors/", headers=auth_headers)
    active_ids = [a["id"] for a in r3.json()]
    assert anchor_id not in active_ids


def test_gate_warns_on_conflict(auth_headers):
    statement = _unique("zephyr cats are allowed")
    created = _create_anchor(statement, level=1, headers=auth_headers)
    payload = {
        "request_summary": "zephyr cats are not allowed",
        "arousal": "unknown",
        "dominance": "unknown",
    }
    r = httpx.post(f"{BASE_URL}/gate/evaluate", json=payload, headers=auth_headers)
    assert r.status_code == 200
    out = r.json()
    assert out.get("conflicted_anchor_ids"), out
    _archive_anchor(created["id"], headers=auth_headers)


def test_gate_proceeds_when_no_conflict(auth_headers):
    payload = {
        "request_summary": f"completely unrelated xyzzy request {uuid.uuid4().hex}",
        "arousal": "unknown",
        "dominance": "unknown",
    }
    r = httpx.post(f"{BASE_URL}/gate/evaluate", json=payload, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["decision"] == "proceed"


def test_gate_refuses_on_multi_l3(auth_headers):
    tag = uuid.uuid4().hex[:8]
    anchor1 = _create_anchor(f"smoke refusal alpha {tag}", level=3, headers=auth_headers)
    anchor2 = _create_anchor(f"smoke refusal beta {tag}", level=3, headers=auth_headers)
    try:
        payload = {
            "request_summary": f"smoke refusal alpha beta {tag}",
            "arousal": "unknown",
            "dominance": "unknown",
        }
        r = httpx.post(f"{BASE_URL}/gate/evaluate", json=payload, headers=auth_headers)
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["decision"] == "refuse", out
        assert out["reason"] == "multi_l3_conflict", out
        assert len(out["conflicted_anchor_ids"]) >= 2, out
    finally:
        _archive_anchor(anchor1["id"], headers=auth_headers)
        _archive_anchor(anchor2["id"], headers=auth_headers)


def test_gate_logs_are_listed(auth_headers):
    payload = {
        "request_summary": _unique("smoke test log entry"),
        "arousal": "low",
        "dominance": "high",
    }
    r = httpx.post(f"{BASE_URL}/gate/evaluate", json=payload, headers=auth_headers)
    assert r.status_code == 200
    log_id = r.json()["log_id"]
    r2 = httpx.get(f"{BASE_URL}/gate/logs", headers=auth_headers)
    assert r2.status_code == 200
    data = r2.json()
    assert "items" in data
    assert any(item["id"] == log_id for item in data["items"])
