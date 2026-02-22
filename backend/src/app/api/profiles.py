from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db import get_db
from app.models import PolicyProfile, PolicyProfileAnchor, TruthAnchor
from app.schemas import (
    PolicyProfileCreate,
    PolicyProfileOut,
    PolicyProfileListOut,
    ProfileAnchorsIn,
    ProfileAnchorsOut,
)

router = APIRouter()


@router.post("/", response_model=PolicyProfileOut)
def create_profile(payload: PolicyProfileCreate, db: Session = Depends(get_db)):
    profile = PolicyProfile(
        name=payload.name,
        description=payload.description or "",
        active=True,
        is_default=payload.is_default or False,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@router.get("/", response_model=PolicyProfileListOut)
def list_profiles(db: Session = Depends(get_db)):
    rows = list(db.scalars(select(PolicyProfile).order_by(PolicyProfile.id)).all())
    return PolicyProfileListOut(items=rows, total=len(rows))


@router.get("/{profile_id}", response_model=PolicyProfileOut)
def get_profile(profile_id: int, db: Session = Depends(get_db)):
    profile = db.get(PolicyProfile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.post("/{profile_id}/anchors", response_model=ProfileAnchorsOut)
def assign_anchors(profile_id: int, payload: ProfileAnchorsIn, db: Session = Depends(get_db)):
    profile = db.get(PolicyProfile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    # Verify all anchor IDs exist
    for anchor_id in payload.anchor_ids:
        if not db.get(TruthAnchor, anchor_id):
            raise HTTPException(status_code=404, detail=f"Anchor {anchor_id} not found")

    # Clear existing assignments and replace
    db.query(PolicyProfileAnchor).filter(
        PolicyProfileAnchor.profile_id == profile_id
    ).delete()

    for i, anchor_id in enumerate(payload.anchor_ids):
        db.add(PolicyProfileAnchor(
            profile_id=profile_id,
            anchor_id=anchor_id,
            priority=i,
            enabled=True,
        ))

    db.commit()
    return ProfileAnchorsOut(profile_id=profile_id, anchor_ids=payload.anchor_ids)


@router.get("/{profile_id}/anchors", response_model=ProfileAnchorsOut)
def get_profile_anchors(profile_id: int, db: Session = Depends(get_db)):
    profile = db.get(PolicyProfile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    rows = list(db.scalars(
        select(PolicyProfileAnchor)
        .where(PolicyProfileAnchor.profile_id == profile_id)
        .where(PolicyProfileAnchor.enabled == True)  # noqa: E712
        .order_by(PolicyProfileAnchor.priority)
    ).all())

    return ProfileAnchorsOut(
        profile_id=profile_id,
        anchor_ids=[r.anchor_id for r in rows],
    )