from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
import environments.high_speed.virtual_runtime_replay as replay_module
import application.composition.automated_virtual_runtime_factory as factory_module
from environments.high_speed.virtual_runtime_replay import HighSpeedVirtualRuntimeReplayRunner

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/derived_scenario/q25_s05_3_s7_concurrent"
MANIFEST = DATASET / "manifest.json"
PROFILE = ROOT / "config/validation_only/q25_s05_3_s7_concurrent/risk_profile.json"
TRACE = ROOT / "reports/synth/Q25_A5_S06_3_S7_U16_TIMEOUT_RUNTIME_TRACE_20261107.jsonl"
REPORT = ROOT / "reports/synth/Q25_A5_S06_3_S7_U16_TIMEOUT_RUNTIME_E2E_20261107.json"
RUN_ID = "Q25-A5-S06-3-S7-U16-TIMEOUT-RUNTIME-20261107"

def main():
    if TRACE.exists() or REPORT.exists():
        raise SystemExit("S06_3_OUTPUT_ALREADY_EXISTS")

    captured = {}
    pending_submissions = []
    cancel_records = []
    clock_advances = []
    original_attach = replay_module.attach_standard_automated_loop
    original_build_registry = factory_module.build_standard_strategy_registry
    original_execute = VirtualMultiLegExecutionBridge.execute
    original_cancel = VirtualMultiLegExecutionBridge.cancel_pending_order

    def build_registry_capture():
        registry = original_build_registry()
        captured['registry'] = registry
        return registry

    def attach_capture(bootstrap, *args, **kwargs):
        loop = original_attach(bootstrap, *args, **kwargs)
        captured["bootstrap"] = bootstrap
        captured["loop"] = loop
        captured["vssf"] = bootstrap.bundle.execution._authoritative_execute.__self__.vssf_runtime

        original_on_tick = loop.on_tick
        bootstrap.bundle.market.unsubscribe(original_on_tick)

        def on_tick_with_validation_clock(tick):
            result = original_on_tick(tick)
            strategy = captured['registry'].get(
                "track7_volatility_skew_weekly_insurance", "1.0"
            )
            state = strategy.state
            client_order_id = state.call_client_order_id
            if (state.entry_stage == "CALL_PENDING" and client_order_id
                    and client_order_id not in {x["client_order_id"] for x in clock_advances}):
                if state.put_entry_filled_at is None:
                    clock_advances.append({
                        "client_order_id": client_order_id,
                        "status": "BLOCKED_MISSING_PUT_FILL_TIMESTAMP",
                    })
                else:
                    deadline = state.put_entry_filled_at + timedelta(minutes=10)
                    captured["vssf"]._market_time = deadline
                    pending_result = loop.pending_multi_leg_processor(
                        SimpleNamespace(timestamp=deadline.isoformat())
                    )
                    matching = [x for x in cancel_records if x["client_order_id"] == client_order_id]
                    clock_advances.append({
                        "client_order_id": client_order_id,
                        "put_filled_at": state.put_entry_filled_at.isoformat(),
                        "timeout_at": deadline.isoformat(),
                        "pending_result_count": len(pending_result or ()),
                        "cancel_seen": bool(matching),
                        "state_after_timeout": strategy.state.entry_stage,
                        "block_reason": strategy.state.entry_block_reason,
                        "put_open": strategy.state.put_open,
                        "call_open": strategy.state.call_open,
                    })
            return result

        loop.on_tick = on_tick_with_validation_clock
        bootstrap.bundle.market.subscribe(on_tick_with_validation_clock)
        return loop

    def execute_with_pending_call(self, plan, **kwargs):
        if (plan.purpose == "WEEKLY_INSURANCE_ENTRY_CALL"
                and not kwargs.get("reconciled_reports")):
            leg = plan.legs[0]
            forced_limit = Decimal("0.01")
            plan = replace(plan, legs=(replace(leg, requested_price=forced_limit),))
        result = original_execute(self, plan, **kwargs)
        pending_submissions.append({
            "purpose": plan.purpose,
            "group_id": plan.group_id,
            "reports": [{
                "client_order_id": r.client_order_id,
                "status": r.status,
                "filled_quantity": r.filled_quantity,
                "remaining_quantity": r.remaining_quantity,
                "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
                "execution_id": r.execution_id,
            } for r in result.reports],
            "pending_legs": result.pending_legs,
        })
        return result

    def cancel_and_record(self, client_order_id, **kwargs):
        result = original_cancel(self, client_order_id, **kwargs)
        cancel_records.append({
            "client_order_id": client_order_id,
            "reports": [{
                "status": r.status,
                "filled_quantity": r.filled_quantity,
                "remaining_quantity": r.remaining_quantity,
                "execution_id": r.execution_id,
                "lifecycle_reason": r.lifecycle_reason,
            } for r in result.reports],
            "pending_legs": result.pending_legs,
            "position_flat": result.position_flat,
        })
        return result

    replay_module.attach_standard_automated_loop = attach_capture
    factory_module.build_standard_strategy_registry = build_registry_capture
    VirtualMultiLegExecutionBridge.execute = execute_with_pending_call
    VirtualMultiLegExecutionBridge.cancel_pending_order = cancel_and_record
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
        replay_module.attach_standard_automated_loop = original_attach
        factory_module.build_standard_strategy_registry = original_build_registry
        VirtualMultiLegExecutionBridge.execute = original_execute
        VirtualMultiLegExecutionBridge.cancel_pending_order = original_cancel

    loop = captured.get("loop")
    if loop is None:
        raise SystemExit("S7_RUNTIME_LOOP_NOT_CAPTURED")
    bridge = loop.multi_leg_bridge
    strategy = captured['registry'].get(
        "track7_volatility_skew_weekly_insurance", "1.0"
    )
    open_lots = bridge.position_lot_store.open_lots()
    states = {
        expiry: {
            "entry_stage": state.entry_stage,
            "entry_block_reason": state.entry_block_reason,
            "put_open": state.put_open,
            "call_open": state.call_open,
            "entry_pending": state.entry_pending,
            "put_entry_filled_at": state.put_entry_filled_at.isoformat() if state.put_entry_filled_at else None,
        }
        for expiry, state in strategy._states_by_expiry.items()
    }
    strategy_status = [{
        "strategy_id": s.strategy_id,
        "runtime_failures": s.runtime_failures,
        "signals": s.reaction_signals,
        "approved": s.approved,
        "routed": s.routed,
        "filled_quantity": s.filled_quantity,
    } for s in result.strategy_status]
    call_initial = [
        r for item in pending_submissions
        if item["purpose"] == "WEEKLY_INSURANCE_ENTRY_CALL"
        for r in item["reports"] if r["status"] == "NEW"
    ]
    all_cancelled = (
        len(cancel_records) == 2
        and all(item["reports"] and item["reports"][0]["status"] == "CANCELLED"
                and item["reports"][0]["filled_quantity"] == 0
                and item["reports"][0]["lifecycle_reason"] == "TIMEOUT_10M"
                for item in cancel_records)
    )
    all_put_only = (
        len(open_lots) == 2
        and all(str(lot.instrument_identity.option_type).upper() == "PUT" for lot in open_lots)
        and all(state["entry_stage"] == "BLOCKED_U16"
                and state["put_open"] and not state["call_open"] and state["entry_pending"]
                for state in states.values())
    )
    passed = (
        result.events == 216 and result.exhausted
        and len(call_initial) == 2
        and all(r["status"] == "NEW" and r["remaining_quantity"] == 1 for r in call_initial)
        and len(clock_advances) == 2
        and all(x.get("timeout_at") and x.get("cancel_seen") for x in clock_advances)
        and all_cancelled and all_put_only
        and len(bridge.pending_legs) == 0
        and all(s["runtime_failures"] == 0 for s in strategy_status
                if s["strategy_id"] == "track7_volatility_skew_weekly_insurance")
    )
    report = {
        "report_id": "Q25_A5_S06_3_S7_U16_TIMEOUT_RUNTIME_E2E_20261107",
        "verdict": "PSB_PASS_U16_VALIDATION_ONLY" if passed else "PSB_UNVERIFIED",
        "stage_verdict": "PSB_UNVERIFIED_U17_RUNTIME_E2E_PENDING",
        "run_id": RUN_ID,
        "dataset_sha256": runner.s7_validation_runtime_adapter.evidence.dataset_sha256,
        "manifest_sha256": runner.s7_validation_runtime_adapter.evidence.manifest_sha256,
        "risk_profile_sha256": runner.s7_validation_runtime_adapter.evidence.risk_profile_sha256,
        "events": result.events,
        "signals": result.signals,
        "approved": result.approved,
        "routed": result.routed,
        "filled": result.filled,
        "rejected": result.rejected,
        "exhausted": result.exhausted,
        "pending_call_submissions": pending_submissions,
        "timeout_clock_advances": clock_advances,
        "cancel_reconciliations": cancel_records,
        "expiry_states": states,
        "open_lot_count": len(open_lots),
        "open_lots": [{
            "group_id": lot.group_id,
            "instrument_id": lot.instrument_id,
            "option_type": str(lot.instrument_identity.option_type),
            "remaining_quantity": lot.remaining_quantity,
            "execution_id": lot.execution_id,
        } for lot in open_lots],
        "pending_bridge_order_count": len(bridge.pending_legs),
        "strategy_status": strategy_status,
        "timeout_cancel_runtime_e2e_verified": passed,
        "u16_policy": "PUT_FILL_PLUS_10M_CANCEL_CALL_KEEP_PUT_BLOCK_ADDITIONAL_ENTRY",
        "pending_fill_control": "Synthetic CALL BUY limit held at 0.01 to force a deterministic no-fill; PUT/CALL strategy signals remained natural StrategyHub outputs.",
        "u17_runtime_e2e_verified": False,
        "validation_only": True,
        "runtime_eligible": False,
        "production_runtime_eligible": False,
        "kis_api_called": False,
        "live_orders_or_real_account_used": False,
        "assertions": {
            "two_natural_call_orders_pending": len(call_initial) == 2 and all(r["status"] == "NEW" for r in call_initial),
            "timeout_clock_from_put_fill": len(clock_advances) == 2 and all(x.get("timeout_at") for x in clock_advances),
            "both_cancelled_and_reconciled": all_cancelled,
            "put_single_leg_positions_retained": all_put_only,
            "no_pending_orders": len(bridge.pending_legs) == 0,
            "zero_runtime_failures": all(s["runtime_failures"] == 0 for s in strategy_status if s["strategy_id"] == "track7_volatility_skew_weekly_insurance"),
        },
        "trace_path": str(TRACE.relative_to(ROOT)).replace("\\", "/"),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not passed:
        raise SystemExit("S06_3_U16_RUNTIME_E2E_ASSERTIONS_FAILED")
    print(json.dumps({
        "verdict": report["verdict"],
        "events": result.events,
        "signals": result.signals,
        "routed": result.routed,
        "filled": result.filled,
        "cancelled": len(cancel_records),
        "open_lots": len(open_lots),
        "states": states,
    }, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()

