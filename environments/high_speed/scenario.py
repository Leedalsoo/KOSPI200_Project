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
