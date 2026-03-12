import secrets
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from pydantic import BaseModel

from app.dependencies import get_db
from app.models import Tenant
from app.auth import generate_api_key


router = APIRouter()


class TenantCreateIn(BaseModel):
    name: str


class TenantOut(BaseModel):
    id: int
    name: str
    active: bool


class TenantCreatedOut(BaseModel):
    id: int
    name: str
    api_key: str  # only returned once at creation — store it


@router.post("/", response_model=TenantCreatedOut)
def create_tenant(payload: TenantCreateIn, db: Session = Depends(get_db)):
    existing = db.scalar(select(Tenant).where(Tenant.name == payload.name))
    if existing:
        raise HTTPException(status_code=409, detail="Tenant name already exists")

    raw_key, hashed = generate_api_key()
    tenant = Tenant(name=payload.name, api_key_hash=hashed)
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    return TenantCreatedOut(id=tenant.id, name=tenant.name, api_key=raw_key)


@router.get("/", response_model=list[TenantOut])
def list_tenants(db: Session = Depends(get_db)):
    rows = db.execute(select(Tenant).order_by(Tenant.id)).scalars().all()
    return [TenantOut(id=r.id, name=r.name, active=r.active) for r in rows]