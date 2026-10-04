from __future__ import annotations

import json
from bisect import bisect_right
from datetime import datetime
from pathlib import Path

from contracts.kis_index_price_source import KISIndexPriceObservation
from contracts.kis_index_price_websocket_adapter import KISIndexPriceWebSocketAdapter


class HistoricalIndexPriceObservationReplay:
    """Replay REAL_VTS H0UPCNT0 observations by raw received_at order."""

    def __init__(self, raw_path: str | Path, *, adapter: KISIndexPriceWebSocketAdapter | None = None) -> None:
        self.raw_path = Path(raw_path)
        self.adapter = adapter or KISIndexPriceWebSocketAdapter()
        self._events: list[tuple[datetime, KISIndexPriceObservation]] = []
        self._times: list[datetime] = []
        self._cursor = 0
        self._load()

    def _load(self) -> None:
        if not self.raw_path.is_file():
            raise FileNotFoundError(str(self.raw_path))
        with self.raw_path.open("r", encoding="utf-8-sig") as handle:
            for line in handle:
                record = json.loads(line)
                if record.get("tr_id") != "H0UPCNT0":
                    continue
                received_at = datetime.fromisoformat(str(record["received_at"]))
                payload = str(record["payload"])
                observed_hour = payload.split("|")[3].split("^")[1].strip()
                if len(observed_hour) not in {6, 9} or not observed_hour.isdigit() or int(observed_hour[:2]) > 23:
                    continue
                observation = self.adapter.adapt(payload, source="KIS:H0UPCNT0")
                observed_at = received_at.replace(
                    hour=int(observation.observed_hour[:2]),
                    minute=int(observation.observed_hour[2:4]),
                    second=int(observation.observed_hour[4:6]),
                    microsecond=(int(observation.observed_hour[6:9]) * 1000 if len(observation.observed_hour) == 9 else 0),
                    tzinfo=None,
                )
                self._events.append((received_at, KISIndexPriceObservation(
                    underlying_symbol="KOSPI200",
                    index_code="2001",
                    price=observation.price,
                    observed_at=observed_at,
                    collected_at=received_at,
                    source=observation.source,
                    tr_id="H0UPCNT0",
                )))
        self._events.sort(key=lambda item: item[0])
        self._times = [item[0] for item in self._events]

    @property
    def total_events(self) -> int:
        return len(self._events)

    @property
    def consumed_events(self) -> int:
        return self._cursor

    def consume_until(self, timestamp: str | datetime) -> tuple[KISIndexPriceObservation, ...]:
        target = timestamp if isinstance(timestamp, datetime) else datetime.fromisoformat(str(timestamp))
        end = bisect_right(self._times, target, lo=self._cursor)
        observations = tuple(item[1] for item in self._events[self._cursor:end])
        self._cursor = end
        return observations

    def reset(self) -> None:
        self._cursor = 0
