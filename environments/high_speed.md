폴더 페이지

[Child Page] replay.py
```python
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator, Sequence

@dataclass(frozen=True)
class ReplayEvent:
    sequence: int
    observed_at: datetime
    payload: object

class ReplayStream:
    """Deterministic ordered input stream for High-Speed/Virtual reuse."""
    def __init__(self, events: Sequence[ReplayEvent]) -> None:
        self._events = tuple(sorted(events, key=lambda event: (event.observed_at, event.sequence)))
        self._index = 0
        self._paused = False

    def __iter__(self) -> Iterator[ReplayEvent]:
        while self._index < len(self._events) and not self._paused:
            event = self._events[self._index]
            self._index += 1
            yield event

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def seek(self, sequence: int) -> None:
        for index, event in enumerate(self._events):
            if event.sequence >= sequence:
                self._index = index
                return
        self._index = len(self._events)

    def reset(self) -> None:
        self._index = 0
        self._paused = False
```

[Child Page] speed_policy.py
```python
from dataclasses import dataclass

ALLOWED_SPEEDS = (1.0, 100.0, 300.0, 500.0, 1000.0)

@dataclass(frozen=True)
class HighSpeedPolicy:
    speed_multiplier: float = 1.0
    max_cpu_ratio: float = 0.90
    max_memory_ratio: float = 0.90

    def validate(self) -> None:
        if self.speed_multiplier not in ALLOWED_SPEEDS and self.speed_multiplier != float("inf"):
            raise ValueError("unsupported speed multiplier")
        if not 0 < self.max_cpu_ratio <= 1:
            raise ValueError("invalid max_cpu_ratio")
        if not 0 < self.max_memory_ratio <= 1:
            raise ValueError("invalid max_memory_ratio")

    @property
    def is_max(self) -> bool:
        return self.speed_multiplier == float("inf")
```

[Child Page] bundle.py
```python
from dataclasses import dataclass

from environments.high_speed.clock import AcceleratedClock, AcceleratedClockConfig
from environments.high_speed.replay import ReplayStream
from environments.high_speed.speed_policy import HighSpeedPolicy

@dataclass
class HighSpeedEnvironmentBundle:
    """High-Speed is a Virtual execution policy, not a second trading Core."""
    policy: HighSpeedPolicy
    clock: AcceleratedClock
    replay: ReplayStream

    @classmethod
    def create(cls, policy: HighSpeedPolicy, clock, replay: ReplayStream):
        policy.validate()
        accelerated = AcceleratedClock(
            AcceleratedClockConfig(policy.speed_multiplier), clock.now
        )
        return cls(policy=policy, clock=accelerated, replay=replay)

    def stop_safely(self, cpu_ratio: float, memory_ratio: float) -> bool:
        if cpu_ratio >= self.policy.max_cpu_ratio:
            return True
        if memory_ratio >= self.policy.max_memory_ratio:
            return True
        return False
```

[Child Page] scenario.py
```python
from dataclasses import dataclass
from typing import Sequence

@dataclass(frozen=True)
class ScenarioEvent:
    sequence: int
    kind: str
    payload: object

class DeterministicScenario:
    """Explicit event stream; randomness must be seeded outside this boundary."""
    def __init__(self, events: Sequence[ScenarioEvent]) -> None:
        self._events = tuple(sorted(events, key=lambda event: event.sequence))

    def events(self) -> tuple[ScenarioEvent, ...]:
        return self._events

    def fingerprint(self) -> tuple[tuple[int, str], ...]:
        return tuple((event.sequence, event.kind) for event in self._events)
```

[Child Page] clock.py
```python
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
```

[Child Page] README.md
High-Speed is not a fifth trading system. It is the Virtual Environment executed with accelerated Clock/Replay/Scenario policies.
The Standard Option Core and Strategy are never duplicated. The speed multiplier changes execution time, not trading meaning.
Paper/Live credentials are prohibited by construction and must not be reachable from this package.

[Child Page] SAFETY_BOUNDARY.md
    - High-Speed has no live credential path.
    - High-Speed must not import Paper/Live adapters.
    - MAX speed must stop safely when resource thresholds are reached.
    - A replay failure must stop the current run and preserve the scenario/result evidence.
    - Speed multiplication is applied to Clock progression only; it must not alter order semantics, strategy rules, risk rules, or position rules.
    - Calendar source work remains outside this phase; the existing Calendar Simulator is treated as Virtual simulation input, not as proof of a real KRX calendar source.

[Child Page] contract_identity.py
```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterator, Sequence


@dataclass(frozen=True)
class ScenarioEvent:
    sequence: int
    kind: str
    payload: object
    scenario_contract_key: str | None = None


class DeterministicScenario:
    """Explicit event stream; contract identity is optional metadata."""

    def __init__(self, events: Sequence[ScenarioEvent]) -> None:
        self._events = tuple(sorted(events, key=lambda event: event.sequence))

    def events(self) -> tuple[ScenarioEvent, ...]:
        return self._events

    def fingerprint(self) -> tuple[tuple[int, str], ...]:
        return tuple((event.sequence, event.kind) for event in self._events)


@dataclass(frozen=True)
class ReplayEvent:
    sequence: int
    observed_at: datetime
    payload: object
    scenario_contract_key: str | None = None


class ReplayStream:
    """Deterministic ordered input stream for High-Speed/Virtual reuse."""

    def __init__(self, events: Sequence[ReplayEvent]) -> None:
        self._events = tuple(
            sorted(events, key=lambda event: (event.observed_at, event.sequence))
        )
        self._index = 0
        self._paused = False

    def __iter__(self) -> Iterator[ReplayEvent]:
        while self._index < len(self._events) and not self._paused:
            event = self._events[self._index]
            self._index += 1
            yield event

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def seek(self, sequence: int) -> None:
        for index, event in enumerate(self._events):
            if event.sequence >= sequence:
                self._index = index
                return
        self._index = len(self._events)

    def reset(self) -> None:
        self._index = 0
        self._paused = False
```
## 경계
기존 ScenarioEvent/ReplayEvent의 payload 구조를 변경하지 않고 선택적 scenario_contract_key metadata만 추가한다.
    - 기존 호출 호환성 유지: 기본값 None
    - identity가 필요한 Virtual 구성에서는 key 존재 여부를 composition validation에서 별도로 검사
    - High-Speed deterministic ordering/fingerprint semantics 유지
    - Scenario/Replay가 KIS identity를 직접 해석하지 않음