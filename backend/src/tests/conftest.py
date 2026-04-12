import os
import sys
import pytest

# Ensure imports like `from app.main import app` work when running pytest from /src
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

# Ensure imports like `from app.main import app` work when running pytest from /src
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

from app.main import app
from app.db import get_db
from app.models import Base, Tenant
from app.auth import get_current_tenant
import app.security as security
# Single in-memory SQLite DB shared across the whole test session
TEST_DATABASE_URL = "sqlite://"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

def override_get_current_tenant():
    return Tenant(
        id=1,
        name="Test Tenant",
        slug="test-tenant",
        api_key_hash="test",
        active=True,
    )


app.dependency_overrides[get_current_tenant] = override_get_current_tenant

@pytest.fixture(autouse=True)
def reset_rate_limiter():
    security._hits.clear()
    yield
    security._hits.clear()

@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=engine)
    print("TEST DB TABLES:", list(Base.metadata.tables.keys()))
    yield
    Base.metadata.drop_all(bind=engine)

@pytest.fixture(scope="module")
def db_session(setup_test_db):
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="module")
def shared_db(db_session):
    yield db_session


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c