from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db import get_db
from app.models import TruthAnchor
from app.schemas import TruthAnchorCreate, TruthAnchorOut

router = APIRouter()


@router.post("/", response_model=TruthAnchorOut)
def create_anchor(payload: TruthAnchorCreate, db: Session = Depends(get_db)):
    anchor = TruthAnchor(level=payload.level, statement=payload.statement, scope=payload.scope)
    db.add(anchor)
    db.commit()
    db.refresh(anchor)
    return anchor

@router.get("/", response_model=list[TruthAnchorOut])
def list_anchors(active_only: bool = True, db: Session = Depends(get_db)):
    stmt = select(TruthAnchor)
    if active_only:
        stmt = stmt.where(TruthAnchor.active == True)  # noqa: E712
    stmt = stmt.order_by(TruthAnchor.created_at.desc())
    return list(db.scalars(stmt).all())

@router.post("/{anchor_id}/archive", response_model=TruthAnchorOut)
def archive_anchor(anchor_id: int, db: Session = Depends(get_db)):
    anchor = db.get(TruthAnchor, anchor_id)
    if not anchor:
        raise HTTPException(status_code=404, detail="Anchor not found")
    anchor.active = False
    db.commit()
    db.refresh(anchor)
    return anchor



@router.get("/{anchor_id}", response_model=TruthAnchorOut)
def get_anchor(anchor_id: int, db: Session = Depends(get_db)):
    anchor = db.get(TruthAnchor, anchor_id)

    if not anchor:
        raise HTTPException(status_code=404, detail="Anchor not found")

    return anchor

