"""
POST /execute/trusted — Gate → Execute → Record

This is the minimal execution layer. It:
1. Runs the same gate evaluation used by /gate/evaluate (no duplication)
2. Maps the decision to an execution action
3. Dispatches to a connector if allowed
4. Writes an ExecutionLog linked to the DecisionTrace

ExecutionLog.status semantics:
  blocked  — governance said no (gate/refuse); no connector call attempted
  executed — governance said yes; connector returned success
  failed   — governance said yes; connector returned error (timeout, etc.)

Constraints:
- No execution without a trace
- Deterministic: same input → same gate decision → same execution outcome
- Shadow mode: executes but marks would_block
- Soft mode: allows override if override_reason present
- Hard mode: strict enforcement
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.security import verify_api_key, rate_limit
from app.db import get_db
from app.auth import get_tenant
from app.models import Tenant, ExecutionLog
from app.schemas import ExecuteTrustedIn, ExecuteTrustedOut, ExecutionResultOut
from app.connectors.registry import get_connector
from app.connectors.redaction import redact_sensitive


router = APIRouter(
    dependencies=[Depends(verify_api_key)],
)


def _rl(request: Request):
    rate_limit(request, limit=60, window_s=60)


router.dependencies.append(Depends(_rl))


@router.post("/trusted", response_model=ExecuteTrustedOut)
def execute_trusted(
    payload: ExecuteTrustedIn,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_tenant),
):
    """
    Evaluate a request through the gate, then execute if allowed.

    Decision → Behavior mapping:
      proceed  → execute via connector
      gate     → DO NOT execute (return blocked)
      refuse   → DO NOT execute (return blocked)

    Enforcement mode modifiers:
      shadow → always execute, but flag would_block in response
      soft   → allow override if override_reason present
      hard   → strict — gate/refuse always block

    ExecutionLog.status:
      blocked  — governance blocked; no connector call
      executed — connector succeeded
      failed   — connector error (timeout, connection, non-2xx)
    """
    # --- 1. Run gate evaluation (shared with /gate/evaluate) ---
    from app.api.gate import _run_gate_evaluation

    ev = _run_gate_evaluation(
        request_summary=payload.raw_text,
        arousal=payload.arousal,
        dominance=payload.dominance,
        profile_id=payload.profile_id,
        override_reason=payload.override_reason,
        tenant_id=tenant.id,
        db=db,
    )

    decision = ev["decision"]
    enforcement_mode = ev["enforcement_mode"]
    would_block = ev["would_block"]

    # --- 2. Determine whether to execute ---
    should_execute = False
    connector_result = None

    if decision == "proceed":
        should_execute = True
    elif decision == "gate":
        # Soft mode: allow if override_reason is present
        if enforcement_mode == "soft" and payload.override_reason:
            should_execute = True
        # Shadow mode: execute but the decision is already "proceed" due to enforcement
        # (shadow always downgrades to proceed in apply_enforcement_mode)
    elif decision == "refuse":
        should_execute = False

    # --- 3. Execute via connector if allowed ---
    execution_status = "blocked"
    connector_name = payload.connector

    if should_execute:
        try:
            connector = get_connector(connector_name)
            connector_result = connector.execute({
                "raw_text": payload.raw_text,
                "domain": payload.domain,
                "context": payload.context,
            })
            # Connector returned a result — check if it was a success or error
            if isinstance(connector_result, dict) and connector_result.get("status") == "error":
                execution_status = "failed"
            else:
                execution_status = "executed"
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            # Unexpected connector failure
            connector_result = {"status": "error", "error": str(e)}
            execution_status = "failed"
    else:
        connector_result = None

    # --- 4. Redact sensitive fields before storage and response ---
    # The connector returns raw results (e.g. webhook response_body, mock echo).
    # Redaction ensures secrets, tokens, and credentials are never persisted
    # in ExecutionLog.response_json or leaked in API responses.
    safe_result = redact_sensitive(connector_result) if connector_result else None

    # --- 5. Write ExecutionLog (stores redacted result) ---
    exec_log = ExecutionLog(
        tenant_id=tenant.id,
        trace_id=ev["trace_id"],
        decision=decision,
        connector=connector_name,
        status=execution_status,
        response_json=json.dumps(safe_result, ensure_ascii=False) if safe_result else "",
    )
    try:
        db.add(exec_log)
        db.commit()
        db.refresh(exec_log)
    except Exception:
        db.rollback()
        raise

    # --- 6. Build response (also uses redacted result) ---
    return ExecuteTrustedOut(
        decision=decision,
        reason=ev["reason"],
        trace_id=ev["trace_id"],
        log_id=ev["log_id"],
        execution=ExecutionResultOut(
            status=execution_status,
            connector=connector_name,
            result=safe_result,
        ),
        enforcement_mode=enforcement_mode,
        would_block=would_block,
        conflicted_anchor_ids=ev["conflicted_ids"],
        explanation=ev["explanations_list"][0] if ev["explanations_list"] else None,
    )
