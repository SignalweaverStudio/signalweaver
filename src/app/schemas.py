from datetime import datetime
from enum import Enum
from typing import List, Optional, Any
from typing import Literal

DecisionLiteral = Literal["proceed", "gate", "refuse"]
from pydantic import BaseModel, Field, ConfigDict


class Arousal(str, Enum):
    low = "low"
    med = "med"
    high = "high"
    unknown = "unknown"


class Dominance(str, Enum):
    low = "low"
    med = "med"
    high = "high"
    unknown = "unknown"


def parse_id_list(s: Optional[str]) -> List[int]:
    if not s:
        return []
    out = []
    for part in s.split(","):
        part = part.strip()
        if part:
            try:
                out.append(int(part))
            except ValueError:
                pass
    return out


class TruthAnchorCreate(BaseModel):
    level: int = Field(ge=1, le=3)
    statement: str = Field(min_length=1)
    scope: str = Field(default="global", min_length=1)


class TruthAnchorOut(BaseModel):
    id: int
    level: int
    statement: str
    scope: str
    active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AnchorOut(TruthAnchorOut):
    pass


class GateEvaluateIn(BaseModel):
    request_summary: str = Field(min_length=1)
    arousal: Arousal = Arousal.unknown
    dominance: Dominance = Dominance.unknown


class GateEvaluateOut(BaseModel):
    decision: DecisionLiteral
    reason: str
    conflicted_anchor_ids: List[int] = []
    log_id: int

    # optional/extended fields (previously being silently dropped)
    trace_id: Optional[int] = None
    interpretation: Optional[str] = None
    suggestion: Optional[str] = None
    explanations: Optional[List[str]] = None
    next_actions: Optional[List[str]] = None
    ethos_refs: List[str] = []
    warnings: List[str] = []
    warning_anchors: List[AnchorOut] = []

class GateLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    request_summary: str
    arousal: Arousal
    dominance: Dominance
    decision: DecisionLiteral
    reason: str
    interpretation: str = ""
    suggestion: str = ""
    next_actions: List[str] = Field(default_factory=list)
    conflicted_anchor_ids: List[int] = Field(default_factory=list)
    user_choice: str = ""


class GateLogListOut(BaseModel):
    items: List[GateLogOut]
    total: int


class GateReframeIn(BaseModel):
    log_id: int
    new_intent: str
    arousal: Optional[Arousal] = None
    dominance: Optional[Dominance] = None


class GateReframeOut(BaseModel):
    decision: DecisionLiteral
    reason: str
    reframed_request: str
    conflicted_anchor_ids: List[int] = []
    log_id: int
    trace_id: Optional[int] = None

    # optional/extended fields (previously being silently dropped)
    interpretation: Optional[str] = None
    suggestion: Optional[str] = None
    explanations: Optional[List[str]] = None
    next_actions: Optional[List[str]] = None
    ethos_refs: List[str] = []
    warnings: List[str] = []
    warning_anchors: List[AnchorOut] = []


class ReplayOut(BaseModel):
    trace_id: int
    same_decision: bool
    same_reason: bool
    same_explanation: bool
    anchor_drift: Any

    decision_before: str
    decision_now: str

    reason_before: str
    reason_now: str

    explanation: str = ""

class PolicyProfileCreate(BaseModel):
    name: str
    description: Optional[str] = None
    is_default: Optional[bool] = False
    parent_id: Optional[int] = None


class PolicyProfileUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_default: Optional[bool] = None
    parent_id: Optional[int] = None


class PolicyProfileOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    is_default: bool
    parent_id: Optional[int]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PolicyProfileListOut(BaseModel):
    items: List[PolicyProfileOut]
    total: int


class ProfileAnchorsIn(BaseModel):
    anchor_ids: List[int]


class ProfileAnchorsOut(BaseModel):
    profile_id: int
    anchor_ids: List[int]
