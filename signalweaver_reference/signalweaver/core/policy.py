"""
core/policy.py

Static local policy pack.

Policies are pure functions: (MachineTraceFrame) -> PolicySignal.
No dynamic loading. No external calls. No state mutation.

A PolicySignal carries:
- verdict:    one of PROCEED / EXPLORE / GATE / REFUSE (integer 0-3)
- reason:     human-readable string, stable for a given input
- policy_id:  stable identifier for the policy that fired

Policies are registered in POLICY_REGISTRY — a plain list, evaluated in
declaration order. The evaluator (evaluator.py) applies monotonic escalation
across all signals; the highest verdict wins.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List

# Verdict constants — integers so that max() gives the dominant verdict
PROCEED = 0
EXPLORE = 1
GATE    = 2
REFUSE  = 3

VERDICT_NAMES = {
    PROCEED: "PROCEED",
    EXPLORE: "EXPLORE",
    GATE:    "GATE",
    REFUSE:  "REFUSE",
}


# ---------------------------------------------------------------------------
# PolicySignal
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PolicySignal:
    """
    The output of a single policy evaluation.

    Fields
    ------
    verdict    : One of PROCEED(0), EXPLORE(1), GATE(2), REFUSE(3).
    reason     : Stable, human-readable string describing why.
    policy_id  : Identifier of the policy that produced this signal.
    """
    verdict:   int
    reason:    str
    policy_id: str

    def __post_init__(self) -> None:
        if self.verdict not in VERDICT_NAMES:
            raise ValueError(f"verdict must be 0-3, got {self.verdict!r}")
        if not self.policy_id:
            raise ValueError("policy_id must be non-empty")

    def verdict_name(self) -> str:
        return VERDICT_NAMES[self.verdict]

    def to_dict(self) -> dict:
        return {
            "verdict":     self.verdict,
            "verdict_name": self.verdict_name(),
            "reason":      self.reason,
            "policy_id":   self.policy_id,
        }


# ---------------------------------------------------------------------------
# Policy function type
# ---------------------------------------------------------------------------

PolicyFn = Callable[["MachineTraceFrame"], PolicySignal]  # type: ignore[name-defined]


# ---------------------------------------------------------------------------
# Static policy definitions
# ---------------------------------------------------------------------------

def policy_default_proceed(frame) -> PolicySignal:
    """
    POL-000: Baseline — every frame PROCEEDs unless another policy fires higher.
    Always runs. Always returns PROCEED.
    """
    return PolicySignal(
        verdict=PROCEED,
        reason="No policy constraint matched. Default pass-through.",
        policy_id="POL-000",
    )


def policy_treasury_threshold(frame) -> PolicySignal:
    """
    POL-100: Treasury transfer threshold guard.

    Fires GATE if:
    - action is "transfer.outbound"
    - payload contains "amount_pence" (int)
    - amount_pence > 10_000_00  (£10,000 in pence — 1,000,000)

    Fires REFUSE if amount_pence > 100_000_00  (£100,000 in pence — 10,000,000)
    """
    if frame.action != "transfer.outbound":
        return PolicySignal(verdict=PROCEED, reason="Action not in scope.", policy_id="POL-100")

    amount = frame.payload.get("amount_pence")
    if not isinstance(amount, int):
        return PolicySignal(
            verdict=EXPLORE,
            reason="transfer.outbound payload missing integer amount_pence.",
            policy_id="POL-100",
        )

    # Hard refusal: > £100k
    if amount > 10_000_000:
        return PolicySignal(
            verdict=REFUSE,
            reason=(
                f"Transfer amount {amount} pence exceeds hard REFUSE threshold "
                f"(10,000,000 pence / £100,000)."
            ),
            policy_id="POL-100",
        )

    # Soft gate: > £10k
    if amount > 1_000_000:
        return PolicySignal(
            verdict=GATE,
            reason=(
                f"Transfer amount {amount} pence exceeds GATE threshold "
                f"(1,000,000 pence / £10,000). Human approval required."
            ),
            policy_id="POL-100",
        )

    return PolicySignal(
        verdict=PROCEED,
        reason=f"Transfer amount {amount} pence within permitted threshold.",
        policy_id="POL-100",
    )


def policy_treasury_velocity(frame) -> PolicySignal:
    """
    POL-101: Treasury velocity anomaly guard.

    Fires GATE if:
    - action is "transfer.outbound"
    - payload contains "velocity_transfers_1h" (int)
    - velocity_transfers_1h >= 5

    This represents: too many transfers in the last hour, regardless of amount.
    No external state is queried — the frame is expected to carry a pre-computed
    velocity counter (produced by the upstream system being governed).
    """
    if frame.action != "transfer.outbound":
        return PolicySignal(verdict=PROCEED, reason="Action not in scope.", policy_id="POL-101")

    velocity = frame.payload.get("velocity_transfers_1h")
    if not isinstance(velocity, int):
        return PolicySignal(
            verdict=PROCEED,
            reason="No velocity field present — skipping velocity policy.",
            policy_id="POL-101",
        )

    if velocity >= 5:
        return PolicySignal(
            verdict=GATE,
            reason=(
                f"Velocity anomaly: {velocity} outbound transfers in the last hour "
                f"meets or exceeds threshold (5). Human review required."
            ),
            policy_id="POL-101",
        )

    return PolicySignal(
        verdict=PROCEED,
        reason=f"Velocity {velocity}/h within permitted range.",
        policy_id="POL-101",
    )


def policy_actor_blocklist(frame) -> PolicySignal:
    """
    POL-200: Static actor blocklist.

    Fires REFUSE for any action from a blocked actor identity.
    Blocklist is hardcoded — no external lookups.
    """
    _BLOCKED_ACTORS = frozenset({
        "actor:system:compromised",
        "actor:test:force_refuse",
    })

    if frame.actor in _BLOCKED_ACTORS:
        return PolicySignal(
            verdict=REFUSE,
            reason=f"Actor {frame.actor!r} is on the static blocklist.",
            policy_id="POL-200",
        )

    return PolicySignal(
        verdict=PROCEED,
        reason="Actor not on blocklist.",
        policy_id="POL-200",
    )


def policy_tag_sensitive(frame) -> PolicySignal:
    """
    POL-300: Sensitive tag escalation.

    Any frame tagged "sensitive" that is also tagged "unreviewed" is GATEd.
    Both tags must be present for the policy to fire above PROCEED.
    """
    has_sensitive   = "sensitive" in frame.tags
    has_unreviewed  = "unreviewed" in frame.tags

    if has_sensitive and has_unreviewed:
        return PolicySignal(
            verdict=GATE,
            reason="Frame carries both 'sensitive' and 'unreviewed' tags. Gating for review.",
            policy_id="POL-300",
        )

    return PolicySignal(
        verdict=PROCEED,
        reason="Tag combination does not trigger escalation.",
        policy_id="POL-300",
    )


# ---------------------------------------------------------------------------
# Policy registry — evaluated in order, highest verdict wins
# ---------------------------------------------------------------------------

POLICY_REGISTRY: List[PolicyFn] = [
    policy_default_proceed,      # POL-000 — baseline
    policy_treasury_threshold,   # POL-100 — amount threshold
    policy_treasury_velocity,    # POL-101 — velocity anomaly
    policy_actor_blocklist,      # POL-200 — blocked actors
    policy_tag_sensitive,        # POL-300 — sensitive tag pair
]
