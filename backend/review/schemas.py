from datetime import datetime
from pydantic import BaseModel, Field
from typing import List


# -----------------------------
# Helpers
# -----------------------------

def parse_id_list(value: str) -> List[int]:
    """
    Converts stored anchor id strings into lists.

    Examples:
        ""        -> []
        "1,2,3"   -> [1,2,3]
        "[1,2]"   -> [1,2]
    """
    if not value:
        return []

    v = value.strip()

    if v == "" or v == "[]":
        return []

    if v.startswith("[") and v.endswith("]"):
        v = v[1:-1]

    parts = v.split(",")

    result: List[int] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        try:
            result.append(int(p))
        except ValueError:
            continue

    return result


# -----------------------------
# Truth Anchor schemas (canonical names expected by anchors.py)
# -----------------------------

class TruthAnchorCreate(BaseModel):
    level: int
    statement: str
    scope: str = "global"
    active: bool = True


class TruthAnchorOut(BaseModel):
    id: int
    level: int
    statement: str
    scope: str
    active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# Backwards/alternate friendly aliases (so other files can use shorter names)
AnchorCreate = TruthAnchorCreate
AnchorOut = TruthAnchorOut


# -----------------------------
# Gate evaluate schemas (match current gate router usage)
# -----------------------------

class GateEvaluateIn(BaseModel):
    request_summary: str
    arousal: str = "unknown"
    dominance: str = "unknown"


class GateEvaluateOut(BaseModel):
    decision: str
    reason: str
    conflicted_anchor_ids: List[int] = []
    warnings: List[str] = []
    warning_anchors: List[TruthAnchorOut] = []
    log_id: int


# -----------------------------
# Gate log read schemas
# -----------------------------

class GateLogOut(BaseModel):
    id: int
    created_at: datetime
    request_summary: str
    arousal: str
    dominance: str
    decision: str
    reason: str
    conflicted_anchor_ids: List[int] = []
    user_choice: str

    class Config:
        from_attributes = True


class GateLogListOut(BaseModel):
    items: List[GateLogOut]
    total: int
    limit: int
    offset: int
