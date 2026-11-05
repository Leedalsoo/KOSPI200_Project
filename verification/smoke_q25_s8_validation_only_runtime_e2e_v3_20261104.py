from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
from environments.high_speed.virtual_runtime_replay import HighSpeedVirtualRuntimeReplayRunner

STRATEGY = "track8_macro_regime_monthly_strangle"


def plain(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    if hasattr(value, "value"):
        return value.value
    return value


def run_scenario(regime: str) -> dict[str, Any]:
    folder = ROOT / "data/derived_scenario/q25_s8_v3/strategy8_monthly" / regime
    profile = ROOT / "config/validation_only/q25_s8_v3" / regime / "risk_profile.json"
    captured: dict[str, Any] = {}
    original_execute = VirtualMultiLegExecutionBridge.execute

    def capture_execute(bridge, plan, *args, **kwargs):
        result = original_execute(bridge, plan, *args, **kwargs)
        if plan.strategy_id == STRATEGY:
            captured["open_lots"] = plain(bridge.position_lot_store.open_lots())
            captured["position_groups"] = plain(bridge.position_groups.all())
            captured["group_snapshots"] = {
                key: plain(bridge.position_groups.snapshot(key))
                for key in bridge.position_groups.all()
            }
            captured["fee_records"] = plain(bridge.fee_ledger.snapshot(run_id=bridge.run_id))
        return result

    VirtualMultiLegExecutionBridge.execute = capture_execute
    try:
        runner = HighSpeedVirtualRuntimeReplayRunner(
            folder,
            validation_only_synthetic=True,
            validation_only_synthetic_manifest=folder / "manifest.json",
            validation_only_s8_risk_profile=profile,
            strategy_keys=((STRATEGY, "2.0"),),
        )
        report = runner.run()
    finally:
        VirtualMultiLegExecutionBridge.execute = original_execute

    adapter = runner.s8_validation_runtime_adapter
    s8_status = next((item for item in report.strategy_status if item.strategy_id == STRATEGY), None)
    return {
        "scenario": regime.upper(),
        "run_id": report.run_id,
        "events": report.events,
        "signals": report.signals,
        "approved": report.approved,
        "routed": report.routed,
        "filled": report.filled,
        "rejected": report.rejected,
        "execution_ids": list(report.execution_ids),
        "realized_pnl": report.realized_pnl,
        "unrealized_pnl": report.unrealized_pnl,
        "net_pnl": report.net_pnl,
        "strategy_status": plain(s8_status),
        "open_position_lots": captured.get("open_lots", []),
        "position_groups": captured.get("position_groups", {}),
        "group_snapshots": captured.get("group_snapshots", {}),
        "fee_records": captured.get("fee_records", []),
        "risk_audit": plain(adapter.risk_audit_records),
        "manifest_sha256": adapter.evidence.manifest_sha256,
        "dataset_sha256": adapter.evidence.dataset_sha256,
        "risk_profile_sha256": adapter.evidence.risk_profile_sha256,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=("normal", "high_vol", "both"), default="both")
    args = parser.parse_args()
    scenarios = ("normal", "high_vol") if args.scenario == "both" else (args.scenario,)
    results = [run_scenario(item) for item in scenarios]
    print(json.dumps(results, indent=2, default=str))
    for item in results:
        if (item["events"] <= 0 or item["signals"] <= 0 or item["approved"] <= 0
                or item["routed"] <= 0 or item["filled"] <= 0 or item["rejected"] != 0
                or not item["execution_ids"] or not item["open_position_lots"]
                or not item["position_groups"] or not item["fee_records"]
                or not item["risk_audit"]
                or any(len(group.get("legs", ())) != 2 for group in item["position_groups"].values())
                or any(not snapshot.get("complete") or len(snapshot.get("legs", ())) != 2
                       for snapshot in item["group_snapshots"].values())):
            raise SystemExit(f"S8_VALIDATION_E2E_INCOMPLETE:{item['scenario']}")


if __name__ == "__main__":
    main()
