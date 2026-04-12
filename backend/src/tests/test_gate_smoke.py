import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

import app.db as db
import app.models as models

# 1. Create a fresh engine with StaticPool for in-memory persistence across connections
engine = create_engine(
    "sqlite://", 
    connect_args={"check_same_thread": False}, 
    poolclass=StaticPool
)

# 3. Create the SessionLocal factory bound to our fresh engine
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def test_evaluate_returns_trace_id_and_gates_refund(monkeypatch):
    # 4. Patch SessionLocal in the db module before importing the app
    monkeypatch.setattr(db, "SessionLocal", SessionLocal, raising=True)

    # 5. Build the schema fresh in memory
    models.Base.metadata.create_all(bind=engine)

    # 6. Import app only AFTER patching
    from app.main import app
    from app.auth import generate_api_key
    from app.db import get_db

    client = TestClient(app)

    # 7. Override get_db locally for this test
    def override_get_db():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db

    session = SessionLocal()
    try:
        # 8. Create the authenticated tenant in this fresh DB
        raw_key, hashed = generate_api_key()
        tenant = models.Tenant(
            name=f"gate-smoke-{raw_key[:8]}",
            api_key_hash=hashed,
            active=True,
        )
        session.add(tenant)
        
        # Seed TruthAnchor
        anchor = models.TruthAnchor(
            statement="Do not refund £10000 to customer",
            level=3,
            scope="payments.refunds",
            active=True,
        )
        session.add(anchor)
        session.commit()
        
        # 9. Use auth headers on requests
        auth_headers = {"Authorization": f"Bearer {raw_key}"}

        payload = {
    "request_summary": "Refund £10000 to customer",
    "arousal": "med",
    "dominance": "med",
}

        r = client.post(
    "/gate/evaluate",
    json=payload,
    headers={"Authorization": "Bearer test"},
)

        assert r.status_code == 200, r.text
        data = r.json()

        assert data["decision"] == "gate"
        assert data["reason"] in ("l3_anchor_conflict", "anchor_conflict")
        assert "trace_id" in data
        assert isinstance(data["trace_id"], int)

    finally:
        # Restore the previous override and cleanup
        app.dependency_overrides[get_db] = previous_override
        session.close()
        models.Base.metadata.drop_all(bind=engine)