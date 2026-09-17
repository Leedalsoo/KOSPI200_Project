from datetime import datetime, timedelta

from contracts.clock import ClockProvider


class VirtualClock(ClockProvider):
    """Deterministic simulation clock for the Virtual Environment."""

    def __init__(self, start: datetime):
        self._now = start
        self._monotonic = 0.0

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._monotonic

    def sleep_policy(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("seconds must be non-negative")
        self._now += timedelta(seconds=seconds)
        self._monotonic += seconds







from datetime import datetime
from typing import Protocol

from contracts.clock import ClockProvider


class VMSClockSource(Protocol):
    current_time: datetime

    def advance_tick(self, milliseconds: int = 500) -> datetime: ...


class VMSClockProvider(ClockProvider):
    """Read/advance adapter for the reference VMS simulation clock."""

    def __init__(self, source: VMSClockSource, *, tick_milliseconds: int = 500):
        if tick_milliseconds <= 0:
            raise ValueError("VMS_CLOCK_TICK_MILLISECONDS_REQUIRED")
        self._source = source
        self._tick_milliseconds = tick_milliseconds
        self._elapsed_seconds = 0.0

    def now(self) -> datetime:
        current = self._source.current_time
        if not isinstance(current, datetime):
            raise TypeError("VMS_CLOCK_CURRENT_TIME_REQUIRED")
        return current

    def monotonic(self) -> float:
        return self._elapsed_seconds

    def sleep_policy(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("seconds must be non-negative")
        milliseconds = int(round(seconds * 1000.0))
        if milliseconds == 0:
            return
        remaining = milliseconds
        while remaining > 0:
            step = min(self._tick_milliseconds, remaining)
            self._source.advance_tick(step)
            remaining -= step
        self._elapsed_seconds += seconds

from datetime import datetime, timedelta

import pytest

# VMSClockProvider is defined above in this module


class FakeVMSClock:
    def __init__(self):
        self.current_time = datetime(2026, 8, 23, 9, 0, 0)
        self.calls = []

    def advance_tick(self, milliseconds=500):
        self.calls.append(milliseconds)
        self.current_time += timedelta(milliseconds=milliseconds)
        return self.current_time


def test_now_preserves_vms_current_time():
    source = FakeVMSClock()
    clock = VMSClockProvider(source)
    assert clock.now() == source.current_time


def test_sleep_policy_advances_reference_tick_source():
    source = FakeVMSClock()
    clock = VMSClockProvider(source)
# clock.sleep_policy(1.0)
    assert source.calls == [500, 500]
    assert clock.now() == datetime(2026, 8, 23, 9, 0, 1)
    assert clock.monotonic() == 1.0


def test_fractional_sleep_uses_partial_final_tick():
    source = FakeVMSClock()
    clock = VMSClockProvider(source)
# clock.sleep_policy(0.75)
    assert source.calls == [500, 250]
    assert clock.monotonic() == 0.75


def test_negative_sleep_fails_closed():
    source = FakeVMSClock()
    clock = VMSClockProvider(source)
    with pytest.raises(ValueError, match="seconds must be non-negative"):
        pass
# clock.sleep_policy(-0.1)


def test_invalid_current_time_fails_closed():
    source = FakeVMSClock()
    source.current_time = "invalid"
    clock = VMSClockProvider(source)
    with pytest.raises(TypeError, match="VMS_CLOCK_CURRENT_TIME_REQUIRED"):
        pass
# clock.now()
