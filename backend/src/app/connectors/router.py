from __future__ import annotations
import time
import uuid
from typing import Any, Dict, FrozenSet, List, Optional, Tuple
from .base import (
    Domain, ExecutionResult, OperatorResponse, ExecutionMode,
    StatefulConnector,
)
from .stripe import StripeConnector
from .database import DatabaseConnector


class PaymentMockAdapter:
    """Mock payment adapter for refund/transfer operations."""

    MAX_SINGLE_REFUND = 10000

    def execute(self, operator_response: OperatorResponse, context: Dict[str, Any]) -> ExecutionResult:
        action = operator_response.action
        trace_id = operator_response.trace_id
        ts = int(time.time() * 1000)

        if action == "REFUND":
            amount = context.get("amount", 0)
            if not isinstance(amount, (int, float)) or amount <= 0:
                return ExecutionResult("failed", "refund_invalid_amount", "payment_mock", ts, trace_id,
                                       {"error": "Invalid or missing amount", "amount_provided": amount})
            if amount > self.MAX_SINGLE_REFUND:
                return ExecutionResult("blocked", "refund_exceeds_cap", "payment_mock", ts, trace_id,
                                       {"error": f"amount exceeds cap {self.MAX_SINGLE_REFUND}",
                                        "cap": self.MAX_SINGLE_REFUND})
            refund_id = f"REF-MOCK-{uuid.uuid4().hex[:10].upper()}"
            return ExecutionResult("success", f"refund_gbp_{amount:.2f}", "payment_mock", ts, trace_id,
                                   {"refund_id": refund_id, "amount": amount, "currency": "GBP",
                                    "status": "mock_processed"})

        return ExecutionResult("failed", f"unsupported_action_{action}", "payment_mock", ts, trace_id,
                               {"error": f"Unsupported action: {action}"})


class DataMockAdapter:
    """Mock data adapter for query/delete operations."""

    DELETION_ROLES: FrozenSet[str] = frozenset({"admin", "dpo", "data_protection_officer"})

    def execute(self, operator_response: OperatorResponse, context: Dict[str, Any]) -> ExecutionResult:
        action = operator_response.action
        trace_id = operator_response.trace_id
        ts = int(time.time() * 1000)
        role = context.get("role", "unknown")
        data_type = context.get("data_type", "unspecified")

        if action == "QUERY":
            qid = f"QRY-MOCK-{uuid.uuid4().hex[:10].upper()}"
            return ExecutionResult("success", f"query_{data_type}", "data_mock", ts, trace_id,
                                   {"query_id": qid, "records_returned": 0, "gdpr_ref": "Article 15"})

        if action == "DELETE":
            if role not in self.DELETION_ROLES:
                return ExecutionResult("blocked", "delete_role_insufficient", "data_mock", ts, trace_id,
                                       {"error": f"Role '{role}' not authorised for deletion",
                                        "required_roles": list(self.DELETION_ROLES)})
            did = f"DEL-MOCK-{uuid.uuid4().hex[:10].upper()}"
            return ExecutionResult("success", f"soft_delete_{data_type}", "data_mock", ts, trace_id,
                                   {"deletion_id": did, "data_type": data_type,
                                    "status": "soft_deleted", "gdpr_ref": "Article 17"})

        return ExecutionResult("failed", f"unsupported_action_{action}", "data_mock", ts, trace_id,
                               {"error": f"Unsupported action: {action}"})


class AccessMockAdapter:
    """Mock access adapter for permission/override operations."""

    OVERRIDE_ALLOWED_ROLES: FrozenSet[str] = frozenset({"admin", "ops_manager", "security_admin", "manager"})

    def execute(self, operator_response: OperatorResponse, context: Dict[str, Any]) -> ExecutionResult:
        action = operator_response.action
        trace_id = operator_response.trace_id
        ts = int(time.time() * 1000)
        role = context.get("role", "unknown")

        if action == "MODIFY":
            cid = f"ACC-MOCK-{uuid.uuid4().hex[:10].upper()}"
            return ExecutionResult("success", "modify_permission", "access_mock", ts, trace_id,
                                   {"change_id": cid, "status": "mock_queued"})
        if action == "QUERY":
            return ExecutionResult("success", "query_permissions", "access_mock", ts, trace_id,
                                   {"queried_by": role, "status": "completed"})

        return ExecutionResult("failed", f"unsupported_action_{action}", "access_mock", ts, trace_id,
                               {"error": f"Unsupported action: {action}"})


class AdapterRouter:
    """Routes execution to the correct mock adapter by domain."""

    def __init__(self) -> None:
        self._payment = PaymentMockAdapter()
        self._data = DataMockAdapter()
        self._access = AccessMockAdapter()

    def route(self, operator_response: OperatorResponse, context: Dict[str, Any]) -> ExecutionResult:
        match operator_response.domain:
            case Domain.FINANCIAL.value:
                return self._payment.execute(operator_response, context)
            case Domain.DATA.value:
                return self._data.execute(operator_response, context)
            case Domain.ACCESS.value:
                return self._access.execute(operator_response, context)
            case _:
                return ExecutionResult("failed", "unknown_domain", "router", int(time.time() * 1000),
                                       operator_response.trace_id,
                                       {"error": f"No adapter for domain: {operator_response.domain}"})


class ConnectorRouter:
    """Routes to stateful connectors based on domain (vNext.10)."""

    def __init__(self, mode: ExecutionMode = ExecutionMode.MOCK,
                 db_path: Optional[str] = None,
                 state_store: Optional[object] = None) -> None:
        self._mode = mode
        self._state_store = state_store
        self._stripe = StripeConnector(mode, state_store=self._state_store)
        self._database = DatabaseConnector(mode, db_path=db_path, state_store=self._state_store)
        self._mock_router = AdapterRouter()

    def resolve(self, domain: str) -> Optional[StatefulConnector]:
        """Return the three-phase connector for *domain*, or None."""
        match domain:
            case Domain.FINANCIAL.value:
                return self._stripe
            case Domain.DATA.value:
                return self._database
            case _:
                return None

    def health_check(self) -> Dict[str, Any]:
        return {
            "mode": self._mode.value,
            "stripe": self._stripe.health_check(),
            "database": self._database.health_check(),
        }
