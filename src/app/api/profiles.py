from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from fastapi import Request
from sqlalchemy import delete
from app.security import verify_api_key, rate_limit
from app.db import get_db
from app.models import PolicyProfile, PolicyProfileAnchor, TruthAnchor
from app.schemas import (
    PolicyProfileCreate,
    PolicyProfileUpdate,
    PolicyProfileOut,
    PolicyProfileListOut,
    ProfileAnchorsIn,
    ProfileAnchorsOut,
)

def _rl(request: Request):
    rate_limit(request, limit=60, window_s=60)

router = APIRouter(
    dependencies=[Depends(verify_api_key), Depends(_rl)]
)


@router.post("", response_model=PolicyProfileOut, status_code=201)
def create_profile(payload: PolicyProfileCreate, db: Session = Depends(get_db)):
    existing = db.scalar(
        select(PolicyProfile).where(PolicyProfile.name == payload.name)
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Profile with name '{payload.name}' already exists",
        )

    if payload.is_default:
        for prof in db.scalars(
            select(PolicyProfile).where(PolicyProfile.is_default == True)  # noqa: E712
        ):
            prof.is_default = False

    profile = PolicyProfile(
        name=payload.name,
        description=payload.description,
        is_default=payload.is_default or False,
        enforcement_mode=payload.enforcement_mode.value,
    )

    db.add(profile)
    db.commit()
    db.refresh(profile)

    return PolicyProfileOut.model_validate(profile, from_attributes=True)


@router.get("", response_model=PolicyProfileListOut)
def list_profiles(db: Session = Depends(get_db)):
    profiles = list(db.scalars(select(PolicyProfile)).all())
    return PolicyProfileListOut(
        items=[
            PolicyProfileOut.model_validate(p, from_attributes=True) for p in profiles
        ],
        total=len(profiles),
    )


@router.get("/{profile_id}", response_model=PolicyProfileOut)
def get_profile(profile_id: int, db: Session = Depends(get_db)):
    profile = db.get(PolicyProfile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return PolicyProfileOut.model_validate(profile, from_attributes=True)


@router.patch("/{profile_id}", response_model=PolicyProfileOut)
def update_profile(
    profile_id: int,
    payload: PolicyProfileUpdate,
    db: Session = Depends(get_db),
):
    profile = db.get(PolicyProfile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    if payload.name is not None and payload.name != profile.name:
        existing = db.scalar(
            select(PolicyProfile).where(PolicyProfile.name == payload.name)
        )
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Profile with name '{payload.name}' already exists",
            )
        profile.name = payload.name

    if payload.description is not None:
        profile.description = payload.description

    if payload.enforcement_mode is not None:
        profile.enforcement_mode = payload.enforcement_mode.value

    if payload.is_default is not None and payload.is_default:
        for prof in db.scalars(
            select(PolicyProfile).where(PolicyProfile.is_default == True)  # noqa: E712
        ):
            if prof.id != profile_id:
                prof.is_default = False
        profile.is_default = True

    db.commit()
    db.refresh(profile)

    return PolicyProfileOut.model_validate(profile, from_attributes=True)


@router.delete("/{profile_id}", status_code=204)
def delete_profile(profile_id: int, db: Session = Depends(get_db)):
    profile = db.get(PolicyProfile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    if profile.is_default:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete default profile. Set another profile as default first.",
        )

    db.delete(profile)
    db.commit()


@router.get("/{profile_id}/anchors", response_model=ProfileAnchorsOut)
def get_profile_anchors(profile_id: int, db: Session = Depends(get_db)):
    profile = db.get(PolicyProfile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    anchor_ids = [a.id for a in profile.anchors]
    return ProfileAnchorsOut(profile_id=profile_id, anchor_ids=anchor_ids)


@router.put("/{profile_id}/anchors", response_model=ProfileAnchorsOut)
def set_profile_anchors(
    profile_id: int,
    payload: ProfileAnchorsIn,
    db: Session = Depends(get_db),
):
    profile = db.get(PolicyProfile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    if payload.anchor_ids:
        existing_ids = set(
            db.scalars(
                select(TruthAnchor.id).where(TruthAnchor.id.in_(payload.anchor_ids))
            ).all()
        )
        missing = set(payload.anchor_ids) - existing_ids
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Anchor IDs not found: {sorted(missing)}",
            )

    db.execute(
        delete(PolicyProfileAnchor).where(
            PolicyProfileAnchor.profile_id == profile_id
        )
    )

    for anchor_id in payload.anchor_ids:
        db.add(PolicyProfileAnchor(profile_id=profile_id, anchor_id=anchor_id))

    db.commit()
    db.refresh(profile)
    anchor_ids = [a.id for a in profile.anchors]
    return ProfileAnchorsOut(profile_id=profile_id, anchor_ids=anchor_ids)