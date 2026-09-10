from datetime import datetime, timedelta

import pytest

from environments.virtual.clock.vms_clock_provider_adapter import VMSClockProvider


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
