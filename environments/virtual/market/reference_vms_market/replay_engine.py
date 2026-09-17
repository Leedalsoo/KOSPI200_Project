from collections.abc import Iterable, Iterator
from typing import List, Optional
from environments.virtual.market.reference_vms_market.canonical import ReferenceCanonicalMarketTick


class HistoricalReplayEngine:
    def __init__(self, ticks: Optional[Iterable[ReferenceCanonicalMarketTick]] = None) -> None:
        self._ticks: List[ReferenceCanonicalMarketTick] = list(ticks or [])
        self._cursor = 0

    @property
    def active(self) -> bool:
        return bool(self._ticks)

    @property
    def exhausted(self) -> bool:
        return self._cursor >= len(self._ticks)

    @property
    def cursor(self) -> int:
        return self._cursor

    def load(self, ticks: Iterable[ReferenceCanonicalMarketTick]) -> None:
        self._ticks = list(ticks)
        self._cursor = 0

    def clear(self) -> None:
        self._ticks = []
        self._cursor = 0

    def reset(self) -> None:
        self._cursor = 0

    def next_tick(self) -> Optional[ReferenceCanonicalMarketTick]:
        if self.exhausted:
            return None
        tick = self._ticks[self._cursor]
        self._cursor += 1
        return tick
