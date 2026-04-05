from __future__ import annotations
import base64
import hashlib
import hmac
import json
import logging
import re
import threading
import time
import uuid
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from .base import (
    _logger, _STRIPE_AVAILABLE,
    AuthIdentity, TrustedContext, OverrideRequest, TrustedExecutionTrace,
    ExternalGuarantee, Decision, Domain, ExecutionMode, ExecutionStatus,
    SafetyDecision, StateCheckResult, ConfirmationResult, CompensationAssessment,
    ConnectorResult, ExecutionResult, ExecutionTrace, OperatorResponse,
    SafetyReport, TenantRecord, ActorRecord, TokenRecord,
    DecisionResult, TRUTH_ANCHORS, _INTENT_PATTERNS, _REASON_TEMPLATES,
)
from .idempotency import DeterministicIdempotency
from .context_builder import TrustedContextBuilder
from .firewall import ContextFirewall
from .override import OverrideGovernance
from .state_store import StateStore
from .router import ConnectorRouter, AdapterRouter
from .stripe import StripeConnector
from .database import DatabaseConnector


class TenantRegistry:
    """In-memory multi-tenant registry with API key and token management.

    Production would use a database. This implementation uses in-memory
    dicts protected by a threading lock.
    """

    def __init__(self) -> None:
        self._api_keys: Dict[str, TenantRecord] = {}     # api_key_hash → TenantRecord
        self._api_key_raw_map: Dict[str, str] = {}       # api_key_raw → api_key_hash
        self._tokens: Dict[str, TokenRecord] = {}        # token_secret → TokenRecord
        self._actors: Dict[str, ActorRecord] = {}        # actor_id → ActorRecord
        self._lock = threading.Lock()

    def _hash_key(self, api_key: str, tenant_secret: str) -> str:
        """HMAC-SHA256 hash of API key with tenant secret."""
        return hmac.new(
            tenant_secret.encode("utf-8"),
            api_key.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def register_tenant(
        self, tenant_id: str, tenant_name: str, secret: str,
        api_key: Optional[str] = None, actors: Optional[List[Dict[str, str]]] = None,
    ) -> TenantRecord:
        """Register a new tenant. Generates API key if not provided.

        Args:
            tenant_id: Unique tenant identifier (e.g. "tenant_acme")
            tenant_name: Human-readable name
            secret: HMAC secret for this tenant
            api_key: Optional pre-generated API key
            actors: Optional list of {"actor_id": ..., "actor_role": ...} dicts

        Returns:
            TenantRecord with the generated API key
        """
        if api_key is None:
            api_key = f"sw_{tenant_id}_{uuid.uuid4().hex}"

        with self._lock:
            key_hash = self._hash_key(api_key, secret)
            record = TenantRecord(
                tenant_id=tenant_id,
                tenant_name=tenant_name,
                api_key_hash=key_hash,
                api_key_raw=api_key,
                actors=actors or [],
                created_at=int(time.time() * 1000),
                secret=secret,
            )
            self._api_keys[key_hash] = record
            self._api_key_raw_map[api_key] = key_hash

            # Register actors if provided
            for actor_def in (actors or []):
                actor_id = actor_def["actor_id"]
                actor_role = actor_def["actor_role"]
                token_secret = f"tok_{tenant_id}_{actor_id}_{uuid.uuid4().hex}"
                actor_record = ActorRecord(
                    actor_id=actor_id,
                    actor_role=actor_role,
                    tenant_id=tenant_id,
                    token_secret=token_secret,
                )
                self._actors[actor_id] = actor_record
                self._tokens[token_secret] = TokenRecord(
                    token_secret=token_secret,
                    actor_id=actor_id,
                    tenant_id=tenant_id,
                    actor_role=actor_role,
                    created_at=int(time.time() * 1000),
                )

            return record

    def register_actor(self, tenant_id: str, actor_id: str, actor_role: str) -> Optional[ActorRecord]:
        """Register an additional actor for an existing tenant."""
        with self._lock:
            tenant = None
            for rec in self._api_keys.values():
                if rec.tenant_id == tenant_id:
                    tenant = rec
                    break
            if tenant is None:
                return None

            token_secret = f"tok_{tenant_id}_{actor_id}_{uuid.uuid4().hex}"
            actor_record = ActorRecord(
                actor_id=actor_id,
                actor_role=actor_role,
                tenant_id=tenant_id,
                token_secret=token_secret,
            )
            self._actors[actor_id] = actor_record
            self._tokens[token_secret] = TokenRecord(
                token_secret=token_secret,
                actor_id=actor_id,
                tenant_id=tenant_id,
                actor_role=actor_role,
                created_at=int(time.time() * 1000),
            )
            return actor_record

    def validate_api_key(self, api_key: str) -> Tuple[bool, Optional[TenantRecord], str]:
        """Validate an API key. Returns (valid, tenant_record, error_reason)."""
        if not api_key or not isinstance(api_key, str):
            return False, None, "api_key_missing_or_invalid"

        with self._lock:
            key_hash_lookup = self._api_key_raw_map.get(api_key)
            if key_hash_lookup is None:
                return False, None, "api_key_not_found"

            record = self._api_keys.get(key_hash_lookup)
            if record is None:
                return False, None, "api_key_tenant_not_found"

            # Re-verify HMAC to prevent hash collision attacks
            expected_hash = self._hash_key(api_key, record.secret)
            if expected_hash != key_hash_lookup:
                return False, None, "api_key_hash_mismatch"

            return True, record, ""

    def validate_token(self, token_str: str) -> Tuple[bool, Optional[AuthIdentity], str]:
        """Validate a JWT-like token (header.payload.signature).

        Structure: base64url(header) + "." + base64url(payload) + "." + signature
        signature = HMAC-SHA256(header + "." + payload, token_secret)
        """
        if not token_str or not isinstance(token_str, str):
            return False, None, "token_missing_or_invalid"

        parts = token_str.split(".")
        if len(parts) != 3:
            return False, None, "token_invalid_format"

        header_b64, payload_b64, signature = parts

        # Decode header
        try:
            header_json = base64.urlsafe_b64decode(header_b64 + "==").decode("utf-8")
            header = json.loads(header_json)
        except Exception:
            return False, None, "token_header_decode_failed"

        if header.get("alg") != "HS256":
            return False, None, "token_unsupported_algorithm"

        # Decode payload
        try:
            payload_json = base64.urlsafe_b64decode(payload_b64 + "==").decode("utf-8")
            payload = json.loads(payload_json)
        except Exception:
            return False, None, "token_payload_decode_failed"

        actor_id = payload.get("actor_id")
        tenant_id = payload.get("tenant_id")
        if not actor_id or not tenant_id:
            return False, None, "token_missing_claims"

        with self._lock:
            actor_record = self._actors.get(actor_id)
            if actor_record is None:
                return False, None, "token_actor_not_found"

            if actor_record.tenant_id != tenant_id:
                return False, None, "token_tenant_mismatch"

            token_secret = actor_record.token_secret

        # Verify signature: HMAC-SHA256(header_b64.payload_b64, token_secret)
        signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
        expected_sig = hmac.new(
            token_secret.encode("utf-8"),
            signing_input,
            hashlib.sha256,
        ).hexdigest()

        # Accept both hex and base64url encoded signatures
        sig_to_check = signature
        try:
            # Try base64url decode to see if it matches
            decoded_sig = base64.urlsafe_b64decode(signature + "==").hex()
            sig_to_check = decoded_sig
        except Exception:
            pass

        if sig_to_check != expected_sig:
            # Also try direct hex comparison
            if signature != expected_sig:
                return False, None, "token_signature_invalid"

        identity = AuthIdentity(
            actor_id=actor_id,
            actor_role=actor_record.actor_role,
            tenant_id=tenant_id,
            auth_method="TOKEN",
            authenticated_at=int(time.time() * 1000),
        )
        return True, identity, ""

    def get_actor(self, actor_id: str) -> Optional[ActorRecord]:
        """Look up an actor by ID."""
        with self._lock:
            return self._actors.get(actor_id)

    def create_token_for_actor(self, actor_id: str) -> Optional[str]:
        """Generate a JWT-like token for an actor."""
        with self._lock:
            actor = self._actors.get(actor_id)
            if actor is None:
                return None

            header = {"alg": "HS256", "typ": "SW"}
            payload = {
                "actor_id": actor.actor_id,
                "actor_role": actor.actor_role,
                "tenant_id": actor.tenant_id,
                "iat": int(time.time()),
            }

            header_b64 = base64.urlsafe_b64encode(
                json.dumps(header).encode("utf-8")
            ).rstrip(b"=").decode("utf-8")
            payload_b64 = base64.urlsafe_b64encode(
                json.dumps(payload).encode("utf-8")
            ).rstrip(b"=").decode("utf-8")

            signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
            sig = hmac.new(
                actor.token_secret.encode("utf-8"),
                signing_input,
                hashlib.sha256,
            ).hexdigest()

            token = f"{header_b64}.{payload_b64}.{sig}"
            return token

    def list_tenants(self) -> List[Dict[str, Any]]:
        """List all registered tenants (without secrets)."""
        with self._lock:
            return [
                {
                    "tenant_id": r.tenant_id,
                    "tenant_name": r.tenant_name,
                    "actors_count": len(r.actors),
                    "created_at": r.created_at,
                }
                for r in self._api_keys.values()
            ]


# ── Authentication Layer ─────────────────────────────────────────────────────


class AuthLayer:
    """Authenticates requests using API key or JWT-like token.

    Auth identity is the single source of truth for actor metadata.
    Role is ALWAYS derived from the authenticated identity — never from
    the request body.
    """

    def __init__(self, registry: Optional[TenantRegistry] = None) -> None:
        self._registry = registry or TenantRegistry()

    @property
    def registry(self) -> TenantRegistry:
        return self._registry

    def authenticate(
        self,
        api_key: Optional[str] = None,
        token: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> Tuple[bool, Optional[AuthIdentity], str]:
        """Authenticate a request.

        Priority: token > api_key. If both provided, token is used.
        If neither provided, authentication fails.

        Returns:
            (success, identity_or_none, error_reason)
        """
        # Prefer token authentication
        if token:
            valid, identity, reason = self._registry.validate_token(token)
            if valid and identity:
                # Cross-tenant check if tenant_id is specified
                if tenant_id and identity.tenant_id != tenant_id:
                    return False, None, "token_tenant_mismatch_with_request"
                _logger.info(
                    "Token auth success: actor=%s role=%s tenant=%s",
                    identity.actor_id, identity.actor_role, identity.tenant_id,
                )
                return True, identity, ""
            return False, None, reason

        # Fall back to API key authentication
        if api_key:
            valid, record, reason = self._registry.validate_api_key(api_key)
            if valid and record:
                # Cross-tenant check if tenant_id is specified
                if tenant_id and record.tenant_id != tenant_id:
                    return False, None, "api_key_tenant_mismatch_with_request"

                # For API key auth, use the first actor in the tenant
                # (or a default "service" identity)
                actor_id = record.actors[0]["actor_id"] if record.actors else "service"
                actor_role = record.actors[0]["actor_role"] if record.actors else "analyst"

                # Try to get more specific actor from registry
                actor_record = self._registry.get_actor(actor_id)
                if actor_record:
                    actor_role = actor_record.actor_role

                identity = AuthIdentity(
                    actor_id=actor_id,
                    actor_role=actor_role,
                    tenant_id=record.tenant_id,
                    auth_method="API_KEY",
                    authenticated_at=int(time.time() * 1000),
                )
                _logger.info(
                    "API key auth success: actor=%s role=%s tenant=%s",
                    identity.actor_id, identity.actor_role, identity.tenant_id,
                )
                return True, identity, ""
            return False, None, reason

        return False, None, "no_auth_credentials_provided"


class DecisionEngine:
    """Deterministic rule-based intent classifier and decision maker.

    Pattern matching over canonicalised input produces one of four
    decisions: PROCEED, GATE, REFUSE, EXPLORE.
    No ML, no probabilities — pure string matching against known patterns.
    """

    def classify(self, raw_text: str, context: Optional[Dict[str, Any]] = None) -> DecisionResult:
        ctx = context or {}
        text_lower = raw_text.lower().strip()
        trace_id = f"SW-{uuid.uuid4().hex[:16].upper()}"
        timestamp = int(time.time() * 1000)

        best_match: Optional[Dict[str, Any]] = None
        best_score = 0

        for pattern_def in _INTENT_PATTERNS:
            score = 0
            matched_triggers: List[str] = []
            for pat in pattern_def["patterns"]:
                m = re.search(pat, text_lower, re.IGNORECASE)
                if m:
                    score += 1
                    matched_triggers.append(m.group(0))

            if ctx.get("domain", "").upper() == pattern_def["domain"].value:
                score += 2

            if score > best_score:
                best_score = score
                best_match = {**pattern_def, "_matched_triggers": matched_triggers}

        if best_match is None or best_score == 0:
            return DecisionResult(
                decision=Decision.EXPLORE.value,
                confidence=30,
                triggers=[],
                truth_anchor_level="L1_compliance",
                domain=Domain.UNKNOWN.value,
                action="CLARIFY",
                risk_flags=["unknown_intent"],
                required_fields=[],
                missing_fields=["intent"],
                trace_id=trace_id,
                timestamp=timestamp,
            )

        provided = set(ctx.keys())
        required = set(best_match["required_fields"])
        missing = list(required - provided)

        decision = best_match["decision"]
        if missing:
            if decision == Decision.PROCEED.value:
                decision = Decision.GATE.value

        return DecisionResult(
            decision=decision,
            confidence=best_match["confidence"],
            triggers=best_match.get("_matched_triggers", []),
            truth_anchor_level=best_match["truth_anchor"],
            domain=best_match["domain"].value,
            action=best_match["action"],
            risk_flags=list(best_match["risk_flags"]),
            required_fields=best_match["required_fields"],
            missing_fields=missing,
            trace_id=trace_id,
            timestamp=timestamp,
        )


class DecisionCompletionEngine:
    """Enriches a DecisionResult into a full OperatorResponse."""

    _FIELD_SUGGESTIONS: Dict[str, str] = {
        "amount": "e.g. 150.00 (GBP)",
        "payment_intent_id": "e.g. pi_3abcdef123456",
        "recipient": "e.g. account-holder-name",
        "recipient_account": "e.g. GB29 NWBK 6016 1331 9268 19",
        "data_type": "e.g. personal, transaction, account",
        "user_id": "e.g. usr_12345678",
        "confirmation": "Type 'I confirm' to proceed",
        "target_user": "e.g. usr_target_001",
        "new_role": "e.g. viewer, analyst, manager",
        "justification": "e.g. Project X access required until 2025-12-31",
    }

    def complete(self, decision: DecisionResult) -> OperatorResponse:
        template = _REASON_TEMPLATES.get(decision.decision, "Decision: {decision}")
        operator_message = template.format(
            action=decision.action, domain=decision.domain,
            decision=decision.decision,
        )

        suggested_inputs = {
            f: self._FIELD_SUGGESTIONS.get(f, "please provide this field")
            for f in decision.missing_fields
        }

        match decision.decision:
            case "PROCEED":
                next_actions = ["Execute request", "Review risk flags", "Confirm with customer"]
            case "GATE":
                next_actions = (
                    [f"Provide: {f}" for f in decision.missing_fields]
                    + ["Request override if applicable", "Escalate to manager"]
                )
            case "REFUSE":
                next_actions = ["Review policy", "Contact compliance team", "Submit formal appeal"]
            case "EXPLORE":
                next_actions = ["Clarify intent", "Provide more details", "Contact support"]
            case _:
                next_actions = ["Contact administrator"]

        auto_fix: Dict[str, str] = {}
        if "currency" in decision.missing_fields:
            auto_fix["currency"] = "GBP (UK jurisdiction default)"
        if "country" in decision.missing_fields:
            auto_fix["country"] = "GB (UK jurisdiction default)"

        structured_prompt = (
            f"[SignalWeaver] Decision: {decision.decision} | "
            f"Domain: {decision.domain} | Action: {decision.action} | "
            f"Confidence: {decision.confidence}% | "
            f"Risk: {', '.join(decision.risk_flags) or 'none'} | "
            f"Missing: {', '.join(decision.missing_fields) or 'none'}"
        )

        decision_summary = (
            f"{decision.decision}/{decision.domain}/{decision.action}"
            f" (conf={decision.confidence}%, anchor={decision.truth_anchor_level})"
        )

        return OperatorResponse(
            trace_id=decision.trace_id,
            decision=decision.decision,
            domain=decision.domain,
            action=decision.action,
            confidence=decision.confidence,
            operator_message=operator_message,
            required_fields=decision.required_fields,
            missing_fields=decision.missing_fields,
            suggested_inputs=suggested_inputs,
            next_actions=next_actions,
            risk_flags=decision.risk_flags,
            structured_prompt=structured_prompt,
            auto_fix=auto_fix,
            decision_summary=decision_summary,
            timestamp=int(time.time() * 1000),
        )


class ExecutionGuard:
    """Deterministic gate between decision and execution.

    PROCEED -> allowed | GATE -> blocked unless override
    REFUSE / EXPLORE -> hard block, never allowed.
    """

    @staticmethod
    def check(operator_response: OperatorResponse, override: bool = False) -> Tuple[bool, str]:
        match operator_response.decision:
            case "PROCEED":
                return True, "execution_allowed_by_proceed_decision"
            case "GATE":
                if override:
                    return True, "execution_allowed_by_override_gate"
                return False, "execution_blocked_gate_requires_override"
            case "REFUSE":
                return False, "execution_hard_blocked_refuse_decision"
            case "EXPLORE":
                return False, "execution_blocked_explore_requires_clarification"
            case _:
                return False, f"execution_blocked_unknown_decision_{operator_response.decision}"


class SafetyEnvelope:
    """Deterministic safety validation before any real execution."""

    ADVERSARIAL_FLAGS: FrozenSet[str] = frozenset({
        "adversarial_injection", "prompt_injection", "privilege_escalation",
        "sql_injection", "data_exfiltration",
    })

    REFUND_CAP = 10000

    LIVE_BLOCKED_ACTIONS: FrozenSet[str] = frozenset({
        "DELETE",
    })

    def validate(
        self,
        execution_trace: ExecutionTrace,
        mode: ExecutionMode,
        context: Dict[str, Any],
    ) -> SafetyReport:
        violations: List[str] = []
        warnings: List[str] = []
        op = execution_trace.operator_response
        ts = int(time.time() * 1000)

        if op["decision"] != "PROCEED":
            violations.append(f"decision_not_proceed: {op['decision']}")

        risk_flags = op.get("risk_flags", [])
        for flag in risk_flags:
            if flag in self.ADVERSARIAL_FLAGS:
                violations.append(f"adversarial_flag_detected: {flag}")

        missing = op.get("missing_fields", [])
        if missing:
            violations.append(f"missing_required_fields: {', '.join(missing)}")

        if execution_trace.override_used and op["decision"] != "GATE":
            violations.append(
                f"override_misuse: override=True but decision={op['decision']} "
                f"(override only valid for GATE decisions)"
            )

        if op.get("action") == "REFUND":
            amount = context.get("amount", 0)
            if isinstance(amount, (int, float)) and amount > self.REFUND_CAP:
                violations.append(
                    f"refund_exceeds_cap: {amount:,.2f} > {self.REFUND_CAP:,.2f}"
                )

        if mode == ExecutionMode.LIVE:
            if op.get("action") in self.LIVE_BLOCKED_ACTIONS:
                violations.append(
                    f"action_blocked_in_live_mode: {op['action']} "
                    f"(destructive operations require manual approval)"
                )
            currency = context.get("currency", "GBP")
            if currency.upper() != "GBP":
                violations.append(
                    f"currency_not_gbp_in_live: {currency} (UK jurisdiction requires GBP)"
                )

        pass_fail = "pass" if not violations else "fail"
        safety = SafetyDecision.ALLOW.value if pass_fail == "pass" else SafetyDecision.BLOCK.value

        return SafetyReport(
            pass_fail=pass_fail,
            safety_decision=safety,
            violations=violations,
            warnings=warnings,
            checked_at=ts,
        )


class TraceStore:
    """Thread-safe in-memory store for trace records."""

    MAX_CAPACITY = 10_000

    def __init__(self) -> None:
        self._traces: Dict[str, Any] = {}
        self._lock = threading.Lock()

    def store(self, trace_id: str, trace: Any) -> None:
        with self._lock:
            if len(self._traces) >= self.MAX_CAPACITY:
                oldest_key = next(iter(self._traces))
                del self._traces[oldest_key]
                _logger.warning("TraceStore evicted oldest trace (capacity=%d)", self.MAX_CAPACITY)
            self._traces[trace_id] = trace

    def get(self, trace_id: str) -> Optional[Any]:
        with self._lock:
            return self._traces.get(trace_id)

    def health(self) -> Dict[str, Any]:
        with self._lock:
            return {"stored_traces": len(self._traces), "max_capacity": self.MAX_CAPACITY}


# ================================================================
# vNext.10: Three-phase guarantee classification + compensation
# ================================================================

def classify_guarantee(
    state_check: StateCheckResult,
    connector_result: ConnectorResult,
    confirmation: ConfirmationResult,
) -> ExternalGuarantee:
    """Deterministic guarantee classification (pure function)."""
    if not state_check.state_ok:
        return ExternalGuarantee.PRECONDITION_FAILED
    if connector_result.status in ("blocked", "failed"):
        return ExternalGuarantee.REJECTED
    if confirmation.confirmed:
        return ExternalGuarantee.CONFIRMED
    if connector_result.status == "success" and not confirmation.confirmed:
        return ExternalGuarantee.ACCEPTED_NOT_CONFIRMED
    return ExternalGuarantee.UNKNOWN

def assess_compensation(
    state_check: StateCheckResult,
    connector_result: ConnectorResult,
    confirmation: ConfirmationResult,
    guarantee: ExternalGuarantee,
) -> CompensationAssessment:
    """Deterministic compensation logic (pure function)."""
    ts = int(time.time() * 1000)

    if not state_check.state_ok:
        return CompensationAssessment(
            True, False, False, "BLOCK_RETRIES",
            "precondition_failed: " + "; ".join(state_check.violations), ts,
        )

    if connector_result.status in ("blocked", "failed"):
        error = connector_result.details.get("error", "")
        if "already_refunded" in error:
            return CompensationAssessment(
                True, False, False, "BLOCK_RETRIES",
                "connector_rejected_already_refunded", ts,
            )
        return CompensationAssessment(
            True, True, False, "MANUAL_REVIEW",
            f"connector_failed: status={connector_result.status} error={error}", ts,
        )

    if not confirmation.confirmed:
        if confirmation.discrepancies:
            return CompensationAssessment(
                True, True, True, "MANUAL_REVIEW",
                "confirmation_discrepancy: " + "; ".join(confirmation.discrepancies), ts,
            )
        return CompensationAssessment(
            True, False, True, "MARK_INCONSISTENT",
            "confirmation_failed_no_discrepancies", ts,
        )

    return CompensationAssessment(
        False, False, False, "NONE", "execution_confirmed", ts,
    )


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


# ═══════════════════════════════════════════════════════════════════════════════
# vNext.9: Trusted Orchestrator — Full Pipeline with Trust Boundary
# ═══════════════════════════════════════════════════════════════════════════════

class TrustedOrchestrator:
    """vNext.9 orchestrator with full trust boundary layer.

    Pipeline:
      auth → context_build → decision → firewall → override → guard → safety → connector

    The orchestrator ensures:
      - Role ALWAYS comes from authenticated identity, never request body
      - Override is a structured request with audit trail, not a boolean
      - Idempotency keys are deterministic (same actor + request = same key)
      - Context firewall validates all fields against domain-specific schema
      - Every step produces an auditable log entry
    """

    def __init__(
        self,
        mode: ExecutionMode = ExecutionMode.MOCK,
        db_path: Optional[str] = None,
        registry: Optional[TenantRegistry] = None,
    ) -> None:
        self._mode = mode
        self._auth = AuthLayer(registry or TenantRegistry())
        self._context_builder = TrustedContextBuilder()
        self._firewall = ContextFirewall()
        self._override_gov = OverrideGovernance()
        self._idempotency = DeterministicIdempotency()

        # vNext.5/6/7/8 components (unchanged core)
        self._engine = DecisionEngine()
        self._completion = DecisionCompletionEngine()
        self._guard = ExecutionGuard()
        self._safety = SafetyEnvelope()
        self._state_store = StateStore()
        self._connector_router = ConnectorRouter(mode, db_path=db_path, state_store=self._state_store)
        self._trace_store = TraceStore()

    @property
    def mode(self) -> ExecutionMode:
        return self._mode

    @property
    def trace_store(self) -> TraceStore:
        return self._trace_store

    @property
    def registry(self) -> TenantRegistry:
        return self._auth.registry

    def execute(
        self,
        raw_text: str,
        context: Optional[Dict[str, Any]] = None,
        override_request: Optional[OverrideRequest] = None,
        api_key: Optional[str] = None,
        token: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> TrustedExecutionTrace:
        """Full pipeline with trust boundary.

        Args:
            raw_text: Natural language request
            context: Raw request body from user (will be validated/sanitised)
            override_request: Structured override request (if applicable)
            api_key: API key for authentication
            token: JWT-like token for authentication
            tenant_id: Optional tenant ID for cross-tenant validation

        Returns:
            TrustedExecutionTrace with full audit trail across all layers
        """
        pipeline_start = time.perf_counter()
        ctx = context or {}
        override_chain: List[Dict[str, Any]] = []

        # ── Step 0: Authentication ────────────────────────────────────────
        auth_ok, identity, auth_error = self._auth.authenticate(
            api_key=api_key, token=token, tenant_id=tenant_id,
        )

        if not auth_ok:
            return self._build_auth_failure_trace(
                raw_text, ctx, auth_error, pipeline_start,
            )

        # ── Step 1: Build Trusted Context ─────────────────────────────────
        trusted_ctx, build_errors = self._context_builder.build(ctx, identity)

        if build_errors:
            return self._build_context_failure_trace(
                identity, trusted_ctx, raw_text, ctx, build_errors, pipeline_start,
            )

        # ── Step 2: Run Decision Engine with VERIFIED fields only ─────────
        # CRITICAL: Feed only verified_fields to the engine, never raw context.
        # This prevents any spoofed fields from reaching the core logic.
        decision_context = {
            **trusted_ctx.verified_fields,
            "domain": trusted_ctx.verified_fields.get("domain", ""),
        }
        decision = self._engine.classify(raw_text, decision_context)

        # Update request_type in trusted context
        trusted_ctx.request_type = f"{decision.domain}/{decision.action}"

        # ── Step 3: Context Firewall (domain-specific validation) ──────────
        firewall_passed, firewall_violations = self._firewall.validate(
            trusted_ctx, decision.domain,
        )
        firewall_result = {
            "passed": firewall_passed,
            "violations": firewall_violations,
            "domain": decision.domain,
        }

        if not firewall_passed:
            return self._build_firewall_failure_trace(
                identity, trusted_ctx, decision, firewall_result,
                raw_text, ctx, pipeline_start,
            )

        # ── Step 4: Override Governance ───────────────────────────────────
        override_used = False
        override_result = None

        if override_request is not None:
            override_valid, override_violations = self._override_gov.validate_override(
                override_request, identity,
            )
            override_result = {
                "valid": override_valid,
                "violations": override_violations,
                "request": override_request.to_dict(),
            }
            override_chain.append(override_request.to_dict())

            if not override_valid:
                return self._build_override_failure_trace(
                    identity, trusted_ctx, decision, firewall_result,
                    override_result, raw_text, ctx, pipeline_start,
                )
            override_used = True

        # ── Step 5: Decision Completion (vNext.6) ─────────────────────────
        operator_response = self._completion.complete(decision)

        # ── Step 6: Execution Guard (vNext.7) ────────────────────────────
        guard_allowed, guard_reason = self._guard.check(operator_response, override_used)

        execution_result: Optional[ExecutionResult] = None

        if not guard_allowed:
            execution_result = ExecutionResult(
                status="blocked", action_taken="none", system="execution_guard",
                timestamp=int(time.time() * 1000), trace_id=decision.trace_id,
                details={"reason": guard_reason, "decision": operator_response.decision},
            )
        else:
            # ── Step 7: Safety Envelope (vNext.8) ─────────────────────────
            # Build execution context with identity-derived role
            exec_context = {
                **trusted_ctx.verified_fields,
                "role": identity.actor_role,  # From TRUSTED source
            }
            exec_trace = ExecutionTrace(
                trace_id=decision.trace_id, raw_text=raw_text, context=exec_context,
                operator_response=operator_response.to_dict(),
                execution_result=None, total_latency_us=0, override_used=override_used,
            )
            safety_report = self._safety.validate(exec_trace, self._mode, exec_context)

            if safety_report.safety_decision == SafetyDecision.BLOCK.value:
                execution_result = ExecutionResult(
                    status="blocked", action_taken="none", system="safety_envelope",
                    timestamp=int(time.time() * 1000), trace_id=decision.trace_id,
                    details={"reason": "safety_envelope_block",
                             "violations": safety_report.violations},
                )
            else:
                # ── Step 8: Deterministic Idempotency Key ─────────────────
                idem_key = DeterministicIdempotency.make_key(
                    raw_text=raw_text,
                    actor_id=identity.actor_id,
                    domain=decision.domain,
                    action=decision.action,
                    amount=trusted_ctx.verified_fields.get("amount"),
                    recipient=trusted_ctx.verified_fields.get("recipient"),
                    tenant_id=identity.tenant_id,
                )

                # ── Step 9: Connector Resolution (vNext.10 three-phase) ───
                connector = self._connector_router.resolve(decision.domain)

                if connector is None:
                    # No stateful connector for this domain — fall back to
                    # vNext.9 mock-only path (preserves ACCESS domain behaviour)
                    mock_router = AdapterRouter()
                    mock_result = mock_router.route(operator_response, exec_context)
                    execution_result = mock_result
                    connector_result = ConnectorResult(
                        status=mock_result.status,
                        external_id=mock_result.details.get("refund_id")
                                      or mock_result.details.get("query_id"),
                        system=mock_result.system,
                        timestamp=mock_result.timestamp,
                        trace_id=mock_result.trace_id,
                        live_mode=False,
                        details=mock_result.details,
                    )
                    is_dup, cached = self._idempotency.check_and_store(
                        idem_key, connector_result)
                    if is_dup and cached is not None:
                        connector_result = cached
                    # Sentinel so trace assembly below cannot reference undefined names
                    guarantee = ExternalGuarantee.UNKNOWN
                else:
                    # ── Step 10: PRECHECK ────────────────────────────────
                    pre_state = connector.precheck(exec_context)

                    if not pre_state.state_ok:
                        # Precondition failed — short-circuit before execution
                        blocked_result = ConnectorResult(
                            "blocked", None, pre_state.connector,
                            int(time.time() * 1000), decision.trace_id, False,
                            {"error": "precondition_failed",
                             "violations": pre_state.violations},
                        )
                        negative_confirm = ConfirmationResult(
                            False, "precondition_failed",
                            pre_state.observed_state,
                            pre_state.violations,
                            int(time.time() * 1000),
                        )
                        guarantee = classify_guarantee(
                            pre_state, blocked_result, negative_confirm)
                        comp = assess_compensation(
                            pre_state, blocked_result, negative_confirm, guarantee)

                        total_us = int((time.perf_counter() - pipeline_start) * 1_000_000)
                        trace = TrustedExecutionTrace(
                            auth_identity=identity.to_dict(),
                            trusted_context=trusted_ctx.to_dict(),
                            decision_trace=decision.to_dict(),
                            operator_response=operator_response.to_dict(),
                            firewall_result=firewall_result,
                            override_result=override_result,
                            execution_result=blocked_result.to_dict(),
                            connector_result=blocked_result.to_dict(),
                            mode=self._mode.value,
                            safety_report=safety_report.to_dict(),
                            idempotency_key=idem_key,
                            override_chain=override_chain,
                            total_latency_us=total_us,
                            pre_state_check=pre_state.to_dict(),
                            post_execution_confirmation=negative_confirm.to_dict(),
                            external_guarantee=guarantee.value,
                            compensation_assessment=comp.to_dict(),
                            state_version_info=None,
                        )
                        self._trace_store.store(decision.trace_id, trace)
                        return trace

                    # ── Step 11: EXECUTE ────────────────────────────────
                    # Add action hint for database connector
                    if decision.domain == Domain.DATA.value:
                        exec_context["_data_action"] = operator_response.action

                    connector_result = connector.execute(
                        exec_context,
                        idempotency_key=idem_key,
                        trace_id=decision.trace_id,
                        pre_state_check=pre_state,
                    )

                    # ── Step 12: CONFIRM ────────────────────────────────
                    confirmation = connector.confirm(
                        exec_context, connector_result, pre_state)

                    # ── Step 13: CLASSIFY + ASSESS ─────────────────────
                    guarantee = classify_guarantee(
                        pre_state, connector_result, confirmation)
                    comp = assess_compensation(
                        pre_state, connector_result, confirmation, guarantee)
                    version_info = IntegrityTraceDelta.build_version_info(
                        pre_state, confirmation)

                    # Check idempotency
                    is_dup, cached = self._idempotency.check_and_store(
                        idem_key, connector_result)
                    if is_dup and cached is not None:
                        connector_result = cached

                    execution_result = ExecutionResult(
                        status=connector_result.status,
                        action_taken=operator_response.action,
                        system=connector_result.system,
                        timestamp=connector_result.timestamp,
                        trace_id=connector_result.trace_id,
                        details=connector_result.details,
                    )

                total_us = int((time.perf_counter() - pipeline_start) * 1_000_000)

                trace = TrustedExecutionTrace(
                    auth_identity=identity.to_dict(),
                    trusted_context=trusted_ctx.to_dict(),
                    decision_trace=decision.to_dict(),
                    operator_response=operator_response.to_dict(),
                    firewall_result=firewall_result,
                    override_result=override_result,
                    execution_result=execution_result.to_dict(),
                    connector_result=connector_result.to_dict(),
                    mode=self._mode.value,
                    safety_report=safety_report.to_dict(),
                    idempotency_key=idem_key,
                    override_chain=override_chain,
                    total_latency_us=total_us,
                    pre_state_check=pre_state.to_dict() if connector else None,
                    post_execution_confirmation=confirmation.to_dict() if connector else None,
                    external_guarantee=guarantee.value if connector else ExternalGuarantee.UNKNOWN.value,
                    compensation_assessment=comp.to_dict() if connector else None,
                    state_version_info=version_info if connector else None,
                )
                self._trace_store.store(decision.trace_id, trace)
                _logger.info(
                    "Pipeline complete: trace=%s decision=%s connector=%s guarantee=%s latency=%dus",
                    decision.trace_id, decision.decision, connector_result.status,
                    guarantee.value if connector else "N/A", total_us,
                )
                return trace

        total_us = int((time.perf_counter() - pipeline_start) * 1_000_000)

        # Build idempotency key even for failed executions
        idem_key = DeterministicIdempotency.make_key(
            raw_text=raw_text,
            actor_id=identity.actor_id,
            domain=decision.domain,
            action=decision.action,
            amount=trusted_ctx.verified_fields.get("amount"),
            recipient=trusted_ctx.verified_fields.get("recipient"),
            tenant_id=identity.tenant_id,
        )

        trace = TrustedExecutionTrace(
            auth_identity=identity.to_dict(),
            trusted_context=trusted_ctx.to_dict(),
            decision_trace=decision.to_dict(),
            operator_response=operator_response.to_dict(),
            firewall_result=firewall_result,
            override_result=override_result,
            execution_result=execution_result.to_dict() if execution_result else None,
            connector_result=None,
            mode=self._mode.value,
            safety_report=None,
            idempotency_key=idem_key,
            override_chain=override_chain,
            total_latency_us=total_us,
        )
        self._trace_store.store(decision.trace_id, trace)
        _logger.info(
            "Pipeline blocked: trace=%s decision=%s latency=%dus",
            decision.trace_id, decision.decision, total_us,
        )
        return trace

    def _build_auth_failure_trace(
        self, raw_text: str, ctx: Dict[str, Any], error: str, start: float,
    ) -> TrustedExecutionTrace:
        """Build trace for authentication failure."""
        total_us = int((time.perf_counter() - start) * 1_000_000)
        return TrustedExecutionTrace(
            auth_identity={},
            trusted_context={},
            decision_trace={},
            operator_response={},
            firewall_result={"passed": False, "violations": ["authentication_failed"], "domain": "UNKNOWN"},
            override_result=None,
            execution_result={"status": "blocked", "action_taken": "none",
                             "system": "auth_layer", "timestamp": int(time.time() * 1000),
                             "trace_id": "", "details": {"reason": error}},
            connector_result=None,
            mode=self._mode.value,
            safety_report=None,
            idempotency_key="",
            override_chain=[],
            total_latency_us=total_us,
        )

    def _build_context_failure_trace(
        self, identity: AuthIdentity, trusted_ctx: TrustedContext,
        raw_text: str, ctx: Dict[str, Any], errors: List[str], start: float,
    ) -> TrustedExecutionTrace:
        """Build trace for context build failure."""
        total_us = int((time.perf_counter() - start) * 1_000_000)
        return TrustedExecutionTrace(
            auth_identity=identity.to_dict(),
            trusted_context=trusted_ctx.to_dict(),
            decision_trace={},
            operator_response={},
            firewall_result={"passed": False, "violations": errors, "domain": "UNKNOWN"},
            override_result=None,
            execution_result={"status": "blocked", "action_taken": "none",
                             "system": "context_builder", "timestamp": int(time.time() * 1000),
                             "trace_id": "", "details": {"reason": "context_build_failed",
                                                         "errors": errors}},
            connector_result=None,
            mode=self._mode.value,
            safety_report=None,
            idempotency_key="",
            override_chain=[],
            total_latency_us=total_us,
        )

    def _build_firewall_failure_trace(
        self, identity: AuthIdentity, trusted_ctx: TrustedContext,
        decision: DecisionResult, firewall_result: Dict[str, Any],
        raw_text: str, ctx: Dict[str, Any], start: float,
    ) -> TrustedExecutionTrace:
        """Build trace for firewall failure."""
        total_us = int((time.perf_counter() - start) * 1_000_000)
        return TrustedExecutionTrace(
            auth_identity=identity.to_dict(),
            trusted_context=trusted_ctx.to_dict(),
            decision_trace=decision.to_dict(),
            operator_response={},
            firewall_result=firewall_result,
            override_result=None,
            execution_result={"status": "blocked", "action_taken": "none",
                             "system": "context_firewall", "timestamp": int(time.time() * 1000),
                             "trace_id": decision.trace_id,
                             "details": {"reason": "firewall_violations",
                                         "violations": firewall_result["violations"]}},
            connector_result=None,
            mode=self._mode.value,
            safety_report=None,
            idempotency_key="",
            override_chain=[],
            total_latency_us=total_us,
        )

    def _build_override_failure_trace(
        self, identity: AuthIdentity, trusted_ctx: TrustedContext,
        decision: DecisionResult, firewall_result: Dict[str, Any],
        override_result: Dict[str, Any],
        raw_text: str, ctx: Dict[str, Any], start: float,
    ) -> TrustedExecutionTrace:
        """Build trace for override governance failure."""
        total_us = int((time.perf_counter() - start) * 1_000_000)
        return TrustedExecutionTrace(
            auth_identity=identity.to_dict(),
            trusted_context=trusted_ctx.to_dict(),
            decision_trace=decision.to_dict(),
            operator_response={},
            firewall_result=firewall_result,
            override_result=override_result,
            execution_result={"status": "blocked", "action_taken": "none",
                             "system": "override_governance",
                             "timestamp": int(time.time() * 1000),
                             "trace_id": decision.trace_id,
                             "details": {"reason": "override_validation_failed",
                                         "violations": override_result["violations"]}},
            connector_result=None,
            mode=self._mode.value,
            safety_report=None,
            idempotency_key="",
            override_chain=[r["request"] for r in [override_result]],
            total_latency_us=total_us,
        )
