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
    """Create a new policy profile."""
    # Check name uniqueness
    existing = db.scalar(
        select(PolicyProfile).where(PolicyProfile.name == payload.name)
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Profile with name '{payload.name}' already exists",
        )

    # If setting as default, unset previous default (transactionally)
    if payload.is_default:
        for prof in db.scalars(
            select(PolicyProfile).where(PolicyProfile.is_default == True)  # noqa: E712
        ):
            prof.is_default = False

    profile = PolicyProfile(
        name=payload.name,
        description=payload.description,
        is_default=payload.is_default or False,
        
    )

    db.add(profile)
    db.commit()
    db.refresh(profile)

    return PolicyProfileOut.model_validate(profile, from_attributes=True)


@router.get("", response_model=PolicyProfileListOut)
def list_profiles(db: Session = Depends(get_db)):
    """List all policy profiles."""
    profiles = list(db.scalars(select(PolicyProfile)).all())
    return PolicyProfileListOut(
        items=[
            PolicyProfileOut.model_validate(p, from_attributes=True) for p in profiles
        ],
        total=len(profiles),
    )


@router.get("/{profile_id}", response_model=PolicyProfileOut)
def get_profile(profile_id: int, db: Session = Depends(get_db)):
    """Get a single policy profile by ID."""
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
    """Update a policy profile."""
    profile = db.get(PolicyProfile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    # Check name uniqueness if changing name
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

    

    # If setting as default, unset previous default (transactionally)
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
    """
    Delete a policy profile.
    Rule: Cannot delete the default profile. Set another profile as default first.
    """
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
    """Get all anchors assigned to a profile."""
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
    """
    Replace entire anchor set for a profile (deterministic, transactional).
    """
    profile = db.get(PolicyProfile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    # Validate all anchor IDs exist
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

    # Clear existing associations
    db.execute(
    delete(PolicyProfileAnchor).where(
        PolicyProfileAnchor.profile_id == profile_id
    )
)

    # Add new associations
    for anchor_id in payload.anchor_ids:
        db.add(PolicyProfileAnchor(profile_id=profile_id, anchor_id=anchor_id))

    db.commit()

    # Return updated list
    db.refresh(profile)
    anchor_ids = [a.id for a in profile.anchors]
    return ProfileAnchorsOut(profile_id=profile_id, anchor_ids=anchor_ids)