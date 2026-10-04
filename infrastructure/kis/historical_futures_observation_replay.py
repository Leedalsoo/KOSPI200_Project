from __future__ import annotations

import json
from bisect import bisect_right
from datetime import datetime
from pathlib import Path

from contracts.kis_index_futures_market_ws_adapter import (
    KISIndexFuturesMarketWebSocketAdapter,
    KisIndexFuturesMarketObservation,
)


class HistoricalFuturesObservationReplay:
    """Replay REAL_VTS H0IFCNT0 observations by raw received_at order."""

    def __init__(self, raw_path: str | Path, *, adapter: KISIndexFuturesMarketWebSocketAdapter | None = None) -> None:
        self.raw_path = Path(raw_path)
        self.adapter = adapter or KISIndexFuturesMarketWebSocketAdapter()
        self._events: list[tuple[datetime, KisIndexFuturesMarketObservation]] = []
        self._times: list[datetime] = []
        self._cursor = 0
        self._load()

    def _load(self) -> None:
        if not self.raw_path.is_file():
            raise FileNotFoundError(str(self.raw_path))
        with self.raw_path.open("r", encoding="utf-8-sig") as handle:
            for line in handle:
                record = json.loads(line)
                if record.get("tr_id") != "H0IFCNT0":
                    continue
                received_at = datetime.fromisoformat(str(record["received_at"]))
                payload = str(record["payload"])
                for observation in self.adapter.adapt_many(payload, source="KIS:H0IFCNT0"):
                    self._events.append((received_at, observation))
        self._events.sort(key=lambda item: item[0])
        self._times = [item[0] for item in self._events]

    @property
    def total_events(self) -> int:
        return len(self._events)

    @property
    def consumed_events(self) -> int:
        return self._cursor

    def consume_until(self, timestamp: str | datetime) -> tuple[KisIndexFuturesMarketObservation, ...]:
        target = timestamp if isinstance(timestamp, datetime) else datetime.fromisoformat(str(timestamp))
        end = bisect_right(self._times, target, lo=self._cursor)
        observations = tuple(item[1] for item in self._events[self._cursor:end])
        self._cursor = end
        return observations

    def reset(self) -> None:
        self._cursor = 0
