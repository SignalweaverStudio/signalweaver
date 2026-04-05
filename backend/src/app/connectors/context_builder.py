from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from .base import _logger, TrustedContext, AuthIdentity


class TrustedContextBuilder:
    """Constructs a TrustedContext from raw request + authenticated identity.

    Critical behaviour:
      - STRIPS all user-supplied sensitive fields (role, override, etc.)
      - Reconstructs them deterministically from AuthIdentity
      - Validates numeric fields and rejects malformed input
      - Constructs derived flags based on identity and fields
    """

    STRIP_FIELDS = frozenset({
        "role", "override", "permissions", "is_admin", "privilege_level",
        "auth_token", "api_key", "secret", "can_bypass", "auth_method",
        "actor_id", "tenant_id", "actor_role",
    })

    ALLOWED_FIELDS = frozenset({
        "amount", "currency", "payment_intent_id", "recipient",
        "recipient_account", "data_type", "user_id", "confirmation",
        "target_user", "new_role", "justification", "table_name",
        "domain", "country",
    })

    def build(
        self, raw_request: Dict[str, Any], identity: AuthIdentity
    ) -> Tuple[TrustedContext, List[str]]:
        """Build a trusted context from raw request and auth identity.

        Returns:
            (trusted_context, errors). Empty errors = success.
        """
        errors: List[str] = []
        log: List[str] = []
        ts = int(time.time() * 1000)

        log.append(f"Step 1: Received raw request with {len(raw_request)} fields")
        log.append(f"Step 2: Auth identity verified: actor={identity.actor_id} role={identity.actor_role}")

        # Detect and strip sensitive fields
        stripped: List[str] = []
        unknown_fields: List[str] = []
        verified: Dict[str, Any] = {}

        for key, value in raw_request.items():
            if key in self.STRIP_FIELDS:
                stripped.append(key)
                log.append(f"Step 3a: STRIPPED sensitive field '{key}' (value not trusted)")
            elif key in self.ALLOWED_FIELDS:
                # Validate the field
                validation_error = self._validate_field(key, value)
                if validation_error:
                    errors.append(validation_error)
                    log.append(f"Step 3b: REJECTED field '{key}': {validation_error}")
                else:
                    verified[key] = value
                    log.append(f"Step 3c: VERIFIED field '{key}' type={type(value).__name__}")
            else:
                unknown_fields.append(key)
                log.append(f"Step 3d: UNKNOWN field '{key}' — will be rejected by firewall")

        if stripped:
            log.append(f"Step 4: Stripped {len(stripped)} sensitive field(s): {', '.join(sorted(stripped))}")
            _logger.warning(
                "Context builder stripped sensitive fields: %s",
                ", ".join(sorted(stripped)),
            )

        if unknown_fields:
            errors.append(f"unknown_fields_not_allowed: {', '.join(sorted(unknown_fields))}")
            log.append(f"Step 5: REJECTED {len(unknown_fields)} unknown field(s): {', '.join(sorted(unknown_fields))}")

        # Reconstruct identity-derived fields
        log.append("Step 6: Reconstructing identity-derived metadata")

        # Build derived flags
        derived_flags: Dict[str, bool] = {
            "is_financial_actor": identity.actor_role in {"analyst", "manager", "ops_manager", "admin"},
            "can_override": identity.actor_role in {
                "supervisor", "ops_manager", "security_admin", "admin",
            },
            "is_privileged": identity.actor_role in {"admin", "security_admin", "ops_manager"},
            "is_data_protector": identity.actor_role in {"dpo", "data_protection_officer", "admin"},
            "is_self_service": identity.actor_role in {"customer", "viewer"},
        }

        log.append(f"Step 7: Derived flags: {json.dumps(derived_flags)}")

        # Extract justification if present
        justification = verified.pop("justification", None)

        context = TrustedContext(
            actor_id=identity.actor_id,
            actor_role=identity.actor_role,
            tenant_id=identity.tenant_id,
            request_type="UNKNOWN",  # will be updated by decision engine
            justification=justification,
            verified_fields=verified,
            derived_flags=derived_flags,
            stripped_fields=sorted(stripped),
            context_build_log=log,
            built_at=ts,
        )

        log.append(f"Step 8: TrustedContext built with {len(verified)} verified fields")
        return context, errors

    def _validate_field(self, key: str, value: Any) -> Optional[str]:
        """Validate a single field. Returns error string or None if valid."""
        if key == "amount":
            if not isinstance(value, (int, float)):
                return f"amount_must_be_number: got {type(value).__name__}"
            if value <= 0:
                return "amount_must_be_positive"
            if value > 100000:
                return "amount_exceeds_maximum_100000"
            return None

        if key == "currency":
            if not isinstance(value, str):
                return f"currency_must_be_string: got {type(value).__name__}"
            if len(value) != 3 or not value.isalpha():
                return "currency_must_be_3_letter_iso_code"
            return None

        if key == "user_id":
            if not isinstance(value, str):
                return f"user_id_must_be_string: got {type(value).__name__}"
            if len(value) > 200:
                return "user_id_exceeds_max_length"
            return None

        if key == "payment_intent_id":
            if not isinstance(value, str):
                return f"payment_intent_id_must_be_string: got {type(value).__name__}"
            if len(value) > 200:
                return "payment_intent_id_exceeds_max_length"
            return None

        if key == "data_type":
            if not isinstance(value, str):
                return f"data_type_must_be_string: got {type(value).__name__}"
            if len(value) > 100:
                return "data_type_exceeds_max_length"
            return None

        if key == "recipient":
            if not isinstance(value, str):
                return f"recipient_must_be_string: got {type(value).__name__}"
            if len(value) > 200:
                return "recipient_exceeds_max_length"
            return None

        if key == "recipient_account":
            if not isinstance(value, str):
                return f"recipient_account_must_be_string: got {type(value).__name__}"
            if len(value) > 100:
                return "recipient_account_exceeds_max_length"
            return None

        if key == "target_user":
            if not isinstance(value, str):
                return f"target_user_must_be_string: got {type(value).__name__}"
            if len(value) > 200:
                return "target_user_exceeds_max_length"
            return None

        if key == "new_role":
            if not isinstance(value, str):
                return f"new_role_must_be_string: got {type(value).__name__}"
            if value not in {"viewer", "analyst", "manager", "admin", "supervisor",
                             "ops_manager", "security_admin", "dpo", "data_protection_officer", "customer"}:
                return f"new_role_invalid_value: {value}"
            return None

        if key == "confirmation":
            if not isinstance(value, str):
                return f"confirmation_must_be_string: got {type(value).__name__}"
            return None

        if key == "table_name":
            if not isinstance(value, str):
                return f"table_name_must_be_string: got {type(value).__name__}"
            return None

        if key == "domain":
            if not isinstance(value, str):
                return f"domain_must_be_string: got {type(value).__name__}"
            return None

        if key == "country":
            if not isinstance(value, str):
                return f"country_must_be_string: got {type(value).__name__}"
            if len(value) != 2 or not value.isalpha():
                return "country_must_be_2_letter_code"
            return None

        if key == "justification":
            if not isinstance(value, str):
                return f"justification_must_be_string: got {type(value).__name__}"
            if len(value) < 10:
                return "justification_too_short_minimum_10_chars"
            return None

        # Unknown but in ALLOWED_FIELDS — accept with type check
        if isinstance(value, (str, int, float, bool)):
            return None

        return f"field_{key}_has_unexpected_type"
