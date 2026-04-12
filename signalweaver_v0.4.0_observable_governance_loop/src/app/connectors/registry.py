"""
Connector registry.

Wire new connectors here by adding them to the CONNECTORS dict.
The ``get_connector`` factory raises a clear 400-class error for
unknown names so callers don't need to handle KeyError themselves.
"""

from __future__ import annotations
from app.connectors.base import Connector
from app.connectors.mock import MockConnector
from app.connectors.webhook import WebhookConnector

CONNECTORS: dict[str, Connector] = {
    "mock": MockConnector(),
    "webhook": WebhookConnector(),
}


def get_connector(name: str) -> Connector:
    """Return the named connector or raise ValueError."""
    connector = CONNECTORS.get(name)
    if connector is None:
        available = ", ".join(sorted(CONNECTORS.keys()))
        raise ValueError(
            f"Unknown connector '{name}'. Available: {available}"
        )
    return connector
