import hashlib
import secrets

from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.dependencies import get_db
from app.models import Tenant


bearer_scheme = HTTPBearer(auto_error=False)


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def generate_api_key() -> tuple[str, str]:
    """Returns (raw_key, hashed_key). Store only the hash."""
    raw = secrets.token_urlsafe(32)
    return raw, _hash_key(raw)


def get_tenant(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    db: Session = Depends(get_db),
) -> Tenant:
    if not credentials:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    key_hash = _hash_key(credentials.credentials)
    tenant = db.scalar(
        select(Tenant)
        .where(Tenant.api_key_hash == key_hash)
        .where(Tenant.active == True)  # noqa: E712
    )
    if not tenant:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")

    return tenant