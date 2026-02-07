from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from app.db import SessionLocal
from app.models import TruthAnchor, GateLog
from app.schemas import (
    GateEvaluateIn,
    GateEvaluateOut,
    GateLogOut,
    GateLogListOut,
    parse_id_list,
    AnchorOut,
)
from app.gate import UserState, decide

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _norm(s: str) -> str:
    return " ".join(s.strip().lower().split())


def _has_not(s: str) -> bool:
    s = _norm(s)
    return " not " in f" {s} "


def _strip_not(s: str) -> str:
    s = _norm(s)
    return " ".join(tok for tok in s.split() if tok != "not")


def naive_conflicts(request_summary: str, anchors: list[TruthAnchor]) -> list[TruthAnchor]:
    req_norm = _norm(request_summary)
    req_has_not = _has_not(req_norm)
    req_wo_not = _strip_not(req_norm)

    hits: list[TruthAnchor] = []

    for a in anchors:
        stmt_norm = _norm(a.statement)
        stmt_has_not = _has_not(stmt_norm)
        stmt_wo_not = _strip_not(stmt_norm)

        # Strong negation conflict
        if req_wo_not == stmt_wo_not and (req_has_not != stmt_has_not):
            hits.append(a)
            continue

        # Weak keyword overlap fallback
        if any(tok in req_norm for tok in stmt_norm.split()[:8]):
            hits.append(a)

    return hits


@router.post("/evaluate", response_model=GateEvaluateOut)
def evaluate(payload: GateEvaluateIn, db: Session = Depends(get_db)):
    stmt_all = select(TruthAnchor).where(TruthAnchor.active == True)  # noqa: E712
    active_anchors = list(db.scalars(stmt_all).all())

    conflicts = naive_conflicts(payload.request_summary, active_anchors)

    conflicted_ids = [a.id for a in conflicts]
    warnings = [a.statement for a in conflicts]
    warning_anchors = conflicts

    max_level = max((a.level for a in conflicts), default=0)


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
        conflicted_anchor_ids=",".join(str(i) for i in conflicted_ids),
    )

    db.add(log)
    db.commit()
    db.refresh(log)

    # Convert ORM anchors -> schema objects for response stability
    warning_anchor_out = [
        AnchorOut.model_validate(a, from_attributes=True) for a in warning_anchors
    ]

    return GateEvaluateOut(
        decision=decision.decision,
        reason=decision.reason,
        conflicted_anchor_ids=conflicted_ids,
        warnings=warnings,
        warning_anchors=warning_anchor_out,
        log_id=log.id,
    )


@router.get("/logs", response_model=GateLogListOut)
def list_gate_logs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    decision: str | None = Query(
        default=None, description="Optional filter: proceed|gate|refuse"
    ),
    since: datetime | None = Query(
        default=None, description="Optional filter: ISO timestamp (e.g. 2026-02-06T18:00:00)"
    ),
    db: Session = Depends(get_db),
):
    """
    List gate logs, newest-first, with optional filters.

    Filters:
    - decision: only return logs with this decision
    - since: only return logs created_at >= since
    """
    base_where = []

    if decision is not None:
        # Keep this strict to avoid surprises/typos
        if decision not in ("proceed", "gate", "refuse"):
            raise HTTPException(status_code=422, detail="decision must be proceed|gate|refuse")
        base_where.append(GateLog.decision == decision)

    if since is not None:
        base_where.append(GateLog.created_at >= since)

    # total count for the same filtered set
    count_stmt = select(func.count()).select_from(GateLog)
    if base_where:
        count_stmt = count_stmt.where(*base_where)
    total = db.scalar(count_stmt) or 0

    stmt = select(GateLog)
    if base_where:
        stmt = stmt.where(*base_where)

    stmt = stmt.order_by(GateLog.id.desc()).limit(limit).offset(offset)
    rows = list(db.scalars(stmt).all())

    items: list[GateLogOut] = []
    for r in rows:
        items.append(
            GateLogOut(
                id=r.id,
                created_at=r.created_at,
                request_summary=r.request_summary,
                arousal=r.arousal,
                dominance=r.dominance,
                decision=r.decision,
                reason=r.reason,
                conflicted_anchor_ids=parse_id_list(r.conflicted_anchor_ids),
                user_choice=r.user_choice,
            )
        )

    return GateLogListOut(items=items, total=total, limit=limit, offset=offset)


@router.get("/logs/{log_id}", response_model=GateLogOut)
def get_gate_log(log_id: int, db: Session = Depends(get_db)):
    row = db.get(GateLog, log_id)
    if row is None:
        raise HTTPException(status_code=404, detail="gate log not found")

    return GateLogOut(
        id=row.id,
        created_at=row.created_at,
        request_summary=row.request_summary,
        arousal=row.arousal,
        dominance=row.dominance,
        decision=row.decision,
        reason=row.reason,
        conflicted_anchor_ids=parse_id_list(row.conflicted_anchor_ids),
        user_choice=row.user_choice,
    )
