import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.strategy.track6_order_lifecycle import Track6LifecycleConfig
from environments.high_speed.virtual_runtime_replay import HighSpeedVirtualRuntimeReplayRunner

runner = HighSpeedVirtualRuntimeReplayRunner(
    "data/derived_scenario/q25_a2_1_strategy6",
    run_id="Q25-A4-S6-SMOKE-R5-PER-ORDER",
    strategy_keys=(("track6_daily_tail_insurance", "1.0"),),
    validation_only_synthetic=True,
    validation_only_synthetic_manifest="reports/synth/Q25_A4_S6_SYN_EVT_MANIFEST_20261106_v3.json",
    validation_only_track6_execution_mode=True,
    validation_only_track6_lifecycle_config=Track6LifecycleConfig(
        first_rank=5, timeout_split="per_order",
    ),
    validation_only_track6_risk_profile=Path(
        "config/validation_only/q25_s6_a4_matrix_v3/risk_profile.json"
    ),
)
report = runner.run()
print(json.dumps(asdict(report), ensure_ascii=False, default=str))
