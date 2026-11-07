import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import json
from dataclasses import asdict
from environments.high_speed.virtual_runtime_replay import HighSpeedVirtualRuntimeReplayRunner

runner = HighSpeedVirtualRuntimeReplayRunner(
    "data/derived_scenario/q25_a2_1_strategy6",
    run_id="Q25-A1-3-S6-NORMAL-20261103",
    strategy_keys=(("track6_daily_tail_insurance", "1.0"),),
    validation_only_synthetic=True,
    validation_only_synthetic_manifest="reports/synth/Q25_A2_1_S6_SYN_EVT_MANIFEST_20261102.json",
)
report = runner.run()
print(json.dumps(asdict(report), default=str, ensure_ascii=False))
