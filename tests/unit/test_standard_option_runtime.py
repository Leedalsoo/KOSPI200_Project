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

# Consolidated from tests\integration\test_standard_option_runtime_track4_integration.py; retained because it covers the same production boundary.

from datetime import datetime
from types import SimpleNamespace

import pytest

from core.runtime.standard_option_runtime import StandardOptionRuntime


AS_OF = datetime(2026, 1, 2, 10, 0)


class RecordingTrack4RuntimeStrategySeam:
    """Integration double preserving the real seam's evaluate_tick boundary."""

    def __init__(self):
        self.calls = []

    def evaluate_tick(self, tick, observed_at):
        self.calls.append((tick, observed_at))
        return ("track4-evaluation",)


def authoritative_tick(sequence=101, timestamp=AS_OF.isoformat()):
    return SimpleNamespace(source_sequence=sequence, timestamp=timestamp)


def test_standard_runtime_to_track4_seam_same_tick_boundary_is_lossless():
    seam = RecordingTrack4RuntimeStrategySeam()
    runtime = StandardOptionRuntime(seam)
    tick = authoritative_tick()

    result = runtime.process_tick(tick, AS_OF)

    assert result == ("track4-evaluation",)
    assert seam.calls == [(tick, AS_OF)]


def test_invalid_tick_is_rejected_before_track4_seam():
    seam = RecordingTrack4RuntimeStrategySeam()
    runtime = StandardOptionRuntime(seam)

    with pytest.raises(ValueError, match="RUNTIME_SOURCE_SEQUENCE_REQUIRED"):
        pass
        runtime.process_tick(authoritative_tick(sequence=None), AS_OF)

    assert seam.calls == []


def test_timestamp_mismatch_is_rejected_before_track4_seam():
    seam = RecordingTrack4RuntimeStrategySeam()
    runtime = StandardOptionRuntime(seam)

    with pytest.raises(ValueError, match="RUNTIME_TICK_TIMESTAMP_MISMATCH"):
        pass
        runtime.process_tick(authoritative_tick(timestamp="2026-01-02T10:00:01"), AS_OF)

    assert seam.calls == []
