from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
import application.composition.automated_virtual_runtime_factory as factory_module
import environments.high_speed.virtual_runtime_replay as replay_module
from environments.high_speed.virtual_runtime_replay import HighSpeedVirtualRuntimeReplayRunner

SOURCE = ROOT / "data/derived_scenario/q25_s05_3_s7_concurrent"
SOURCE_DATA = SOURCE / "20261103.jsonl"
SOURCE_MANIFEST = SOURCE / "manifest.json"
SOURCE_PROFILE = ROOT / "config/validation_only/q25_s05_3_s7_concurrent/risk_profile.json"
OUT_ROOT = ROOT / "data/derived_scenario/q25_s06_3_u17_natural_signal"
PROFILE_ROOT = ROOT / "config/validation_only/q25_s06_3_u17_natural_signal"
REPORT = ROOT / "reports/synth/Q25_A5_S06_3_S7_U17_NATURAL_SIGNAL_RUNTIME_E2E_20261107.json"
EXPIRY = "20261112"
CALL_STRIKE = 512.5
RUN_PREFIX = "Q25-A5-S06-3-S7-U17-NATURAL-20261107"

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def build_variant(name: str, *, race_fill: bool):
    out = OUT_ROOT / name
    profile_dir = PROFILE_ROOT / name
    out.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)
    data_path = out / "20261103.jsonl"
    manifest_path = out / "manifest.json"
    profile_path = profile_dir / "risk_profile.json"

    rows = [json.loads(line) for line in SOURCE_DATA.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != 216:
        raise RuntimeError(f"U17_SOURCE_ROWS_REQUIRED:{len(rows)}")

    # Shift only the validation scenario's Thursday entry-day clock so its natural
    # PUT fill/CALL submission occur immediately before the 15:00 KST cutoff.
    if race_fill:
        time_map = {
            "08:45:00": "14:59:30",
            "09:00:00": "14:59:45",
            "09:10:00": "15:00:00",
            "10:00:00": "15:00:15",
            "13:00:00": "15:00:30",
            "15:10:00": "15:00:45",
        }
    else:
        time_map = {
            "08:45:00": "14:59:30",
            "09:00:00": "15:00:00",
            "09:10:00": "15:00:15",
            "10:00:00": "15:00:30",
            "13:00:00": "15:00:45",
            "15:10:00": "15:01:00",
        }

    for row in rows:
        tick = row["tick"]
        if str(tick["timestamp"]).startswith("2026-11-05T"):
            old_time = str(tick["timestamp"])[11:19]
            if old_time not in time_map:
                raise RuntimeError(f"U17_UNMAPPED_SOURCE_TIME:{old_time}")
            tick["timestamp"] = f"2026-11-05T{time_map[old_time]}+09:00"

    rows.sort(key=lambda row: (
        str(row["tick"]["timestamp"]),
        str(row["scenario_metadata"]["group_id"]),
        0 if str(row["scenario_metadata"]["leg_id"]).upper() == "PUT" else 1,
        int(row["tick"]["seq_id"]),
    ))
    timestamps = [str(row["tick"]["timestamp"]) for row in rows]
    if timestamps != sorted(timestamps):
        raise RuntimeError("U17_DATASET_CHRONOLOGY_FAILED")
    data_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )
    dataset_hash = sha(data_path)

    manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    manifest.update({
        "dataset_path": str(data_path.relative_to(ROOT)).replace("\\", "/"),
        "output_path": str(data_path.relative_to(ROOT)).replace("\\", "/"),
        "dataset_sha256": dataset_hash,
        "output_sha256": dataset_hash,
        "output_bytes": data_path.stat().st_size,
        "rows": len(rows),
        "validation_clock_scenario": "U17_NATURAL_STRATEGY_SIGNAL_NEAR_1500_KST",
        "validation_clock_mapping_20261105": time_map,
        "race_fill_enabled": race_fill,
        "runtime_eligible": False,
        "production_runtime_eligible": False,
        "validation_only": True,
    })
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_hash = sha(manifest_path)

    profile = json.loads(SOURCE_PROFILE.read_text(encoding="utf-8"))
    profile.update({
        "dataset_path": str(data_path.relative_to(ROOT)).replace("\\", "/"),
        "dataset_manifest": str(manifest_path.relative_to(ROOT)).replace("\\", "/"),
        "dataset_sha256": dataset_hash,
        "manifest_sha256": manifest_hash,
        "validation_clock_scenario": "U17_NATURAL_STRATEGY_SIGNAL_NEAR_1500_KST",
        "race_fill_enabled": race_fill,
        "validation_only": True,
        "runtime_eligible": False,
        "production_runtime_eligible": False,
        "allow_kis_api": False,
        "allow_live_orders": False,
        "allow_real_account": False,
        "operational_config_mutated": False,
    })
    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return data_path, manifest_path, profile_path

def run_case(name: str, *, race_fill: bool):
    data_path, manifest_path, profile_path = build_variant(name, race_fill=race_fill)
    run_id = f"{RUN_PREFIX}-{name.upper()}"
    trace_path = ROOT / f"reports/synth/Q25_A5_S06_3_S7_U17_{name.upper()}_TRACE_20261107.jsonl"
    if trace_path.exists():
        raise RuntimeError(f"U17_TRACE_EXISTS:{trace_path.name}")

    captured = {}
    submissions = []
    cancels = []
    lifecycle_actions = []
    race_injections = []
    original_attach = replay_module.attach_standard_automated_loop
    original_registry = factory_module.build_standard_strategy_registry
    original_execute = VirtualMultiLegExecutionBridge.execute
    original_cancel = VirtualMultiLegExecutionBridge.cancel_pending_order
    original_clock_action = None

    def build_registry_capture():
        registry = original_registry()
        captured["registry"] = registry
        return registry

    def attach_capture(bootstrap, *args, **kwargs):
        loop = original_attach(bootstrap, *args, **kwargs)
        captured["loop"] = loop
        captured["bootstrap"] = bootstrap
        captured["vssf"] = bootstrap.bundle.execution._authoritative_execute.__self__.vssf_runtime
        from contracts.track7_order_timeout import Track7OrderTimeoutPolicy
        captured["vssf"].timeout_source._policy = Track7OrderTimeoutPolicy(
            Decimal("600"), "S7-U17-VALIDATION-10M-AFTER-1500"
        )
        bridge = loop.multi_leg_bridge
        original_on_tick = loop.on_tick
        bootstrap.bundle.market.unsubscribe(original_on_tick)

        def on_tick_natural_with_optional_race_quote(tick):
            if race_fill and str(tick.timestamp) == "2026-11-05T14:59:45+09:00" and not race_injections:
                pending = [
                    item for item in bridge.pending_legs.values()
                    if item[0].purpose == "WEEKLY_INSURANCE_ENTRY_CALL"
                ]
                if pending:
                    _group_plan, _leg, broker_command = pending[0]
                    target_id = broker_command.instrument_id
                    vssf = captured["vssf"]
                    vssf.order_book.update_bid_ask(0.005, 0.01, instrument_id=target_id)
                    race_tick = replace(
                        tick,
                        instrument_id=target_id,
                        symbol=target_id,
                        option_type="CALL",
                        strike_price=CALL_STRIKE,
                        expiry=EXPIRY,
                        bid_price=0.005,
                        ask_price=0.01,
                        last_price=0.01,
                    )
                    vssf.process_market_data(race_tick)
                    race_injections.append({
                        "timestamp": str(tick.timestamp),
                        "instrument_id": target_id,
                        "bid": 0.005,
                        "ask": 0.01,
                        "injection_reason": "VALIDATION_ONLY_MARKET_QUOTE_TO_WIN_CANCEL_RACE",
                    })
            return original_on_tick(tick)

        loop.on_tick = on_tick_natural_with_optional_race_quote
        bootstrap.bundle.market.subscribe(on_tick_natural_with_optional_race_quote)
        return loop

    def execute_capture(self, plan, **kwargs):
        if plan.purpose == "WEEKLY_INSURANCE_ENTRY_CALL" and not kwargs.get("reconciled_reports"):
            plan = replace(plan, legs=(replace(plan.legs[0], requested_price=Decimal("0.01")),))
        result = original_execute(self, plan, **kwargs)
        if not kwargs.get("reconciled_reports"):
            submissions.append({
            "purpose": plan.purpose,
            "group_id": plan.group_id,
            "requested_price": str(plan.legs[0].requested_price) if plan.legs else None,
            "reports": [{
                "client_order_id": report.client_order_id,
                "status": report.status,
                "filled_quantity": report.filled_quantity,
                "remaining_quantity": report.remaining_quantity,
                "submitted_at": report.submitted_at.isoformat() if report.submitted_at else None,
                "execution_timestamp": report.execution_timestamp.isoformat() if report.execution_timestamp else None,
                "execution_id": report.execution_id,
                "lifecycle_reason": report.lifecycle_reason,
            } for report in result.reports],
            "pending_legs": result.pending_legs,
            })
        return result

    def cancel_capture(self, client_order_id, **kwargs):
        result = original_cancel(self, client_order_id, **kwargs)
        cancels.append({
            "client_order_id": client_order_id,
            "reason": kwargs.get("reason"),
            "reports": [{
                "status": report.status,
                "filled_quantity": report.filled_quantity,
                "remaining_quantity": report.remaining_quantity,
                "execution_id": report.execution_id,
                "execution_timestamp": report.execution_timestamp.isoformat() if report.execution_timestamp else None,
                "lifecycle_reason": report.lifecycle_reason,
            } for report in result.reports],
            "pending_legs": result.pending_legs,
        })
        return result

    from core.strategy.track7_volatility_skew_weekly_insurance import Track7VolatilitySkewWeeklyInsurance
    original_clock_action = Track7VolatilitySkewWeeklyInsurance.lifecycle_clock_action

    def clock_action_capture(self, now):
        action = original_clock_action(self, now)
        if action is not None:
            lifecycle_actions.append({
                "now": now.isoformat(),
                "kind": action.kind,
                "client_order_id": action.client_order_id,
                "reason": action.reason,
                "expiry": self.state.expiry,
            })
        return action

    replay_module.attach_standard_automated_loop = attach_capture
    factory_module.build_standard_strategy_registry = build_registry_capture
    VirtualMultiLegExecutionBridge.execute = execute_capture
    VirtualMultiLegExecutionBridge.cancel_pending_order = cancel_capture
    Track7VolatilitySkewWeeklyInsurance.lifecycle_clock_action = clock_action_capture
    try:
        replay_rows = [
            json.loads(line) for line in data_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        stop_timestamp = (
            "2026-11-05T14:59:45+09:00" if race_fill
            else "2026-11-05T15:00:00+09:00"
        )
        stop_index = next(
            (index for index, row in enumerate(replay_rows)
             if row["tick"]["timestamp"] == stop_timestamp),
            None,
        )
        if stop_index is None:
            raise RuntimeError(f"U17_STOP_TIMESTAMP_NOT_FOUND:{stop_timestamp}")
        event_limit = stop_index + 1

        runner = HighSpeedVirtualRuntimeReplayRunner(
            data_path.parent,
            run_id=run_id,
            strategy_keys=(("track7_volatility_skew_weekly_insurance", "1.0"),),
            validation_only_synthetic=True,
            validation_only_synthetic_manifest=manifest_path,
            validation_only_s7_risk_profile=profile_path,
            log_mode="detailed",
            trace_output=trace_path,
        )
        result = runner.run(max_events=event_limit)
    finally:
        replay_module.attach_standard_automated_loop = original_attach
        factory_module.build_standard_strategy_registry = original_registry
        VirtualMultiLegExecutionBridge.execute = original_execute
        VirtualMultiLegExecutionBridge.cancel_pending_order = original_cancel
        Track7VolatilitySkewWeeklyInsurance.lifecycle_clock_action = original_clock_action

    loop = captured.get("loop")
    if loop is None:
        raise RuntimeError("U17_NATURAL_RUNTIME_LOOP_NOT_CAPTURED")
    bridge = loop.multi_leg_bridge
    strategy = captured["registry"].get("track7_volatility_skew_weekly_insurance", "1.0")
    vssf = captured["vssf"]
    state = strategy._states_by_expiry.get(EXPIRY)
    call_submissions = [
        item for item in submissions
        if item["purpose"] == "WEEKLY_INSURANCE_ENTRY_CALL"
        and item["reports"]
        and str(item["reports"][0]["submitted_at"] or "").startswith("2026-11-05")
    ]
    call_orders = [
        report for item in call_submissions for report in item["reports"]
    ]
    target_call_order_ids = [report["client_order_id"] for report in call_orders]
    final_orders = []
    for client_order_id in target_call_order_ids:
        report = vssf.query_order(client_order_id)
        target_group_id = next(
            item["group_id"] for item in call_submissions
            if any(report["client_order_id"] == client_order_id for report in item["reports"])
        )
        reconciled = next((
            item for item in reversed(bridge.group_reports(target_group_id))
            if item.leg_id == "call" and item.status in {"FILLED", "CANCELLED"}
        ), None)
        final_orders.append({
            "client_order_id": client_order_id,
            "status": report.status if report else None,
            "filled_quantity": getattr(reconciled, "filled_quantity", 0) if reconciled else None,
            "remaining_quantity": getattr(reconciled, "remaining_quantity", None) if reconciled else None,
            "execution_id": getattr(reconciled, "execution_id", None) if reconciled else None,
            "execution_timestamp": getattr(reconciled, "execution_timestamp", None).isoformat()
                if reconciled and getattr(reconciled, "execution_timestamp", None) else None,
            "lifecycle_reason": getattr(report, "lifecycle_reason", None) if report else None,
        })

    open_lots = [
        {
            "group_id": lot.group_id,
            "option_type": str(lot.instrument_identity.option_type),
            "quantity": lot.remaining_quantity,
            "execution_id": lot.execution_id,
        }
        for lot in bridge.position_lot_store.open_lots()
        if str(lot.instrument_identity.expiry).replace("-", "")[:8] == EXPIRY
    ]
    return {
        "case": name,
        "race_fill": race_fill,
        "events": result.events,
        "event_limit": event_limit,
        "exhausted": result.exhausted,
        "signals": result.signals,
        "approved": result.approved,
        "routed": result.routed,
        "filled": result.filled,
        "rejected": result.rejected,
        "runtime_failures": next((item.runtime_failures for item in result.strategy_status
                                  if item.strategy_id == "track7_volatility_skew_weekly_insurance"), None),
        "natural_strategy_signal_count": result.signals,
        "call_submissions": call_submissions,
        "call_final_orders": final_orders,
        "lifecycle_actions": [
            item for item in lifecycle_actions
            if item["expiry"] == EXPIRY and item["reason"] == "15:00_CUTOFF"
        ],
        "cancel_reconciliations": [
            item for item in cancels
            if item["reason"] == "15:00_CUTOFF" and item["client_order_id"] in target_call_order_ids
        ],
        "race_quote_injections": race_injections,
        "validation_timeout_policy_seconds": "600",
        "strategy_state": None if state is None else {
            "entry_stage": state.entry_stage,
            "entry_block_reason": state.entry_block_reason,
            "put_entry_filled_at": state.put_entry_filled_at.isoformat() if state.put_entry_filled_at else None,
            "call_submitted_at": state.call_submitted_at.isoformat() if state.call_submitted_at else None,
            "put_open": state.put_open,
            "call_open": state.call_open,
            "insurance_active": state.insurance_active,
            "entry_pending": state.entry_pending,
            "entry_cancel_reason": state.entry_cancel_reason,
        },
        "open_lots": open_lots,
        "pending_bridge_orders": len(bridge.pending_legs),
        "trace_path": str(trace_path.relative_to(ROOT)).replace("\\", "/"),
        "dataset_sha256": runner.s7_validation_runtime_adapter.evidence.dataset_sha256,
        "manifest_sha256": runner.s7_validation_runtime_adapter.evidence.manifest_sha256,
        "risk_profile_sha256": runner.s7_validation_runtime_adapter.evidence.risk_profile_sha256,
    }

def main():
    if REPORT.exists():
        raise SystemExit("U17_NATURAL_SIGNAL_REPORT_ALREADY_EXISTS")
    cancelled = run_case("cancel_at_1500", race_fill=False)
    filled = run_case("fill_before_1500_cancel", race_fill=True)

    cancel_ok = (
        cancelled["events"] == cancelled["event_limit"] and not cancelled["exhausted"]
        and cancelled["runtime_failures"] == 0
        and cancelled["strategy_state"] is not None
        and cancelled["strategy_state"]["entry_stage"] == "BLOCKED_U17"
        and cancelled["strategy_state"]["put_open"]
        and not cancelled["strategy_state"]["call_open"]
        and cancelled["strategy_state"]["entry_cancel_reason"] == "15:00_CUTOFF"
        and len(cancelled["call_submissions"]) == 1
        and cancelled["call_submissions"][0]["reports"][0]["submitted_at"] == "2026-11-05T14:59:30+09:00"
        and len(cancelled["call_final_orders"]) == 1
        and cancelled["call_final_orders"][0]["status"] == "CANCELLED"
        and cancelled["call_final_orders"][0]["lifecycle_reason"] == "15:00_CUTOFF"
        and len(cancelled["lifecycle_actions"]) == 1
        and cancelled["lifecycle_actions"][0]["reason"] == "15:00_CUTOFF"
        and cancelled["pending_bridge_orders"] == 0
        and {lot["option_type"] for lot in cancelled["open_lots"]} == {"PUT"}
    )
    fill_ok = (
        filled["events"] == filled["event_limit"] and not filled["exhausted"]
        and filled["runtime_failures"] == 0
        and filled["strategy_state"] is not None
        and filled["strategy_state"]["entry_stage"] == "COMPLETE"
        and filled["strategy_state"]["put_open"]
        and filled["strategy_state"]["call_open"]
        and filled["strategy_state"]["insurance_active"]
        and len(filled["call_submissions"]) == 1
        and filled["call_submissions"][0]["reports"][0]["submitted_at"] == "2026-11-05T14:59:30+09:00"
        and len(filled["call_final_orders"]) == 1
        and filled["call_final_orders"][0]["status"] == "FILLED"
        and filled["call_final_orders"][0]["execution_id"]
        and len(filled["race_quote_injections"]) == 1
        and len(filled["lifecycle_actions"]) == 0
        and filled["pending_bridge_orders"] == 0
        and {lot["option_type"] for lot in filled["open_lots"]} == {"PUT", "CALL"}
    )
    passed = cancel_ok and fill_ok
    report = {
        "report_id": "Q25_A5_S06_3_S7_U17_NATURAL_SIGNAL_RUNTIME_E2E_20261107",
        "verdict": "PSB_PASS_U17_NATURAL_SIGNAL_VALIDATION_ONLY" if passed else "PSB_UNVERIFIED",
        "stage_verdict": "PSB_PASS_U16_U17_VALIDATION_ONLY" if passed else "PSB_UNVERIFIED_U17_NATURAL_SIGNAL_RUNTIME_E2E",
        "cancel_at_1500": cancelled,
        "fill_before_cancel_race": filled,
        "assertions": {
            "natural_strategy_call_submitted_before_1500_and_cancelled_at_cutoff": cancel_ok,
            "natural_strategy_call_fill_wins_before_1500_cancel": fill_ok,
        },
        "natural_strategy_signal_used": True,
        "validation_only_order_price_control": "CALL BUY requested_price=0.01 is applied only in the validation runner after StrategyHub emitted the natural CALL signal, to maintain a pending order until the cutoff/race event.",
        "validation_only_race_quote": "The race case injects a synthetic CALL quote at 14:59:45 KST to make the pending CALL fill before the 15:00 lifecycle check.",
        "validation_only_order_timeout_policy": "600 seconds, so the broker's separate timeout occurs after the 15:00 cutoff and cannot pre-empt the S7 cutoff cancellation.",
        "validation_only": True,
        "runtime_eligible": False,
        "production_runtime_eligible": False,
        "kis_api_called": False,
        "live_orders_or_real_account_used": False,
        "operational_risk_config_modified": False,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not passed:
        raise SystemExit("U17_NATURAL_SIGNAL_RUNTIME_ASSERTIONS_FAILED")
    print(json.dumps({
        "verdict": report["verdict"],
        "cancel_at_1500": {
            "signals": cancelled["signals"],
            "call_submission": cancelled["call_submissions"],
            "final_order": cancelled["call_final_orders"],
            "state": cancelled["strategy_state"],
        },
        "fill_before_cancel_race": {
            "signals": filled["signals"],
            "call_submission": filled["call_submissions"],
            "final_order": filled["call_final_orders"],
            "state": filled["strategy_state"],
        },
    }, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()

