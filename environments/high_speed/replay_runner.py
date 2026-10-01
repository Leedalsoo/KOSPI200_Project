from __future__ import annotations
import argparse
import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from environments.virtual.market.canonical import ReferenceCanonicalMarketTick

@dataclass(frozen=True)
class ReplayReport:
    dataset: str
    events: int
    first_timestamp: str | None
    last_timestamp: str | None
    elapsed_seconds: float
    events_per_second: float
    speed: float
    exhausted: bool

class HighSpeedReplayRunner:
    """Period-independent replay runner for synthetic or historical canonical ticks."""
    def __init__(self, dataset_path: str | Path):
        self.root = Path(dataset_path)

    def _files(self, start: str | None, end: str | None) -> list[Path]:
        files = sorted(self.root.glob("*.jsonl"))
        selected = []
        for path in files:
            try:
                day = path.stem
                if start and day < start:
                    continue
                if end and day > end:
                    continue
                datetime.strptime(day, "%Y-%m-%d")
            except ValueError:
                continue
            selected.append(path)
        return selected

    def events(self, start: str | None = None, end: str | None = None) -> Iterable[ReferenceCanonicalMarketTick]:
        for path in self._files(start, end):
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    if record.get("provenance") not in {"SYNTHETIC", "DERIVED_SCENARIO"}:
                        raise ValueError("SYNTHETIC_DATASET_PROVENANCE_REQUIRED")
                    if record.get("schema") != "reference-canonical-market-tick-v1":
                        raise ValueError("UNSUPPORTED_SYNTHETIC_DATASET_SCHEMA")
                    yield ReferenceCanonicalMarketTick(**record["tick"])

    @staticmethod
    def _sleep_for_speed(previous: ReferenceCanonicalMarketTick | None,
                         current: ReferenceCanonicalMarketTick, speed: float) -> None:
        if speed <= 0:
            raise ValueError("REPLAY_SPEED_MUST_BE_POSITIVE")
        if speed == float("inf") or previous is None:
            return
        delta = (
            datetime.fromisoformat(current.timestamp)
            - datetime.fromisoformat(previous.timestamp)
        ).total_seconds()
        if delta > 0:
            time.sleep(delta / speed)
    def run(
        self,
        *,
        start: str | None = None,
        end: str | None = None,
        speed: float = float("inf"),
        on_event: Callable[[ReferenceCanonicalMarketTick], None] | None = None,
        max_events: int | None = None,
    ) -> ReplayReport:
        started = time.perf_counter()
        count = 0
        first = None
        last = None
        for tick in self.events(start, end):
            self._sleep_for_speed(last, tick, speed)
            if first is None:
                first = tick.timestamp
            if on_event is not None:
                on_event(tick)
            last = tick
            count += 1
            if max_events is not None and count >= max_events:
                break
        elapsed = max(time.perf_counter() - started, 1e-9)
        return ReplayReport(
            dataset=self.root.name,
            events=count,
            first_timestamp=first,
            last_timestamp=last.timestamp if last else None,
            elapsed_seconds=elapsed,
            events_per_second=count / elapsed,
            speed=speed,
            exhausted=max_events is None or count < max_events,
        )

def main() -> None:
    parser = argparse.ArgumentParser(description="Period-independent high-speed market replay")
    parser.add_argument("--dataset", default="data/synthetic_market_data/1y_5min_v1")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--speed", type=float, default=float("inf"))
    parser.add_argument("--max-events", type=int)
    args = parser.parse_args()
    report = HighSpeedReplayRunner(args.dataset).run(
        start=args.start, end=args.end, speed=args.speed, max_events=args.max_events
    )
    print(json.dumps({
        "dataset": report.dataset,
        "events": report.events,
        "first_timestamp": report.first_timestamp,
        "last_timestamp": report.last_timestamp,
        "elapsed_seconds": round(report.elapsed_seconds, 6),
        "events_per_second": round(report.events_per_second, 2),
        "speed": "inf" if report.speed == float("inf") else report.speed,
        "exhausted": report.exhausted,
    }, ensure_ascii=False))

if __name__ == "__main__":
    main()
