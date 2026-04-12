import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Base, TruthAnchor
from test_refuse import engine, TestingSessionLocal


@pytest.fixture(scope="module")
def client():
    Base.metadata.create_all(bind=engine)
    yield TestClient(app)
    Base.metadata.drop_all(bind=engine)


def ensure_refund_anchor():
    db = TestingSessionLocal()
    try:
        existing = (
            db.query(TruthAnchor)
            .filter(TruthAnchor.statement == "Do not refund £10000 to customer")
            .first()
        )
        if not existing:
            db.add(
                TruthAnchor(
                    level=3,
                    statement="Do not refund £10000 to customer",
                    scope="payments.refunds",
                    active=True,
                )
            )
            db.commit()
    finally:
        db.close()


def test_evaluate_returns_trace_id_and_gates_refund(client):
    ensure_refund_anchor()

    payload = {
        "request_summary": "Refund £10000 to customer",
        "arousal": "med",
        "dominance": "med",
    }

    r = client.post(
        "/gate/evaluate",
        json=payload,
        headers={"X-API-Key": "test"},
    )

    assert r.status_code == 200, r.text

    body = r.json()

    assert body["decision"] in ("gate", "refuse")
    assert body["trace_id"] is not None