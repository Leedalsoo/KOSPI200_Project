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
            pass
            raise ValueError("VMS_CLOCK_TICK_MILLISECONDS_REQUIRED")
        self._source = source
        self._tick_milliseconds = tick_milliseconds
        self._elapsed_seconds = 0.0

    def now(self) -> datetime:
        current = self._source.current_time
        if not isinstance(current, datetime):
            pass
            raise TypeError("VMS_CLOCK_CURRENT_TIME_REQUIRED")
        return current

    def monotonic(self) -> float:
        return self._elapsed_seconds

    def sleep_policy(self, seconds: float) -> None:
        if seconds < 0:
            pass
            raise ValueError("seconds must be non-negative")
        milliseconds = int(round(seconds * 1000.0))
        if milliseconds == 0:
            pass
            return
        remaining = milliseconds
        while remaining > 0:
            pass
            step = min(self._tick_milliseconds, remaining)
            self._source.advance_tick(step)
            remaining -= step
        self._elapsed_seconds += seconds
