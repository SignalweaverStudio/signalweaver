from __future__ import annotations

from typing import Protocol

from lacunar_mirror_v0 import EngineState, TelemetryFrame


class Engine(Protocol):
    def step(self, telemetry: TelemetryFrame, dt: float) -> EngineState:
        ...