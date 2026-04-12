import pytest


@pytest.mark.skip(reason="Obsolete in-memory DB harness; covered by smoke/refuse integration tests.")
def test_gate_flow_with_in_memory_db():
    pass
