from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Iterator

from environments.virtual.market.canonical import ReferenceCanonicalMarketTick


class HistoricalMarketStore:
    """Append-only JSONL store for canonical market events.

    The store is source-neutral: real KRX-derived events, replay data, and
    synthetic events must be explicitly identified by the caller and must not
    be silently mixed.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, tick: ReferenceCanonicalMarketTick, *, source: str) -> None:
        source = str(source).strip()
        if not source:
            raise ValueError("MARKET_DATA_SOURCE_REQUIRED")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "schema": "reference-canonical-market-tick-v1",
            "source": source,
            "tick": tick.__dict__,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    def append_many(self, ticks: Iterable[ReferenceCanonicalMarketTick], *, source: str) -> int:
        count = 0
        for tick in ticks:
            self.append(tick, source=source)
            count += 1
        return count

    def records(self) -> Iterator[dict]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"INVALID_MARKET_DATA_RECORD_LINE:{line_number}") from exc
                if record.get("schema") != "reference-canonical-market-tick-v1":
                    raise ValueError(f"UNSUPPORTED_MARKET_DATA_SCHEMA_LINE:{line_number}")
                if not record.get("source"):
                    raise ValueError(f"MARKET_DATA_SOURCE_REQUIRED_LINE:{line_number}")
                yield record

    def load_ticks(self, *, source: str | None = None) -> list[ReferenceCanonicalMarketTick]:
        ticks: list[ReferenceCanonicalMarketTick] = []
        for record in self.records():
            if source is not None and record["source"] != source:
                continue
            ticks.append(ReferenceCanonicalMarketTick(**record["tick"]))
        return ticks
