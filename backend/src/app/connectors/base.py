from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import sqlite3
import threading
import time
import uuid
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

# Try to import stripe — graceful fallback to mock-only if unavailable
try:
    import stripe as _stripe_lib
    _STRIPE_AVAILABLE = True
except ImportError:
    _stripe_lib = None
    _STRIPE_AVAILABLE = False
    logging.getLogger("signalweaver").warning(
        "stripe library not installed — Stripe connector will fall back to mock mode"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Logging Configuration — sensitive field masking
# ═══════════════════════════════════════════════════════════════════════════════

class _SensitiveFormatter(logging.Formatter):
    """Masks API keys, token-like strings, and optionally amounts in logs."""
    _MASK_PATTERNS = [
        (re.compile(r'(sk_live_|sk_test_|rk_live_|pk_live_|pk_test_)\S+'), r'\1****MASKED****'),
        (re.compile(r'("api_key":\s*")([^"]+)(")'), r'\1****MASKED****\3'),
        (re.compile(r'(token[=:]\s*)\S+'), r'\1****MASKED****'),
        (re.compile(r'("api_key_raw":\s*")([^"]+)(")'), r'\1****MASKED****\3'),
    ]

    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        for pattern, replacement in self._MASK_PATTERNS:
            msg = pattern.sub(replacement, msg)
        return msg

_logger = logging.getLogger("signalweaver")
_handler = logging.StreamHandler()
_handler.setFormatter(_SensitiveFormatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
if not _logger.handlers:
    _logger.addHandler(_handler)
_logger.setLevel(logging.INFO)


# ═══════════════════════════════════════════════════════════════════════════════
# LAYER 0 — vNext.9: Trust Boundary Layer (PRIMARY FOCUS)
# Authentication, Context Construction, Firewall, Override Governance,
# Deterministic Idempotency
# ═══════════════════════════════════════════════════════════════════════════════

# ── Data Classes ─────────────────────────────────────────────────────────────


@dataclass
class AuthIdentity:
    """Authenticated identity — the single source of truth for actor metadata."""
    actor_id: str
    actor_role: str
    tenant_id: str
    auth_method: str          # "API_KEY" or "TOKEN"
    authenticated_at: int     # epoch ms

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TrustedContext:
    """Immutable, verified context constructed from auth identity + validated request."""
    actor_id: str
    actor_role: str
    tenant_id: str
    request_type: str               # derived from intent (initially "UNKNOWN")
    justification: Optional[str]
    verified_fields: Dict[str, Any] # validated user fields (amount, etc.)
    derived_flags: Dict[str, bool]  # system-derived flags
    stripped_fields: List[str]      # fields removed from user input
    context_build_log: List[str]    # steps taken during context construction
    built_at: int                   # epoch ms

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OverrideRequest:
    """Structured override request — NOT a boolean."""
    requested_by: str               # actor_id
    role: str                       # actor_role at time of override
    reason: str                     # mandatory justification
    target_decision: str            # original decision being overridden
    requires_dual_approval: bool    # True for high-risk operations
    approved_by: Optional[str]      # second approver actor_id (if dual approval)
    approved_at: Optional[int]      # epoch ms
    created_at: int                 # epoch ms

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TrustedExecutionTrace:
    """Complete end-to-end trace across all 5 layers (0–4)."""
    auth_identity: Dict[str, Any]
    trusted_context: Dict[str, Any]
    decision_trace: Dict[str, Any]
    operator_response: Dict[str, Any]
    firewall_result: Optional[Dict[str, Any]]
    override_result: Optional[Dict[str, Any]]
    execution_result: Dict[str, Any]
    connector_result: Optional[Dict[str, Any]]
    mode: str
    safety_report: Optional[Dict[str, Any]]
    idempotency_key: str
    override_chain: List[Dict[str, Any]]
    total_latency_us: int
    pre_state_check: Optional[Dict[str, Any]] = None
    post_execution_confirmation: Optional[Dict[str, Any]] = None
    external_guarantee: str = "UNKNOWN"
    compensation_assessment: Optional[Dict[str, Any]] = None
    state_version_info: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ExternalGuarantee(str, Enum):
    CONFIRMED = "CONFIRMED"
    ACCEPTED_NOT_CONFIRMED = "ACCEPTED_NOT_CONFIRMED"
    PRECONDITION_FAILED = "PRECONDITION_FAILED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


@dataclass
class StateCheckResult:
    state_ok: bool
    observed_state: Dict[str, Any]
    violations: List[str]
    state_version: Optional[str]
    checked_at: int
    connector: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ConfirmationResult:
    confirmed: bool
    confirmation_source: str
    observed_outcome: Dict[str, Any]
    discrepancies: List[str]
    confirmed_at: int
    read_failed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CompensationAssessment:
    compensation_required: bool
    manual_review: bool
    externally_inconsistent: bool
    action: str
    reason: str
    assessed_at: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

# ── Tenant Registry ──────────────────────────────────────────────────────────


@dataclass
class TenantRecord:
    """A registered tenant with API key credentials."""
    tenant_id: str
    tenant_name: str
    api_key_hash: str
    api_key_raw: str           # stored only at registration, used for return
    actors: List[Dict[str, str]]
    created_at: int
    secret: str                # HMAC secret for this tenant


@dataclass
class ActorRecord:
    """An actor within a tenant."""
    actor_id: str
    actor_role: str
    tenant_id: str
    token_secret: str          # secret used for token HMAC


@dataclass
class TokenRecord:
    """A token associated with an actor."""
    token_secret: str
    actor_id: str
    tenant_id: str
    actor_role: str
    created_at: int


# ═══════════════════════════════════════════════════════════════════════════════
# LAYER 1 — vNext.5: Decision Engine (inline — UNCHANGED CORE)
# Deterministic intent classification using rule-based pattern matching
# ═══════════════════════════════════════════════════════════════════════════════

class Decision(str, Enum):
    PROCEED = "PROCEED"
    GATE = "GATE"
    REFUSE = "REFUSE"
    EXPLORE = "EXPLORE"


class Domain(str, Enum):
    FINANCIAL = "FINANCIAL"
    DATA = "DATA"
    ACCESS = "ACCESS"
    UNKNOWN = "UNKNOWN"


# Truth anchor levels for compliance checks
TRUTH_ANCHORS: Dict[str, int] = {
    "L1_compliance": 1,
    "L2_policy": 2,
    "L3_fully_bound": 3,
}

# ── Intent pattern definitions ──────────────────────────────────────────────
_INTENT_PATTERNS: List[Dict[str, Any]] = [
    {
        "intent": "refund",
        "domain": Domain.FINANCIAL,
        "action": "REFUND",
        "patterns": [
            r"\brefund\b", r"\breturn\s+(?:my\s+)?money\b",
            r"\bgive\s+(?:me\s+)?(?:my\s+)?(?:money|cash)\s+back\b",
            r"\breverse\s+(?:the\s+)?(?:payment|charge|transaction)\b",
            r"\bcancel\s+(?:and\s+)?(?:the\s+)?(?:payment|charge|order)\b",
        ],
        "decision": Decision.PROCEED,
        "confidence": 92,
        "truth_anchor": "L3_fully_bound",
        "required_fields": ["amount", "payment_intent_id"],
        "risk_flags": ["financial_outbound"],
    },
    {
        "intent": "transfer",
        "domain": Domain.FINANCIAL,
        "action": "TRANSFER",
        "patterns": [
            r"\btransfer\b", r"\bsend\s+money\b",
            r"\bmove\s+(?:funds?|money)\b",
            r"\bpay\s+(?:someone|to)\b",
        ],
        "decision": Decision.GATE,
        "confidence": 85,
        "truth_anchor": "L2_policy",
        "required_fields": ["amount", "recipient", "recipient_account"],
        "risk_flags": ["financial_outbound", "new_recipient"],
    },
    {
        "intent": "data_access",
        "domain": Domain.DATA,
        "action": "QUERY",
        "patterns": [
            r"\b(?:show|view|see|get|list|retrieve|fetch|access)\b.*\b(?:my\s+)?data\b",
            r"\bwhat\s+data\b", r"\bdata\s+(?:about|on|for)\s+(?:me|my)\b",
            r"\bGDPR\s+access\b", r"\bsubject\s+access\s+request\b",
        ],
        "decision": Decision.PROCEED,
        "confidence": 95,
        "truth_anchor": "L3_fully_bound",
        "required_fields": ["data_type", "user_id"],
        "risk_flags": ["data_read"],
    },
    {
        "intent": "data_delete",
        "domain": Domain.DATA,
        "action": "DELETE",
        "patterns": [
            r"\b(?:delete|remove|erase|destroy|purge)\b.*\b(?:my\s+)?data\b",
            r"\bforget\s+me\b", r"\bright\s+to\s+(?:be\s+)?forgotten\b",
            r"\berase\s+(?:all\s+)?(?:my\s+)?(?:data|records?|information)\b",
        ],
        "decision": Decision.GATE,
        "confidence": 78,
        "truth_anchor": "L1_compliance",
        "required_fields": ["data_type", "user_id", "confirmation"],
        "risk_flags": ["data_destructive", "gdpr_article_17"],
    },
    {
        "intent": "permission_change",
        "domain": Domain.ACCESS,
        "action": "MODIFY",
        "patterns": [
            r"\b(?:change|update|modify|set|grant|revoke)\b.*\b(?:permissions?|access|role)\b",
            r"\b(?:elevate|promote|demote)\b.*\b(?:role|privilege|access)\b",
            r"\bgive\s+(?:me\s+)?(?:admin|manager|root)\b",
        ],
        "decision": Decision.REFUSE,
        "confidence": 70,
        "truth_anchor": "L1_compliance",
        "required_fields": ["target_user", "new_role", "justification"],
        "risk_flags": ["privilege_escalation"],
    },
]


@dataclass
class DecisionResult:
    """Output of the vNext.5 decision engine."""
    decision: str
    confidence: int
    triggers: List[str]
    truth_anchor_level: str
    domain: str
    action: str
    risk_flags: List[str]
    required_fields: List[str]
    missing_fields: List[str]
    trace_id: str
    timestamp: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ═══════════════════════════════════════════════════════════════════════════════
# LAYER 2 — vNext.6: Completion Engine (inline — UNCHANGED CORE)
# Wraps DecisionResult into operator-friendly structured response
# ═══════════════════════════════════════════════════════════════════════════════

_REASON_TEMPLATES: Dict[str, str] = {
    "PROCEED": "Request approved. {action} on {domain} is permitted for execution.",
    "GATE": "Request gated. {action} on {domain} requires additional information or override approval.",
    "REFUSE": "Request refused. {action} on {domain} is not permitted under current policy.",
    "EXPLORE": "Request unclear. Please clarify your intent so we can assist you.",
}


@dataclass
class OperatorResponse:
    """Enriched, operator-friendly response wrapping a DecisionResult."""
    trace_id: str
    decision: str
    domain: str
    action: str
    confidence: int
    operator_message: str
    required_fields: List[str]
    missing_fields: List[str]
    suggested_inputs: Dict[str, str]
    next_actions: List[str]
    risk_flags: List[str]
    structured_prompt: str
    auto_fix: Dict[str, str]
    decision_summary: str
    timestamp: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ═══════════════════════════════════════════════════════════════════════════════
# LAYER 3 — vNext.7: Execution Guard + Mock Adapters (inline — UNCHANGED CORE)
# ═══════════════════════════════════════════════════════════════════════════════

class ExecutionStatus(str, Enum):
    SUCCESS = "success"
    BLOCKED = "blocked"
    FAILED = "failed"
    DRY_RUN = "dry_run"


@dataclass
class ExecutionResult:
    """Result from an adapter execution attempt."""
    status: str
    action_taken: str
    system: str
    timestamp: int
    trace_id: str
    details: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutionTrace:
    """Links decision → operator response → execution result."""
    trace_id: str
    raw_text: str
    context: Dict[str, Any]
    operator_response: Dict[str, Any]
    execution_result: Optional[Dict[str, Any]]
    total_latency_us: int
    override_used: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ═══════════════════════════════════════════════════════════════════════════════
# LAYER 4 — vNext.8: Live Integration Layer (inline — UNCHANGED CORE)
# Connectors, Safety Envelope, Idempotency, Mode Control
# ═══════════════════════════════════════════════════════════════════════════════

class ExecutionMode(str, Enum):
    MOCK = "MOCK"
    SANDBOX = "SANDBOX"
    LIVE = "LIVE"


class SafetyDecision(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"


@dataclass
class SafetyReport:
    """Result of safety envelope validation."""
    pass_fail: str
    safety_decision: str
    violations: List[str]
    warnings: List[str]
    checked_at: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ConnectorResult:
    """Result from a live (or mock) connector execution."""
    status: str
    external_id: Optional[str]
    system: str
    timestamp: int
    trace_id: str
    live_mode: bool
    details: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FullExecutionTrace:
    """Complete end-to-end trace across all 4 layers (vNext.8)."""
    decision_trace: Dict[str, Any]
    operator_response: Dict[str, Any]
    execution_result: Dict[str, Any]
    connector_result: Optional[Dict[str, Any]]
    mode: str
    safety_report: Optional[Dict[str, Any]]
    idempotency_key: str
    pre_state_check: Optional[Dict[str, Any]] = None
    post_execution_confirmation: Optional[Dict[str, Any]] = None
    external_guarantee: str = "UNKNOWN"
    compensation_assessment: Optional[Dict[str, Any]] = None
    state_version_info: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class StatefulConnector(ABC):
    """Three-phase connector: precheck → execute → confirm.

    Replaces vNext.9's two-phase BaseConnector (execute only).
    Each phase reads from the real external system (or StateStore
    in MOCK mode).
    """

    @abstractmethod
    def precheck(self, trusted_context: Dict[str, Any]) -> StateCheckResult:
        """Read external state BEFORE execution. Return what was observed."""
        ...

    @abstractmethod
    def execute(self, trusted_context: Dict[str, Any],
                idempotency_key: str, trace_id: str,
                pre_state_check: Optional[StateCheckResult] = None) -> ConnectorResult:
        """Perform the action. Return what the external system claims."""
        ...

    @abstractmethod
    def confirm(self, trusted_context: Dict[str, Any],
                connector_result: ConnectorResult,
                pre_state_check: StateCheckResult) -> ConfirmationResult:
        """Re-read external state AFTER execution. Detect reality gaps."""
        ...

    @abstractmethod
    def health_check(self) -> Dict[str, Any]:
        ...


class IntegrityTraceDelta:
    """Only the NEW fields added to the trace (extends vNext.9 FullExecutionTrace).

    Integration: add these fields to IntegrityExecutionTrace dataclass.
    """

    pre_state_check: Optional[Dict[str, Any]] = None
    post_execution_confirmation: Optional[Dict[str, Any]] = None
    external_guarantee: str = ExternalGuarantee.UNKNOWN.value
    compensation_assessment: Optional[Dict[str, Any]] = None
    state_version_info: Optional[Dict[str, Any]] = None

    @staticmethod
    def build_version_info(pre_state_check: StateCheckResult,
                           confirmation: ConfirmationResult) -> Dict[str, Any]:
        pre_v = pre_state_check.state_version
        expected_post = str(int(pre_v) + 1) if pre_v is not None else None
        # Extract observed version from confirm's observed_outcome (if available)
        observed_post = None
        if not confirmation.read_failed and confirmation.observed_outcome:
            observed_post = confirmation.observed_outcome.get("version")
        return {
            "pre_version": pre_v,
            "expected_post_version": expected_post,
            "observed_post_version": observed_post,
        }
