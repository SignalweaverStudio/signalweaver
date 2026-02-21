from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_evaluate_returns_trace_id_and_gates_refund():
    payload = {
        "request_summary": "Refund £10000 to customer",
        "arousal": "med",
        "dominance": "med",
    }
    r = client.post("/gate/evaluate", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["decision"] == "gate"
    assert data["reason"] == "l3_anchor_conflict"
    assert "trace_id" in data
    assert isinstance(data["trace_id"], int)


def test_replay_same_decision_for_trace():
    payload = {
        "request_summary": "Refund £10000 to customer",
        "arousal": "med",
        "dominance": "med",
    }
    r1 = client.post("/gate/evaluate", json=payload)
    assert r1.status_code == 200, r1.text
    trace_id = r1.json()["trace_id"]

    r2 = client.get(f"/gate/replay/{trace_id}")
    assert r2.status_code == 200, r2.text
    data = r2.json()

    assert data["trace_id"] == trace_id
    assert data["same_decision"] is True
    assert data["same_reason"] is True