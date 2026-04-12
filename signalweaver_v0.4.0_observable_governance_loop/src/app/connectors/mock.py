"""
Mock connector — echoes the request back for testing and demonstration.

This is the default connector. It always succeeds and returns the
original raw_text, proving the execution path is wired end-to-end.
"""

from __future__ import annotations
from typing import Any

from app.connectors.base import Connector


class MockConnector(Connector):
    """Deterministic mock that echoes the request payload."""

    def execute(self, request: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "success",
            "connector": "mock",
            "echo": request.get("raw_text", ""),
            "context": request.get("context", {}),
        }
