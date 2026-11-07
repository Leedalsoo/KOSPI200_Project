from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from environments.high_speed.replay_trace import ReplayLogMode

BASE_RUNNER = ROOT / "verification/run_q25_s06_3_s7_normal_path_20261107.py"
REPORT = ROOT / "reports/synth/Q25_A5_S08_S7_FAST_DETAILED_E2E_20261107.json"
TRACE = ROOT / "reports/synth/Q25_A5_S08_S7_DETAILED_TRACE_20261107.jsonl"
FAST_INTERMEDIATE = ROOT / "reports/synth/Q25_A5_S08_S7_FAST_INTERMEDIATE_20261107.json"
DETAILED_INTERMEDIATE = ROOT / "reports/synth/Q25_A5_S08_S7_DETAILED_INTERMEDIATE_20261107.json"

SEMANTIC_KEYS = (
    "dataset_sha256", "manifest_sha256", "risk_profile_sha256",
    "events", "exhausted", "signals", "approved", "routed", "filled",
    "rejected", "multi_leg_decisions", "execution_ids", "entry_group_ids",
    "group_expiries", "all_group_expiries", "concurrent_open_lot_snapshots",
    "concurrent_two_expiry_groups_proven", "sequential_put_call_order",
    "sequential_group_id_reused", "execution_records",
    "position_group_snapshots", "group_pnl", "lot_history_count",
    "close_event_count", "remaining_open_lot_count", "remaining_open_lots",
    "nonzero_account_positions", "risk_audit_records",
    "risk_reservations_after_execution",
    "risk_reservation_retained_until_group_flat",
    "risk_reservations_released", "group_pnl_snapshot_sum",
    "group_pnl_reconciliation_delta", "group_pnl_reconciles_with_account",
    "runtime_failures", "realized_pnl", "unrealized_pnl", "net_pnl",
    "pnl_status", "fees_total_krw", "fee_model_status",
    "fee_inclusive_pnl_verified", "pnl_basis",
)

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def load_base_module():
    spec = importlib.util.spec_from_file_location("s7_normal_path_runner", BASE_RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("S7_BASE_RUNNER_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def run_mode(module, mode: ReplayLogMode, trace_path: Path | None, report_path: Path) -> dict:
    if report_path.exists():
        raise FileExistsError(f"REFUSING_TO_OVERWRITE:{report_path.name}")
    if trace_path is not None and trace_path.exists():
        raise FileExistsError(f"REFUSING_TO_OVERWRITE:{trace_path.name}")

    original_class = module.HighSpeedVirtualRuntimeReplayRunner
    original_trace = module.TRACE
    original_report = module.REPORT

    class ModeRunner(original_class):
        def __init__(self, *args, **kwargs):
            kwargs["log_mode"] = mode
            kwargs["trace_output"] = trace_path
            super().__init__(*args, **kwargs)

    module.HighSpeedVirtualRuntimeReplayRunner = ModeRunner
    module.TRACE = trace_path if trace_path is not None else ROOT / "reports/synth/.S7_FAST_TRACE_NOT_CREATED"
    module.REPORT = report_path
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            module.main()
    finally:
        module.HighSpeedVirtualRuntimeReplayRunner = original_class
        module.TRACE = original_trace
        module.REPORT = original_report

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    if payload.get("verdict") != "PSB_PASS_NORMAL_PATH_ONLY":
        raise AssertionError(f"{mode.value}_BASE_RUNTIME_NOT_PASS:{payload.get('verdict')}")
    return payload

def semantic_projection(payload: dict) -> dict:
    return {key: payload.get(key) for key in SEMANTIC_KEYS}

def main() -> None:
    for path in (REPORT, TRACE, FAST_INTERMEDIATE, DETAILED_INTERMEDIATE):
        if path.exists():
            raise FileExistsError(f"REFUSING_TO_OVERWRITE:{path.name}")

    module = load_base_module()
    fast = run_mode(module, ReplayLogMode.FAST, None, FAST_INTERMEDIATE)
    detailed = run_mode(module, ReplayLogMode.DETAILED, TRACE, DETAILED_INTERMEDIATE)

    fast_semantic = semantic_projection(fast)
    detailed_semantic = semantic_projection(detailed)
    semantic_equal = fast_semantic == detailed_semantic
    input_hash_equal = all(
        fast.get(key) == detailed.get(key)
        for key in ("dataset_sha256", "manifest_sha256", "risk_profile_sha256")
    )

    observer = detailed.get("execution_observer_summary") or {}
    trace_records = [
        json.loads(line) for line in TRACE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    market_events = [item for item in trace_records if item.get("event_type") == "market_event"]
    trace_sequence = [item.get("trace_sequence") for item in trace_records]
    detailed_observer_ok = (
        observer.get("status") == "CONNECTED"
        and observer.get("trace_write_errors") == []
        and observer.get("order_commands_observed") == 8
        and observer.get("execution_reports_observed") == 8
        and observer.get("fills_observed") == 8
        and len(market_events) == detailed.get("events") == 216
        and trace_sequence == list(range(len(trace_records)))
    )

    group_rows = []
    for group_id, group in sorted((fast.get("group_pnl") or {}).items()):
        legs = group.get("legs") or []
        group_rows.append({
            "group_id": group_id,
            "expiry": group.get("expiry"),
            "realized_pnl_krw": group.get("realized_pnl"),
            "unrealized_pnl_krw": group.get("unrealized_pnl"),
            "total_pnl_krw": group.get("total_pnl"),
            "leg_count": len(legs),
            "all_legs_flat": bool(legs) and all(int(leg.get("quantity", -1)) == 0 for leg in legs),
        })

    group_pnl_sum = sum(float(row["realized_pnl_krw"]) for row in group_rows)
    account_realized = float(fast.get("realized_pnl") or 0)
    pnl_delta = account_realized - group_pnl_sum
    position_flat = (
        fast.get("remaining_open_lot_count") == 0
        and fast.get("remaining_open_lots") == []
        and fast.get("nonzero_account_positions") == {}
        and all(row["all_legs_flat"] for row in group_rows)
    )
    assertions = {
        "fast_and_detailed_semantics_equal": semantic_equal,
        "same_dataset_manifest_and_risk_profile_hashes": input_hash_equal,
        "both_modes_exhausted_216_events": (
            fast.get("events") == detailed.get("events") == 216
            and fast.get("exhausted") is True and detailed.get("exhausted") is True
        ),
        "natural_strategy_signals_and_full_execution": (
            fast.get("signals") == detailed.get("signals") == 8
            and fast.get("approved") == detailed.get("approved") == 8
            and fast.get("routed") == detailed.get("routed") == 8
            and fast.get("filled") == detailed.get("filled") == 8
            and fast.get("rejected") == detailed.get("rejected") == 0
        ),
        "monday_and_thursday_expiry_groups": (
            fast.get("all_group_expiries") == ["20261109", "20261112"]
            and len(group_rows) == 2
        ),
        "each_group_has_two_legs_and_is_flat": (
            all(row["leg_count"] == 2 and row["all_legs_flat"] for row in group_rows)
        ),
        "all_positions_flat": position_flat,
        "group_realized_pnl_matches_account": math.isclose(pnl_delta, 0.0, rel_tol=0.0, abs_tol=0.01),
        "risk_reservations_released": fast.get("risk_reservations_released") is True,
        "runtime_failures_zero": fast.get("runtime_failures") == detailed.get("runtime_failures") == 0,
        "detailed_trace_and_observer_valid": detailed_observer_ok,
        "validation_only_no_kis_or_live_orders": (
            fast.get("validation_only") is True
            and detailed.get("validation_only") is True
            and fast.get("kis_api_called") is False
            and detailed.get("kis_api_called") is False
            and fast.get("live_orders_or_real_account_used") is False
            and detailed.get("live_orders_or_real_account_used") is False
        ),
    }
    passed = all(assertions.values())

    report = {
        "report_id": "Q25_A5_S08_S7_FAST_DETAILED_E2E_20261107",
        "scope": "VALIDATION_ONLY_DERIVED_SCENARIO_VIRTUAL_STRATEGY7",
        "verdict": "PSB_PASS" if passed else "PSB_UNVERIFIED",
        "stage_verdict": "PSB_PASS_S7_NATURAL_SIGNAL_FAST_DETAILED_POSITION_PNL_VALIDATION_ONLY" if passed else "PSB_UNVERIFIED",
        "run_id": fast.get("run_id"),
        "dataset_path": fast.get("dataset_path"),
        "input_hashes": {
            "dataset_sha256": fast.get("dataset_sha256"),
            "manifest_sha256": fast.get("manifest_sha256"),
            "risk_profile_sha256": fast.get("risk_profile_sha256"),
        },
        "fast": {
            "mode": "fast",
            "events": fast.get("events"),
            "signals": fast.get("signals"),
            "approved": fast.get("approved"),
            "routed": fast.get("routed"),
            "filled": fast.get("filled"),
            "rejected": fast.get("rejected"),
            "execution_ids": fast.get("execution_ids"),
            "realized_pnl_krw": fast.get("realized_pnl"),
            "unrealized_pnl_krw": fast.get("unrealized_pnl"),
            "net_pnl_krw": fast.get("net_pnl"),
        },
        "detailed": {
            "mode": "detailed",
            "events": detailed.get("events"),
            "signals": detailed.get("signals"),
            "approved": detailed.get("approved"),
            "routed": detailed.get("routed"),
            "filled": detailed.get("filled"),
            "rejected": detailed.get("rejected"),
            "execution_ids": detailed.get("execution_ids"),
            "realized_pnl_krw": detailed.get("realized_pnl"),
            "unrealized_pnl_krw": detailed.get("unrealized_pnl"),
            "net_pnl_krw": detailed.get("net_pnl"),
            "observer": observer,
            "trace": {
                "path": str(TRACE.relative_to(ROOT)).replace("\\", "/"),
                "records": len(trace_records),
                "market_events": len(market_events),
                "sha256": sha256(TRACE),
            },
        },
        "expiry_group_reconciliation": {
            "groups": group_rows,
            "group_realized_pnl_sum_krw": group_pnl_sum,
            "account_realized_pnl_krw": account_realized,
            "delta_krw": pnl_delta,
            "status": "PASS" if assertions["group_realized_pnl_matches_account"] else "FAIL",
            "positions_flat": position_flat,
        },
        "fast_detailed_equivalence": {
            "status": "PASS" if semantic_equal and input_hash_equal else "FAIL",
            "semantic_fields_compared": list(SEMANTIC_KEYS),
            "semantic_equal": semantic_equal,
            "input_hash_equal": input_hash_equal,
        },
        "assertions": assertions,
        "limitations": [
            "DERIVED_SCENARIO synthetic quotes, account, expiry, and calendar; not REAL_VTS or Live evidence.",
            "Synthetic contract identity owner remains unresolved; expiry_is_authoritative=false.",
            "Synthetic zero fees; KIS fee schedule not modeled and fee-inclusive PnL is unverified.",
            "This verdict is validation-only and does not authorize production runtime or orders.",
        ],
        "validation_only": True,
        "runtime_eligible": False,
        "production_runtime_eligible": False,
        "kis_api_called": False,
        "live_orders_or_real_account_used": False,
        "operational_risk_config_modified": False,
        "intermediate_reports": [
            str(FAST_INTERMEDIATE.relative_to(ROOT)).replace("\\", "/"),
            str(DETAILED_INTERMEDIATE.relative_to(ROOT)).replace("\\", "/"),
        ],
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps({
        "report": str(REPORT.relative_to(ROOT)),
        "verdict": report["verdict"],
        "assertions": assertions,
        "events": [fast.get("events"), detailed.get("events")],
        "signals": [fast.get("signals"), detailed.get("signals")],
        "fills": [fast.get("filled"), detailed.get("filled")],
        "expiry_groups": group_rows,
        "group_pnl_sum": group_pnl_sum,
        "account_realized_pnl": account_realized,
        "delta": pnl_delta,
        "detailed_trace_records": len(trace_records),
        "detailed_trace_sha256": sha256(TRACE),
        "report_sha256": sha256(REPORT),
    }, ensure_ascii=False, indent=2, default=str))

if __name__ == "__main__":
    main()
