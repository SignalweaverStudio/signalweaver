from typing import Protocol

from lacunar_mirror_v0 import TelemetryFrame


class AcquisitionSource(Protocol):
    def acquire(self) -> TelemetryFrame:
        ...