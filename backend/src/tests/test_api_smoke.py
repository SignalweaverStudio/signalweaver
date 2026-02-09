from fastapi.testclient import TestClient
from app.main import app


def test_ethos_endpoint_works():
    client = TestClient(app)
    r = client.get("/ethos")
    assert r.status_code == 200
    assert "SignalWeaver Ethos" in r.text


def test_docs_endpoint_works():
    client = TestClient(app)
    r = client.get("/docs")
    assert r.status_code == 200
