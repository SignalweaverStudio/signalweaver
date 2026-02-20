import httpx

BASE_URL = "http://127.0.0.1:8000"


def test_health_ok():
    r = httpx.get(f"{BASE_URL}/health")
    assert r.status_code == 200


def test_create_and_list_anchor():
    payload = {"level": 1, "statement": "pytest anchor"}
    r = httpx.post(f"{BASE_URL}/anchors/", json=payload)
    assert r.status_code == 200
    created = r.json()
    assert created["statement"] == payload["statement"]
    assert "id" in created

    r2 = httpx.get(f"{BASE_URL}/anchors/")
    assert r2.status_code == 200
    items = r2.json()
    assert any(a["id"] == created["id"] for a in items)


def test_archive_anchor():
    payload = {"level": 1, "statement": "pytest anchor to archive"}
    r = httpx.post(f"{BASE_URL}/anchors/", json=payload)
    assert r.status_code == 200
    created = r.json()
    anchor_id = created["id"]

    r2 = httpx.post(f"{BASE_URL}/anchors/{anchor_id}/archive")
    assert r2.status_code == 200
    archived = r2.json()

    assert archived.get("active") in (False, 0)


def test_gate_warns_on_conflict():
    # Create anchor
    anchor = {"level": 1, "statement": "cats are allowed"}
    r = httpx.post(f"{BASE_URL}/anchors/", json=anchor)
    assert r.status_code == 200

    # Gate evaluation with conflicting statement
    payload = {
        "request_summary": "cats are not allowed",
        "arousal": "unknown",
        "dominance": "unknown",
    }

    r2 = httpx.post(f"{BASE_URL}/gate/evaluate", json=payload)
    assert r2.status_code == 200

    out = r2.json()

    # Gate returns conflicted anchor IDs (our "warning" signal)
    assert out.get("conflicted_anchor_ids"), out


