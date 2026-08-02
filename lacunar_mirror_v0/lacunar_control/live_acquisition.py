from __future__ import annotations

from typing import Optional

from lacunar_mirror_v0 import LiveTimingTelemetry, TelemetryFrame


class LiveAcquisitionSource:
    """
    Adapts LiveTimingTelemetry to the AcquisitionSource protocol.
    """

    def __init__(self, telemetry: LiveTimingTelemetry) -> None:
        self._telemetry = telemetry
        self._latest_frame: Optional[TelemetryFrame] = None
        self._started = False

    def start(self) -> None:
        if not self._started:
            self._telemetry.start()
            self._started = True

    def stop(self) -> None:
        if self._started:
            self._telemetry.stop()
            self._started = False

    def acquire(self) -> TelemetryFrame:
        if not self._started:
            self.start()

        self._latest_frame = self._telemetry.sample()
        return self._latest_frame

    @property
    def latest_frame(self) -> Optional[TelemetryFrame]:
        return self._latest_frame