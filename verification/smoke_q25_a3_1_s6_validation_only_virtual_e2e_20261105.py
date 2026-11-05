from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from environments.high_speed.virtual_runtime_replay import HighSpeedVirtualRuntimeReplayRunner

DATASET = "data/derived_scenario/q25_a3_1_s6_budget_fit"
MANIFEST = "reports/synth/Q25_A3_1_S6_BUDGET_FIT_MANIFEST_20261105.json"
RUN_ID = "Q25-A3-1-S6-BUDGET-FIT-VERIFY-20261105"


def main() -> None:
    runner = HighSpeedVirtualRuntimeReplayRunner(
        DATASET,
        run_id=RUN_ID,
        strategy_keys=(("track6_daily_tail_insurance", "1.0"),),
        validation_only_synthetic=True,
        validation_only_synthetic_manifest=MANIFEST,
        validation_only_track6_execution_mode=True,
    )
    report = runner.run(max_events=4632)
    status = next(item for item in report.strategy_status if item.strategy_id == "track6_daily_tail_insurance")
    expected = {"events": 4632, "signals": 3, "approved": 3, "routed": 4, "filled": 4, "rejected": 0}
    actual = {key: getattr(report, key) for key in expected}
    if actual != expected:
        raise SystemExit(f"S6_VIRTUAL_E2E_COUNTS_MISMATCH:{actual}")
    if status.runtime_failures or status.decision_rejected or status.risk_rejected:
        raise SystemExit(f"S6_VIRTUAL_E2E_STRATEGY_STATUS_NOT_CLEAN:{asdict(status)}")
    if (status.approved, status.routed, status.filled_quantity) != (3, 4, 4):
        raise SystemExit(f"S6_VIRTUAL_E2E_STRATEGY_COUNTS_MISMATCH:{asdict(status)}")
    if report.pnl_status != "VSSF_ACCOUNT_PNL_CONNECTED" or report.unrealized_pnl != 0:
        raise SystemExit(f"S6_VIRTUAL_E2E_PNL_NOT_FLAT:{report.pnl_status}:{report.unrealized_pnl}")
    print(json.dumps({"status": "PASS", "report": asdict(report)}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
