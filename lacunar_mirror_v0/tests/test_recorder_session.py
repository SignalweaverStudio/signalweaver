from dataclasses import FrozenInstanceError
import threading

import pytest

from lacunar_control.lifecycle import (
    IllegalLifecycleTransition,
    LifecycleState,
)
from lacunar_control.recorder_session import RecorderSession


class FakeClock:
    def __init__(self, initial: float = 0.0) -> None:
        self._now = initial

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def test_INT_002_session_follows_legal_transition_order() -> None:
    session = RecorderSession()

    assert session.snapshot().state is LifecycleState.READY

    session.start()
    assert session.snapshot().state is LifecycleState.RECORDING

    session.request_stop()
    assert session.snapshot().state is LifecycleState.STOPPING

    session.mark_recorded()
    assert session.snapshot().state is LifecycleState.RECORDED


def test_INT_002_illegal_transition_is_rejected() -> None:
    session = RecorderSession()

    with pytest.raises(IllegalLifecycleTransition):
        session.request_stop()


def test_INT_001_elapsed_time_is_backend_owned() -> None:
    current_time = 100.0

    def fake_clock() -> float:
        return current_time

    session = RecorderSession(clock=fake_clock)
    session.start()

    current_time = 101.5
    assert session.snapshot().elapsed_seconds == 1.5

    session.request_stop()

    current_time = 101.75
    session.mark_recorded()

    frozen = session.snapshot().elapsed_seconds
    assert frozen == 1.75

    current_time = 200.0
    assert session.snapshot().elapsed_seconds == frozen


def test_INT_001_snapshot_is_immutable() -> None:
    session = RecorderSession()
    snapshot = session.snapshot()

    with pytest.raises(FrozenInstanceError):
        snapshot.elapsed_seconds = 10.0


def test_INT_001_snapshot_does_not_mutate_session() -> None:
    session = RecorderSession()
    first = session.snapshot()
    second = session.snapshot()

    assert first is not second
    assert first == second


def test_worker_thread_stops_cleanly() -> None:
    session = RecorderSession()

    session.start()

    worker = session._worker
    assert worker is not None
    assert worker.is_alive()

    session.request_stop()
    session.mark_recorded()

    assert not worker.is_alive()


def test_acquire_sample_increments_count() -> None:
    session = RecorderSession()

    assert session.snapshot().sample_count == 0

    session._acquire_sample()

    assert session.snapshot().sample_count == 1


def test_acquisition_source_is_called() -> None:
    calls = []

    class FakeAcquisitionSource:
        def acquire(self) -> object:
            calls.append("called")
            return object()

    session = RecorderSession(
        acquisition_source=FakeAcquisitionSource(),
    )

    session._acquire_sample()

    assert calls == ["called"]
    assert session.snapshot().sample_count == 1


def test_worker_invokes_acquisition_source() -> None:
    calls = []
    acquisition_event = threading.Event()

    class FakeAcquisitionSource:
        def acquire(self) -> None:
            calls.append("called")
            if len(calls) >= 2:
                acquisition_event.set()

    session = RecorderSession(
        acquisition_source=FakeAcquisitionSource(),
    )

    session.start()

    assert acquisition_event.wait(timeout=1.0)

    session.request_stop()
    session.mark_recorded()

    assert len(calls) >= 2


def test_acquisition_frame_is_passed_to_engine() -> None:
    expected_frame = object()
    expected_state = object()

    class FakeAcquisitionSource:
        def acquire(self) -> object:
            return expected_frame

    class FakeEngine:
        def __init__(self) -> None:
            self.calls = []

        def step(self, telemetry: object, dt: float) -> object:
            self.calls.append((telemetry, dt))
            return expected_state

    engine = FakeEngine()
    session = RecorderSession(
        acquisition_source=FakeAcquisitionSource(),
        engine=engine,
    )

    session._acquire_sample(dt=0.25)

    assert engine.calls == [(expected_frame, 0.25)]
    assert session.latest_engine_state is expected_state


def test_worker_loop_passes_measured_dt() -> None:
    class FakeStopEvent:
        def __init__(self) -> None:
            self.calls = 0

        def wait(self, timeout: float) -> bool:
            self.calls += 1
            return self.calls > 1

    clock_values = iter([10.0, 10.25, 10.25])
    received_dt = []

    session = RecorderSession()
    session._state = LifecycleState.STOPPING
    session._clock = lambda: next(clock_values)
    session._stop_event = FakeStopEvent()
    session._acquire_sample = lambda dt: received_dt.append(dt)

    session._worker_loop()

    assert received_dt == [0.25]


def test_failed_acquisition_does_not_increment_count() -> None:
    class FailingAcquisitionSource:
        def acquire(self) -> object:
            raise RuntimeError("acquisition failed")

    session = RecorderSession(
        acquisition_source=FailingAcquisitionSource(),
    )

    with pytest.raises(RuntimeError, match="acquisition failed"):
        session._acquire_sample()

    assert session.snapshot().sample_count == 0


def test_snapshot_includes_latest_engine_state() -> None:
    expected_frame = object()
    expected_state = object()

    class FakeAcquisitionSource:
        def acquire(self) -> object:
            return expected_frame

    class FakeEngine:
        def step(self, telemetry: object, dt: float) -> object:
            return expected_state

    session = RecorderSession(
        acquisition_source=FakeAcquisitionSource(),
        engine=FakeEngine(),
    )

    assert session.snapshot().latest_engine_state is None

    session._acquire_sample(dt=0.25)

    assert session.snapshot().latest_engine_state is expected_state


def test_start_resets_latest_engine_state() -> None:
    session = RecorderSession()

    previous_state = object()
    session._latest_engine_state = previous_state

    session.start()

    assert session.latest_engine_state is None

    session.request_stop()
    session._worker.join(timeout=1.0)