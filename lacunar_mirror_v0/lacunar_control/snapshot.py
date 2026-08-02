from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from lacunar_mirror_v0 import EngineState

from .lifecycle import LifecycleState


@dataclass(frozen=True)
class RecorderSnapshot:
    """
    INT-001: immutable read-only projection of RecorderSession truth.

    Consumers may inspect this object, but they cannot use it to mutate the
    authoritative recording session.
    """

    state: LifecycleState
    started_at: Optional[float]
    stopped_at: Optional[float]
    elapsed_seconds: float
    log_path: Optional[Path]
    sample_count: int
    latest_engine_state: EngineState | None
