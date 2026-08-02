from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable, Optional

from lacunar_control.acquisition import AcquisitionSource
from lacunar_mirror_v0 import EngineState, TelemetryFrame
from .engine import Engine
from .lifecycle import LifecycleState, validate_transition
from .snapshot import RecorderSnapshot

Clock = Callable[[], float]


class RecorderSession:
    """
    INT-001: authoritative owner of recorder lifecycle and elapsed time.

    The UI and other consumers may request immutable snapshots, but they do not
    own or advance lifecycle state.
    """

    def __init__(
        self,
        log_path: Optional[Path] = None,
        clock: Clock = time.perf_counter,
        acquisition_source: Optional[AcquisitionSource] = None,
        engine: Optional[Engine] = None,
    ) -> None:
        self._clock = clock
        self._log_path = log_path
        self._acquisition_source: AcquisitionSource | None = acquisition_source
        self._engine: Engine | None = engine
        self._latest_engine_state: EngineState | None = None
        self._state = LifecycleState.READY
        self._started_at: Optional[float] = None
        self._stopped_at: Optional[float] = None

        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._sample_count = 0

    def start(self) -> None:
        with self._lock:
            validate_transition(self._state, LifecycleState.RECORDING)

            now = self._clock()
            self._started_at = now
            self._stopped_at = None
            self._state = LifecycleState.RECORDING
            self._sample_count = 0
            self._latest_engine_state = None
            self._stop_event.clear()
            self._worker = threading.Thread(
                target=self._worker_loop,
                name="lacunar-recorder-worker",
                daemon=True,
            )
            self._worker.start()

    def request_stop(self) -> None:
        with self._lock:
            validate_transition(self._state, LifecycleState.STOPPING)
            self._state = LifecycleState.STOPPING
            self._stop_event.set()

    def mark_recorded(self) -> None:
        with self._lock:
            validate_transition(self._state, LifecycleState.RECORDED)
            worker = self._worker

        if worker is not None:
            worker.join(timeout=1.0)

            if worker.is_alive():
                raise RuntimeError("Recorder worker did not stop")

        with self._lock:
            self._stopped_at = self._clock()
            self._state = LifecycleState.RECORDED

    def snapshot(self) -> RecorderSnapshot:
        with self._lock:
            return RecorderSnapshot(
                state=self._state,
                started_at=self._started_at,
                stopped_at=self._stopped_at,
                elapsed_seconds=self._elapsed_seconds_unlocked(),
                log_path=self._log_path,
                sample_count=self._sample_count,
                latest_engine_state=self._latest_engine_state,
            )

    @property
    def latest_engine_state(self) -> EngineState | None:
        with self._lock:
            return self._latest_engine_state

    def _elapsed_seconds_unlocked(self) -> float:
        if self._started_at is None:
            return 0.0

        end_time = (
            self._stopped_at
            if self._stopped_at is not None
            else self._clock()
        )

        return max(0.0, end_time - self._started_at)

    def _acquire_sample(self, dt: float = 0.01) -> None:
        """
        Perform one acquisition and engine-update cycle.
        """

        if self._acquisition_source is None:
            with self._lock:
                self._sample_count += 1
            return

        frame = self._acquire_frame()
        self._update_engine(frame, dt)

    def _acquire_frame(self) -> TelemetryFrame:
        """
        Acquire one telemetry frame and record the successful sample.
        """

        frame = self._acquisition_source.acquire()

        with self._lock:
            self._sample_count += 1

        return frame

    def _update_engine(
        self,
        frame: TelemetryFrame,
        dt: float,
    ) -> None:
        """
        Pass one telemetry frame to the engine.
        """

        if self._engine is None:
            return

        state = self._engine.step(frame, dt)

        with self._lock:
            self._latest_engine_state = state

    def _worker_loop(self) -> None:
        """
        Background worker owned by RecorderSession.
        """

        previous_time = self._clock()

        while not self._stop_event.wait(timeout=0.01):
            current_time = self._clock()
            dt = current_time - previous_time
            previous_time = current_time

            self._acquire_sample(dt=dt)

        with self._lock:
            self._stopped_at = self._clock()
            validate_transition(
                self._state,
                LifecycleState.RECORDED,
            )
            self._state = LifecycleState.RECORDED