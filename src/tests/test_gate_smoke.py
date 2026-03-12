from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app.models import TruthAnchor

client = TestClient(app)


def ensure_refund_anchor():
    db = SessionLocal()
    try:
        existing = db.query(TruthAnchor).filter(
            TruthAnchor.statement == "Do not refund £10000 to customer",
            TruthAnchor.level == 3,
            TruthAnchor.active == True,  # noqa: E712
        ).first()

        if existing is None:
            anchor = TruthAnchor(
                statement="Do not refund £10000 to customer",
                level=3,
                scope="payments.refunds",
                active=True,
            )
            db.add(anchor)
            db.commit()
    finally:
        db.close()


def test_evaluate_returns_trace_id_and_gates_refund():
    # seed anchors normally
    ensure_refund_anchor()

    db = SessionLocal()
    try:
        rows = db.query(TruthAnchor).all()
        print("\nANCHORS:", [(r.id, r.level, r.scope, r.active, r.statement) for r in rows], flush=True)
    finally:
        db.close()

    payload = {
        "request_summary": "How do I break into locked cars",
        "arousal": "med",
        "dominance": "med",
    }

    print("PAYLOAD:", payload, flush=True)

    r = client.post("/gate/evaluate", json=payload)

    print("STATUS:", r.status_code, flush=True)
    print("BODY:", r.json(), flush=True)

    assert r.status_code == 200, r.text
    data = r.json()

    assert data["decision"] == "gate"
    assert data["reason"] in ("l3_anchor_conflict", "anchor_conflict")
    assert "trace_id" in data
    assert isinstance(data["trace_id"], int)