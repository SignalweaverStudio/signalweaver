from __future__ import annotations

import hashlib
import logging
import re
import threading
from typing import Any, Dict, List, Optional, Tuple

_logger = logging.getLogger("signalweaver")


class DeterministicIdempotency:
    """Fixed idempotency using deterministic keys.

    The vNext.8 flaw: idempotency key depends on random trace_id → useless.
    vNext.9 fix: key = SHA-256(canonical_request + actor + domain + action + amount + recipient + tenant).
    Same actor, same request, same domain/action → same key.
    """

    def __init__(self) -> None:
        self._store: Dict[str, Any] = {}
        self._lock = threading.Lock()

    @staticmethod
    def make_key(
        raw_text: str,
        actor_id: str,
        domain: str,
        action: str,
        amount: Any = None,
        recipient: Any = None,
        tenant_id: str = "",
    ) -> str:
        """Deterministic key from canonical request + actor identity + stable fields.

        Key = SHA-256(normalize(raw_text) + "|" + actor_id + "|" + domain + "|"
                      action + "|" + str(amount) + "|" + str(recipient) + "|" + tenant_id)
        """
        # Normalize raw_text: lowercase, strip whitespace, collapse multi-spaces
        normalized = re.sub(r'\s+', ' ', raw_text.lower().strip())
        parts = [
            normalized,
            actor_id,
            domain,
            action,
            str(amount) if amount is not None else "",
            str(recipient) if recipient is not None else "",
            tenant_id,
        ]
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def check_and_store(
        self, key: str, result: Any
    ) -> Tuple[bool, Optional[Any]]:
        """Returns (is_duplicate, cached_or_none).

        If key exists -> return (True, cached_result), do NOT store.
        If key is new -> store result and return (False, None).
        """
        with self._lock:
            if key in self._store:
                _logger.info("Deterministic idempotency HIT: key=%s...", key[:16])
                return True, self._store[key]
            self._store[key] = result
            _logger.info("Deterministic idempotency STORED: key=%s...", key[:16])
            return False, None

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            return self._store.get(key)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
