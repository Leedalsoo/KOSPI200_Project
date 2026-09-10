from datetime import datetime
from types import SimpleNamespace

import pytest

from core.runtime.standard_option_runtime import StandardOptionRuntime


AS_OF = datetime(2026, 1, 2, 10, 0)


class StubSeam:
    def __init__(self):
        self.calls = []

    def evaluate_tick(self, tick, observed_at):
        self.calls.append((tick, observed_at))
        return ("evaluated",)


def valid_tick(sequence=17):
    return SimpleNamespace(
        source_sequence=sequence,
        timestamp=AS_OF.isoformat(),
    )


def test_process_tick_delegates_authoritative_tick_without_mutation():
    seam = StubSeam()
    runtime = StandardOptionRuntime(seam)
    tick = valid_tick()

    result = runtime.process_tick(tick, AS_OF)

    assert result == ("evaluated",)
    assert seam.calls == [(tick, AS_OF)]
    assert tick.source_sequence == 17


@pytest.mark.parametrize("sequence", [None, 0, -1])
def test_process_tick_rejects_missing_or_non_positive_authoritative_sequence(sequence):
    runtime = StandardOptionRuntime(StubSeam())
    tick = valid_tick(sequence)

    with pytest.raises(ValueError, match="RUNTIME_SOURCE_SEQUENCE_REQUIRED"):
        runtime.process_tick(tick, AS_OF)


def test_process_tick_rejects_timestamp_mismatch_before_strategy_evaluation():
    seam = StubSeam()
    runtime = StandardOptionRuntime(seam)
    tick = valid_tick()
    tick.timestamp = "2026-01-02T10:00:01"

    with pytest.raises(ValueError, match="RUNTIME_TICK_TIMESTAMP_MISMATCH"):
        runtime.process_tick(tick, AS_OF)

    assert seam.calls == []
