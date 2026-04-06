from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from .base import _logger


class StateStore:
    """In-memory external state simulation for MOCK mode only.

    In SANDBOX/LIVE, connectors read the real Stripe API / SQLite DB
    directly. StateStore is NEVER the source of truth outside MOCK.
    """

    def __init__(self) -> None:
        self._payments: Dict[str, Dict[str, Any]] = {}
        self._records: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    # -- payments --

    def seed_payment(
        self, payment_intent_id: str, amount: float, status: str = "succeeded",
        currency: str = "GBP", refunded: bool = False, refund_count: int = 0,
        refunded_amount: float = 0.0, version: int = 1,
    ) -> None:
        with self._lock:
            self._payments[payment_intent_id] = {
                "payment_intent_id": payment_intent_id,
                "amount": amount, "currency": currency,
                "status": status, "refunded": refunded,
                "refund_count": refund_count,
                "refunded_amount": refunded_amount,
                "version": version,
            }

    def get_payment(self, pid: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._payments.get(pid)

    def apply_refund(self, pid: str, refund_amount: float, success: bool) -> None:
        with self._lock:
            state = self._payments.get(pid)
            if state is None:
                return
            if success:
                state["refunded"] = True
                state["refund_count"] += 1
                state["refunded_amount"] += refund_amount
            state["version"] += 1

    def mutate_version(self, pid: str) -> None:
        with self._lock:
            state = self._payments.get(pid)
            if state is not None:
                state["version"] += 1

    # -- records --

    def seed_record(
        self, table: str, user_id: str, data_type: str,
        data_value: str = "test_data", exists: bool = True,
        deleted: bool = False, version: int = 1,
    ) -> None:
        with self._lock:
            self._records[f"{table}:{user_id}:{data_type}"] = {
                "table": table, "user_id": user_id, "data_type": data_type,
                "data_value": data_value, "exists": exists,
                "deleted": deleted,
                "deleted_at": int(time.time() * 1000) if deleted else None,
                "version": version,
            }

    def get_record(self, table: str, user_id: str, data_type: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._records.get(f"{table}:{user_id}:{data_type}")

    def mark_deleted(self, table: str, user_id: str, data_type: str) -> bool:
        with self._lock:
            state = self._records.get(f"{table}:{user_id}:{data_type}")
            if state is None or state["deleted"]:
                return False
            state["deleted"] = True
            state["deleted_at"] = int(time.time() * 1000)
            state["version"] += 1
            return True
