from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from app.auth import get_tenant
from app.db import get_db
from app.models import DecisionTrace, DecisionTraceAnchor, TruthAnchor
from app.schemas import ShadowSummaryOut
from fastapi import Request




router = APIRouter(
    dependencies=[Depends(get_tenant)]
)


@router.get("/shadow-summary", response_model=ShadowSummaryOut)
def shadow_summary(db: Session = Depends(get_db)):

    # Total decisions evaluated
    total_evaluated = db.scalar(
        select(func.count()).select_from(DecisionTrace)
    ) or 0

    # Total where an L3 anchor was matched
    total_l3_conflicts = db.scalar(
        select(func.count(DecisionTraceAnchor.id.distinct()))
        .where(
            DecisionTraceAnchor.matched == True,  # noqa: E712
            DecisionTraceAnchor.level_snapshot == 3,
        )
    ) or 0

    # Total where an L2 anchor was matched
    total_l2_conflicts = db.scalar(
        select(func.count(DecisionTraceAnchor.id.distinct()))
        .where(
            DecisionTraceAnchor.matched == True,  # noqa: E712
            DecisionTraceAnchor.level_snapshot == 2,
        )
    ) or 0

    # Total shadow hypothetical blocks
    total_would_block = db.scalar(
        select(func.count())
        .select_from(DecisionTrace)
        .where(DecisionTrace.would_block == True)  # noqa: E712
    ) or 0

    # Total overrides (override_reason was provided)
    total_overrides = db.scalar(
        select(func.count())
        .select_from(DecisionTrace)
        .where(DecisionTrace.override_reason != "")
    ) or 0

    # Top triggered anchors by frequency
    rows = db.execute(
        select(
            DecisionTraceAnchor.anchor_id,
            TruthAnchor.statement,
            TruthAnchor.level,
            TruthAnchor.scope,
            func.count(DecisionTraceAnchor.id).label("trigger_count"),
        )
        .join(TruthAnchor, TruthAnchor.id == DecisionTraceAnchor.anchor_id)
        .where(DecisionTraceAnchor.matched == True)  # noqa: E712
        .group_by(DecisionTraceAnchor.anchor_id)
        .order_by(func.count(DecisionTraceAnchor.id).desc())
        .limit(10)
    ).all()

    top_triggered_anchors = [
        {
            "anchor_id": r.anchor_id,
            "statement": r.statement,
            "level": r.level,
            "scope": r.scope,
            "trigger_count": r.trigger_count,
        }
        for r in rows
    ]

    return ShadowSummaryOut(
        total_evaluated=total_evaluated,
        total_l3_conflicts=total_l3_conflicts,
        total_l2_conflicts=total_l2_conflicts,
        total_would_block=total_would_block,
        total_overrides=total_overrides,
        top_triggered_anchors=top_triggered_anchors,
    )