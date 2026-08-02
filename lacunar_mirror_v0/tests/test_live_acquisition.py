from lacunar_control.live_acquisition import LiveAcquisitionSource


def test_live_acquisition_stores_latest_frame() -> None:
    expected_frame = object()

    class FakeTelemetry:
        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

        def sample(self) -> object:
            return expected_frame

    source = LiveAcquisitionSource(FakeTelemetry())

    assert source.latest_frame is None

    returned_frame = source.acquire()

    assert returned_frame is expected_frame
    assert source.latest_frame is expected_frame