from collections.abc import Iterable
from typing import List, Optional

from environments.virtual.market.canonical import ReferenceCanonicalMarketTick
from environments.virtual.market.historical_market_store import HistoricalMarketStore


class HistoricalReplayEngine:
    def __init__(self, ticks: Optional[Iterable[ReferenceCanonicalMarketTick]] = None) -> None:
        self._ticks: List[ReferenceCanonicalMarketTick] = list(ticks or [])
        self._cursor = 0

    @classmethod
    def from_store(cls, store: HistoricalMarketStore, *, source: str | None = None) -> "HistoricalReplayEngine":
        return cls(store.load_ticks(source=source))

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

    def load_store(self, store: HistoricalMarketStore, *, source: str | None = None) -> None:
        self.load(store.load_ticks(source=source))

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
