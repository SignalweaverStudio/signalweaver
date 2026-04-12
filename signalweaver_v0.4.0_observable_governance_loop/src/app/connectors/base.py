"""
Base connector interface.

Every connector must implement execute() and return a dict with at least
a "status" key. The contract is intentionally minimal — no retries, no
async orchestration, no distributed dispatch. Just: receive a request,
do the thing, return the result.
"""

from __future__ import annotations
from typing import Any


class Connector:
    """Abstract base for execution connectors."""

    def execute(self, request: dict[str, Any]) -> dict[str, Any]:
        """
        Execute an action described by *request*.

        Parameters
        ----------
        request: dict
            Must contain at least ``raw_text`` and ``context``.

        Returns
        -------
        dict
            Must contain at least ``status`` (one of "success", "error").
            May contain arbitrary additional keys.
        """
        raise NotImplementedError
