from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))

from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
from environments.high_speed.replay_trace import ReplayLogMode
from environments.high_speed.virtual_runtime_replay import HighSpeedVirtualRuntimeReplayRunner

STRATEGY = "track8_macro_regime_monthly_strangle"
OUTPUT = ROOT / "reports/synth/Q25_S8_MTM_FAST_DETAILED_EQUIV_20261105.json"


def plain(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {key: plain(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "value"):
        return value.value
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_mode(regime: str, mode: ReplayLogMode, run_id: str) -> dict[str, Any]:
    folder = ROOT / "data/derived_scenario/q25_s8_v3/strategy8_monthly" / regime
    manifest = folder / "manifest.json"
    profile = ROOT / "config/validation_only/q25_s8_v3" / regime / "risk_profile.json"
    trace_path = (
        ROOT / "reports/synth" / f"Q25_S8_MTM_{regime.upper()}_DETAILED_20261105.jsonl"
        if mode is ReplayLogMode.DETAILED else None
    )
    if trace_path is not None and trace_path.exists():
        raise FileExistsError(f"REFUSING_TO_OVERWRITE_TRACE:{trace_path.name}")

    captured_bridges: list[VirtualMultiLegExecutionBridge] = []
    original_init = VirtualMultiLegExecutionBridge.__init__

    def capture_init(bridge, *args, **kwargs):
        original_init(bridge, *args, **kwargs)
        captured_bridges.append(bridge)

    runner = HighSpeedVirtualRuntimeReplayRunner(
        folder,
        run_id=run_id,
        strategy_keys=((STRATEGY, "2.0"),),
        validation_only_synthetic=True,
        validation_only_synthetic_manifest=manifest,
        validation_only_s8_risk_profile=profile,
        log_mode=mode,
        trace_output=trace_path,
    )
    with patch.object(VirtualMultiLegExecutionBridge, "__init__", capture_init):
        report = runner.run()

    if not captured_bridges:
        raise RuntimeError("S8_REPLAY_BRIDGE_NOT_CAPTURED")
    bridge = captured_bridges[-1]
    vssf = bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime
    snapshots = {
        group_id: plain(bridge.position_groups.snapshot(group_id))
        for group_id in bridge.position_groups.all()
    }
    groups = {
        group_id: plain(group)
        for group_id, group in bridge.position_groups.all().items()
    }
    adapter = runner.s8_validation_runtime_adapter
    semantic = {
        "events": report.events,
        "signals": report.signals,
        "approved": report.approved,
        "routed": report.routed,
        "filled": report.filled,
        "rejected": report.rejected,
        "execution_ids": list(report.execution_ids),
        "multi_leg_decisions": report.multi_leg_decisions,
        "strategy_signal_counts": plain(report.strategy_signal_counts),
        "strategy_status": plain(report.strategy_status),
        "realized_pnl": report.realized_pnl,
        "unrealized_pnl": report.unrealized_pnl,
        "net_pnl": report.net_pnl,
        "open_lots": plain(bridge.position_lot_store.open_lots()),
        "groups": groups,
        "group_snapshots": snapshots,
        "fee_records": plain(bridge.fee_ledger.snapshot(run_id=bridge.run_id)),
        "risk_audit": plain(adapter.risk_audit_records),
        "account_positions": plain(vssf.account.positions),
    }
    trace = None
    if trace_path is not None:
        records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        market_events = [item for item in records if item.get("event_type") == "market_event"]
        if len(market_events) != report.events:
            raise AssertionError(f"DETAILED_MARKET_EVENT_COUNT:{len(market_events)}!={report.events}")
        sequences = [item["trace_sequence"] for item in records]
        if sequences != list(range(len(records))):
            raise AssertionError("DETAILED_TRACE_SEQUENCE_NOT_CONTIGUOUS")
        if not market_events:
            raise AssertionError("DETAILED_MARKET_EVENTS_MISSING")
        final_counts = market_events[-1]["payload"]["cumulative_counts"]
        expected_counts = {
            "events": report.events, "signals": report.signals,
            "approved": report.approved, "routed": report.routed,
            "filled": report.filled, "rejected": report.rejected,
        }
        if final_counts != expected_counts:
            raise AssertionError(f"DETAILED_FINAL_COUNTS_MISMATCH:{final_counts}")
        observer = report.execution_observer_summary or {}
        if observer.get("status") != "CONNECTED" or observer.get("trace_write_errors"):
            raise AssertionError(f"DETAILED_OBSERVER_FAILED:{observer}")
        if observer.get("order_commands_observed", 0) <= 0 or observer.get("fills_observed", 0) <= 0:
            raise AssertionError(f"DETAILED_EXECUTION_EVIDENCE_MISSING:{observer}")
        trace = {
            "path": str(trace_path.relative_to(ROOT)),
            "sha256": sha256(trace_path),
            "records": len(records),
            "market_events": len(market_events),
            "observer": observer,
        }

    return {
        "mode": mode.value,
        "run_id": report.run_id,
        "semantic": semantic,
        "trace": trace,
        "elapsed_seconds": report.elapsed_seconds,
        "events_per_second": report.events_per_second,
        "trace_status": report.trace_status,
        "manifest_sha256": adapter.evidence.manifest_sha256,
        "dataset_sha256": adapter.evidence.dataset_sha256,
        "risk_profile_sha256": adapter.evidence.risk_profile_sha256,
    }


def assert_pnl_reconciles(result: dict[str, Any]) -> None:
    semantic = result["semantic"]
    snapshots = tuple(semantic["group_snapshots"].values())
    if not snapshots:
        raise AssertionError("S8_POSITION_GROUP_SNAPSHOT_MISSING")
    group_realized = sum(item["realized_pnl"] for item in snapshots)
    group_unrealized = sum(item["unrealized_pnl"] for item in snapshots)
    group_total = sum(item["total_pnl"] for item in snapshots)
    for label, actual, expected in (
        ("REALIZED", group_realized, semantic["realized_pnl"]),
        ("UNREALIZED", group_unrealized, semantic["unrealized_pnl"]),
        ("NET", group_total, semantic["net_pnl"]),
    ):
        if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=0.01):
            raise AssertionError(f"POSITION_GROUP_ACCOUNT_{label}_MISMATCH:{actual}!={expected}")
    for snapshot in snapshots:
        if not snapshot["complete"] or len(snapshot["legs"]) != 2:
            raise AssertionError("S8_POSITION_GROUP_NOT_COMPLETE_TWO_LEGS")


def run_scenario(regime: str) -> dict[str, Any]:
    run_id = f"Q25-S8-{regime.upper()}-FAST-DETAILED-20261105"
    fast = run_mode(regime, ReplayLogMode.FAST, run_id)
    detailed = run_mode(regime, ReplayLogMode.DETAILED, run_id)
    assert_pnl_reconciles(fast)
    assert_pnl_reconciles(detailed)
    if fast["semantic"] != detailed["semantic"]:
        raise AssertionError(f"FAST_DETAILED_SEMANTIC_MISMATCH:{regime}")
    if (fast["manifest_sha256"], fast["dataset_sha256"], fast["risk_profile_sha256"]) != (
        detailed["manifest_sha256"], detailed["dataset_sha256"], detailed["risk_profile_sha256"]
    ):
        raise AssertionError(f"FAST_DETAILED_INPUT_HASH_MISMATCH:{regime}")
    semantic = fast["semantic"]
    if (
        semantic["events"] != 216 or semantic["signals"] <= 0
        or semantic["approved"] <= 0 or semantic["routed"] <= 0
        or semantic["filled"] <= 0 or semantic["rejected"] != 0
        or len(semantic["open_lots"]) != 2 or len(semantic["fee_records"]) != 2
    ):
        raise AssertionError(f"S8_E2E_EXPECTATIONS_FAILED:{regime}")
    return {
        "scenario": regime.upper(),
        "run_id": run_id,
        "equivalence": "PASS",
        "position_group_account_pnl_reconciliation": "PASS",
        "fast": fast,
        "detailed": detailed,
    }


def main() -> None:
    if OUTPUT.exists():
        raise FileExistsError(f"REFUSING_TO_OVERWRITE_RESULT:{OUTPUT.name}")
    results = [run_scenario("normal"), run_scenario("high_vol")]
    payload = {
        "scope": "VALIDATION_ONLY_DERIVED_SCENARIO_VIRTUAL_S8",
        "results": results,
    }
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    print(json.dumps({
        "result_path": str(OUTPUT.relative_to(ROOT)),
        "result_sha256": sha256(OUTPUT),
        "scenarios": [
            {
                "scenario": item["scenario"],
                "run_id": item["run_id"],
                "events": item["fast"]["semantic"]["events"],
                "signals": item["fast"]["semantic"]["signals"],
                "approved": item["fast"]["semantic"]["approved"],
                "routed": item["fast"]["semantic"]["routed"],
                "filled": item["fast"]["semantic"]["filled"],
                "rejected": item["fast"]["semantic"]["rejected"],
                "group_unrealized_pnl": sum(
                    snapshot["unrealized_pnl"]
                    for snapshot in item["fast"]["semantic"]["group_snapshots"].values()
                ),
                "account_unrealized_pnl": item["fast"]["semantic"]["unrealized_pnl"],
                "group_net_pnl": sum(
                    snapshot["total_pnl"]
                    for snapshot in item["fast"]["semantic"]["group_snapshots"].values()
                ),
                "account_net_pnl": item["fast"]["semantic"]["net_pnl"],
                "fast_detailed": item["equivalence"],
                "detailed_trace": item["detailed"]["trace"],
            }
            for item in results
        ],
    }, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
