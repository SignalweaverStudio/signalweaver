from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db import SessionLocal
from app.models import TruthAnchor, GateLog
from app.schemas import GateEvaluateIn, GateEvaluateOut
from app.gate import UserState, decide

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def naive_conflicts(request_summary: str, anchors: list[TruthAnchor]) -> list[TruthAnchor]:
    """
    v0 conflict detection:
    - crude keyword overlap heuristic (better than nothing; replace later)
    """
    req = request_summary.lower()
    hits = []
    for a in anchors:
        # a very simple "does it mention the anchor language" check
        # (later: embeddings, structured intents, etc.)
        if any(tok in req for tok in a.statement.lower().split()[:8]):  # small slice to avoid nonsense
            hits.append(a)
    return hits

@router.post("/evaluate", response_model=GateEvaluateOut)
def evaluate(payload: GateEvaluateIn, db: Session = Depends(get_db)):
    # Only active L3 anchors participate in hard gating in v0
    stmt = select(TruthAnchor).where(TruthAnchor.active == True).where(TruthAnchor.level == 3)  # noqa: E712
    l3_anchors = list(db.scalars(stmt).all())

    conflicts = naive_conflicts(payload.request_summary, l3_anchors)
    conflicted_ids = [a.id for a in conflicts]
    max_level = 3 if conflicted_ids else 0

    decision = decide(
        state=UserState(arousal=payload.arousal, dominance=payload.dominance),
        conflicted_anchor_ids=conflicted_ids,
        max_level_conflict=max_level,
    )

    log = GateLog(
        request_summary=payload.request_summary,
        arousal=payload.arousal,
        dominance=payload.dominance,
        decision=decision.decision,
        reason=decision.reason,
        conflicted_anchor_ids=",".join(str(i) for i in decision.conflicted_anchor_ids),
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    return GateEvaluateOut(
        decision=decision.decision,
        reason=decision.reason,
        conflicted_anchor_ids=decision.conflicted_anchor_ids,
        log_id=log.id,
    )
