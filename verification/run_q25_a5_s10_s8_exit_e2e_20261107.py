from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
REPORT_PATH = ROOT / "reports/synth/Q25_A5_S10_S8_EXIT_FAST_DETAILED_20261107_FINAL3.json"
STRATEGY = "track8_macro_regime_monthly_strangle"
SCENARIOS = {
    "stop": {
        "expected_exit_reason": "CALL_LEG_50PCT_ENTRY_FILL_STOP",
        "expected_close_purpose": "MONTHLY_STRANGLE_CLOSE_CALL",
        "expected_fills": 3,
        "expected_open_lots": 1,
        "expected_state": {"is_active": True, "call_open": False, "put_open": True},
    },
    "trailing": {
        "expected_exit_reason": "CALL_LEG_2X_ARMED_10PCT_DRAWDOWN",
        "expected_close_purpose": "MONTHLY_STRANGLE_CLOSE_CALL",
        "expected_fills": 3,
        "expected_open_lots": 1,
        "expected_state": {"is_active": True, "call_open": False, "put_open": True},
    },
    "expiry": {
        "expected_exit_reason": "MONTHLY_EXPIRY_15:10_FORCE_CLOSE",
        "expected_close_purpose": "MONTHLY_STRANGLE_CLOSE",
        "expected_fills": 4,
        "expected_open_lots": 0,
        "expected_state": {"is_active": False, "call_open": False, "put_open": False},
    },
}


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def plain(value: Any) -> Any:
    if is_dataclass(value):
        return plain(asdict(value))
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set)):
        return [plain(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return value.as_posix()
    return value


def strategy_state(strategy: Any) -> dict[str, Any]:
    state = strategy.state
    return {
        key: plain(getattr(state, key))
        for key in (
            "is_active", "entry_pending", "entry_stage", "call_open", "put_open",
            "call_entry_fill_price", "put_entry_fill_price", "call_peak_mark",
            "put_peak_mark", "call_strike", "put_strike", "expiry",
            "entry_block_reason",
        )
    } | {"exit_pending": bool(strategy._exit_pending)}


def report_summary(report: Any) -> dict[str, Any]:
    status = next((item for item in report.strategy_status if item.strategy_id == STRATEGY), None)
    return {
        "run_id": report.run_id,
        "events": report.events,
        "signals": report.signals,
        "approved": report.approved,
        "routed": report.routed,
        "filled": report.filled,
        "rejected": report.rejected,
        "execution_ids": list(report.execution_ids),
        "realized_pnl_krw": report.realized_pnl,
        "unrealized_pnl_krw": report.unrealized_pnl,
        "net_pnl_krw": report.net_pnl,
        "strategy_status": plain(status),
    }


def run_once(scenario: str, mode: str) -> dict[str, Any]:
    from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
    from core.strategy.track8_macro_regime_monthly_strangle import Track8MacroRegimeMonthlyStrangle
    from environments.high_speed.replay_trace import ReplayLogMode
    from environments.high_speed.virtual_runtime_replay import HighSpeedVirtualRuntimeReplayRunner

    folder = ROOT / "data/derived_scenario/q25_a5_s09_s8_exit_scenarios" / scenario
    manifest_path = folder / "manifest.json"
    risk_profile_path = ROOT / "config/validation_only/q25_a5_s09_s8_exit_scenarios" / scenario / "risk_profile.json"
    trace_path = (
        ROOT / "reports/synth" /
        f"Q25_A5_S10_S8_{scenario.upper()}_DETAILED_TRACE_20261107_FINAL3.jsonl"
        if mode == "detailed" else None
    )
    run_id = f"Q25-A5-S10-{scenario.upper()}-20261107"
    captured: dict[str, Any] = {
        "execution_events": [],
        "strategy_callbacks": [],
        "exit_evaluations": [],
        "exit_signals": [],
        "final_runtime_snapshot": None,
    }

    original_execute = VirtualMultiLegExecutionBridge.execute
    original_refresh = VirtualMultiLegExecutionBridge.refresh_position_group_marks
    original_callback = Track8MacroRegimeMonthlyStrangle.on_execution_result
    original_take_profit = Track8MacroRegimeMonthlyStrangle.evaluate_take_profit
    original_expiry = Track8MacroRegimeMonthlyStrangle.evaluate_expiry_cutoff

    def capture_runtime_snapshot(bridge: Any) -> dict[str, Any]:
        groups = bridge.position_groups.all()
        return {
            "open_lots": plain(bridge.position_lot_store.open_lots()),
            "position_groups": plain(groups),
            "group_snapshots": {
                group_id: plain(bridge.position_groups.snapshot(group_id))
                for group_id in groups
            },
            "fee_records": plain(bridge.fee_ledger.snapshot(run_id=bridge.run_id)),
        }

    def capture_execute(bridge: Any, plan: Any, *args: Any, **kwargs: Any):
        result = original_execute(bridge, plan, *args, **kwargs)
        if getattr(plan, "strategy_id", None) == STRATEGY:
            captured["execution_events"].append({
                "purpose": str(getattr(plan, "purpose", "") or ""),
                "plan_legs": [
                    {
                        "leg_id": leg.leg_id,
                        "side": leg.side,
                        "option_type": leg.option_type,
                        "strike": str(leg.strike),
                        "quantity": leg.quantity,
                    }
                    for leg in plan.legs
                ],
                "reports": [
                    {
                        "leg_id": getattr(item, "leg_id", None),
                        "status": str(getattr(item, "status", "")),
                        "filled_quantity": getattr(item, "filled_quantity", 0),
                        "remaining_quantity": getattr(item, "remaining_quantity", 0),
                        "execution_id": getattr(item, "execution_id", None),
                        "execution_price": plain(getattr(item, "execution_price", None)),
                        "rejected_reason": getattr(item, "rejected_reason", None),
                    }
                    for item in getattr(result, "reports", ())
                ],
                "group_complete": bool(getattr(result, "group_complete", False)),
                "position_flat": bool(getattr(result, "position_flat", False)),
            })
        return result

    def capture_refresh(bridge: Any, *args: Any, **kwargs: Any):
        result = original_refresh(bridge, *args, **kwargs)
        captured["final_runtime_snapshot"] = capture_runtime_snapshot(bridge)
        return result

    def capture_callback(strategy_obj: Any, purpose: str, result: Any):
        before = strategy_state(strategy_obj)
        original_callback(strategy_obj, purpose, result)
        after = strategy_state(strategy_obj)
        captured["strategy_callbacks"].append({
            "purpose": purpose,
            "before": before,
            "after": after,
            "position_flat": bool(getattr(result, "position_flat", False)),
            "group_complete": bool(getattr(result, "group_complete", False)),
            "reports": [
                {
                    "leg_id": getattr(item, "leg_id", None),
                    "status": str(getattr(item, "status", "")),
                    "filled_quantity": getattr(item, "filled_quantity", 0),
                    "remaining_quantity": getattr(item, "remaining_quantity", 0),
                    "execution_id": getattr(item, "execution_id", None),
                    "rejected_reason": getattr(item, "rejected_reason", None),
                }
                for item in getattr(result, "reports", ())
            ],
        })

    def capture_take_profit(strategy_obj: Any, context: Any):
        analytics = context.analytics
        marks = {
            key: plain(getattr(analytics.get(key), "value", None))
            for key in ("options.track8_call_mark_price", "options.track8_put_mark_price")
        }
        signals = original_take_profit(strategy_obj, context)
        captured["exit_evaluations"].append({
            "kind": "PER_LEG_STOP_OR_TRAILING",
            "timestamp": analytics.as_of.isoformat(),
            "marks": marks,
            "state_after_evaluation": strategy_state(strategy_obj),
            "signals": [signal.reason for signal in signals],
        })
        captured["exit_signals"].extend({
            "timestamp": analytics.as_of.isoformat(),
            "reason": signal.reason,
            "kind": "PER_LEG_STOP_OR_TRAILING",
        } for signal in signals)
        return signals

    def capture_expiry(strategy_obj: Any, context: Any):
        signals = original_expiry(strategy_obj, context)
        if signals:
            captured["exit_evaluations"].append({
                "kind": "EXPIRY_CUTOFF",
                "timestamp": context.analytics.as_of.isoformat(),
                "state_after_evaluation": strategy_state(strategy_obj),
                "signals": [signal.reason for signal in signals],
            })
            captured["exit_signals"].extend({
                "timestamp": context.analytics.as_of.isoformat(),
                "reason": signal.reason,
                "kind": "EXPIRY_CUTOFF",
            } for signal in signals)
        return signals

    VirtualMultiLegExecutionBridge.execute = capture_execute
    VirtualMultiLegExecutionBridge.refresh_position_group_marks = capture_refresh
    Track8MacroRegimeMonthlyStrangle.on_execution_result = capture_callback
    Track8MacroRegimeMonthlyStrangle.evaluate_take_profit = capture_take_profit
    Track8MacroRegimeMonthlyStrangle.evaluate_expiry_cutoff = capture_expiry

    try:
        runner = HighSpeedVirtualRuntimeReplayRunner(
            folder,
            run_id=run_id,
            validation_only_synthetic=True,
            validation_only_synthetic_manifest=manifest_path,
            validation_only_s8_risk_profile=risk_profile_path,
            strategy_keys=((STRATEGY, "2.0"),),
            log_mode=ReplayLogMode.DETAILED if mode == "detailed" else ReplayLogMode.FAST,
            trace_output=trace_path,
        )
        report = runner.run()
        runtime_adapter = runner.s8_validation_runtime_adapter
    finally:
        VirtualMultiLegExecutionBridge.execute = original_execute
        VirtualMultiLegExecutionBridge.refresh_position_group_marks = original_refresh
        Track8MacroRegimeMonthlyStrangle.on_execution_result = original_callback
        Track8MacroRegimeMonthlyStrangle.evaluate_take_profit = original_take_profit
        Track8MacroRegimeMonthlyStrangle.evaluate_expiry_cutoff = original_expiry

    if captured["final_runtime_snapshot"] is None:
        raise RuntimeError(f"S10_FINAL_RUNTIME_SNAPSHOT_MISSING:{scenario}:{mode}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        "scenario": scenario,
        "mode": mode,
        "report": report_summary(report),
        "scenario_id": manifest["scenario_id"],
        "dataset_sha256": digest_bytes((folder / "20261107.jsonl").read_bytes()),
        "manifest_sha256": digest_bytes(manifest_path.read_bytes()),
        "risk_profile_sha256": digest_bytes(risk_profile_path.read_bytes()),
        "risk_audit": plain(runtime_adapter.risk_audit_records),
        "execution_events": captured["execution_events"],
        "strategy_callbacks": captured["strategy_callbacks"],
        "exit_evaluations": captured["exit_evaluations"],
        "exit_signals": captured["exit_signals"],
        "final_runtime_snapshot": captured["final_runtime_snapshot"],
        "trace": {
            "status": report.trace_status,
            "path": trace_path.relative_to(ROOT).as_posix() if trace_path else None,
            "sha256": digest_bytes(trace_path.read_bytes()) if trace_path and trace_path.is_file() else None,
            "execution_observer": plain(report.execution_observer_summary),
        },
    }


def semantic_projection(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "report": result["report"],
        "scenario_id": result["scenario_id"],
        "dataset_sha256": result["dataset_sha256"],
        "manifest_sha256": result["manifest_sha256"],
        "risk_profile_sha256": result["risk_profile_sha256"],
        "risk_audit": result["risk_audit"],
        "execution_events": result["execution_events"],
        "strategy_callbacks": result["strategy_callbacks"],
        "exit_evaluations": result["exit_evaluations"],
        "exit_signals": result["exit_signals"],
        "final_runtime_snapshot": result["final_runtime_snapshot"],
    }


def verify_scenario(scenario: str, fast: dict[str, Any], detailed: dict[str, Any]) -> dict[str, Any]:
    expected = SCENARIOS[scenario]
    semantic_equal = (
        json.dumps(semantic_projection(fast), sort_keys=True, separators=(",", ":"))
        == json.dumps(semantic_projection(detailed), sort_keys=True, separators=(",", ":"))
    )
    exit_reasons = [item["reason"] for item in fast["exit_signals"]]
    close_events = [
        item for item in fast["execution_events"]
        if item["purpose"] in {"MONTHLY_STRANGLE_CLOSE_CALL", "MONTHLY_STRANGLE_CLOSE_PUT", "MONTHLY_STRANGLE_CLOSE"}
    ]
    snapshot = fast["final_runtime_snapshot"]
    open_lots = snapshot["open_lots"]
    callbacks = fast["strategy_callbacks"]
    final_state = callbacks[-1]["after"] if callbacks else {}
    close_reports = []
    if close_events:
        close_report_count = 2 if close_events[0]["purpose"] == "MONTHLY_STRANGLE_CLOSE" else 1
        close_reports = close_events[0]["reports"][-close_report_count:]
    close_fills = sum(
        1 for report in close_reports
        if report["status"] == "FILLED" and report["filled_quantity"] > 0
    )
    expected_close_fills = 2 if expected["expected_close_purpose"] == "MONTHLY_STRANGLE_CLOSE" else 1
    state_matches = all(final_state.get(key) == value for key, value in expected["expected_state"].items())
    scenario_pass = (
        semantic_equal
        and exit_reasons.count(expected["expected_exit_reason"]) == 1
        and len(close_events) == 1
        and close_events[0]["purpose"] == expected["expected_close_purpose"]
        and fast["report"]["filled"] == expected["expected_fills"]
        and fast["report"]["rejected"] == 0
        and len(open_lots) == expected["expected_open_lots"]
        and state_matches
        and close_fills == expected_close_fills
        and all(report["status"] == "FILLED" for report in close_reports)
        and bool(snapshot["position_groups"])
    )
    return {
        "scenario": scenario,
        "status": "PASS" if scenario_pass else "FAIL",
        "fast_detailed_semantic_equivalence": semantic_equal,
        "expected_exit_reason": expected["expected_exit_reason"],
        "observed_exit_reasons": exit_reasons,
        "close_purpose": close_events[0]["purpose"] if close_events else None,
        "expected_fills": expected["expected_fills"],
        "observed_fills": fast["report"]["filled"],
        "rejected": fast["report"]["rejected"],
        "close_filled_reports": close_fills,
        "expected_open_lots": expected["expected_open_lots"],
        "observed_open_lots": len(open_lots),
        "final_strategy_state": final_state,
        "strategy_state_matches": state_matches,
        "realized_pnl_krw": fast["report"]["realized_pnl_krw"],
        "unrealized_pnl_krw": fast["report"]["unrealized_pnl_krw"],
        "net_pnl_krw": fast["report"]["net_pnl_krw"],
        "position_group_snapshots": snapshot["group_snapshots"],
        "fee_records": snapshot["fee_records"],
    }


POLICY_MATRIX = [
    {
        "id": "S8-U16",
        "question": "Entry window 3 days and 15:00 cutoff; holidays/short sessions",
        "status": "PARTIALLY_RESOLVED",
        "validation_basis": "No.1169 sets a 3-trading-day retry window and third-day 15:00 KST cutoff; holiday/short-session boundary remains unresolved.",
    },
    {
        "id": "S8-U17",
        "question": "DTE entry gate 15 or 10 trading days",
        "status": "RESOLVED_BY_NO1169",
        "validation_basis": "DTE >= 10 trading days; the earlier DTE >= 15 gate is superseded.",
    },
    {
        "id": "S8-U18",
        "question": "Minimum budget 200,000 KRW gate",
        "status": "RESOLVED_BY_NO1169",
        "validation_basis": "The old 200,000 KRW minimum-budget gate is retired.",
    },
    {
        "id": "S8-U19",
        "question": "Which strike rank is attempted first, 5 or 6",
        "status": "OPEN",
        "validation_basis": "No explicit first-rank choice is included in S09; operational setting remains unset/fail-closed.",
    },
    {
        "id": "S8-U20",
        "question": "Opposite-leg timeout and retry/single-leg exposure policy",
        "status": "BLOCKED_POLICY_CODE_MISMATCH",
        "validation_basis": "No.1169 confirms the 10-minute no-fill timer and 3-trading-day retry window, but leaves retry interval and attempt count UNSET. Current Track8 code still contains retry_count >= 3; this legacy code default is not an approved policy and the retry path was not exercised in S10.",
        "code_observation": "core/strategy/track8_macro_regime_monthly_strangle.py hard-codes retry_count >= 3; requires a separate approved policy/code reconciliation before retry-path promotion.",
    },
    {
        "id": "S8-U21",
        "question": "Authoritative active/base volatility source, window, cadence and freshness",
        "status": "OPEN",
        "validation_basis": "No authoritative source/window/freshness contract is promoted by this synthetic exit validation.",
    },
    {
        "id": "S8-U22",
        "question": "Per-leg maximum premium and strategy/account maximum-loss/margin limits",
        "status": "OPEN",
        "validation_basis": "S09's 2,300,000 KRW cap is a validation-only scenario limit, not an approved operational risk limit.",
    },
]


def main() -> None:
    if REPORT_PATH.exists():
        raise FileExistsError(f"S10 report already exists; refusing to overwrite: {REPORT_PATH}")
    results = []
    for scenario in ("stop", "trailing", "expiry"):
        fast = run_once(scenario, "fast")
        detailed = run_once(scenario, "detailed")
        results.append({
            "scenario": scenario,
            "fast": fast,
            "detailed": detailed,
            "verification": verify_scenario(scenario, fast, detailed),
        })

    all_pass = all(item["verification"]["status"] == "PASS" for item in results)
    report = {
        "report_id": "Q25_A5_S10_S8_EXIT_FAST_DETAILED_20261107",
        "stage": "S10",
        "status": "PSB_PASS_VALIDATION_ONLY_SYNTHETIC" if all_pass else "PSB_FAIL_OR_UNVERIFIED",
        "provenance": "DERIVED_SCENARIO",
        "validation_only": True,
        "runtime_eligible": False,
        "production_runtime_eligible": False,
        "created_at_kst": datetime.now().astimezone().isoformat(),
        "scenario_count": len(results),
        "scenario_results": results,
        "policy_matrix": POLICY_MATRIX,
        "policy_readiness": "BLOCKED_OPEN_OR_UNAPPROVED_ENTRY_POLICIES",
        "next_stage": "S11 — S8 PLUMBING_ONLY-to-natural-signal promotion mapping, eligible-case re-run and verdict; separate stage approval required.",
        "mark_policy": {
            "source_field": "DERIVED_SCENARIO tick.last_price",
            "scope": "S8 validation-only manifest-bound quote mark",
            "production_authority": False,
        },
        "fee_policy": {
            "status": "NOT_INCLUDED",
            "virtual_fill_fee_krw": 0,
            "actual_account_fee_claim": False,
        },
        "limitations": [
            "S8 v0.3 remains a draft/unapproved specification; 50% stop, 2x/10% trailing and expiry 15:10 are exercised only as validation-only scenario assumptions.",
            "The synthetic last_price is the mark source for this validation run; production mark source/cadence/freshness remains unresolved.",
            "S09 entry ask reference values are not used as cost basis; exit thresholds use actual Virtual execution fill prices.",
            "STOP/TRAILING close only the triggered leg; the opposite leg remains open and independently managed.",
            "EXPIRY closes both remaining legs at 15:10 KST through Virtual Broker; no cash settlement is run in S10.",
            "No fees are applied in these S09 scenario risk profiles.",
            "S8-U16 remains partially resolved; S8-U20 is blocked by a code/policy mismatch; U19/U21/U22 remain open. No operational default was changed.",
            "No.1169 leaves retry interval and attempt count UNSET; current code's retry_count >= 3 is an unapproved legacy default and must not be promoted as a confirmed rule.",
            "No KIS API, REAL_VTS, Live, real account, real order, or production risk configuration was used.",
        ],
        "safety": {
            "kis_api_called": False,
            "real_vts_used": False,
            "live_used": False,
            "real_account_used": False,
            "real_order_api_called": False,
            "operational_risk_config_changed": False,
            "existing_s09_dataset_overwritten": False,
        },
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    REPORT_PATH.write_bytes(raw)
    report_hash = digest_bytes(raw)
    REPORT_PATH.with_name(REPORT_PATH.name + ".sha256").write_text(
        f"{report_hash}  {REPORT_PATH.name}\n", encoding="ascii"
    )
    print(json.dumps({
        "status": report["status"],
        "report_path": REPORT_PATH.relative_to(ROOT).as_posix(),
        "report_sha256": report_hash,
        "scenario_verifications": [item["verification"] for item in results],
        "policy_matrix": POLICY_MATRIX,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
