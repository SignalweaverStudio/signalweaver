import uuid
import pytest
import httpx

BASE_URL = "http://127.0.0.1:8000"


@pytest.fixture(scope="session")
def auth_headers():
    r = httpx.post(
        f"{BASE_URL}/tenants/",
        json={"name": f"pytest-{uuid.uuid4().hex[:8]}"},
    )
    assert r.status_code == 200, f"Could not create test tenant: {r.text}"
    api_key = r.json()["api_key"]
    return {"Authorization": f"Bearer {api_key}"}
