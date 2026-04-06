"""GET /connectors/health, GET /connectors/{domain} — Stage 14 connector status."""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter

from app.connectors import (
    ConnectorRouter,
    ExecutionMode,
)

_logger = logging.getLogger(__name__)

router = APIRouter()

# Shared router instance (MOCK mode)
_connector_router = ConnectorRouter(mode=ExecutionMode.MOCK)


@router.get("/health")
def connectors_health():
    """Health check for all registered connectors.

    Returns status of each connector (stripe, database).
    """
    try:
        return _connector_router.health_check()
    except Exception as exc:
        _logger.error("Connector health check failed: %s", exc)
        return {
            "status": "error",
            "error": str(exc),
        }


@router.get("/{domain}")
def connector_status(domain: str):
    """Get status of a specific connector by domain.

    Supported domains: FINANCIAL, DATA.
    Returns 404-style response for unknown domains.
    """
    try:
        connector = _connector_router.resolve(domain)
        if connector is None:
            return {
                "domain": domain,
                "status": "not_registered",
                "message": (
                    f"No stateful connector registered for domain '{domain}'. "
                    "Falling back to mock adapter."
                ),
            }
        return connector.health_check()
    except Exception as exc:
        _logger.error("Connector status check failed for %s: %s", domain, exc)
        return {
            "domain": domain,
            "status": "error",
            "error": str(exc),
        }

