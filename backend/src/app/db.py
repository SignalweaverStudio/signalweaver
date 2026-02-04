from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Local SQLite database file in backend/ directory
DATABASE_URL = "sqlite:///./signalweaver.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # needed for SQLite + FastAPI
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
