from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from environments.high_speed.replay_runner import HighSpeedReplayRunner


class FakeClock:
    def __init__(self):
        self.sleeps: list[float] = []
        self.elapsed = 0.0

    def now(self):
        return datetime(2026, 10, 28, 9, 0, 0)

    def monotonic(self):
        return self.elapsed

    def sleep_policy(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("seconds must be non-negative")
        self.sleeps.append(seconds)
        self.elapsed += seconds


def tick(timestamp: str):
    return SimpleNamespace(timestamp=timestamp)


def test_replay_pacing_uses_injected_clock_without_system_sleep():
    clock = FakeClock()
    previous = tick("2026-10-28T09:00:00+09:00")
    current = tick("2026-10-28T09:00:02+09:00")

    HighSpeedReplayRunner._sleep_for_speed(previous, current, 2.0, clock)

    assert clock.sleeps == [1.0]
    assert clock.monotonic() == 1.0


def test_infinite_speed_does_not_sleep():
    clock = FakeClock()
    HighSpeedReplayRunner._sleep_for_speed(
        tick("2026-10-28T09:00:00+09:00"),
        tick("2026-10-28T09:00:02+09:00"),
        float("inf"),
        clock,
    )
    assert clock.sleeps == []


def test_non_positive_speed_fails_closed_with_injected_clock():
    clock = FakeClock()
    with pytest.raises(ValueError, match="REPLAY_SPEED_MUST_BE_POSITIVE"):
        HighSpeedReplayRunner._sleep_for_speed(
            tick("2026-10-28T09:00:00+09:00"),
            tick("2026-10-28T09:00:01+09:00"),
            0.0,
            clock,
        )
    assert clock.sleeps == []
