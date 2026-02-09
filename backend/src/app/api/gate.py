from datetime import datetime
from typing import List, Optional

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
    GateReframeIn,
    GateReframeOut,
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

    # Keep this simple but less noisy
    filler = {"a", "an", "the", "to", "and", "or", "of", "in", "on", "for"}
    stop = filler | {"i", "you", "we", "it", "is", "are", "be", "will", "not"}

    hits: list[TruthAnchor] = []

    for a in anchors:
        stmt_norm = _norm(a.statement)
        stmt_has_not = _has_not(stmt_norm)
        stmt_wo_not = _strip_not(stmt_norm)

        # Strong negation conflict (semantic inversion)
        if req_wo_not == stmt_wo_not and (req_has_not != stmt_has_not):
            hits.append(a)
            continue

        # Keyword overlap fallback (meaningful tokens only)
        stmt_tokens = [t for t in stmt_norm.split() if t not in filler][:8]
        matched = [t for t in stmt_tokens if len(t) >= 3 and t not in stop and (t in req_norm)]

        if matched:
            hits.append(a)

    return hits


def _build_explanations(request_summary: str, conflicts: list[TruthAnchor]) -> list[str]:
    """
    Create plain-English per-anchor explanations for why each anchor was flagged.

    This is intentionally lightweight and transparent:
    - If we hit the "strong negation conflict", explain that.
    - Otherwise, explain that there was keyword overlap and show which words matched.
    """
    req_norm = _norm(request_summary)
    req_has_not = _has_not(req_norm)
    req_wo_not = _strip_not(req_norm)

    explanations: list[str] = []

    # Keep these small and obvious; this is MVP explainability, not NLP.
    filler = {"a", "an", "the", "to", "and", "or", "of", "in", "on", "for"}
    stop = filler | {"i", "you", "we", "it", "is", "are", "be", "will", "not"}

    for a in conflicts:
        stmt_norm = _norm(a.statement)
        stmt_has_not = _has_not(stmt_norm)
        stmt_wo_not = _strip_not(stmt_norm)

        header = f"Anchor L{a.level} ({a.scope}): “{a.statement}”"

        # Strong negation conflict (semantic inversion)
        if req_wo_not == stmt_wo_not and (req_has_not != stmt_has_not):
            explanations.append(
                f"{header} — triggered because the request and anchor match after removing 'not', "
                f"but one is negated and the other isn’t (semantic inversion)."
            )
            continue

        # Keyword overlap explanation (same general idea as naive_conflicts, but cleaner tokens)
        stmt_tokens = [t for t in stmt_norm.split() if t not in filler][:8]
        matched = [t for t in stmt_tokens if len(t) >= 3 and t not in stop and (t in req_norm)]

        if matched:
            explanations.append(
                f"{header} — triggered because the request contains keyword overlap: {', '.join(matched)}."
            )
        else:
            explanations.append(
                f"{header} — triggered by the current matching rules (no specific keyword extracted)."
            )

    return explanations


@router.post("/evaluate", response_model=GateEvaluateOut, response_model_exclude_none=True)
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

    # Only include the "wow" explanation when gated/refused
    interpretation: Optional[str] = None
    suggestion: Optional[str] = None
    explanations: Optional[List[str]] = None
    next_actions: Optional[List[str]] = None

    if decision.decision != "proceed":
        interpretation = getattr(decision, "interpretation", None)
        suggestion = getattr(decision, "suggestion", None)
        next_actions = getattr(decision, "next_actions", None)
        explanations = _build_explanations(payload.request_summary, conflicts)

    return GateEvaluateOut(
        decision=decision.decision,
        reason=decision.reason,
        interpretation=interpretation,
        suggestion=suggestion,
        explanations=explanations,
        next_actions=next_actions,
        conflicted_anchor_ids=conflicted_ids,
        warnings=warnings,
        warning_anchors=warning_anchor_out,
        log_id=log.id,
    )


@router.post("/reframe", response_model=GateReframeOut)
def reframe(payload: GateReframeIn, db: Session = Depends(get_db)):
    parent = db.get(GateLog, payload.log_id)
    if parent is None:
        raise HTTPException(status_code=404, detail="gate log not found")

    # Simple MVP "reframe": treat new_intent as the new request summary
    reframed = payload.new_intent.strip()

    # Reuse original state unless overridden
    arousal = payload.arousal or parent.arousal
    dominance = payload.dominance or parent.dominance

    # Re-run conflict detection on the reframed text
    stmt_all = select(TruthAnchor).where(TruthAnchor.active == True)  # noqa: E712
    active_anchors = list(db.scalars(stmt_all).all())

    conflicts = naive_conflicts(reframed, active_anchors)
    conflicted_ids = [a.id for a in conflicts]
    warnings = [a.statement for a in conflicts]

    max_level = max((a.level for a in conflicts), default=0)

    decision = decide(
        state=UserState(arousal=arousal, dominance=dominance),
        conflicted_anchor_ids=conflicted_ids,
        max_level_conflict=max_level,
    )

    # Write a new log entry for the reframed attempt
    log = GateLog(
        request_summary=reframed,
        arousal=arousal,
        dominance=dominance,
        interpretation=getattr(decision, "interpretation", ""),
        suggestion=getattr(decision, "suggestion", ""),
        decision=decision.decision,
        reason=decision.reason,
        conflicted_anchor_ids=",".join(str(i) for i in conflicted_ids),
        user_choice="reframe_from:" + str(parent.id),
    )

    db.add(log)
    db.commit()
    db.refresh(log)

    warning_anchor_out = [
        AnchorOut.model_validate(a, from_attributes=True) for a in conflicts
    ]

    # Only include explanations when not proceed (keeps responses tidy)
    explanations: Optional[List[str]] = None
    if decision.decision != "proceed":
        explanations = _build_explanations(reframed, conflicts)

    return GateReframeOut(
        parent_log_id=parent.id,
        reframed_request_summary=reframed,
        decision=decision.decision,
        reason=decision.reason,
        interpretation=getattr(decision, "interpretation", ""),
        suggestion=getattr(decision, "suggestion", ""),
        explanations=explanations,
        next_actions=getattr(decision, "next_actions", []),
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
        default=None,
        description="Optional filter: ISO timestamp (e.g. 2026-02-06T18:00:00)",
    ),
    db: Session = Depends(get_db),
):
    """
    List gate logs, newest-first, with optional filters.
    """

    base_where = []

    if decision is not None:
        if decision not in ("proceed", "gate", "refuse"):
            raise HTTPException(
                status_code=422,
                detail="decision must be proceed|gate|refuse",
            )
        base_where.append(GateLog.decision == decision)

    if since is not None:
        base_where.append(GateLog.created_at >= since)

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

    return GateLogListOut(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


