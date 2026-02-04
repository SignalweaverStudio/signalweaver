from datetime import datetime
from pydantic import BaseModel, Field

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

    model_config = {"from_attributes": True}
class GateEvaluateIn(BaseModel):
    request_summary: str = Field(min_length=1)
    arousal: str = Field(default="unknown")      # low/med/high/unknown
    dominance: str = Field(default="unknown")    # low/med/high/unknown

class GateEvaluateOut(BaseModel):
    decision: str                  # proceed/gate/refuse
    reason: str
    conflicted_anchor_ids: list[int] = []
    log_id: int
