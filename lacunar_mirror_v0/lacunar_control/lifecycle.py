from __future__ import annotations

from enum import Enum


class LifecycleState(str, Enum):
    """
    INT-002: authoritative RecorderSession lifecycle states.

    The initial implementation slice supports only:

        READY -> RECORDING -> STOPPING -> RECORDED
    """

    READY = "ready"
    RECORDING = "recording"
    STOPPING = "stopping"
    RECORDED = "recorded"


LEGAL_TRANSITIONS: dict[LifecycleState, frozenset[LifecycleState]] = {
    LifecycleState.READY: frozenset(
        {
            LifecycleState.RECORDING,
        }
    ),
    LifecycleState.RECORDING: frozenset(
        {
            LifecycleState.STOPPING,
        }
    ),
    LifecycleState.STOPPING: frozenset(
        {
            LifecycleState.RECORDED,
        }
    ),
    LifecycleState.RECORDED: frozenset(),
}


class IllegalLifecycleTransition(RuntimeError):
    """Raised when a caller attempts an invalid lifecycle transition."""


def validate_transition(
    current: LifecycleState,
    requested: LifecycleState,
) -> None:
    """
    Validate a lifecycle transition.

    This function does not change state. RecorderSession remains the authority
    that performs transitions after validation.
    """

    allowed = LEGAL_TRANSITIONS[current]

    if requested not in allowed:
        raise IllegalLifecycleTransition(
            f"Illegal lifecycle transition: "
            f"{current.value} -> {requested.value}"
        )
