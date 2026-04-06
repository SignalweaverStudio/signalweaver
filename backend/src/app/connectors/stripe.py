from __future__ import annotations
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple
from .base import (
    StatefulConnector, StateCheckResult, ConfirmationResult, ConnectorResult,
    ExecutionMode, _logger, _STRIPE_AVAILABLE, _stripe_lib,
)
from .state_store import StateStore


class StripeConnector(StatefulConnector):
    """Three-phase Stripe connector.

    MOCK  → reads/writes StateStore.
    SANDBOX/LIVE → reads/writes real Stripe API.
    Falls back to MOCK if Stripe credentials not configured.
    """

    REFUND_CAP = 10_000

    def __init__(
        self, mode: ExecutionMode = ExecutionMode.MOCK,
        state_store: Optional[StateStore] = None,
    ) -> None:
        self._mode = mode
        self._store = state_store or StateStore()

    # -- internal: Stripe config --

    def _configure_stripe(self) -> bool:
        if not _STRIPE_AVAILABLE:
            return False
        if self._mode == ExecutionMode.SANDBOX:
            key = os.environ.get("STRIPE_TEST_API_KEY", "")
            if not key:
                return False
            _stripe_lib.api_key = key
            return True
        if self._mode == ExecutionMode.LIVE:
            key = os.environ.get("STRIPE_LIVE_API_KEY", "")
            if not key:
                return False
            _stripe_lib.api_key = key
            return True
        return False

    @property
    def _is_real(self) -> bool:
        return self._mode != ExecutionMode.MOCK and self._configure_stripe()

    # -- Phase 1: PRECHECK --

    def precheck(self, trusted_context: Dict[str, Any]) -> StateCheckResult:
        pid = trusted_context.get("payment_intent_id", "")
        amount = trusted_context.get("amount", 0)
        ts = int(time.time() * 1000)

        if self._is_real:
            return self._precheck_real(pid, amount, ts)
        return self._precheck_mock(pid, amount, ts)

    def _precheck_mock(
        self, pid: str, amount: float, ts: int,
    ) -> StateCheckResult:
        payment = self._store.get_payment(pid)
        if payment is None:
            return StateCheckResult(
                False, {}, [f"payment_not_found: {pid}"],
                None, ts, "stripe",
            )
        violations = self._check_refundable(payment, amount)
        observed = {
            "payment_intent_id": pid,
            "status": payment["status"],
            "amount": payment["amount"],
            "refunded": payment["refunded"],
            "refund_count": payment["refund_count"],
            "refunded_amount": payment["refunded_amount"],
        }
        return StateCheckResult(
            len(violations) == 0, observed, violations,
            str(payment["version"]), ts, "stripe",
        )

    def _precheck_real(
        self, pid: str, amount: float, ts: int,
    ) -> StateCheckResult:
        try:
            pi = _stripe_lib.PaymentIntent.retrieve(pid)
            amount_refunded = pi.get("amount_refunded", 0) / 100.0
            refunded = amount_refunded > 0
            observed = {
                "payment_intent_id": pid,
                "status": pi.status,
                "amount": pi.amount / 100.0,
                "refunded": refunded,
                "refund_count": len(pi.get("refunds", {}).get("data", [])),
                "refunded_amount": amount_refunded,
                "stripe_id": pi.id,
            }
            # Stripe has no integer version counter; do not fake one
            version = None
            # Check refundable
            violations = []
            if pi.status not in ("succeeded", "requires_capture"):
                violations.append(f"payment_not_refundable: status={pi.status}")
            remaining = pi.amount / 100.0 - amount_refunded
            if amount > remaining:
                violations.append(
                    f"refund_exceeds_remaining: request={amount} remaining={remaining:.2f}"
                )
            return StateCheckResult(
                len(violations) == 0, observed, violations, version, ts, "stripe",
            )
        except Exception as exc:
            return StateCheckResult(
                False, {}, [f"stripe_retrieve_failed: {exc}"],
                None, ts, "stripe",
            )

    @staticmethod
    def _check_refundable(payment: Dict[str, Any], request_amount: float) -> List[str]:
        violations = []
        if payment["status"] not in ("succeeded", "requires_capture"):
            violations.append(f"payment_not_refundable: status={payment['status']}")
        if payment["refunded"]:
            violations.append(
                f"payment_already_refunded: refund_count={payment['refund_count']}"
            )
        remaining = payment["amount"] - payment["refunded_amount"]
        if request_amount > remaining:
            violations.append(
                f"refund_exceeds_remaining: request={request_amount} remaining={remaining:.2f}"
            )
        return violations

    # -- Phase 2: EXECUTE --

    def execute(self, trusted_context: Dict[str, Any],
                idempotency_key: str, trace_id: str,
                pre_state_check: Optional[StateCheckResult] = None) -> ConnectorResult:
        ts = int(time.time() * 1000)
        amount = trusted_context.get("amount", 0)
        pid = trusted_context.get("payment_intent_id", "")
        is_live = self._mode == ExecutionMode.LIVE

        if not isinstance(amount, (int, float)) or amount <= 0:
            return ConnectorResult(
                "failed", None, "stripe", ts, trace_id, is_live,
                {"error": "invalid_amount", "amount_provided": amount},
            )

        if amount > self.REFUND_CAP:
            return ConnectorResult(
                "blocked", None, "stripe", ts, trace_id, is_live,
                {"error": f"refund_exceeds_cap: {amount} > {self.REFUND_CAP}",
                 "amount": amount, "cap": self.REFUND_CAP},
            )

        if self._is_real:
            return self._execute_real(pid, amount, idempotency_key, trace_id, ts, is_live)
        return self._execute_mock(pid, amount, trace_id, ts)

    def _execute_mock(
        self, pid: str, amount: float, trace_id: str, ts: int,
    ) -> ConnectorResult:
        refund_id = f"re_mock_{uuid.uuid4().hex[:12]}"
        self._store.apply_refund(pid, amount, success=True)
        return ConnectorResult(
            "success", refund_id, "stripe_mock", ts, trace_id, False,
            {"refund_id": refund_id, "amount": amount, "payment_intent_id": pid},
        )

    def _execute_real(
        self, pid: str, amount: float, idempotency_key: str,
        trace_id: str, ts: int, is_live: bool,
    ) -> ConnectorResult:
        try:
            refund = _stripe_lib.Refund.create(
                payment_intent=pid,
                amount=int(amount * 100),
                idempotency_key=idempotency_key,
            )
            return ConnectorResult(
                "success", refund.id, "stripe", ts, trace_id, is_live,
                {"refund_id": refund.id, "amount": amount, "status": refund.status},
            )
        except Exception as exc:
            error_str = str(exc)
            is_already = "already_refunded" in error_str.lower()
            status = "blocked" if is_already else "failed"
            return ConnectorResult(
                status, None, "stripe", ts, trace_id, is_live,
                {"error": error_str, "already_refunded": is_already},
            )

    # -- Phase 3: CONFIRM --

    def confirm(self, trusted_context: Dict[str, Any],
                connector_result: ConnectorResult,
                pre_state_check: StateCheckResult) -> ConfirmationResult:
        ts = int(time.time() * 1000)

        if connector_result.status == "blocked":
            return ConfirmationResult(
                False, "connector_blocked",
                {"connector_status": "blocked"},
                [f"connector_status_not_success: blocked"],
                ts,
            )

        if connector_result.status == "failed":
            # Attempt confirm read anyway for audit purposes
            pid = trusted_context.get("payment_intent_id", "")
            return self._confirm_audit_read(pid, connector_result, ts)

        pid = trusted_context.get("payment_intent_id", "")
        request_amount = trusted_context.get("amount", 0)

        # Key fix: use pre_state_check to compute expected TOTAL refunded
        pre_refunded = pre_state_check.observed_state.get("refunded_amount", 0)
        expected_total = pre_refunded + request_amount

        if self._is_real:
            return self._confirm_real(
                pid, request_amount, expected_total, ts, pre_state_check, connector_result)
        return self._confirm_mock(pid, request_amount, expected_total, ts, pre_state_check)

    def _confirm_mock(
        self, pid: str, request_amount: float,
        expected_total: float, ts: int,
        pre_state_check: StateCheckResult,
    ) -> ConfirmationResult:
        payment = self._store.get_payment(pid)
        if payment is None:
            return ConfirmationResult(
                False, "direct_read",
                {"payment_found": False},
                [f"payment_disappeared_after_refund: {pid}"], ts,
            )

        actual_total = payment["refunded_amount"]
        discrepancies, tolerance_applied = self._compare_refund_totals(
            expected_total, actual_total)

        # Version mismatch detection (optimistic concurrency)
        pre_version = str(pre_state_check.state_version or "0")
        current_version = str(payment["version"])
        if current_version != str(int(pre_version) + 1):
            discrepancies.append(
                f"version_mismatch: expected={int(pre_version) + 1} "
                f"actual={current_version} (out-of-band mutation detected)"
            )

        source = "direct_read" if not discrepancies else "direct_read_with_discrepancies"
        observed: Dict[str, Any] = {
            "payment_intent_id": pid, "refunded": payment["refunded"],
            "refund_count": payment["refund_count"],
            "refunded_amount": actual_total,
            "version": payment["version"],
        }
        if tolerance_applied:
            observed["tolerance_applied"] = True
        return ConfirmationResult(
            len(discrepancies) == 0, source,
            observed, discrepancies, ts,
        )

    def _confirm_audit_read(
        self, pid: str, connector_result: ConnectorResult, ts: int,
    ) -> ConfirmationResult:
        """Read external state after connector failure for audit trail."""
        if self._is_real:
            try:
                pi = _stripe_lib.PaymentIntent.retrieve(pid)
                observed = {
                    "payment_intent_id": pid,
                    "stripe_status": pi.status,
                    "amount_refunded": pi.get("amount_refunded", 0) / 100.0,
                    "audit_read_after_failure": True,
                }
                return ConfirmationResult(
                    False, "audit_read_after_failure",
                    observed,
                    [f"connector_failed: {connector_result.details.get('error', 'unknown')}"],
                    ts,
                )
            except Exception as exc:
                return ConfirmationResult(
                    False, "audit_read_failed",
                    {"error": str(exc), "audit_read_after_failure": True},
                    [f"connector_failed_and_read_error: {exc}"],
                    ts, read_failed=True,
                )
        # MOCK: read StateStore for audit
        payment = self._store.get_payment(pid)
        if payment is None:
            return ConfirmationResult(
                False, "audit_read_after_failure",
                {"payment_found": False, "audit_read_after_failure": True},
                [f"connector_failed: {connector_result.details.get('error', 'unknown')}"],
                ts,
            )
        observed = {
            "payment_intent_id": pid, "status": payment["status"],
            "refunded_amount": payment["refunded_amount"],
            "version": payment["version"],
            "audit_read_after_failure": True,
        }
        return ConfirmationResult(
            False, "audit_read_after_failure",
            observed,
            [f"connector_failed: {connector_result.details.get('error', 'unknown')}"],
            ts,
        )

    def _confirm_real(
        self, pid: str, request_amount: float,
        expected_total: float, ts: int,
        pre_state_check: StateCheckResult,
        connector_result: ConnectorResult,
    ) -> ConfirmationResult:
        try:
            pi = _stripe_lib.PaymentIntent.retrieve(pid)
            actual_total = pi.get("amount_refunded", 0) / 100.0
            discrepancies, tolerance_applied = self._compare_refund_totals(
                expected_total, actual_total)

            # Verify specific refund object exists (not just aggregate total)
            refund_verified = False
            external_refund_id = connector_result.external_id
            if external_refund_id:
                refunds_data = pi.get("refunds", {}).get("data", [])
                refund_ids = [r.get("id") for r in refunds_data if isinstance(r, dict)]
                if external_refund_id in refund_ids:
                    refund_verified = True
                else:
                    discrepancies.append("refund_object_not_verified")

            # Aggregate match alone is NOT sufficient for CONFIRMED
            if not discrepancies and not refund_verified and external_refund_id:
                discrepancies.append("refund_object_not_verified")

            observed_outcome: Dict[str, Any] = {
                "payment_intent_id": pid, "stripe_status": pi.status,
                "amount_refunded": actual_total,
                "refund_verified": refund_verified,
                "refund_id_checked": external_refund_id,
            }
            if tolerance_applied:
                observed_outcome["tolerance_applied"] = True
            if refund_verified:
                observed_outcome["refund_ids_on_pi"] = [
                    r.get("id") for r in pi.get("refunds", {}).get("data", [])
                    if isinstance(r, dict)
                ]

            source = "direct_read" if not discrepancies else "direct_read_with_discrepancies"
            return ConfirmationResult(
                len(discrepancies) == 0, source,
                observed_outcome,
                discrepancies, ts,
            )
        except Exception as exc:
            return ConfirmationResult(
                False, "direct_read_error",
                {"error": str(exc)},
                [f"stripe_retrieve_failed_during_confirm: {exc}"],
                ts, read_failed=True,
            )

    @staticmethod
    def _compare_refund_totals(
        expected: float, actual: float, tolerance: float = 0.01,
    ) -> Tuple[List[str], bool]:
        """Returns (discrepancies, tolerance_applied)."""
        discrepancies: List[str] = []
        tolerance_applied = False
        delta = abs(actual - expected)
        if delta > tolerance:
            discrepancies.append(
                f"refund_amount_mismatch: expected_total={expected:.2f} "
                f"actual_total={actual:.2f} delta={delta:.2f}"
            )
        elif delta > 0:
            tolerance_applied = True
        return discrepancies, tolerance_applied

    def health_check(self) -> Dict[str, Any]:
        stripe_ok = _STRIPE_AVAILABLE and (
            os.environ.get("STRIPE_TEST_API_KEY") or
            os.environ.get("STRIPE_LIVE_API_KEY")
        )
        return {
            "connector": "stripe",
            "mode": self._mode.value,
            "real_stripe": self._is_real,
            "status": "ready" if (self._mode == ExecutionMode.MOCK or stripe_ok) else "degraded",
        }
