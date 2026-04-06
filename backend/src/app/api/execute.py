"""POST /execute_trusted — Stage 14 execution endpoint."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

from app.connectors import (
    TrustedOrchestrator,
    ExecutionMode,
)

_logger = logging.getLogger(__name__)

router = APIRouter()


class ExecuteRequest:
    """Request body for trusted execution."""
    pass


@router.post("/trusted")
def execute_trusted(
    raw_text: str,
    context: Optional[Dict[str, Any]] = None,
    api_key: Optional[str] = Query(None),
):
    """Execute a trusted request through the 3-phase orchestrator.

    Accepts natural language request and optional context fields.
    Returns the full TrustedExecutionTrace as JSON.
    """
    orch = TrustedOrchestrator(mode=ExecutionMode.MOCK)

    try:
        trace = orch.execute(
            raw_text=raw_text,
            context=context or {},
            api_key=api_key,
        )
        return trace.to_dict()
    except Exception as exc:
        _logger.error("Execute trusted failed: %s", exc)
        return {
            "error": str(exc),
            "status": "internal_error",
        }

