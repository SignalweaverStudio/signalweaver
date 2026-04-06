from __future__ import annotations

import time
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from .base import AuthIdentity, OverrideRequest


class OverrideGovernance:
    """Manages override permissions, validation, and audit trail.

    Override is a STRUCTURED REQUEST, not a boolean flag. It requires:
      - Actor must have an override-eligible role
      - Target decision must be overridable
      - Mandatory justification (min 10 chars)
      - Dual approval for high-risk actions
    """

    OVERRIDE_ELIGIBLE_ROLES = frozenset({
        "supervisor", "ops_manager", "security_admin", "admin",
    })

    OVERRIDABLE_DECISIONS = frozenset({"GATE"})

    DUAL_APPROVAL_ACTIONS = frozenset({"DELETE", "TRANSFER", "MODIFY"})

    def validate_override(
        self, request: OverrideRequest, identity: AuthIdentity
    ) -> Tuple[bool, List[str]]:
        """Validate an override request.

        Returns:
            (valid, violations). Empty violations = valid.
        """
        violations: List[str] = []

        # 1. Actor role must be override-eligible
        if identity.actor_role not in self.OVERRIDE_ELIGIBLE_ROLES:
            violations.append(
                f"override_role_not_eligible: {identity.actor_role} "
                f"(eligible: {', '.join(sorted(self.OVERRIDE_ELIGIBLE_ROLES))})"
            )

        # 2. Target decision must be overridable
        if request.target_decision not in self.OVERRIDABLE_DECISIONS:
            violations.append(
                f"override_target_not_overridable: {request.target_decision} "
                f"(overridable: {', '.join(sorted(self.OVERRIDABLE_DECISIONS))})"
            )

        # 3. Mandatory justification
        if not request.reason or len(request.reason.strip()) < 10:
            violations.append("override_justification_required_minimum_10_characters")

        # 4. Check dual approval for high-risk actions
        if request.requires_dual_approval and not request.approved_by:
            violations.append(
                "override_requires_dual_approval: a second approver must endorse this override"
            )

        # 5. Cannot override your own request
        if request.requested_by == request.approved_by:
            violations.append("override_self_approval_not_allowed")

        return len(violations) == 0, violations

    def create_override(
        self,
        identity: AuthIdentity,
        reason: str,
        target_decision: str,
        action: str,
    ) -> OverrideRequest:
        """Create a new override request from an authenticated identity."""
        requires_dual = action in self.DUAL_APPROVAL_ACTIONS
        return OverrideRequest(
            requested_by=identity.actor_id,
            role=identity.actor_role,
            reason=reason,
            target_decision=target_decision,
            requires_dual_approval=requires_dual,
            approved_by=None,
            approved_at=None,
            created_at=int(time.time() * 1000),
        )
