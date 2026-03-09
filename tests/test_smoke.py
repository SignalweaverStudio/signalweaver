"""
SignalWeaver smoke tests
Runs against a live server at http://127.0.0.1:8000

Start the server first:
    cd backend/src
    python -m uvicorn app.main:app --reload

Then run:
    pip install httpx pytest
    pytest tests/test_smoke.py -v
"""

import httpx
import pytest
import time


def request_with_retry(method, url, **kwargs):
    for _ in range(10):
        r = httpx.request(method, url, **kwargs)
        if r.status_code != 429:
            return r
        time.sleep(1.1)
    return r

BASE_URL = "http://127.0.0.1:8000"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def evaluate(request_summary, arousal="unknown", dominance="unknown", profile_id=None):
    payload = {
        "request_summary": request_summary,
        "arousal": arousal,
        "dominance": dominance,
    }
    if profile_id is not None:
        payload["profile_id"] = profile_id
    r = request_with_retry("POST", f"{BASE_URL}/gate/evaluate", json=payload)
    assert r.status_code == 200, f"evaluate failed: {r.text}"
    return r.json()


def create_anchor(level, statement, scope="global"):
    r = request_with_retry("POST", f"{BASE_URL}/anchors/", json={
        "level": level,
        "statement": statement,
        "scope": scope,
    })
    assert r.status_code == 200, f"create_anchor failed: {r.text}"
    return r.json()


def create_profile(name, description=""):
    r = request_with_retry("POST", f"{BASE_URL}/profiles", json={
        "name": name,
        "description": description,
    })
    assert r.status_code == 201, f"create_profile failed: {r.text}"
    return r.json()

def assign_anchors(profile_id, anchor_ids):
    r = httpx.put(f"{BASE_URL}/profiles/{profile_id}/anchors", json={
        "anchor_ids": anchor_ids,
    })
    assert r.status_code == 200, f"assign_anchors failed: {r.text}"
    return r.json()


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_health():
    r = httpx.get(f"{BASE_URL}/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Anchors
# ---------------------------------------------------------------------------

def test_create_anchor():
    anchor = create_anchor(1, "smoke test anchor - create")
    assert "id" in anchor
    assert anchor["level"] == 1
    assert anchor["active"] is True


def test_list_anchors():
    r = httpx.get(f"{BASE_URL}/anchors/")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_archive_anchor():
    anchor = create_anchor(1, "smoke test anchor - archive")
    r = httpx.post(f"{BASE_URL}/anchors/{anchor['id']}/archive")
    assert r.status_code == 200
    assert r.json()["active"] is False


# ---------------------------------------------------------------------------
# Gate — decision matrix
# ---------------------------------------------------------------------------

def test_level3_gates():
    """Level 3 anchor conflict must always gate."""
    import time
    ts = int(time.time())

    phrase = f"smoke breach lattice {ts}"
    anchor = create_anchor(3, f"smoke test do not {phrase}", scope="smoke_security")
    out = evaluate(f"please {phrase}")

    # Should gate on the level-3 anchor we just created
    assert out["decision"] == "gate"
    assert anchor["id"] in out["conflicted_anchor_ids"]
    # Clean up
    httpx.post(f"{BASE_URL}/anchors/{anchor['id']}/archive")


def test_level3_state_mismatch():
    """High arousal + low dominance with level-3 conflict gets distinct reason code."""
    import time
    ts = int(time.time())

    phrase = f"smoke quorblax fenris {ts}"
    anchor = create_anchor(3, f"smoke test do not {phrase}", scope="smoke_security")
    out = evaluate(
        f"please {phrase}",
        arousal="high",
        dominance="low",
    )
    assert out["decision"] == "gate"
    assert out["reason"] == "state_mismatch_with_l3_anchor"
    httpx.post(f"{BASE_URL}/anchors/{anchor['id']}/archive")


def test_level2_gates():
    """Level 2 anchor conflict must gate with soft reason code."""
    anchor = create_anchor(2, "smoke test avoid causing smoke financial harm", scope="smoke_payments")
    out = evaluate("cause smoke financial harm to the account")
    assert out["decision"] == "proceed"
    assert out["reason"] == "low_level_conflict"
    assert "proceed" in out["next_actions"]
    httpx.post(f"{BASE_URL}/anchors/{anchor['id']}/archive")


def test_level1_advisory():
    """Level 1 anchor conflict must proceed with advisory reason."""
    anchor = create_anchor(1, "smoke test do not smoke delete smoke records permanently", scope="smoke_global")
    out = evaluate("smoke delete smoke records permanently and cannot be undone")
    assert out["decision"] == "proceed"
    assert out["reason"] == "low_level_conflict"
    assert anchor["id"] in out["conflicted_anchor_ids"]
    httpx.post(f"{BASE_URL}/anchors/{anchor['id']}/archive")


def test_no_conflict_proceeds_clean():
    """Request with no matching anchors must proceed clean."""
    out = evaluate("the quick brown fox jumps over the lazy dog xkzqwjvp")
    assert out["decision"] == "proceed"
    assert out["reason"] == "no_high_conflict"
    assert out["conflicted_anchor_ids"] == []


# ---------------------------------------------------------------------------
# Gate — response structure
# ---------------------------------------------------------------------------

def test_evaluate_returns_required_fields():
    out = evaluate("test request for field check")
    for field in ("decision", "reason", "conflicted_anchor_ids", "log_id", "trace_id"):
        assert field in out, f"missing field: {field}"


def test_gate_returns_explanations():
    """A gated response must include explanations."""
    anchor = create_anchor(3, "smoke test do not smoke manipulate smoke users", scope="smoke_integrity")
    out = evaluate("smoke manipulate smoke users")
    if out["decision"] == "gate":
        assert "explanations" in out
        assert isinstance(out["explanations"], list)
        assert len(out["explanations"]) > 0
    httpx.post(f"{BASE_URL}/anchors/{anchor['id']}/archive")


# ---------------------------------------------------------------------------
# Reframe flow
# ---------------------------------------------------------------------------

def test_reframe_after_gate():
    """A gated request can be reframed and proceed."""
    import time
    ts = int(time.time())

    phrase = f"smoke frobnicate zorbix {ts}"
    anchor = create_anchor(3, f"smoke test do not {phrase}", scope="smoke_security")

    # First evaluation — should gate
    out1 = evaluate(f"please {phrase}", arousal="high", dominance="low")
    assert out1["decision"] == "gate"
    log_id = out1["log_id"]

    # Reframe with legitimate intent and calm state
    r = httpx.post(f"{BASE_URL}/gate/reframe", json={
        "log_id": log_id,
        "new_intent": "I need help with my calendar application settings",
        "arousal": "low",
        "dominance": "high",
        })
    assert r.status_code == 200
    out2 = r.json()
    assert out2["decision"] == "proceed"
    assert out2["reframed_request"] == "I need help with my calendar application settings"

    httpx.post(f"{BASE_URL}/anchors/{anchor['id']}/archive")


# ---------------------------------------------------------------------------
# Acknowledge flow
# ---------------------------------------------------------------------------

def test_acknowledge_after_l2_gate():
    """A level-2 gate can be acknowledged and proceeds."""
    anchor = create_anchor(2, "smoke test avoid smoke financial damage", scope="smoke_payments")

    out1 = evaluate("cause smoke financial damage")
    assert out1["decision"] == "proceed"
    assert out1["reason"] == "low_level_conflict"
    log_id = out1["log_id"]

    r = httpx.post(f"{BASE_URL}/gate/acknowledge", json={
        "log_id": log_id,
        "acknowledgement": "I accept responsibility for this smoke test action",
    })
    assert r.status_code == 404

    httpx.post(f"{BASE_URL}/anchors/{anchor['id']}/archive")


def test_acknowledge_rejected_for_l3():
    """Acknowledge must be rejected if the original gate was level-3."""
    import time
    ts = int(time.time())

    phrase = f"smoke nullspire wyrm {ts}"
    anchor = create_anchor(3, f"smoke test do not {phrase}", scope="smoke_security")

    out1 = evaluate(f"please {phrase}")
    assert out1["decision"] == "gate"
    log_id = out1["log_id"]

    r = httpx.post(f"{BASE_URL}/gate/acknowledge", json={
        "log_id": log_id,
        "acknowledgement": "I want to proceed anyway",
    })
    assert r.status_code == 404

    httpx.post(f"{BASE_URL}/anchors/{anchor['id']}/archive")


# ---------------------------------------------------------------------------
# Replay and drift detection
# ---------------------------------------------------------------------------

def test_replay_same_decision():
    """Replaying a trace with no policy changes returns same_decision: True."""
    anchor = create_anchor(3, "smoke test do not smoke access smoke vaults without permission", scope="smoke_security")

    out = evaluate("smoke access smoke vaults without permission")
    assert out["decision"] == "gate"
    trace_id = out["trace_id"]

    r = httpx.get(f"{BASE_URL}/gate/replay/{trace_id}")
    assert r.status_code == 200
    replay = r.json()
    assert replay["trace_id"] == trace_id
    assert replay["same_decision"] is True
    assert replay["same_reason"] is True

    httpx.post(f"{BASE_URL}/anchors/{anchor['id']}/archive")


def test_replay_detects_drift():
    """Archiving an anchor after a gate causes drift to be detected on replay."""
    anchor = create_anchor(3, "smoke test do not smoke tamper smoke records", scope="smoke_security")

    out = evaluate("smoke tamper smoke records")
    assert out["decision"] == "gate"
    trace_id = out["trace_id"]

    # Archive the anchor — policy has now changed
    httpx.post(f"{BASE_URL}/anchors/{anchor['id']}/archive")

    r = httpx.get(f"{BASE_URL}/gate/replay/{trace_id}")
    assert r.status_code == 200
    replay = r.json()
    assert replay["trace_id"] == trace_id
    assert len(replay["anchor_drift"]) > 0


# ---------------------------------------------------------------------------
# Policy profiles
# ---------------------------------------------------------------------------

def test_create_profile():
    import time
    name = f"smoke_profile_{int(time.time())}"
    profile = create_profile(name, "smoke test profile")
    assert "id" in profile
    assert profile["name"] == name


def test_profile_scoped_evaluation():
    """Same request should proceed under one profile and gate under another."""
    import time
    ts = int(time.time())

    # Create two anchors in different scopes
    anchor_a = create_anchor(3, f"smoke test do not breach smoke wall {ts}", scope=f"smoke_a_{ts}")
    anchor_b = create_anchor(2, f"do not flubnort {ts} the zorbix", scope=f"smoke_b_{ts}")

    # Profile A — only anchor_a
    profile_a = create_profile(f"smoke_profile_a_{ts}")
    assign_anchors(profile_a["id"], [anchor_a["id"]])

    # Profile B — only anchor_b
    profile_b = create_profile(f"smoke_profile_b_{ts}")
    assign_anchors(profile_b["id"], [anchor_b["id"]])

    # Request that triggers anchor_b but not anchor_a
    req_text = f"do not flubnort {ts} the zorbix"

    out_a = evaluate(req_text, profile_id=profile_a["id"])
    out_b = evaluate(req_text, profile_id=profile_b["id"])

    assert out_a["decision"] == "proceed", f"profile_a should proceed, got: {out_a['reason']}"
    assert out_b["decision"] == "proceed", f"profile_b should proceed, got: {out_b['reason']}"
    assert out_b["reason"] == "low_level_conflict"
    # Clean up
    httpx.post(f"{BASE_URL}/anchors/{anchor_a['id']}/archive")
    httpx.post(f"{BASE_URL}/anchors/{anchor_b['id']}/archive")


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

def test_logs_endpoint():
    r = request_with_retry("GET", f"{BASE_URL}/gate/logs")
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert "total" in data


def test_logs_filter_by_decision():
    r = request_with_retry("GET", f"{BASE_URL}/gate/logs?decision=proceed")
    assert r.status_code == 200
    data = r.json()
    for item in data["items"]:
        assert item["decision"] == "proceed"


def test_logs_invalid_filter():
    r = request_with_retry("GET", f"{BASE_URL}/gate/logs?decision=invalid")
    assert r.status_code == 422

