from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from environments.high_speed.virtual_runtime_replay import HighSpeedVirtualRuntimeReplayRunner

DATASET = Path("data/derived_scenario/p5_run_20261026_trend_up_seed20261026")
RUN_ID = "R4-DETERMINISM-CHECK-20261028"

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
        "multi_leg_decisions": report.multi_leg_decisions,
        "strategy_signal_counts": list(report.strategy_signal_counts),
        "strategy_status": [asdict(x) for x in report.strategy_status],
        "realized_pnl": report.realized_pnl,
        "unrealized_pnl": report.unrealized_pnl,
        "net_pnl": report.net_pnl,
    }

def main():
    results = []
    for index in (1, 2):
        report = HighSpeedVirtualRuntimeReplayRunner(
            DATASET,
            run_id=RUN_ID,
            validation_only_synthetic=True,
        ).run()
        result = semantic(report)
        results.append(result)
        print(f"RUN_{index}=" + json.dumps(result, sort_keys=True), flush=True)
    print("DETERMINISM_EQUAL=" + str(results[0] == results[1]), flush=True)
    print("RUNS_COMPLETED=2", flush=True)

if __name__ == "__main__":
    main()
