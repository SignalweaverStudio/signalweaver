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


class EnforcementMode(str, Enum):
    shadow = "shadow"
    soft = "soft"
    hard = "hard"


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
    profile_id: Optional[int] = None
    override_reason: Optional[str] = None


class GateEvaluateOut(BaseModel):
    decision: DecisionLiteral
    reason: str
    conflicted_anchor_ids: List[int] = []
    log_id: int

    trace_id: Optional[int] = None
    interpretation: Optional[str] = None
    suggestion: Optional[str] = None
    explanations: Optional[List[str]] = None
    next_actions: Optional[List[str]] = None
    ethos_refs: List[str] = []
    warnings: List[str] = []
    warning_anchors: List[AnchorOut] = []
    enforcement_mode: Optional[str] = None
    would_block: Optional[bool] = None


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
    limit: int = 50
    offset: int = 0


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
    parent_log_id: Optional[int] = None

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
    match_debug: Any = None


class PolicyProfileCreate(BaseModel):
    name: str
    description: Optional[str] = None
    is_default: Optional[bool] = False
    enforcement_mode: EnforcementMode = EnforcementMode.hard


class PolicyProfileUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_default: Optional[bool] = None
    enforcement_mode: Optional[EnforcementMode] = None


class PolicyProfileOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    is_default: bool
    enforcement_mode: str
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


class ShadowSummaryOut(BaseModel):
    total_evaluated: int
    total_l3_conflicts: int
    total_l2_conflicts: int
    total_would_block: int
    total_overrides: int
    top_triggered_anchors: List[dict]


# ============================================================
# Execution Layer
# ============================================================

class ExecuteTrustedIn(BaseModel):
    """Request body for POST /execute/trusted."""
    raw_text: str = Field(min_length=1)
    domain: str = Field(default="global", min_length=1)
    connector: str = Field(default="mock", min_length=1)
    context: dict = Field(default_factory=dict)
    profile_id: Optional[int] = None
    override_reason: Optional[str] = None
    arousal: Arousal = Arousal.unknown
    dominance: Dominance = Dominance.unknown


class ExecutionResultOut(BaseModel):
    """The execution portion of the response."""
    status: str  # "executed" | "blocked"
    connector: str
    result: Optional[dict] = None


class ExecuteTrustedOut(BaseModel):
    """Full response for POST /execute/trusted."""
    decision: DecisionLiteral
    reason: str
    trace_id: int
    log_id: int
    execution: ExecutionResultOut
    enforcement_mode: Optional[str] = None
    would_block: Optional[bool] = None
    conflicted_anchor_ids: List[int] = []
    explanation: Optional[str] = None


# ============================================================
# Execution Analytics Layer (Stage 16)
# ============================================================

class ExecutionHistoryItem(BaseModel):
    """Single item in the execution history response."""
    trace_id: int
    decision: str
    status: str
    connector: str
    created_at: datetime
    would_block: bool = False


class ExecutionHistoryOut(BaseModel):
    """GET /executions response."""
    total: int
    items: List[ExecutionHistoryItem]


class ExecutionSummaryOut(BaseModel):
    """GET /executions/summary response."""
    total_requests: int
    executed: int
    blocked: int
    failed: int = 0
    block_rate: float
    override_rate: float
    shadow_would_block_rate: float


class ConflictedAnchorEntry(BaseModel):
    """Entry for top conflicted anchors."""
    anchor_id: int
    count: int


class TopReasonEntry(BaseModel):
    """Entry for top block reasons."""
    reason: str
    count: int


class GovernanceInsightsOut(BaseModel):
    """GET /governance/insights response."""
    top_conflicted_anchors: List[ConflictedAnchorEntry]
    top_reasons: List[TopReasonEntry]


class ComplianceTraceItem(BaseModel):
    """A single decision trace with execution outcome in the compliance export."""
    trace_id: int
    created_at: datetime
    request_text: str
    decision: str
    reason: str
    explanation: str = ""
    enforcement_mode: str = "hard"
    would_block: bool = False
    conflicted_anchor_ids: List[int] = []
    execution_status: Optional[str] = None
    execution_connector: Optional[str] = None


class ComplianceExportOut(BaseModel):
    """GET /compliance/export response."""
    total: int
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    traces: List[ComplianceTraceItem]


# ============================================================
# Time-Series Analytics (Stage 19)
# ============================================================

class TimeseriesBucketItem(BaseModel):
    """Single time bucket in the timeseries response."""
    start: datetime
    end: datetime
    total_requests: int
    executed: int
    blocked: int
    failed: int
    block_rate: float
    override_rate: float
    shadow_would_block_rate: float


class TimeseriesOut(BaseModel):
    """GET /executions/timeseries response."""
    granularity: str
    buckets: List[TimeseriesBucketItem]


# ============================================================
# Alerting Layer (Stage 20)
# ============================================================

class AlertItem(BaseModel):
    """A single triggered alert."""
    type: str
    value: float
    threshold: float
    metric: Optional[str] = None
    previous_avg: Optional[float] = None


class AlertsOut(BaseModel):
    """GET /alerts response."""
    window: str
    alerts: List[AlertItem]
    status: Literal["ok", "alert"]


# ============================================================
# Alert Dispatch Layer (Stage 21)
# ============================================================

class AlertDispatchIn(BaseModel):
    """Request body for POST /alerts/dispatch.

    Computes alerts over the specified window, then pushes them to an
    external webhook target via the existing secure dispatch path.
    """
    window: str = Field(default="24h", min_length=1, description="Time window: e.g. '1h', '24h', '7d'")
    granularity: Optional[str] = Field(default=None, description="Bucket granularity: hour | day | week")
    context: dict = Field(
        default_factory=dict,
        description="Webhook config: url, method, headers, signing_secret, timeout",
    )
    block_rate_threshold: float = Field(default=0.25, ge=0.0, le=1.0)
    override_rate_threshold: float = Field(default=0.10, ge=0.0, le=1.0)
    failure_rate_threshold: float = Field(default=0.05, ge=0.0, le=1.0)
    spike_multiplier: float = Field(default=2.0, ge=1.0, le=100.0)
    status_filter: Optional[str] = Field(default=None, description="Filter by execution status")
    connector_filter: Optional[str] = Field(default=None, description="Filter by connector name")


class AlertDispatchOut(BaseModel):
    """Response for POST /alerts/dispatch."""
    status: Literal["ok", "alert"]
    alert_count: int
    dispatch_status: str  # "not_sent" | "sent" | "failed"
    connector: str
    result: Optional[dict] = None