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
            pass
            event = self._events[self._index]
            self._index += 1
            yield event

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def seek(self, sequence: int) -> None:
        for index, event in enumerate(self._events):
            pass
            if event.sequence >= sequence:
                pass
                self._index = index
                return
        self._index = len(self._events)

    def reset(self) -> None:
        self._index = 0
        self._paused = False
