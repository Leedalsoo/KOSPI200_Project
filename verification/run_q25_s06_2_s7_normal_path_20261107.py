from __future__ import annotations
import json
from decimal import Decimal
from dataclasses import asdict
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
from environments.high_speed.virtual_runtime_replay import HighSpeedVirtualRuntimeReplayRunner

DATASET = ROOT / "data/derived_scenario/q25_s05_3_s7_concurrent"
MANIFEST = DATASET / "manifest.json"
PROFILE = ROOT / "config/validation_only/q25_s05_3_s7_concurrent/risk_profile.json"
TRACE = ROOT / "reports/synth/Q25_A5_S06_2_S7_NORMAL_PATH_TRACE_20261107.jsonl"
REPORT = ROOT / "reports/synth/Q25_A5_S06_2_S7_NORMAL_PATH_RUNTIME_20261107.json"
RUN_ID = "Q25-A5-S06-2-S7-NORMAL-PATH-20261107"

def main() -> None:
    if TRACE.exists():
        raise SystemExit("TRACE_OUTPUT_ALREADY_EXISTS")
    original_execute = VirtualMultiLegExecutionBridge.execute
    bridge_holder = {}
    execution_records = []
    concurrent_open_lot_snapshots = []
    risk_reservations_after_execution = []

    def capture_execute(self, plan, **kwargs):
        result = original_execute(self, plan, **kwargs)
        bridge_holder["bridge"] = self
        reports = []
        for report in result.reports:
            reports.append({
                "status": report.status,
                "leg_id": report.leg_id,
                "execution_id": report.execution_id,
                "filled_quantity": report.filled_quantity,
                "execution_price": str(report.execution_price) if report.execution_price is not None else None,
                "fee": str(report.fee) if report.fee is not None else None,
                "execution_timestamp": report.execution_timestamp.isoformat() if report.execution_timestamp else None,
                "rejected_reason": report.rejected_reason,
            })
        execution_records.append({
            "group_id": plan.group_id,
            "purpose": plan.purpose,
            "planned_legs": [
                {"leg_id": leg.leg_id, "side": str(leg.side),
                 "option_type": str(leg.option_type), "strike": str(leg.strike),
                 "quantity": int(leg.quantity)}
                for leg in plan.legs
            ],
            "reports": reports,
            "position_flat": bool(result.position_flat),
        })
        gate = getattr(self.validation_order_gate, "__self__", None)
        if gate is not None and hasattr(gate, "_reserved"):
            risk_reservations_after_execution.append({
                "group_id": plan.group_id, "purpose": plan.purpose,
                "reserved_groups_after_execution": sorted(gate._reserved),
                "current_group_reserved": plan.group_id in gate._reserved,
            })
        if plan.purpose.startswith("WEEKLY_INSURANCE_ENTRY"):
            lots = [
                {"group_id": lot.group_id, "expiry": str(lot.instrument_identity.expiry),
                 "option_type": str(lot.instrument_identity.option_type),
                 "instrument_id": lot.instrument_id, "remaining_quantity": lot.remaining_quantity,
                 "execution_id": lot.execution_id}
                for lot in self.position_lot_store.open_lots()
                if lot.strategy_id == "track7_volatility_skew_weekly_insurance" and lot.remaining_quantity > 0
            ]
            concurrent_open_lot_snapshots.append({
                "entry_group_id": plan.group_id,
                "entry_time": reports[0]["execution_timestamp"] if reports else None,
                "open_lot_count": len(lots),
                "open_lots": lots,
                "distinct_expiries": sorted({lot["expiry"] for lot in lots}),
                "distinct_groups": sorted({lot["group_id"] for lot in lots}),
            })
        return result

    VirtualMultiLegExecutionBridge.execute = capture_execute
    try:
        runner = HighSpeedVirtualRuntimeReplayRunner(
            DATASET, run_id=RUN_ID,
            strategy_keys=(("track7_volatility_skew_weekly_insurance", "1.0"),),
            validation_only_synthetic=True,
            validation_only_synthetic_manifest=MANIFEST,
            validation_only_s7_risk_profile=PROFILE,
            log_mode="detailed", trace_output=TRACE,
        )
        result = runner.run(max_events=217)
    finally:
        VirtualMultiLegExecutionBridge.execute = original_execute

    bridge = bridge_holder.get("bridge")
    if bridge is None:
        raise SystemExit("RUNTIME_BRIDGE_NOT_CAPTURED")
    history = bridge.position_lot_store.history()
    close_events = bridge.position_lot_store.close_events()
    open_lots = bridge.position_lot_store.open_lots()
    entry_group_ids = sorted({x["group_id"] for x in execution_records if x["purpose"].startswith("WEEKLY_INSURANCE_ENTRY")})
    group_expiries = {}
    for lot in history:
        group_expiries.setdefault(lot.group_id, set()).add(str(lot.instrument_identity.expiry).replace("-", "")[:8])
    snapshots = {}
    for group_id in entry_group_ids:
        snapshot = bridge.position_groups.snapshot(group_id)
        snapshots[group_id] = asdict(snapshot) if snapshot is not None else None
    vssf = bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime
    nonzero_positions = {
        str(key): value for key, value in vssf.account.positions.items()
        if abs(float(value)) > 1e-12
    }
    adapter = runner.s7_validation_runtime_adapter
    audits = list(adapter.risk_audit_records) if adapter is not None else []
    entries = [x for x in execution_records if x["purpose"].startswith("WEEKLY_INSURANCE_ENTRY")]
    closes = [x for x in execution_records if x["purpose"].startswith("WEEKLY_INSURANCE_CLOSE")]
    fill_reports = [r for x in execution_records for r in x["reports"] if r["status"] == "FILLED"]
    fees_total_krw = sum((Decimal(str(r["fee"] or "0")) for r in fill_reports), Decimal("0"))
    group_pnl = {}
    for group_id, snapshot in snapshots.items():
        if snapshot is not None:
            group_pnl[group_id] = {
                "expiry": sorted(group_expiries.get(group_id, set())),
                "realized_pnl": snapshot["realized_pnl"],
                "unrealized_pnl": snapshot["unrealized_pnl"],
                "total_pnl": snapshot["total_pnl"],
                "legs": snapshot["legs"],
            }
    all_groups_expiries = sorted({expiry for values in group_expiries.values() for expiry in values})
    group_pnl_snapshot_sum = sum(float(value["realized_pnl"]) for value in group_pnl.values())
    group_pnl_reconciliation_delta = float(result.realized_pnl) - group_pnl_snapshot_sum
    group_pnl_reconciles = abs(group_pnl_reconciliation_delta) <= 0.01
    reservation_release_correct = all(
        (not item["current_group_reserved"])
        if item["purpose"].startswith("WEEKLY_INSURANCE_CLOSE_CALL")
        else (item["current_group_reserved"])
        if item["purpose"].startswith("WEEKLY_INSURANCE_CLOSE_PUT")
        else True
        for item in risk_reservations_after_execution
    )
    concurrent_proven = any(
        item["open_lot_count"] == 4
        and len(item["distinct_expiries"]) == 2
        and len(item["distinct_groups"]) == 2
        for item in concurrent_open_lot_snapshots
    )
    sequential_order = [
        item["purpose"] for item in entries
    ] == [
        "WEEKLY_INSURANCE_ENTRY_PUT", "WEEKLY_INSURANCE_ENTRY_CALL",
        "WEEKLY_INSURANCE_ENTRY_PUT", "WEEKLY_INSURANCE_ENTRY_CALL",
    ]
    sequential_groups_reused = all(
        entries[index]["group_id"] == entries[index + 1]["group_id"]
        for index in (0, 2)
    )
    passed = (
        result.events == 216 and result.exhausted
        and len(entries) == 4 and len(entry_group_ids) == 2
        and sequential_order and sequential_groups_reused
        and all(len(group_expiries.get(group_id, set())) == 1 for group_id in entry_group_ids)
        and len(all_groups_expiries) == 2
        and concurrent_proven
        and len(fill_reports) == 8 and result.filled == 8 and result.rejected == 0
        and len(close_events) == 4 and len(open_lots) == 0 and not nonzero_positions
        and len(snapshots) == 2 and all(value is not None for value in snapshots.values())
        and result.strategy_status and all(s.runtime_failures == 0 for s in result.strategy_status if s.strategy_id == "track7_volatility_skew_weekly_insurance")
        and adapter is not None and len(audits) == 4 and not adapter._reserved
        and reservation_release_correct and group_pnl_reconciles
    )
    report = {
        "report_id": "Q25_A5_S06_2_S7_NORMAL_PATH_RUNTIME_20261107",
        "verdict": "PSB_PASS_NORMAL_PATH_ONLY" if passed else "PSB_UNVERIFIED",
        "stage_verdict": "PSB_UNVERIFIED_U16_U17_TIMEOUT_CANCEL_POLICY",
        "timeout_cancel_policy_status": "BLOCKED_SPEC_U16_U17",
        "automatic_retry_enabled": False,
        "run_id": RUN_ID,
        "dataset_path": str(DATASET.relative_to(ROOT)).replace("\\", "/"),
        "dataset_sha256": adapter.evidence.dataset_sha256,
        "manifest_sha256": adapter.evidence.manifest_sha256,
        "risk_profile_sha256": adapter.evidence.risk_profile_sha256,
        "events": result.events, "exhausted": result.exhausted,
        "signals": result.signals, "approved": result.approved,
        "routed": result.routed, "filled": result.filled,
        "rejected": result.rejected, "multi_leg_decisions": result.multi_leg_decisions,
        "execution_ids": list(result.execution_ids),
        "entry_group_ids": entry_group_ids,
        "group_expiries": {k: sorted(v) for k, v in group_expiries.items()},
        "all_group_expiries": all_groups_expiries,
        "concurrent_open_lot_snapshots": concurrent_open_lot_snapshots,
        "concurrent_two_expiry_groups_proven": concurrent_proven,
        "sequential_put_call_order": sequential_order,
        "sequential_group_id_reused": sequential_groups_reused,
        "execution_records": execution_records,
        "position_group_snapshots": snapshots,
        "group_pnl": group_pnl,
        "lot_history_count": len(history),
        "close_event_count": len(close_events),
        "remaining_open_lot_count": len(open_lots),
        "remaining_open_lots": [asdict(x) for x in open_lots],
        "nonzero_account_positions": nonzero_positions,
        "risk_audit_records": audits,
        "risk_reservations_after_execution": risk_reservations_after_execution,
        "risk_reservation_retained_until_group_flat": reservation_release_correct,
        "risk_reservations_released": adapter is not None and not adapter._reserved,
        "group_pnl_snapshot_sum": group_pnl_snapshot_sum,
        "group_pnl_reconciliation_delta": group_pnl_reconciliation_delta,
        "group_pnl_reconciles_with_account": group_pnl_reconciles,
        "group_pnl_reconciliation_status": "PASS" if group_pnl_reconciles else "BLOCKED_S05_4_POSITION_PNL_READ_MODEL",
        "runtime_failures": next((s.runtime_failures for s in result.strategy_status if s.strategy_id == "track7_volatility_skew_weekly_insurance"), None),
        "realized_pnl": result.realized_pnl,
        "unrealized_pnl": result.unrealized_pnl,
        "net_pnl": result.net_pnl,
        "pnl_status": result.pnl_status,
        "fees_total_krw": str(fees_total_krw),
        "fee_model_status": "SYNTHETIC_ZERO_FEE; KIS_FEE_SCHEDULE_NOT_MODELED",
        "fee_inclusive_pnl_verified": False,
        "pnl_basis": "GROSS_SYNTHETIC_VSSF_ACCOUNT_PNL_BEFORE_KIS_FEE_SCHEDULE",
        "execution_observer_summary": result.execution_observer_summary,
        "trace_path": str(TRACE.relative_to(ROOT)).replace("\\", "/"),
        "validation_only": True, "runtime_eligible": False,
        "production_runtime_eligible": False,
        "kis_api_called": False, "live_orders_or_real_account_used": False,
        "operational_risk_config_modified": False,
        "assertions": {
            "two_expiry_groups": len(entry_group_ids) == 2 and len(all_groups_expiries) == 2,
            "concurrent_open_lots": concurrent_proven,
            "all_eight_fills": len(fill_reports) == 8 and result.filled == 8,
            "all_groups_closed": len(close_events) == 4 and len(open_lots) == 0,
            "account_flat": not nonzero_positions,
            "group_pnl_snapshots": len(snapshots) == 2 and all(value is not None for value in snapshots.values()),
            "runtime_failures_zero": next((s.runtime_failures for s in result.strategy_status if s.strategy_id == "track7_volatility_skew_weekly_insurance"), None) == 0,
            "risk_audit_four_sequential_legs": len(audits) == 4,
        "sequential_put_call_order": sequential_order,
        "sequential_group_id_reused": sequential_groups_reused,
            "risk_reservations_released": adapter is not None and not adapter._reserved,
            "risk_reservation_retained_until_group_flat": reservation_release_correct,
            "group_pnl_reconciles_with_account": group_pnl_reconciles,
            "each_group_has_both_entry_legs": all(len(value["legs"]) == 2 for value in group_pnl.values()),
            "all_group_legs_flat_after_close": all(all(leg["quantity"] == 0 for leg in value["legs"]) for value in group_pnl.values()),
        },
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))

if __name__ == "__main__":
    main()
