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
