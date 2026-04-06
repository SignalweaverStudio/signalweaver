from __future__ import annotations

import logging
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from .base import _logger, TrustedContext


class ContextFirewall:
    """Whitelist-based field validation. Rejects unknown keys, enforces schema.

    Runs AFTER the decision engine determines the domain, so it can apply
    domain-specific schema requirements.
    """

    DOMAIN_SCHEMAS: Dict[str, Dict[str, Any]] = {
        "FINANCIAL": {
            "required": frozenset({"amount"}),
            "optional": frozenset({"currency", "payment_intent_id", "recipient", "recipient_account"}),
            "validators": {
                "amount": lambda v: isinstance(v, (int, float)) and 0 < v <= 100000,
                "currency": lambda v: isinstance(v, str) and len(v) == 3 and v.isalpha(),
                "payment_intent_id": lambda v: isinstance(v, str) and len(v) <= 200,
                "recipient": lambda v: isinstance(v, str) and len(v) <= 200,
                "recipient_account": lambda v: isinstance(v, str) and len(v) <= 100,
            },
        },
        "DATA": {
            "required": frozenset({"data_type", "user_id"}),
            "optional": frozenset({"confirmation", "table_name"}),
            "validators": {
                "data_type": lambda v: isinstance(v, str) and len(v) <= 100,
                "user_id": lambda v: isinstance(v, str) and len(v) <= 200,
                "confirmation": lambda v: isinstance(v, str),
                "table_name": lambda v: isinstance(v, str),
            },
        },
        "ACCESS": {
            "required": frozenset({"target_user", "new_role"}),
            "optional": frozenset({"justification"}),
            "validators": {
                "target_user": lambda v: isinstance(v, str) and len(v) <= 200,
                "new_role": lambda v: isinstance(v, str) and v in {
                    "viewer", "analyst", "manager", "admin", "supervisor",
                    "ops_manager", "security_admin", "dpo", "data_protection_officer", "customer",
                },
                "justification": lambda v: isinstance(v, str) and len(v) >= 10,
            },
        },
    }

    def validate(
        self, trusted_context: TrustedContext, detected_domain: str
    ) -> Tuple[bool, List[str]]:
        """Validate trusted context against domain-specific schema.

        Returns:
            (passed, violation_list). Empty violations = pass.
        """
        violations: List[str] = []
        fields = trusted_context.verified_fields

        schema = self.DOMAIN_SCHEMAS.get(detected_domain)
        if schema is None:
            # Unknown domain — pass through (engine already handles this)
            violations.append(f"unknown_domain_schema: {detected_domain}")
            return False, violations

        # Check required fields
        required = schema["required"]
        missing = list(required - set(fields.keys()))
        if missing:
            violations.append(f"missing_required_fields: {', '.join(sorted(missing))}")

        # Check for fields not in schema
        allowed = schema["required"] | schema["optional"]
        extra = set(fields.keys()) - allowed
        if extra:
            violations.append(f"extra_fields_not_allowed_in_domain: {', '.join(sorted(extra))}")

        # Run per-field validators
        validators = schema["validators"]
        for field_name, validator in validators.items():
            if field_name in fields:
                try:
                    if not validator(fields[field_name]):
                        violations.append(
                            f"field_validation_failed: {field_name}={fields[field_name]}"
                        )
                except Exception:
                    violations.append(f"field_validator_error: {field_name}")

        passed = len(violations) == 0
        if not passed:
            _logger.warning(
                "Context firewall violations: %s", "; ".join(violations)
            )
        return passed, violations
