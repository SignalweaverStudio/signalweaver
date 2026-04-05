import hashlib
import secrets

from fastapi import Depends
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.dependencies import get_db
from app.models import Tenant


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def generate_api_key() -> tuple[str, str]:
    """Returns (raw_key, hashed_key). Store only the hash."""
    raw = secrets.token_urlsafe(32)
    return raw, _hash_key(raw)


def get_tenant(
    db: Session = Depends(get_db),
) -> Tenant | None:
    return db.scalar(select(Tenant))