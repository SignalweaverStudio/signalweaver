import os
import sys
import tempfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# --- Redirect DB to a temp file BEFORE any app imports ---
# main.py calls Base.metadata.create_all() at import time; this ensures
# it writes to /tmp, never to the real signalweaver.db or a read-only path.
_tmp_db = tempfile.mktemp(suffix="_test.db")
os.environ["SIGNALWEAVER_DB"] = _tmp_db

# Ensure imports like `from app.main import app` work when running pytest from /src
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

# Now safe to import — db.py picks up SIGNALWEAVER_DB from env
from app.main import app  # noqa: E402
from app.db import get_db  # noqa: E402
from app.models import Base, TruthAnchor  # noqa: E402

# --- In-memory test DB for actual test isolation ---
# StaticPool forces all connections to share one underlying connection,
# which is required for SQLite :memory: databases to persist across requests.
TEST_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_test_db():
    """
    Runs before every test:
    - Creates all tables in the in-memory DB
    - Seeds a level-3 payments.refunds anchor (required for gate smoke tests)
    Drops all tables after each test so each test starts clean.
    """
    Base.metadata.create_all(bind=test_engine)

    db = TestingSessionLocal()
    anchor = TruthAnchor(
        level=3,
        statement="Do not approve refunds above £10000 without manual review",
        scope="payments.refunds",
    )
    db.add(anchor)
    db.commit()
    db.close()

    yield

    Base.metadata.drop_all(bind=test_engine)
