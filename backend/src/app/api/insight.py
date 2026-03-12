from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from pydantic import BaseModel

from app.dependencies import get_db
from app.models import DecisionTrace, GateLog, TruthAnchor

router = APIRouter()


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

    result = []

    for anchor_id, total_gates in totals.items():

        if total_gates < 3:
            continue

        ov = overrides.get(anchor_id, 0)
        rate = round((ov / total_gates) * 100, 1) if total_gates > 0 else 0.0

        result.append(
            AnchorOverrideRate(
                anchor_id=anchor_id,
                statement=statement_map.get(anchor_id, "(missing anchor)"),
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
    priority: int
    scope: str | None
    active: bool


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

    result = []

    for a in anchors:
        if a.id not in matched_ids:
            result.append(
                DeadAnchor(
                    anchor_id=a.id,
                    statement=a.statement,
                )
            )

    result.sort(key=lambda x: x.anchor_id)
    return result