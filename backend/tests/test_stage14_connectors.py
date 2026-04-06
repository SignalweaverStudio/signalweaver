"""
Stage 14 — Connector Regression Tests (modular package version)
===============================================================

5 deterministic tests verifying the full integrated 3-phase execution path
through TrustedOrchestrator. Adapted from test_stage14_orchestrator_regressions.py
to use the modular connectors package.

Target: backend/src/app/connectors/ (vNext.10 modular baseline)
Mode: MOCK (no external dependencies)

Usage:
    cd backend && python -m pytest tests/test_stage14_connectors.py -v
    or:
    cd backend/src && python -m pytest ../tests/test_stage14_connectors.py -v
"""

import json
import sys
import os
import time

import pytest

# Ensure the package is importable
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from app.connectors import (
    TrustedOrchestrator,
    ExecutionMode,
    TenantRegistry,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def admin_registry():
    """Create a registry with an admin tenant and return (registry, api_key)."""
    reg = TenantRegistry()
    rec = reg.register_tenant(
        tenant_id="tenant_regress",
        tenant_name="Regression Tenant",
        secret="secret_regress",
        actors=[
            {"actor_id": "analyst_001", "actor_role": "analyst"},
            {"actor_id": "admin_001", "actor_role": "admin"},
            {"actor_id": "sup_001", "actor_role": "supervisor"},
        ],
    )
    return reg, rec.api_key_raw


@pytest.fixture
def orchestrator(admin_registry):
    """Create a MOCK-mode orchestrator with admin credentials."""
    reg, _ = admin_registry
    return TrustedOrchestrator(mode=ExecutionMode.MOCK, registry=reg)


# ── Test 1: FINANCIAL — confirmed refund ──────────────────────────────────


class TestFinancialConfirmedRefund:
    """Full orchestrator path: seeded payment → PROCEED → 3-phase → CONFIRMED."""

    def test_confirmed_refund(self, orchestrator, admin_registry):
        _, api_key = admin_registry

        # Seed a valid succeeded payment
        orchestrator._state_store.seed_payment("pi_reg_1", 200.00)

        trace = orchestrator.execute(
            raw_text="Refund payment pi_reg_1 for 50 GBP",
            context={
                "amount": 50,
                "payment_intent_id": "pi_reg_1",
                "recipient": "acct_regress_1",
            },
            api_key=api_key,
        )

        assert trace is not None, "Expected trace to be returned"

        d = trace.to_dict()

        # Decision engine returned PROCEED
        assert d["decision_trace"]["decision"] == "PROCEED", \
            f"Expected PROCEED, got {d['decision_trace']['decision']}"

        # Connector result is populated
        cr = d.get("connector_result")
        assert cr is not None, "connector_result must be populated"
        assert cr["status"] == "success", \
            f"Expected connector success, got {cr['status']}"
        assert cr.get("external_id", "").startswith("re_mock_"), \
            f"Expected mock refund ID, got {cr.get('external_id')}"

        # Guarantee is CONFIRMED
        assert d["external_guarantee"] == "CONFIRMED", \
            f"Expected CONFIRMED, got {d['external_guarantee']}"

        # Stage 14 field: pre_state_check
        psc = d.get("pre_state_check")
        assert psc is not None, "pre_state_check must be populated"
        assert psc["state_ok"] is True
        assert psc["connector"] == "stripe"

        # Stage 14 field: post_execution_confirmation
        pec = d.get("post_execution_confirmation")
        assert pec is not None, "post_execution_confirmation must be populated"
        assert pec["confirmed"] is True

        # Stage 14 field: compensation_assessment
        comp = d.get("compensation_assessment")
        assert comp is not None, "compensation_assessment must be populated"
        assert comp["compensation_required"] is False
        assert comp["action"] == "NONE"

        # Stage 14 field: state_version_info
        vi = d.get("state_version_info")
        assert vi is not None, "state_version_info must be populated"
        assert vi["pre_version"] == "1"
        assert vi["expected_post_version"] == "2"
        assert vi["observed_post_version"] == 2


# ── Test 2: FINANCIAL — precondition failure ───────────────────────────────


class TestFinancialPreconditionFailure:
    """Full orchestrator path: already-refunded payment → precheck fails → short-circuit."""

    def test_precondition_failed(self, orchestrator, admin_registry):
        _, api_key = admin_registry

        # Seed an already-refunded payment
        orchestrator._state_store.seed_payment(
            "pi_reg_2", 100.00,
            refunded=True, refund_count=1, refunded_amount=100.00,
        )

        trace = orchestrator.execute(
            raw_text="Refund payment pi_reg_2 for 30 GBP",
            context={
                "amount": 30,
                "payment_intent_id": "pi_reg_2",
                "recipient": "acct_regress_2",
            },
            api_key=api_key,
        )

        assert trace is not None
        d = trace.to_dict()

        cr = d.get("connector_result")
        assert cr is not None
        assert cr["status"] == "blocked"
        assert cr.get("external_id") is None

        assert d["external_guarantee"] == "PRECONDITION_FAILED"

        psc = d.get("pre_state_check")
        assert psc is not None
        assert psc["state_ok"] is False
        assert len(psc["violations"]) > 0

        comp = d.get("compensation_assessment")
        assert comp is not None
        assert comp["compensation_required"] is True
        assert comp["action"] == "BLOCK_RETRIES"

        pec = d.get("post_execution_confirmation")
        assert pec is not None
        assert pec["confirmed"] is False

        assert d["state_version_info"] is None


# ── Test 3: DATA — confirmed query (via 3-phase stateful connector) ──────


class TestDataConfirmedQuery:
    """Full orchestrator path: seeded record → DATA QUERY → 3-phase DB connector."""

    def test_data_query(self, orchestrator, admin_registry):
        _, api_key = admin_registry

        orchestrator._state_store.seed_record(
            "user_data", "u_data_1", "transactions", "sensitive_data"
        )

        trace = orchestrator.execute(
            raw_text="Show me my transactions data for user u_data_1",
            context={
                "data_type": "transactions",
                "user_id": "u_data_1",
                "table_name": "user_data",
            },
            api_key=api_key,
        )

        assert trace is not None
        d = trace.to_dict()

        assert d["decision_trace"]["domain"] == "DATA"

        cr = d.get("connector_result")
        assert cr is not None
        assert cr["status"] == "success"

        psc = d.get("pre_state_check")
        assert psc is not None
        assert psc["state_ok"] is True
        assert psc["connector"] == "database"

        pec = d.get("post_execution_confirmation")
        assert pec is not None

        comp = d.get("compensation_assessment")
        assert comp is not None


# ── Test 4: DATA — precondition failure (record not found) ────────────────


class TestDataPreconditionFailure:
    """Full orchestrator path: unseeded record → precheck fails → short-circuit."""

    def test_record_not_found(self, orchestrator, admin_registry):
        _, api_key = admin_registry

        trace = orchestrator.execute(
            raw_text="Show me my transactions data for user u_missing",
            context={
                "data_type": "transactions",
                "user_id": "u_missing",
                "table_name": "user_data",
            },
            api_key=api_key,
        )

        assert trace is not None
        d = trace.to_dict()

        cr = d.get("connector_result")
        assert cr is not None
        assert cr["status"] == "blocked"

        assert d["external_guarantee"] == "PRECONDITION_FAILED"

        psc = d.get("pre_state_check")
        assert psc is not None
        assert psc["state_ok"] is False
        assert any("not_found" in v for v in psc["violations"])

        comp = d.get("compensation_assessment")
        assert comp is not None
        assert comp["compensation_required"] is True

        pec = d.get("post_execution_confirmation")
        assert pec is not None
        assert pec["confirmed"] is False

        assert d["state_version_info"] is None


# ── Test 5: ACCESS — mock fallback ────────────────────────────────────────


class TestAccessMockFallback:
    """Full orchestrator path: ACCESS domain → resolve returns None → mock fallback."""

    def test_access_fallback(self, orchestrator, admin_registry):
        _, api_key = admin_registry

        trace = orchestrator.execute(
            raw_text="Grant admin access to user u_target",
            context={
                "new_role": "admin",
                "target_user": "u_target",
            },
            api_key=api_key,
        )

        assert trace is not None
        d = trace.to_dict()

        assert d["decision_trace"]["domain"] == "ACCESS"

        er = d.get("execution_result")
        assert er is not None

        # Stateful connector fields should NOT be populated
        assert d["pre_state_check"] is None
        assert d["post_execution_confirmation"] is None
        assert d["compensation_assessment"] is None
        assert d["state_version_info"] is None

        assert d["external_guarantee"] == "UNKNOWN"

        assert d["auth_identity"] is not None
        assert d["decision_trace"] is not None
        assert d["mode"] == "MOCK"