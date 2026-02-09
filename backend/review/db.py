from pathlib import Path
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Always resolve DB to an absolute path so cwd doesn't change where data is stored.
BASE_DIR = Path(__file__).resolve().parents[2]  # .../backend/src
DEFAULT_DB_PATH = BASE_DIR / "signalweaver.db"

DB_PATH = Path(os.getenv("SIGNALWEAVER_DB", str(DEFAULT_DB_PATH))).resolve()
DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # needed for SQLite + FastAPI
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

