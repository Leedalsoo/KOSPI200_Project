from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from environments.high_speed.virtual_runtime_replay import HighSpeedVirtualRuntimeReplayRunner

DATASET = Path("data/derived_scenario/p5_run_20261026_trend_up_seed20261026")
RUN_ID = "R4-FULL-CLOCK-INDEPENDENCE-20261028"


class OffsetFakeClock:
    def __init__(self, wall_origin: datetime, monotonic_origin: float) -> None:
        self.wall_origin = wall_origin
        self.monotonic_origin = monotonic_origin
        self.elapsed = 0.0
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        return self.wall_origin + timedelta(seconds=self.elapsed)

    def monotonic(self) -> float:
        return self.monotonic_origin + self.elapsed

    def sleep_policy(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("CLOCK_SLEEP_NEGATIVE")
        self.sleeps.append(seconds)
        self.elapsed += seconds


def semantic(report):
    return {
        "dataset": report.dataset,
        "run_id": report.run_id,
        "events": report.events,
        "signals": report.signals,
        "approved": report.approved,
        "routed": report.routed,
        "filled": report.filled,
        "rejected": report.rejected,
        "execution_ids": list(report.execution_ids),
        "exhausted": report.exhausted,
        "pnl_status": report.pnl_status,
        "multi_leg_decisions": report.multi_leg_decisions,
        "strategy_signal_counts": list(report.strategy_signal_counts),
        "strategy_status": [asdict(x) for x in report.strategy_status],
        "realized_pnl": report.realized_pnl,
        "unrealized_pnl": report.unrealized_pnl,
        "net_pnl": report.net_pnl,
    }


def main() -> int:
    runs = []
    clocks = (
        OffsetFakeClock(datetime(2001, 1, 1), 1.0),
        OffsetFakeClock(datetime(2099, 12, 31, 23, 59, 59), 9_000_000.0),
    )
    for index, clock in enumerate(clocks, start=1):
        report = HighSpeedVirtualRuntimeReplayRunner(
            DATASET, run_id=RUN_ID, validation_only_synthetic=True, clock=clock
        ).run(speed=float("inf"))
        result = semantic(report)
        runs.append(result)
        print("RUN_" + str(index) + "=" + json.dumps(result, sort_keys=True), flush=True)
        print(
            f"RUN_{index}_TIMING=elapsed:{report.elapsed_seconds},throughput:{report.events_per_second},sleep_calls:{len(clock.sleeps)}",
            flush=True,
        )
    equal = runs[0] == runs[1]
    print("CLOCK_INDEPENDENCE_EQUAL=" + str(equal), flush=True)
    print("RUNS_COMPLETED=2", flush=True)
    return 0 if equal and all(x["events"] == 53550 and x["exhausted"] for x in runs) else 2


if __name__ == "__main__":
    raise SystemExit(main())
