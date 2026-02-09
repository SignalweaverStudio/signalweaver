from datetime import datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, ConfigDict

# -----------------------------
# Helpers
# -----------------------------
Arousal = Literal["low", "med", "high", "unknown"]
Dominance = Literal["low", "med", "high", "unknown"]

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
    level: int = Field(..., ge=1, le=3)
    statement: str = Field(..., min_length=1, max_length=1000)
    scope: str = Field(default="global", max_length=64)
    active: bool = True

class TruthAnchorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    level: int
    statement: str
    scope: str
    active: bool
    created_at: datetime

# Backwards/alternate friendly aliases (so other files can use shorter names)
AnchorCreate = TruthAnchorCreate
AnchorOut = TruthAnchorOut

# -----------------------------
# Gate evaluate schemas (match current gate router usage)
# -----------------------------
class GateEvaluateIn(BaseModel):
    request_summary: str = Field(..., min_length=1, max_length=2000)
    arousal: Arousal = "unknown"
    dominance: Dominance = "unknown"

class GateEvaluateOut(BaseModel):
    decision: str
    reason: str
    # "wow" fields: only present when we need them
    interpretation: Optional[str] = None
    suggestion: Optional[str] = None
    explanations: Optional[List[str]] = None
    next_actions: Optional[List[str]] = None
    conflicted_anchor_ids: List[int] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    warning_anchors: List[TruthAnchorOut] = Field(default_factory=list)
    log_id: int
    trace_id: int | None = None 

# -----------------------------
# Gate log read schemas
# -----------------------------
class GateLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    created_at: datetime
    request_summary: str
    arousal: Arousal
    dominance: Dominance
    decision: str
    reason: str
    conflicted_anchor_ids: List[int] = Field(default_factory=list)
    user_choice: str
    
class GateLogListOut(BaseModel):
    items: List[GateLogOut]
    total: int
    limit: int
    offset: int

class GateReframeIn(BaseModel):
    log_id: int
    new_intent: str = Field(..., min_length=1, max_length=2000)
    # Optional: let caller override state, otherwise we reuse the original log state
    arousal: Optional[Arousal] = None
    dominance: Optional[Dominance] = None

class GateReframeOut(BaseModel):
    parent_log_id: int
    reframed_request_summary: str
    decision: str
    reason: str
    interpretation: str
    suggestion: str
    explanations: Optional[List[str]] = None
    next_actions: List[str] = Field(default_factory=list)
    conflicted_anchor_ids: List[int] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    warning_anchors: List[TruthAnchorOut] = Field(default_factory=list)
    log_id: int
from pydantic import BaseModel
from typing import List


class ReplayOut(BaseModel):
    trace_id: int
    same_decision: bool
    same_reason: bool
    same_explanation: bool

    anchor_drift: List[str]

    decision_before: str
    decision_now: str
    reason_before: str
    reason_now: str
