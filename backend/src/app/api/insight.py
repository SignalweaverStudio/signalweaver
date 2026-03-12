from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from pydantic import BaseModel
from app.api.gate import _detect_conflicts
from app.dependencies import get_db
from app.models import DecisionTrace, GateLog, TruthAnchor
from typing import List

router = APIRouter()


def _is_smoke_test_statement(statement: str | None) -> bool:
    if not statement:
        return False

    text = statement.lower()
    smoke_markers = [
        "smoke test",
        "smoke wall",
        "smoke overflow",
        "smoke vault",
        "smoke locker",
        "flubnort",
        "zorbix",
    ]
    return any(marker in text for marker in smoke_markers)


class DecisionSummary(BaseModel):
    total_decisions: int
    proceed_count: int
    gate_count: int
    refuse_count: int
    proceed_pct: float
    gate_pct: float
    refuse_pct: float
    total_overrides: int
    override_rate: float


@router.get("/summary", response_model=DecisionSummary)
def summary(db: Session = Depends(get_db)):
    rows = db.execute(
        select(DecisionTrace.decision, func.count(DecisionTrace.id).label("n"))
        .group_by(DecisionTrace.decision)
    ).all()

    counts = {r.decision: r.n for r in rows}
    total = sum(counts.values())
    proceed = counts.get("proceed", 0)
    gate = counts.get("gate", 0)
    refuse = counts.get("refuse", 0)

    def pct(n: int) -> float:
        return round((n / total) * 100, 1) if total > 0 else 0.0

    gate_logs_total = db.scalar(
        select(func.count(GateLog.id)).where(GateLog.decision == "gate")
    ) or 0

    overrides = db.scalar(
        select(func.count(GateLog.id)).where(GateLog.reason == "proceed_acknowledged")
    ) or 0

    override_rate = round((overrides / gate_logs_total) * 100, 1) if gate_logs_total > 0 else 0.0

    return DecisionSummary(
        total_decisions=total,
        proceed_count=proceed,
        gate_count=gate,
        refuse_count=refuse,
        proceed_pct=pct(proceed),
        gate_pct=pct(gate),
        refuse_pct=pct(refuse),
        total_overrides=overrides,
        override_rate=override_rate,
    )


class AnchorOverrideRate(BaseModel):
    anchor_id: int
    statement: str
    total_gates: int
    overrides: int
    override_rate: float


@router.get("/override-rate", response_model=list[AnchorOverrideRate])
def override_rate(db: Session = Depends(get_db)):

    gate_rows = db.execute(
        select(GateLog.conflicted_anchor_ids, GateLog.reason, GateLog.decision)
        .where(GateLog.conflicted_anchor_ids.is_not(None))
    ).all()

    totals = {}
    overrides = {}

    for row in gate_rows:
        raw_ids = row.conflicted_anchor_ids or ""
        ids = [int(x.strip()) for x in raw_ids.split(",") if x.strip().isdigit()]

        for anchor_id in ids:
            if row.decision == "gate":
                totals[anchor_id] = totals.get(anchor_id, 0) + 1
            if row.reason == "proceed_acknowledged":
                overrides[anchor_id] = overrides.get(anchor_id, 0) + 1

    if not totals:
        return []

    anchor_ids = list(totals.keys())

    anchors = db.execute(
        select(TruthAnchor.id, TruthAnchor.statement).where(TruthAnchor.id.in_(anchor_ids))
    ).all()

    statement_map = {a.id: a.statement for a in anchors}

    grouped = {}

    for anchor_id, total_gates in totals.items():
        if total_gates < 3:
            continue

        ov = overrides.get(anchor_id, 0)
        statement = statement_map.get(anchor_id, "(missing anchor)")

        if _is_smoke_test_statement(statement):
            continue

        key = statement.strip()

        if key not in grouped:
            grouped[key] = {
                "anchor_id": anchor_id,
                "statement": statement,
                "total_gates": 0,
                "overrides": 0,
            }

        grouped[key]["total_gates"] += total_gates
        grouped[key]["overrides"] += ov

    result = []

    for item in grouped.values():
        total_gates = item["total_gates"]
        ov = item["overrides"]
        rate = round((ov / total_gates) * 100, 1) if total_gates > 0 else 0.0

        result.append(
            AnchorOverrideRate(
                anchor_id=item["anchor_id"],
                statement=item["statement"],
                total_gates=total_gates,
                overrides=ov,
                override_rate=rate,
            )
        )

    result.sort(key=lambda x: x.override_rate, reverse=True)
    return result


class DeadAnchor(BaseModel):
    anchor_id: int
    statement: str


@router.get("/dead-anchors", response_model=list[DeadAnchor])
def dead_anchors(db: Session = Depends(get_db)):

    matched_ids = set()

    rows = db.execute(
        select(GateLog.conflicted_anchor_ids)
        .where(GateLog.conflicted_anchor_ids.is_not(None))
    ).all()

    for row in rows:
        raw_ids = row.conflicted_anchor_ids or ""
        ids = [int(x.strip()) for x in raw_ids.split(",") if x.strip().isdigit()]
        matched_ids.update(ids)

    anchors = db.execute(
        select(TruthAnchor.id, TruthAnchor.statement)
    ).all()

    grouped = {}

    for a in anchors:
        if a.id in matched_ids:
            continue

        if _is_smoke_test_statement(a.statement):
            continue

        key = a.statement.strip()

        if key not in grouped:
            grouped[key] = {
                "anchor_id": a.id,
                "statement": a.statement,
            }

    result = []

    for item in grouped.values():
        result.append(
            DeadAnchor(
                anchor_id=item["anchor_id"],
                statement=item["statement"],
            )
        )

    result.sort(key=lambda x: x.statement.lower())
    return result


class DriftAnchor(BaseModel):
    anchor_id: int
    current_statement: str
    appearances: int


@router.get("/drift", response_model=list[DriftAnchor])
def drift(db: Session = Depends(get_db)):

    matched_ids = []

    rows = db.execute(
        select(GateLog.conflicted_anchor_ids)
        .where(GateLog.conflicted_anchor_ids.is_not(None))
    ).all()

    for row in rows:
        raw_ids = row.conflicted_anchor_ids or ""
        ids = [int(x.strip()) for x in raw_ids.split(",") if x.strip().isdigit()]
        matched_ids.extend(ids)

    if not matched_ids:
        return []

    appearance_counts = {}
    for anchor_id in matched_ids:
        appearance_counts[anchor_id] = appearance_counts.get(anchor_id, 0) + 1

    anchors = db.execute(
        select(TruthAnchor.id, TruthAnchor.statement).where(
            TruthAnchor.id.in_(list(appearance_counts.keys()))
        )
    ).all()

    grouped = {}

    for a in anchors:
        if _is_smoke_test_statement(a.statement):
            continue

        key = a.statement.strip()

        if key not in grouped:
            grouped[key] = {
                "anchor_id": a.id,
                "current_statement": a.statement,
                "appearances": 0,
            }

        grouped[key]["appearances"] += appearance_counts.get(a.id, 0)

    result = []

    for item in grouped.values():
        result.append(
            DriftAnchor(
                anchor_id=item["anchor_id"],
                current_statement=item["current_statement"],
                appearances=item["appearances"],
            )
        )

    result.sort(key=lambda x: x.appearances, reverse=True)
    return result


class InsightReport(BaseModel):
    summary: DecisionSummary
    override_rate: list[AnchorOverrideRate]
    dead_anchors: list[DeadAnchor]
    drift: list[DriftAnchor]


class ProposedAnchorChange(BaseModel):
    anchor_id: int
    new_statement: str


class CounterfactualIn(BaseModel):
    trace_ids: List[int]
    proposed_changes: List[ProposedAnchorChange]


class CounterfactualOut(BaseModel):
    trace_id: int
    original_decision: str
    counterfactual_decision: str
    changed: bool


@router.post("/counterfactual", response_model=list[CounterfactualOut])
def counterfactual(payload: CounterfactualIn, db: Session = Depends(get_db)):
    results = []

    traces = db.execute(
        select(DecisionTrace).where(DecisionTrace.id.in_(payload.trace_ids))
    ).scalars().all()

    change_map = {c.anchor_id: c.new_statement for c in payload.proposed_changes}
    anchors = db.execute(select(TruthAnchor)).scalars().all()

    for trace in traces:
        trace_text = ""

        if hasattr(trace, "input_text") and trace.input_text:
            trace_text = trace.input_text
        elif hasattr(trace, "user_input") and trace.user_input:
            trace_text = trace.user_input
        elif hasattr(trace, "request_text") and trace.request_text:
            trace_text = trace.request_text
        elif hasattr(trace, "prompt") and trace.prompt:
            trace_text = trace.prompt

        patched_anchors = []

        for anchor in anchors:
            if anchor.id in change_map:
                anchor.statement = change_map[anchor.id]
            patched_anchors.append(anchor)

        conflicts, _debug = _detect_conflicts(trace_text, patched_anchors)
        counterfactual_decision = "gate" if conflicts else "proceed"

        results.append(
            CounterfactualOut(
                trace_id=trace.id,
                original_decision=str(trace.decision),
                counterfactual_decision=counterfactual_decision,
                changed=(str(trace.decision) != counterfactual_decision),
            )
        )

    return results


@router.get("/report", response_model=InsightReport)
def report(db: Session = Depends(get_db)):
    summary_data = summary(db)
    override_data = override_rate(db)
    dead_anchor_data = dead_anchors(db)
    drift_data = drift(db)

    return InsightReport(
        summary=summary_data,
        override_rate=override_data,
        dead_anchors=dead_anchor_data,
        drift=drift_data,
    )
