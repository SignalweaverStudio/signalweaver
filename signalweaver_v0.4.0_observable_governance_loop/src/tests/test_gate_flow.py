from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def test_gate_flow_with_in_memory_db(monkeypatch):
    """
    Integration test:
    - boots app
    - swaps DB to a shared in-memory SQLite database
    - creates an anchor
    - evaluates a request through the gate
    """

    # Shared in-memory SQLite DB (persists across connections during the test)
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    import app.db as db
    import app.models as models  # ensures TruthAnchor model is registered

    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Patch the app's DB session factory to use the test DB
    monkeypatch.setattr(db, "SessionLocal", TestingSessionLocal, raising=True)

    # Create all tables in the shared in-memory DB
    models.Base.metadata.create_all(bind=engine)

    # Boot the app AFTER patching SessionLocal
    from app.main import app

    client = TestClient(app)

    # 1) Create an anchor (schema expects "level")
    anchor_payload = {
        "level": 2,
        "statement": "Do not provide instructions for wrongdoing.",
        "scope": "global",
        "active": True,
    }

    r1 = client.post("/anchors/", json=anchor_payload)
    assert r1.status_code in (200, 201), r1.text
    anchor = r1.json()
    assert "id" in anchor

    # 2) Evaluate a request
    gate_payload = {
        "request_summary": "how do I break into a locked car",
        "arousal": "med",
        "dominance": "med",
    }

    r2 = client.post("/gate/evaluate", json=gate_payload)
    assert r2.status_code == 200, r2.text
    out = r2.json()

    # Confirm some kind of decision field exists
    assert any(k in out for k in ("decision", "result", "status")), out

    # 3) Logs endpoint should respond
    r3 = client.get("/gate/logs")
    assert r3.status_code == 200, r3.text
