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
from environments.high_speed.virtual_runtime_replay import HighSpeedVirtualRuntimeReplayRunner

STRATEGY = "track8_macro_regime_monthly_strangle"
OUTPUT = ROOT / "reports/synth/Q25_S8_TERMINAL_CLOSE_FLAT_RECON_20261105.json"


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


def run_scenario(regime: str) -> dict[str, Any]:
    folder = ROOT / "data/derived_scenario/q25_s8_v3/strategy8_monthly" / regime
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    profile = ROOT / "config/validation_only/q25_s8_v3" / regime / "risk_profile.json"
    run_id = f"Q25-S8-TERMINAL-CLOSE-{regime.upper()}-20261105"

    captured: list[VirtualMultiLegExecutionBridge] = []
    original_init = VirtualMultiLegExecutionBridge.__init__

    def capture_init(bridge, *args, **kwargs):
        original_init(bridge, *args, **kwargs)
        captured.append(bridge)

    runner = HighSpeedVirtualRuntimeReplayRunner(
        folder,
        run_id=run_id,
        strategy_keys=((STRATEGY, "2.0"),),
        validation_only_synthetic=True,
        validation_only_synthetic_manifest=manifest_path,
        validation_only_s8_risk_profile=profile,
    )
    with patch.object(VirtualMultiLegExecutionBridge, "__init__", capture_init):
        replay_report = runner.run()

    if not captured:
        raise RuntimeError("S8_TERMINAL_BRIDGE_NOT_CAPTURED")
    bridge = captured[-1]
    if replay_report.filled < 2:
        raise AssertionError(f"S8_NATURAL_ENTRY_FILLS_REQUIRED:{replay_report.filled}")

    groups = bridge.position_groups.all()
    if len(groups) != 1:
        raise AssertionError(f"S8_SINGLE_POSITION_GROUP_REQUIRED:{len(groups)}")
    group_id, entry_group = next(iter(groups.items()))
    if not entry_group.is_complete or len(entry_group.legs) != 2:
        raise AssertionError("S8_ENTRY_GROUP_NOT_COMPLETE_TWO_LEGS")
    entry_snapshot = bridge.position_groups.snapshot(group_id)
    if entry_snapshot is None:
        raise AssertionError("S8_ENTRY_SNAPSHOT_REQUIRED")

    entry_lots = tuple(bridge.position_lot_store.open_lots())
    if len(entry_lots) != 2 or sum(lot.remaining_quantity for lot in entry_lots) != 2:
        raise AssertionError(f"S8_ENTRY_POSITION_LOTS_INVALID:{len(entry_lots)}")

    close_results = []
    for option_type in ("CALL", "PUT"):
        plan = bridge.build_close_plan_from_open_lots(
            strategy_id=STRATEGY,
            purpose=f"MONTHLY_STRANGLE_CLOSE_{option_type}",
            asset_type="OPTION",
            option_type=option_type,
            expiry=str(manifest["groups"][0].split("_")[2]),
        )
        if len(plan.legs) != 1 or plan.legs[0].side != "SELL":
            raise AssertionError(f"S8_TERMINAL_CLOSE_PLAN_INVALID:{option_type}")
        result = bridge.execute(plan)
        if not result.reports or any(
            str(report.status).upper() != "FILLED"
            or report.filled_quantity != plan.legs[index].quantity
            or report.remaining_quantity != 0
            for index, report in enumerate(result.reports)
        ):
            raise AssertionError(f"S8_TERMINAL_CLOSE_NOT_FILLED:{option_type}:{result.reports}")
        close_results.append({
            "option_type": option_type,
            "plan": plain(plan),
            "result": plain(result),
            "position_flat": result.position_flat,
        })

    final_group = bridge.position_groups.get(group_id)
    final_snapshot = bridge.position_groups.snapshot(group_id)
    vssf = bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime
    open_lots = tuple(bridge.position_lot_store.open_lots())
    account_positions = dict(vssf.account.positions)
    group_instruments = {leg.instrument_id for leg in entry_group.legs}
    residual_account_positions = {
        key: value for key, value in account_positions.items()
        if key in group_instruments and int(value.get("qty", 0)) > 0
    }
    close_events = tuple(bridge.position_lot_store.close_events())
    fee_records = tuple(bridge.fee_ledger.snapshot(run_id=run_id))

    if final_snapshot is None:
        raise AssertionError("S8_TERMINAL_SNAPSHOT_MISSING")
    if tuple(leg.leg_id for leg in final_group.legs) != tuple(leg.leg_id for leg in entry_group.legs):
        raise AssertionError("S8_ENTRY_GROUP_LEG_PROVENANCE_NOT_PRESERVED")
    if len(final_snapshot.legs) != 2 or any(leg.quantity != 0 for leg in final_snapshot.legs):
        raise AssertionError("S8_POSITION_GROUP_NOT_FLAT")
    if any(abs(leg.unrealized_pnl) > 0.01 for leg in final_snapshot.legs):
        raise AssertionError("S8_TERMINAL_LEG_UNREALIZED_PNL_NOT_ZERO")
    if open_lots or residual_account_positions:
        raise AssertionError(
            f"S8_FLAT_STATE_MISMATCH:lots={len(open_lots)}:account={residual_account_positions}"
        )
    if len(close_events) != len(entry_lots):
        raise AssertionError(f"S8_CLOSE_EVENT_COUNT_MISMATCH:{len(close_events)}!={len(entry_lots)}")
    if len(fee_records) != 4:
        raise AssertionError(f"S8_ENTRY_AND_CLOSE_FEE_LEDGER_COUNT_MISMATCH:{len(fee_records)}")
    if not close_results[-1]["position_flat"] or close_results[0]["position_flat"]:
        raise AssertionError("S8_GROUP_LEVEL_POSITION_FLAT_TRANSITION_INVALID")

    account_realized = float(vssf.account.realized_pnl)
    account_unrealized = float(vssf.account.unrealized_pnl)
    account_net = account_realized + account_unrealized
    for label, actual, expected in (
        ("REALIZED", final_snapshot.realized_pnl, account_realized),
        ("UNREALIZED", final_snapshot.unrealized_pnl, account_unrealized),
        ("NET", final_snapshot.total_pnl, account_net),
    ):
        if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=0.01):
            raise AssertionError(f"S8_TERMINAL_GROUP_ACCOUNT_{label}_MISMATCH:{actual}!={expected}")

    return {
        "scenario": regime.upper(),
        "run_id": run_id,
        "natural_replay": {
            "events": replay_report.events,
            "signals": replay_report.signals,
            "approved": replay_report.approved,
            "routed": replay_report.routed,
            "filled": replay_report.filled,
            "rejected": replay_report.rejected,
            "execution_ids": list(replay_report.execution_ids),
        },
        "entry_group": plain(entry_group),
        "entry_snapshot": plain(entry_snapshot),
        "entry_lots": plain(entry_lots),
        "close_results": close_results,
        "final_group": plain(final_group),
        "final_snapshot": plain(final_snapshot),
        "open_lots": plain(open_lots),
        "close_events": plain(close_events),
        "fee_records": plain(fee_records),
        "account_positions": plain(account_positions),
        "account_pnl": {
            "realized": account_realized,
            "unrealized": account_unrealized,
            "net": account_net,
        },
        "flat_state": "PASS",
        "realized_pnl_reconciliation": "PASS",
        "manifest_sha256": sha256(manifest_path),
        "dataset_sha256": sha256(folder / manifest["output_path"].split("/")[-1]),
        "risk_profile_sha256": sha256(profile),
    }


def main() -> None:
    if OUTPUT.exists():
        raise FileExistsError(f"REFUSING_TO_OVERWRITE_RESULT:{OUTPUT.name}")
    results = [run_scenario("normal"), run_scenario("high_vol")]
    payload = {
        "scope": "VALIDATION_ONLY_DERIVED_SCENARIO_VIRTUAL_S8",
        "terminal_close": results,
        "expiry_settlement": {
            "status": "BLOCKED_NOT_AUTHORITATIVE",
            "reason": (
                "Both scenario manifests explicitly set expiry_is_authoritative=false; "
                "the current Virtual execution contract has no authoritative option cash-settlement "
                "adapter or settlement-price source. A synthetic expiry payoff is not promoted to "
                "an expiry execution PASS."
            ),
        },
    }
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    print(json.dumps({
        "result_path": str(OUTPUT.relative_to(ROOT)),
        "result_sha256": sha256(OUTPUT),
        "scenarios": [
            {
                "scenario": item["scenario"],
                "events": item["natural_replay"]["events"],
                "signals": item["natural_replay"]["signals"],
                "approved": item["natural_replay"]["approved"],
                "routed": item["natural_replay"]["routed"],
                "filled": item["natural_replay"]["filled"],
                "close_fills": sum(
                    report["result"]["filled_legs"]
                    for report in item["close_results"]
                ),
                "group_realized_pnl": item["final_snapshot"]["realized_pnl"],
                "account_realized_pnl": item["account_pnl"]["realized"],
                "group_unrealized_pnl": item["final_snapshot"]["unrealized_pnl"],
                "account_unrealized_pnl": item["account_pnl"]["unrealized"],
                "flat_state": item["flat_state"],
            }
            for item in results
        ],
        "expiry_settlement": payload["expiry_settlement"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
