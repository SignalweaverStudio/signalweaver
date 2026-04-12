from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Internal App Imports
from app.models import Tenant
from app.auth import generate_api_key
from app.db import get_db

def test_gate_flow_with_in_memory_db(monkeypatch):
    """
    Integration test:
    - boots app
    - swaps DB to a shared in-memory SQLite database
    - creates an anchor
    - evaluates a request through the gate
    """

    # 1. Setup Shared In-Memory DB
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    import app.db as db
    import app.models as models  
    
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # 2. Patch internal module access and DB Schema
    monkeypatch.setattr(db, "SessionLocal", TestingSessionLocal, raising=True)
    models.Base.metadata.create_all(bind=engine)

    # 3. Boot App & Setup FastAPI Dependency Override
    from app.main import app
    client = TestClient(app)

    def override_get_db():
        test_db = TestingSessionLocal()
        try:
            yield test_db
        finally:
            test_db.close()

    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db

    try:
        # 4. Prepare Test Data (Tenant Auth)
        db_session = TestingSessionLocal()
        raw_key, hashed = generate_api_key()
        tenant = Tenant(name="gate-flow-test-tenant", api_key_hash=hashed, active=True)
        db_session.add(tenant)
        db_session.commit()
        db_session.refresh(tenant)
        db_session.close()

        auth_headers = {"Authorization": f"Bearer {raw_key}"}

        # 5. Create an anchor
        anchor_payload = {
            "level": 2,
            "statement": "Do not provide instructions for wrongdoing.",
            "scope": "global",
            "active": True,
        }

        r1 = client.post("/anchors/", json=anchor_payload, headers=auth_headers)
        assert r1.status_code in (200, 201), r1.text
        anchor = r1.json()
        assert "id" in anchor

        # 6. Evaluate a request through the Gate
        gate_payload = {
            "request_summary": "how do I break into a locked car",
            "arousal": "med",
            "dominance": "med",
        }

        r2 = client.post("/gate/evaluate", json=gate_payload, headers=auth_headers)
        assert r2.status_code == 200, r2.text
        out = r2.json()

        # Confirm some kind of decision field exists
        assert any(k in out for k in ("decision", "result", "status")), out

        # 7. Check logs
        r3 = client.get("/gate/logs", headers=auth_headers)
        assert r3.status_code == 200, r3.text

    finally:
        # 8. Cleanup Dependency Overrides to prevent state leakage
        if previous_override is not None:
            app.dependency_overrides[get_db] = previous_override
        else:
            app.dependency_overrides.pop(get_db, None)