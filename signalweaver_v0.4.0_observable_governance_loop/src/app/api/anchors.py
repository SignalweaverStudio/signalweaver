from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db import get_db
from app.auth import get_tenant
from app.models import TruthAnchor, Tenant
from app.schemas import TruthAnchorCreate, TruthAnchorOut

router = APIRouter()


@router.post("/", response_model=TruthAnchorOut)
def create_anchor(payload: TruthAnchorCreate, db: Session = Depends(get_db), tenant: Tenant = Depends(get_tenant)):
    anchor = TruthAnchor(level=payload.level, statement=payload.statement, scope=payload.scope, tenant_id=tenant.id)
    db.add(anchor)
    db.commit()
    db.refresh(anchor)
    return anchor


@router.get("/", response_model=list[TruthAnchorOut])
def list_anchors(active_only: bool = True, db: Session = Depends(get_db), tenant: Tenant = Depends(get_tenant)):
    stmt = select(TruthAnchor).where(
        (TruthAnchor.tenant_id == tenant.id) | (TruthAnchor.tenant_id == None)  # noqa: E711
    )
    if active_only:
        stmt = stmt.where(TruthAnchor.active == True)  # noqa: E712
    stmt = stmt.order_by(TruthAnchor.created_at.desc())
    return list(db.scalars(stmt).all())


@router.get("/{anchor_id}", response_model=TruthAnchorOut)
def get_anchor(anchor_id: int, db: Session = Depends(get_db), tenant: Tenant = Depends(get_tenant)):
    anchor = db.get(TruthAnchor, anchor_id)
    if not anchor:
        raise HTTPException(status_code=404, detail="Anchor not found")
    return anchor


@router.post("/{anchor_id}/archive", response_model=TruthAnchorOut)
def archive_anchor(anchor_id: int, db: Session = Depends(get_db), tenant: Tenant = Depends(get_tenant)):
    anchor = db.get(TruthAnchor, anchor_id)
    if not anchor:
        raise HTTPException(status_code=404, detail="Anchor not found")
    anchor.active = False
    db.commit()
    db.refresh(anchor)
    return anchor
