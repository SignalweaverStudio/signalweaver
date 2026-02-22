from datetime import datetime
from typing import List, Optional
import re
import json
import os
from app.embedding_matcher import find_conflicts_embedding
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from app.db import get_db

from app.models import (
    TruthAnchor,
    GateLog,
    DecisionTrace,
    DecisionTraceAnchor,
    PolicyProfile,
    PolicyProfileAnchor,
)
from app.schemas import (
    GateEvaluateIn,
    GateEvaluateOut,
    GateLogOut,
    GateLogListOut,
    parse_id_list,
    AnchorOut,
    GateReframeIn,
    GateReframeOut,
    ReplayOut,
    GateAcknowledgeIn,
    GateAcknowledgeOut,
)
from app.gate import UserState, decide


router = APIRouter()


def _rl(request: Request):
    # rate_limit() must raise HTTPException on breach; if it only returns a value
    # this dependency silently does nothing. Verified here by calling and ignoring return —
    # ensure your rate_limit() implementation raises HTTPException(429) internally.
    rate_limit(request, limit=60, window_s=60)


def _ethos_refs_for(decision: str, max_level: int | None = None) -> list[str]:
    refs: list[str] = []

    if decision == "proceed":
        refs += ["Minimal necessary intervention"]
    elif decision == "gate":
        refs += ["Explainability over opacity", "Reversibility"]
    elif decision == "refuse":
        refs += ["Refusal is a valid act", "Agency first", "Anti-coercion / anti-gaslight"]
    else:
        refs += ["Explainability over opacity"]

    if max_level is not None and max_level >= 3:
        refs += ["Slow is a feature"]

    # de-dupe while preserving order
    seen = set()
    out: list[str] = []
    for r in refs:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def _norm(s: str) -> str:
    return " ".join(s.strip().lower().split())


def _has_not(s: str) -> bool:
    s = _norm(s)
    return " not " in f" {s} "


def _strip_not(s: str) -> str:
    s = _norm(s)
    return " ".join(tok for tok in s.split() if tok != "not")


def _meaningful_tokens(s: str) -> list[str]:
    filler = {"a", "an", "the", "to", "and", "or", "of", "in", "on", "for"}
    stop = filler | {"i", "you", "we", "it", "is", "are", "be", "will", "not", "do"}

    def _stem(t: str) -> str:
        if t.endswith("ing") and len(t) > 5:
            t = t[:-3]
        elif t.endswith("ed") and len(t) > 4:
            t = t[:-2]
        elif t.endswith("s") and len(t) > 4:
            t = t[:-1]
        return t

    raw_tokens = re.findall(r"[a-z0-9]+", _norm(s))

    toks: list[str] = []
    for raw in raw_tokens:
        t = _stem(raw)
        if len(t) < 3:
            continue
        if t in stop:
            continue
        toks.append(t)

    return toks


def _bigrams(tokens: list[str]) -> set[str]:
    return {f"{tokens[i]} {tokens[i+1]}" for i in range(len(tokens) - 1)}


_MONEY_RE = re.compile(r"(£|\$|€)\s*([0-9][0-9,]*(?:\.[0-9]+)?)")
_REFUND_RE = re.compile(r"\brefund\w*\b", re.IGNORECASE)


def _has_refund_word(text: str) -> bool:
    return bool(_REFUND_RE.search(text))


def _max_money_amount(text: str) -> float:
    """
    Returns the maximum money amount found in text, or 0.0 if none.
    Handles £1,000.50 style numbers.
    """
    max_amt = 0.0
    for m in _MONEY_RE.finditer(text):
        num = m.group(2).replace(",", "")
        try:
            amt = float(num)
            if amt > max_amt:
                max_amt = amt
        except ValueError:
            continue
    return max_amt


def naive_conflicts(request_summary: str, anchors: list[TruthAnchor]) -> list[TruthAnchor]:
    req_norm = _norm(request_summary)
    req_has_not = _has_not(req_norm)
    req_wo_not = _strip_not(req_norm)

    req_tokens = _meaningful_tokens(req_norm)
    req_token_set = set(req_tokens)
    req_bigrams = _bigrams(req_tokens)

    refund_hit = _has_refund_word(request_summary)
    max_amt = _max_money_amount(request_summary)

    hits: list[TruthAnchor] = []

    for a in anchors:
        stmt_norm = _norm(a.statement)
        stmt_has_not = _has_not(stmt_norm)
        stmt_wo_not = _strip_not(stmt_norm)

        # Strong negation conflict (semantic inversion)
        if req_wo_not == stmt_wo_not and (req_has_not != stmt_has_not):
            hits.append(a)
            continue

        stmt_tokens = _meaningful_tokens(stmt_norm)
        stmt_token_set = set(stmt_tokens)
        stmt_bigrams = _bigrams(stmt_tokens)

        token_overlap = len(req_token_set & stmt_token_set)
        bigram_overlap = len(req_bigrams & stmt_bigrams)

        if bigram_overlap >= 1 or token_overlap >= 2:
            hits.append(a)

    # access .active and .scope directly instead of via getattr for consistency
    if refund_hit and max_amt > 100:
        for a in anchors:
            if a.active and a.scope == "payments.refunds":
                if a not in hits:
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

    high_risk_phrases = {
        "break into", "break in", "bypass", "lockpick", "pick lock",
        "hotwire", "slim jim", "jimmy", "forced entry", "steal", "theft",
    }

    high_risk_hits = [p for p in high_risk_phrases if p in req_norm]

    filler = {"a", "an", "the", "to", "and", "or", "of", "in", "on", "for"}
    stop = filler | {"i", "you", "we", "it", "is", "are", "be", "will", "not"}

    for a in conflicts:
        stmt_norm = _norm(a.statement)
        stmt_has_not = _has_not(stmt_norm)
        stmt_wo_not = _strip_not(stmt_norm)

        header = f"Anchor L{a.level} ({a.scope}): \"{a.statement}\""

        # Strong negation conflict (semantic inversion)
        if req_wo_not == stmt_wo_not and (req_has_not != stmt_has_not):
            explanations.append(
                f"{header} — triggered because the request and anchor match after removing 'not', "
                f"but one is negated and the other isn't (semantic inversion)."
            )
            continue

        # High-risk intent explanation (preferred when detected)
        if high_risk_hits:
            explanations.append(
                f"{header} — triggered because the request contains high-risk intent phrasing: "
                f"{', '.join(high_risk_hits)}."
            )
            continue

        # Keyword overlap explanation
        req_tokens = _meaningful_tokens(req_norm)
        req_token_set = set(req_tokens)
        req_bigrams = _bigrams(req_tokens)

        stmt_tokens = _meaningful_tokens(stmt_norm)
        stmt_token_set = set(stmt_tokens)
        stmt_bigrams = _bigrams(stmt_tokens)

        matched_tokens = sorted(req_token_set & stmt_token_set)
        matched_bigrams = sorted(req_bigrams & stmt_bigrams)

        if matched_bigrams:
            explanations.append(
                f"{header} — triggered because the request matches a meaningful phrase: "
                f"{', '.join(matched_bigrams)}."
            )
        elif matched_tokens:
            explanations.append(
                f"{header} — triggered because the request shares multiple meaningful keywords: {', '.join(matched_tokens)}."
            )
        else:
            explanations.append(
                f"{header} — triggered by the current matching rules "
                f"(no specific overlap extracted)."
            )

    return explanations


def _detect_conflicts(request_text: str, anchors: list[TruthAnchor]) -> tuple[list[TruthAnchor], dict]:
    matcher_requested = os.getenv("SW_MATCHER", "naive").lower()
    matcher_used = matcher_requested
    embedding_threshold = 0.50
    fallback_used = False
    fallback_reason: str | None = None
    matched_scores: list[dict] = []

    if matcher_requested == "embedding":
        scored = find_conflicts_embedding(
            request_text,
            anchors,
            threshold=embedding_threshold,
        )
        conflicts = [a for (a, _score) in scored]
        matched_scores = [{"anchor_id": a.id, "score": float(s)} for (a, s) in scored]

        if not conflicts:
            fallback_used = True
            fallback_reason = "embedding_no_matches"
            matcher_used = "naive_fallback"
            conflicts = naive_conflicts(request_text, anchors)
    else:
        conflicts = naive_conflicts(request_text, anchors)

    match_debug = {
        "evaluated_anchor_count": len(anchors),
        "conflicted_ids": [a.id for a in conflicts],
        "matcher_requested": matcher_requested,
        "matcher_used": matcher_used,
        "embedding_threshold": embedding_threshold if matcher_requested == "embedding" else None,
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
        "matched_scores": matched_scores,
    }
    return conflicts, match_debug


def _norm_state(val):
    """Normalize state value (passthrough for now; extend as needed)."""
    return val


@router.post("/evaluate", response_model=GateEvaluateOut, response_model_exclude_none=True)
def evaluate(payload: GateEvaluateIn, db: Session = Depends(get_db)):
    # 1) Load the anchor set we actually evaluated against
    if payload.profile_id is not None:
        profile = db.get(PolicyProfile, payload.profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        rows = list(db.scalars(
            select(PolicyProfileAnchor)
            .where(PolicyProfileAnchor.profile_id == payload.profile_id)
            .where(PolicyProfileAnchor.enabled == True)  # noqa: E712
            .order_by(PolicyProfileAnchor.priority)
        ).all())
        anchor_ids = [r.anchor_id for r in rows]
        active_anchors = list(db.scalars(
            select(TruthAnchor)
            .where(TruthAnchor.id.in_(anchor_ids))
            .where(TruthAnchor.active == True)  # noqa: E712
        ).all())
    else:
        stmt_all = select(TruthAnchor).where(TruthAnchor.active == True)  # noqa: E712
        active_anchors = list(db.scalars(stmt_all).all())

    # 2) Run conflict detection (with audit-safe matcher logging)
    conflicts, match_debug = _detect_conflicts(payload.request_summary, active_anchors)

    explanations_list = _build_explanations(payload.request_summary, conflicts)
    explanation_text = " ".join(explanations_list)

    conflicted_ids = [a.id for a in conflicts]
    warnings = [a.statement for a in conflicts]
    warning_anchors = conflicts
    max_level = max((a.level for a in conflicts), default=0)

    # 3) Run your deterministic decision
    decision = decide(
        state=UserState(arousal=payload.arousal, dominance=payload.dominance),
        conflicted_anchor_ids=conflicted_ids,
        max_level_conflict=max_level,
    )

    # 4) Prepare log row
    log = GateLog(
        request_summary=payload.request_summary,
        arousal=payload.arousal,
        dominance=payload.dominance,
        decision=decision.decision,
        reason=decision.reason,
        conflicted_anchor_ids=",".join(str(i) for i in conflicted_ids),
        interpretation=explanation_text,
    )

    db.add(log)
    db.flush()  # assigns log.id without committing yet

    # 5) Create DecisionTrace
    match_debug["conflicted_ids"] = conflicted_ids
    match_debug["max_level_conflict"] = max_level

    trace = DecisionTrace(
        policy_profile_id=None,
        request_text=payload.request_summary,
        request_normalized=_norm(payload.request_summary),
        arousal=payload.arousal,
        dominance=payload.dominance,
        decision=decision.decision,
        reason=decision.reason,
        explanation=getattr(decision, "explanation", "") or getattr(decision, "explain", "") or "",
        match_debug_json=json.dumps(match_debug, ensure_ascii=False),
    )

    db.add(trace)
    db.flush()  # assigns trace.id

    # 6) Snapshot ALL anchors considered + mark which ones conflicted
    conflicted_set = set(conflicted_ids)
    for a in active_anchors:
        db.add(
            DecisionTraceAnchor(
                trace_id=trace.id,
                anchor_id=a.id,
                anchor_hash=a.stable_hash(),
                level_snapshot=a.level,
                scope_snapshot=a.scope,
                active_snapshot=bool(a.active),
                statement_snapshot=a.statement,
                matched=(a.id in conflicted_set),
                match_note=("conflict" if a.id in conflicted_set else ""),
            )
        )

    # 7) Commit once (log + trace + trace anchors)
    db.commit()
    db.refresh(log)

    # Convert ORM anchors -> schema objects for response stability
    warning_anchor_out = [
        AnchorOut.model_validate(a, from_attributes=True) for a in warning_anchors
    ]

    # Only include the explanation when gated/refused
    interpretation: Optional[str] = None
    suggestion: Optional[str] = None
    explanations: Optional[List[str]] = None
    next_actions: Optional[List[str]] = None

    if decision.decision != "proceed":
        interpretation = getattr(decision, "interpretation", None)
        suggestion = getattr(decision, "suggestion", None)
        next_actions = getattr(decision, "next_actions", None)
        explanations = explanations_list

    return GateEvaluateOut(
        decision=decision.decision,
        reason=decision.reason,
        interpretation=interpretation,
        suggestion=suggestion,
        explanations=explanations,
        next_actions=next_actions,
        conflicted_anchor_ids=conflicted_ids,
        log_id=log.id,
        trace_id=trace.id,
        ethos_refs=_ethos_refs_for(decision.decision, max_level),
        warnings=warnings,
        warning_anchors=warning_anchor_out,
    )


@router.post("/reframe", response_model=GateReframeOut)
def reframe(payload: GateReframeIn, db: Session = Depends(get_db)):
    parent = db.get(GateLog, payload.log_id)
    if parent is None:
        raise HTTPException(status_code=404, detail="gate log not found")

    # Simple MVP "reframe": treat new_intent as the new request summary
    reframed = payload.new_intent.strip()

    # Use explicit None check so empty string "" doesn't fall back to parent value
    arousal_raw = payload.arousal if payload.arousal is not None else parent.arousal
    dominance_raw = payload.dominance if payload.dominance is not None else parent.dominance

    # Normalize state values
    arousal = _norm_state(arousal_raw)
    dominance = _norm_state(dominance_raw)

    # Re-run conflict detection on the reframed text
    stmt_all = select(TruthAnchor).where(TruthAnchor.active == True)  # noqa: E712
    active_anchors = list(db.scalars(stmt_all).all())

    # Run conflict detection with the reframed request
    conflicts, _match_debug = _detect_conflicts(reframed, active_anchors)
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


@router.get("/replay/{trace_id}", response_model=ReplayOut)
def replay(trace_id: int, db: Session = Depends(get_db)):
    trace = db.get(DecisionTrace, trace_id)
    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")

    # Load original trace anchor snapshot rows (the ordered policy set used)
    original_rows = list(trace.anchors)
    anchor_ids = [r.anchor_id for r in original_rows]

    # Load current anchors for those ids
    current_anchors = (
        db.execute(select(TruthAnchor).where(TruthAnchor.id.in_(anchor_ids)))
        .scalars()
        .all()
    )
    current_by_id = {a.id: a for a in current_anchors}

    drift: list[str] = []

    # Drift check: missing, changed hash, or active flip
    for r in original_rows:
        a = current_by_id.get(r.anchor_id)
        if not a:
            drift.append(f"Anchor {r.anchor_id} missing (deleted)")
            continue

        now_hash = a.stable_hash()
        if now_hash != r.anchor_hash:
            drift.append(
                f"Anchor {r.anchor_id} changed (hash {r.anchor_hash[:8]} -> {now_hash[:8]})"
            )

        if bool(a.active) != bool(r.active_snapshot):
            drift.append(
                f"Anchor {r.anchor_id} active flag changed ({r.active_snapshot} -> {bool(a.active)})"
            )

        if a.level != r.level_snapshot:
            drift.append(
                f"Anchor {r.anchor_id} level changed ({r.level_snapshot} -> {a.level})"
            )

        if a.scope != r.scope_snapshot:
            drift.append(
                f"Anchor {r.anchor_id} scope changed ({r.scope_snapshot} -> {a.scope})"
            )

    # Re-run decision using CURRENT anchors (same request)
    request_text = trace.request_text

    # Preserve original anchor ordering from the trace
    anchors_ordered_now = [current_by_id[i] for i in anchor_ids if i in current_by_id]

    # Use _detect_conflicts() so SW_MATCHER env var is respected during replay
    conflicts, _replay_match_debug = _detect_conflicts(request_text, anchors_ordered_now)
    conflicted_ids = [a.id for a in conflicts]
    max_level = max((a.level for a in conflicts), default=0)

    state = UserState(
        arousal=_norm_state(trace.arousal),
        dominance=_norm_state(trace.dominance),
        
    )

    result = decide(
        state=state,
        conflicted_anchor_ids=conflicted_ids,
        max_level_conflict=max_level,
    )

    def _get(obj, name: str, default=""):
        if hasattr(obj, name):
            return getattr(obj, name)
        if isinstance(obj, dict) and name in obj:
            return obj[name]
        return default

    decision_now = _get(result, "decision", "")
    reason_now = _get(result, "reason", "")

    # Re-build explanation from current conflicts so same_explanation is meaningful
    explanations_now = _build_explanations(request_text, conflicts)
    explanation_now = " | ".join(explanations_now)

    # Detect newly added active anchors not present in original trace
    all_active_ids = set(
        db.execute(
            select(TruthAnchor.id).where(TruthAnchor.active == True)  # noqa: E712
        ).scalars().all()
    )

    original_ids = set(anchor_ids)
    new_ids = all_active_ids - original_ids

    if new_ids:
        drift.append(f"{len(new_ids)} new active anchors added since trace (not replayed)")

    match_debug = None
    if trace.match_debug_json:
        try:
            match_debug = json.loads(trace.match_debug_json)
        except Exception:
            match_debug = {"_error": "match_debug_json_invalid"}

    return ReplayOut(
        trace_id=trace.id,
        same_decision=(decision_now == trace.decision),
        same_reason=(reason_now == trace.reason),
        same_explanation=(explanation_now == (trace.explanation or "")),
        anchor_drift=drift,
        decision_before=trace.decision,
        decision_now=decision_now,
        reason_before=trace.reason,
        reason_now=reason_now,
        explanation=explanation_now,
        match_debug=match_debug,
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

    items = []
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
@router.post("/acknowledge", response_model=GateAcknowledgeOut)
def acknowledge(payload: GateAcknowledgeIn, db: Session = Depends(get_db)):
    """
    proceed_acknowledged flow.
    Called when a user chooses to proceed despite a level-2 gate.
    Logs the acknowledgement and returns a proceed decision.
    The original gate log is preserved — this creates a linked follow-on entry.
    """
    parent = db.get(GateLog, payload.log_id)
    if parent is None:
        raise HTTPException(status_code=404, detail="gate log not found")

    # Only valid after a level-2 gate
    if parent.decision != "gate" or "l2" not in parent.reason:
        raise HTTPException(
            status_code=422,
            detail="acknowledge is only valid after a level-2 gate decision"
        )

    arousal = payload.arousal if payload.arousal is not None else parent.arousal
    dominance = payload.dominance if payload.dominance is not None else parent.dominance

    conflicted_ids = parse_id_list(parent.conflicted_anchor_ids)

    log = GateLog(
        request_summary=parent.request_summary,
        arousal=arousal,
        dominance=dominance,
        decision="proceed",
        reason="proceed_acknowledged",
        conflicted_anchor_ids=parent.conflicted_anchor_ids,
        interpretation=f"User acknowledged level-2 conflict and chose to proceed. Acknowledgement: {payload.acknowledgement}",
        suggestion="Proceed. Acknowledgement is on record.",
        user_choice="proceed_acknowledged:" + str(parent.id),
    )

    db.add(log)
    db.commit()
    db.refresh(log)

    return GateAcknowledgeOut(
        parent_log_id=parent.id,
        acknowledgement=payload.acknowledgement,
        decision="proceed",
        reason="proceed_acknowledged",
        interpretation=f"User acknowledged level-2 conflict and chose to proceed.",
        suggestion="Proceed. Acknowledgement is on record.",
        next_actions=["proceed"],
        conflicted_anchor_ids=conflicted_ids,
        warnings=[parent.interpretation],
        log_id=log.id,
    )