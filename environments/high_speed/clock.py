from dataclasses import dataclass
from datetime import datetime, timedelta

@dataclass(frozen=True)
class AcceleratedClockConfig:
    speed_multiplier: float = 1.0

    def __post_init__(self) -> None:
        if self.speed_multiplier <= 0:
            raise ValueError("speed_multiplier must be > 0")

class AcceleratedClock:
    """Virtual-compatible clock; only time progression is accelerated."""
    def __init__(self, config: AcceleratedClockConfig, start: datetime) -> None:
        self.config = config
        self._current = start

    @property
    def now(self) -> datetime:
        return self._current

    def advance(self, elapsed_real_seconds: float) -> datetime:
        if elapsed_real_seconds < 0:
            raise ValueError("elapsed_real_seconds must be >= 0")
        self._current += timedelta(
            seconds=elapsed_real_seconds * self.config.speed_multiplier
        )
        return self._current

    def reset(self, start: datetime) -> None:
        self._current = start
