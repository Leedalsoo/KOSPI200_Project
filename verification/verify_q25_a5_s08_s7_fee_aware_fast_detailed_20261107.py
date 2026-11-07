from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import math
from decimal import Decimal
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from environments.high_speed.replay_trace import ReplayLogMode
from environments.high_speed.validation_only_option_fee_model import MODEL_ID, SOURCE_URL, TAX_SOURCE_URL, calculate_option_fee

BASE_RUNNER = ROOT / "verification/run_q25_s08_s7_fee_aware_normal_path_20261107.py"
REPORT = ROOT / "reports/synth/Q25_A5_S08_S7_FEE_AWARE_FAST_DETAILED_20261107.json"
TRACE = ROOT / "reports/synth/Q25_A5_S08_S7_FEE_AWARE_DETAILED_TRACE_20261107.jsonl"
FAST_INTERMEDIATE = ROOT / "reports/synth/Q25_A5_S08_S7_FEE_AWARE_FAST_INTERMEDIATE_20261107.json"
DETAILED_INTERMEDIATE = ROOT / "reports/synth/Q25_A5_S08_S7_FEE_AWARE_DETAILED_INTERMEDIATE_20261107.json"
DATASET = ROOT / "data/derived_scenario/q25_s08_s7_fee_authority"
MANIFEST = DATASET / "manifest.json"
PROFILE = ROOT / "config/validation_only/q25_s08_s7_fee_authority/risk_profile.json"

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
    "risk_reservations_after_execution", "risk_reservation_retained_until_group_flat",
    "risk_reservations_released", "group_pnl_snapshot_sum",
    "group_pnl_reconciliation_delta", "group_pnl_reconciles_with_account",
    "runtime_failures", "realized_pnl", "unrealized_pnl", "net_pnl",
    "pnl_status", "fees_total_krw", "fee_model_status",
    "fee_inclusive_pnl_verified", "pnl_basis", "fee_accounting",
)

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def load_base_module():
    spec = importlib.util.spec_from_file_location("s7_fee_aware_normal_path_runner", BASE_RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("S7_FEE_BASE_RUNNER_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def apply_fee_accounting(payload: dict) -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    model = profile["fees"]
    if model.get("model_id") != MODEL_ID or model.get("included_in_net_pnl") is not True:
        raise AssertionError("S7_FEE_MODEL_PROFILE_INVALID")
    if manifest.get("validation_identity_owner_status") != "CONFIRMED_VALIDATION_ONLY":
        raise AssertionError("S7_SYNTHETIC_IDENTITY_OWNER_NOT_CONFIRMED")
    expiry_authority = manifest.get("scenario_expiry_authority") or {}
    if (expiry_authority.get("status") != "CONFIRMED_VALIDATION_ONLY"
            or expiry_authority.get("authoritative_within_scenario") is not True):
        raise AssertionError("S7_SCENARIO_EXPIRY_AUTHORITY_NOT_CONFIRMED")

    snapshots = payload.get("position_group_snapshots") or {}
    multiplier_by_group_option = {}
    for group_id, snapshot in snapshots.items():
        for leg in snapshot.get("legs", []):
            leg_id = str(leg.get("leg_id", "")).lower()
            multiplier_by_group_option[(group_id, leg_id)] = Decimal(str(leg["contract_multiplier"]))

    fee_by_group: dict[str, int] = {}
    fee_rows = []
    broker_fee_raw = Decimal("0")
    exchange_fee_raw = Decimal("0")
    entry_fee_by_group: dict[str, int] = {}

    for record in payload.get("execution_records", []):
        group_id = str(record["group_id"])
        purpose = str(record.get("purpose", ""))
        plan_legs = record.get("planned_legs") or []
        if len(plan_legs) != 1:
            raise AssertionError("S7_FEE_LEDGER_EXPECTS_SINGLE_LEG_EXECUTION")
        plan_leg = plan_legs[0]
        option_type = str(plan_leg["option_type"]).lower()
        multiplier = multiplier_by_group_option.get((group_id, option_type))
        if multiplier is None or multiplier != Decimal("250000.0"):
            raise AssertionError("S7_FEE_LEDGER_SYNTHETIC_MASTER_MULTIPLIER_MISMATCH")

        for execution in record.get("reports", []):
            if execution.get("status") != "FILLED":
                continue
            if not execution.get("execution_id") or execution.get("execution_price") is None:
                raise AssertionError("S7_FEE_LEDGER_FILLED_EXECUTION_FIELDS_MISSING")
            fee = calculate_option_fee(
                execution["execution_price"], multiplier, execution["filled_quantity"]
            )
            fee_krw = int(fee["total_fee_krw"])
            execution["fee"] = str(fee_krw)
            execution["fee_model_id"] = MODEL_ID
            execution["fee_breakdown"] = {
                "notional_krw": str(fee["notional_krw"]),
                "brokerage_fee_raw_krw": str(fee["brokerage_fee_raw_krw"]),
                "exchange_fee_raw_krw": str(fee["exchange_fee_raw_krw"]),
                "total_fee_raw_krw": str(fee["total_fee_raw_krw"]),
                "total_fee_krw": fee_krw,
                "tier": fee["tier"],
                "tax_krw": 0,
                "rounding": fee["rounding"],
            }
            fee_by_group[group_id] = fee_by_group.get(group_id, 0) + fee_krw
            broker_fee_raw += Decimal(str(fee["brokerage_fee_raw_krw"]))
            exchange_fee_raw += Decimal(str(fee["exchange_fee_raw_krw"]))
            if purpose.startswith("WEEKLY_INSURANCE_ENTRY"):
                entry_fee_by_group[group_id] = entry_fee_by_group.get(group_id, 0) + fee_krw
            fee_rows.append({
                "execution_id": execution["execution_id"],
                "group_id": group_id,
                "purpose": purpose,
                "side": str(plan_leg["side"]),
                "option_type": str(plan_leg["option_type"]),
                "premium_points": str(execution["execution_price"]),
                "quantity": int(execution["filled_quantity"]),
                "contract_multiplier_krw": int(multiplier),
                "notional_krw": str(fee["notional_krw"]),
                "fee_tier": fee["tier"],
                "brokerage_fee_raw_krw": str(fee["brokerage_fee_raw_krw"]),
                "exchange_fee_raw_krw": str(fee["exchange_fee_raw_krw"]),
                "total_fee_krw": fee_krw,
            })

    if len(fee_rows) != 8:
        raise AssertionError(f"S7_FEE_LEDGER_EXPECTED_8_FILLS_GOT_{len(fee_rows)}")

    gross_account_realized = float(payload.get("realized_pnl") or 0)
    gross_account_net = float(payload.get("net_pnl") or 0)
    gross_group_pnl = {
        group_id: float(group.get("realized_pnl") or 0)
        for group_id, group in (payload.get("group_pnl") or {}).items()
    }
    for group_id, fee_krw in fee_by_group.items():
        group = payload["group_pnl"][group_id]
        group["gross_realized_pnl_before_fees_krw"] = group["realized_pnl"]
        group["fees_total_krw"] = fee_krw
        group["realized_pnl"] = float(group["realized_pnl"]) - fee_krw
        group["total_pnl"] = float(group["total_pnl"]) - fee_krw

        snapshot = payload["position_group_snapshots"][group_id]
        snapshot["gross_realized_pnl_before_fees_krw"] = snapshot["realized_pnl"]
        snapshot["fees_total_krw"] = fee_krw
        snapshot["realized_pnl"] = float(snapshot["realized_pnl"]) - fee_krw
        snapshot["total_pnl"] = float(snapshot["total_pnl"]) - fee_krw

    fees_total = sum(fee_by_group.values())
    net_account_realized = gross_account_realized - fees_total
    net_account_pnl = gross_account_net - fees_total
    group_net_sum = sum(float(group["realized_pnl"]) for group in payload["group_pnl"].values())
    delta = net_account_realized - group_net_sum
    payload["gross_realized_pnl_before_fees_krw"] = gross_account_realized
    payload["gross_net_pnl_before_fees_krw"] = gross_account_net
    payload["realized_pnl"] = net_account_realized
    payload["net_pnl"] = net_account_pnl
    payload["fees_total_krw"] = str(fees_total)
    payload["brokerage_fee_raw_total_krw"] = str(broker_fee_raw)
    payload["exchange_fee_raw_total_krw"] = str(exchange_fee_raw)
    payload["fee_model_status"] = "SYNTHETIC_KIS_STANDARD_BRANCH_ONLINE_REFERENCE_APPLIED"
    payload["fee_inclusive_pnl_verified"] = True
    payload["pnl_basis"] = "NET_SYNTHETIC_VSSF_PNL_AFTER_REFERENCE_BROKER_AND_EXCHANGE_FEES"
    payload["group_pnl_snapshot_sum"] = group_net_sum
    payload["group_pnl_reconciliation_delta"] = delta
    payload["group_pnl_reconciles_with_account"] = math.isclose(delta, 0.0, rel_tol=0.0, abs_tol=0.01)
    payload["group_pnl_reconciliation_status"] = "PASS" if payload["group_pnl_reconciles_with_account"] else "FAIL"
    payload["fee_accounting"] = {
        "model_id": MODEL_ID,
        "source": model["source"],
        "source_url": SOURCE_URL,
        "tax_source_url": TAX_SOURCE_URL,
        "session": model["session"],
        "account_scope": model["account_scope"],
        "rounding": model["rounding"],
        "fills_charged": len(fee_rows),
        "fee_rows": fee_rows,
        "fees_by_group_krw": fee_by_group,
        "entry_fee_reserve_by_group_krw": entry_fee_by_group,
        "brokerage_fee_raw_total_krw": str(broker_fee_raw),
        "exchange_fee_raw_total_krw": str(exchange_fee_raw),
        "total_fee_krw": fees_total,
        "derivatives_transaction_tax_krw": 0,
        "gross_account_realized_pnl_krw": gross_account_realized,
        "net_account_realized_pnl_krw": net_account_realized,
        "net_group_realized_pnl_sum_krw": group_net_sum,
        "group_to_account_delta_krw": delta,
    }
    return payload

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
    module.TRACE = trace_path if trace_path is not None else ROOT / "reports/synth/.S7_FEE_FAST_TRACE_NOT_CREATED"
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
    payload = apply_fee_accounting(payload)
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
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

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    group_rows = []
    for group_id, group in sorted((fast.get("group_pnl") or {}).items()):
        legs = group.get("legs") or []
        group_rows.append({
            "group_id": group_id,
            "expiry": group.get("expiry"),
            "gross_realized_pnl_before_fees_krw": group.get("gross_realized_pnl_before_fees_krw"),
            "fees_total_krw": group.get("fees_total_krw"),
            "net_realized_pnl_krw": group.get("realized_pnl"),
            "unrealized_pnl_krw": group.get("unrealized_pnl"),
            "net_total_pnl_krw": group.get("total_pnl"),
            "leg_count": len(legs),
            "all_legs_flat": bool(legs) and all(int(leg.get("quantity", -1)) == 0 for leg in legs),
        })

    fee_rows = fast["fee_accounting"]["fee_rows"]
    entry_fee_reserve_ok = (
        len(fast.get("risk_audit_records", [])) == 4
        and all("computed_entry_fee_reserve_krw" in row for row in fast["risk_audit_records"])
        and all("computed_concurrent_exposure_including_entry_fees_krw" in row for row in fast["risk_audit_records"])
        and all(Decimal(row["computed_max_loss_krw"]) <= Decimal("3300000") for row in fast["risk_audit_records"])
    )
    identity_owner_ok = (
        manifest.get("validation_identity_owner") == "Q25_S7_SYNTHETIC_OPTION_MASTER"
        and manifest.get("validation_identity_owner_status") == "CONFIRMED_VALIDATION_ONLY"
    )
    expiry_authority_ok = (
        manifest.get("scenario_expiry_authority", {}).get("status") == "CONFIRMED_VALIDATION_ONLY"
        and manifest.get("scenario_expiry_authority", {}).get("authoritative_within_scenario") is True
        and manifest.get("scenario_expiry_authority", {}).get("production_exchange_expiry_authoritative") is False
    )
    gross_group_sum = sum(float(row["gross_realized_pnl_before_fees_krw"]) for row in group_rows)
    net_group_sum = sum(float(row["net_realized_pnl_krw"]) for row in group_rows)
    net_account_realized = float(fast.get("realized_pnl") or 0)
    pnl_delta = net_account_realized - net_group_sum
    position_flat = (
        fast.get("remaining_open_lot_count") == 0
        and fast.get("remaining_open_lots") == []
        and fast.get("nonzero_account_positions") == {}
        and all(row["all_legs_flat"] for row in group_rows)
    )
    assertions = {
        "fast_and_detailed_fee_aware_semantics_equal": semantic_equal,
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
        "synthetic_identity_owner_confirmed": identity_owner_ok,
        "scenario_expiry_authority_confirmed": expiry_authority_ok,
        "each_group_has_two_legs_and_is_flat": (
            all(row["leg_count"] == 2 and row["all_legs_flat"] for row in group_rows)
        ),
        "all_positions_flat": position_flat,
        "all_eight_fills_charged": len(fee_rows) == 8 and all(int(row["total_fee_krw"]) > 0 for row in fee_rows),
        "standard_reference_fee_total_is_8940_krw": fast.get("fees_total_krw") == "8940",
        "entry_fee_reserve_in_validation_risk_gate": entry_fee_reserve_ok,
        "fee_inclusive_group_realized_pnl_matches_account": math.isclose(pnl_delta, 0.0, rel_tol=0.0, abs_tol=0.01),
        "gross_group_pnl_matches_pre_fee_account": math.isclose(gross_group_sum, float(fast.get("gross_realized_pnl_before_fees_krw") or 0), rel_tol=0.0, abs_tol=0.01),
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
        "report_id": "Q25_A5_S08_S7_FEE_AWARE_FAST_DETAILED_20261107",
        "scope": "VALIDATION_ONLY_DERIVED_SCENARIO_VIRTUAL_STRATEGY7_WITH_REFERENCE_FEES",
        "verdict": "PSB_PASS" if passed else "PSB_UNVERIFIED",
        "stage_verdict": "PSB_PASS_S7_NATURAL_SIGNAL_FAST_DETAILED_POSITION_PNL_AND_REFERENCE_FEES_VALIDATION_ONLY" if passed else "PSB_UNVERIFIED",
        "run_id": fast.get("run_id"),
        "dataset_path": fast.get("dataset_path"),
        "input_hashes": {
            "dataset_sha256": fast.get("dataset_sha256"),
            "manifest_sha256": fast.get("manifest_sha256"),
            "risk_profile_sha256": fast.get("risk_profile_sha256"),
        },
        "fee_model": {
            "model_id": MODEL_ID,
            "source": fast["fee_accounting"]["source"],
            "source_url": SOURCE_URL,
            "tax_source_url": TAX_SOURCE_URL,
            "account_scope": fast["fee_accounting"]["account_scope"],
            "calculation": "per filled execution: premium points × contract multiplier × quantity × applicable rate; tier-specific KRX fee; ROUND_HALF_UP per execution",
            "all_fills_in_middle_tier": all(row["fee_tier"] == "0_42_TO_BELOW_2_47_POINT" for row in fee_rows),
            "middle_tier_combined_rate": "0.395554%",
            "derivatives_transaction_tax_krw": 0,
        },
        "synthetic_identity_and_expiry_authority": {
            "identity_owner": manifest["validation_identity_owner"],
            "identity_status": manifest["validation_identity_owner_status"],
            "identity_scope": "manifest-bound validation-only synthetic option master; not a Standard/KIS instrument ID",
            "scenario_expiry_authority": manifest["scenario_expiry_authority"],
            "production_identity_and_exchange_expiry_claimed": False,
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
            "gross_realized_pnl_krw": fast.get("gross_realized_pnl_before_fees_krw"),
            "fees_total_krw": fast.get("fees_total_krw"),
            "net_realized_pnl_krw": fast.get("realized_pnl"),
            "net_unrealized_pnl_krw": fast.get("unrealized_pnl"),
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
            "gross_realized_pnl_krw": detailed.get("gross_realized_pnl_before_fees_krw"),
            "fees_total_krw": detailed.get("fees_total_krw"),
            "net_realized_pnl_krw": detailed.get("realized_pnl"),
            "net_unrealized_pnl_krw": detailed.get("unrealized_pnl"),
            "net_pnl_krw": detailed.get("net_pnl"),
            "observer": observer,
            "trace": {
                "path": str(TRACE.relative_to(ROOT)).replace("\\", "/"),
                "records": len(trace_records),
                "market_events": len(market_events),
                "sha256": sha256(TRACE),
                "note": "Raw observer trace records original Virtual Broker fills; fee ledger is applied post-fill in the validation-only accounting layer and cross-checked against identical FAST/DETAILED results."
            },
        },
        "expiry_group_reconciliation": {
            "groups": group_rows,
            "gross_group_realized_pnl_sum_krw": gross_group_sum,
            "fees_total_krw": fast.get("fees_total_krw"),
            "net_group_realized_pnl_sum_krw": net_group_sum,
            "net_account_realized_pnl_krw": net_account_realized,
            "delta_krw": pnl_delta,
            "status": "PASS" if assertions["fee_inclusive_group_realized_pnl_matches_account"] else "FAIL",
            "positions_flat": position_flat,
        },
        "fee_accounting": fast["fee_accounting"],
        "fast_detailed_equivalence": {
            "status": "PASS" if semantic_equal and input_hash_equal else "FAIL",
            "semantic_fields_compared": list(SEMANTIC_KEYS),
            "semantic_equal": semantic_equal,
            "input_hash_equal": input_hash_equal,
        },
        "assertions": assertions,
        "limitations": [
            "The synthetic identity owner and scenario expiry schedule are confirmed only inside this validation dataset; no production Standard instrument ID or KRX/KIS expiry authority is asserted.",
            "The fee schedule is a public KIS standard branch-account online reference model, not a confirmation of the user's account-specific negotiated/discounted rate.",
            "Fee ledger is applied after Virtual Broker fills as a deterministic validation-only accounting overlay; raw observer trace preserves the broker's zero-fee execution payload.",
            "KIS/REAL_VTS/Live/real account/order APIs were not called; runtime_eligible and production_runtime_eligible remain false.",
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
        "fee_total_krw": fast.get("fees_total_krw"),
        "group_rows": group_rows,
        "net_account_realized_pnl": net_account_realized,
        "delta": pnl_delta,
        "detailed_trace_records": len(trace_records),
        "detailed_trace_sha256": sha256(TRACE),
        "report_sha256": sha256(REPORT),
    }, ensure_ascii=False, indent=2, default=str))

if __name__ == "__main__":
    main()
