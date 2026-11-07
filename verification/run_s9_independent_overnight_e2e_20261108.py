from __future__ import annotations
from dataclasses import asdict, is_dataclass
from pathlib import Path
import hashlib
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from environments.high_speed.replay_trace import ReplayLogMode
from environments.high_speed.virtual_runtime_replay import HighSpeedVirtualRuntimeReplayRunner
DATASET = ROOT / "data/derived_scenario/q25_s9_independent_overnight_20261108"
MANIFEST = DATASET / "manifest.json"
CONTRACT_PROFILE = ROOT / "config/validation_only/track9_independent_synthetic_contract_profile.json"
RISK_PROFILE = ROOT / "config/validation_only/q25_s9_independent_overnight_20261108/risk_profile.json"
STRATEGY_MANIFEST = ROOT / "config/strategies/strategy-manifest.v1.json"
TRACE = ROOT / "reports/synth/S9_INDEPENDENT_ATM_OVERNIGHT_DETAILED_FINAL_20261108.jsonl"
REPORT_PATH = ROOT / "reports/synth/S9_INDEPENDENT_ATM_OVERNIGHT_E2E_FINAL_20261108.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def report_summary(report) -> dict:
    return {
        "events": report.events,
        "signals": report.signals,
        "approved": report.approved,
        "routed": report.routed,
        "filled": report.filled,
        "rejected": report.rejected,
        "realized_pnl_krw": report.realized_pnl,
        "unrealized_pnl_krw": report.unrealized_pnl,
        "net_pnl_krw": report.net_pnl,
        "pnl_status": report.pnl_status,
        "trace_status": report.trace_status,
        "strategy_status": [asdict(item) for item in report.strategy_status],
    }


def snapshot_summary(snapshot: dict) -> dict:
    risk = [
        {key: item[key] for key in ("purpose", "gross_premium_krw", "status", "manifest_sha256", "dataset_sha256", "risk_profile_sha256")}
        for item in snapshot["risk_audit_records"]
    ]
    fees = []
    for item in snapshot["fee_records"]:
        fees.append(asdict(item) if is_dataclass(item) else str(item))
    return {
        "strategy_state": snapshot["strategy_state"],
        "open_lot_count": len(snapshot["open_lots"]),
        "position_group_count": len(snapshot["position_groups"]),
        "fee_records": fees,
        "risk_audit_records": risk,
        "realized_pnl_krw": str(snapshot["realized_pnl"]),
        "unrealized_pnl_krw": str(snapshot["unrealized_pnl"]),
        "net_pnl_krw": str(snapshot["net_pnl"]),
    }


def run_mode(mode: ReplayLogMode, suffix: str, trace_output: Path | None = None):
    runner = HighSpeedVirtualRuntimeReplayRunner(
        DATASET,
        run_id=f"S9-ATM-OVERNIGHT-20261108-{suffix}",
        strategy_keys=(("track9_event_overnight_insurance", "3.0"),),
        validation_only_synthetic=True,
        validation_only_synthetic_manifest=MANIFEST,
        validation_only_s9_contract_profile=CONTRACT_PROFILE,
        validation_only_s9_risk_profile=RISK_PROFILE,
        log_mode=mode,
        trace_output=trace_output,
    )
    report = runner.run()
    return runner, report


def main() -> None:
    os.chdir(ROOT)
    for path in (TRACE, REPORT_PATH):
        if path.exists():
            raise RuntimeError(f"REFUSE_OVERWRITE:{path.relative_to(ROOT)}")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    risk_profile = json.loads(RISK_PROFILE.read_text(encoding="utf-8"))
    official_status = manifest["official_data_status"]
    if not official_status or any(value != "MISSING" for value in official_status.values()):
        raise RuntimeError("OFFICIAL_DATA_STATUS_MUST_REMAIN_MISSING")

    fast_runner, fast_report = run_mode(ReplayLogMode.FAST, "FAST")
    detailed_runner, detailed_report = run_mode(ReplayLogMode.DETAILED, "DETAILED", TRACE)
    fast_snapshot = snapshot_summary(fast_runner.s9_runtime_snapshot)
    detailed_snapshot = snapshot_summary(detailed_runner.s9_runtime_snapshot)
    fast_summary = report_summary(fast_report)
    detailed_summary = report_summary(detailed_report)

    compare_fields = ("events", "signals", "approved", "routed", "filled", "rejected",
                      "realized_pnl_krw", "unrealized_pnl_krw", "net_pnl_krw", "pnl_status")
    equivalence = all(fast_summary[key] == detailed_summary[key] for key in compare_fields)
    equivalence = equivalence and fast_snapshot["strategy_state"] == detailed_snapshot["strategy_state"]
    equivalence = equivalence and fast_snapshot["open_lot_count"] == detailed_snapshot["open_lot_count"] == 0
    equivalence = equivalence and fast_snapshot["risk_audit_records"] == detailed_snapshot["risk_audit_records"]

    for label, summary, snapshot in (("FAST", fast_summary, fast_snapshot), ("DETAILED", detailed_summary, detailed_snapshot)):
        if (summary["events"] != 4 or summary["signals"] != 2 or summary["approved"] != 2
                or summary["routed"] != 4 or summary["filled"] != 4 or summary["rejected"] != 0
                or abs(float(summary["realized_pnl_krw"]) - 1060000.0) > 0.01
                or float(summary["unrealized_pnl_krw"]) != 0.0
                or snapshot["strategy_state"] != "OVERNIGHT_INSURANCE_CLOSED"
                or snapshot["open_lot_count"] != 0
                or snapshot["strategy_state"] != "OVERNIGHT_INSURANCE_CLOSED"
                or any(item.get("unavailable", 0) != 0 for item in summary["strategy_status"])
                or len(snapshot["risk_audit_records"]) != 2
                or any(item["status"] != "ALLOW_VIRTUAL_ONLY" for item in snapshot["risk_audit_records"])):
            raise RuntimeError(f"S9_E2E_ASSERTION_FAILED:{label}")
    if not equivalence:
        raise RuntimeError("S9_FAST_DETAILED_REPLAY_NOT_EQUIVALENT")
    if not TRACE.is_file() or TRACE.stat().st_size == 0:
        raise RuntimeError("S9_DETAILED_TRACE_NOT_WRITTEN")

    result = {
        "status": "PSB_PASS",
        "validation_only": True,
        "scope_note": "PSB_PASS applies only to this manifest-bound synthetic S9 Virtual scenario; it is not official KIS/REAL_VTS/Live validation.",
        "strategy_id": "track9_event_overnight_insurance",
        "strategy_code_version": "3.0",
        "strategy_manifest_sha256": sha(STRATEGY_MANIFEST),
        "runtime_enforced_strategy_policy": manifest["strategy_policy"],
        "legacy_strategy_manifest_parameters": {
            "ENTRY_TIME": "15:10 (accepted for schema compatibility, ignored; runtime is fixed at 15:00)",
            "TRAILING_PROFIT_GIVEBACK": "0.30 (accepted for schema compatibility, ignored; trailing exit is not used)",
        },
        "scenario_id": manifest["scenario_id"],
        "provenance": "SYNTHETIC",
        "official_data_status": official_status,
        "synthetic_contract_multiplier": 100000,
        "synthetic_tradeable": True,
        "virtual_account_initial_capital_krw": risk_profile["initial_capital_krw"],
        "synthetic_risk_limits": risk_profile["limits"],
        "manifest_sha256": sha(MANIFEST),
        "dataset_sha256": sha(DATASET / "20261106.jsonl"),
        "contract_profile_sha256": sha(CONTRACT_PROFILE),
        "risk_profile_sha256": sha(RISK_PROFILE),
        "fast": {"report": fast_summary, "runtime": fast_snapshot},
        "detailed": {"report": detailed_summary, "runtime": detailed_snapshot},
        "fast_detailed_equivalent": equivalence,
        "detailed_trace_path": TRACE.relative_to(ROOT).as_posix(),
        "detailed_trace_sha256": sha(TRACE),
        "production_runtime_eligible": False,
        "kis_real_vts_live_orders_used": False,
        "real_account_used": False,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report_bytes = (json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n").encode()
    REPORT_PATH.write_bytes(report_bytes)
    REPORT_PATH.with_suffix(".json.sha256").write_text(
        hashlib.sha256(report_bytes).hexdigest() + f"  {REPORT_PATH.name}\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "fast_detailed_equivalent": equivalence,
        "signals": fast_summary["signals"],
        "fills": fast_summary["filled"],
        "realized_pnl_krw": fast_summary["realized_pnl_krw"],
        "open_lots": fast_snapshot["open_lot_count"],
        "strategy_state": fast_snapshot["strategy_state"],
        "report": REPORT_PATH.relative_to(ROOT).as_posix(),
        "trace": TRACE.relative_to(ROOT).as_posix(),
    }, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
