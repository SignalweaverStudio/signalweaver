from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from pydantic import BaseModel

from app.dependencies import get_db
from app.models import DecisionTrace, GateLog

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