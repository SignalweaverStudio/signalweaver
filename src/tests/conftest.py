import os
import sys
import pytest

# Ensure imports like `from app.main import app` work when running pytest from /src
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.main import app as fastapi_app
from app.db import get_db
from app.auth import get_tenant
from app import models as app_models
from app.models import Base, Tenant

# Single in-memory SQLite DB shared across each test
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


fastapi_app.dependency_overrides[get_db] = override_get_db


def override_get_tenant():
    return Tenant(
        id=1,
        name="Test Tenant",
        api_key_hash="test",
        active=True,
    )


fastapi_app.dependency_overrides[get_tenant] = override_get_tenant


@pytest.fixture()
def setup_test_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db_session(setup_test_db):
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def client(setup_test_db):
    with TestClient(fastapi_app) as c:
        yield c