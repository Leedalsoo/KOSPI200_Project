from __future__ import annotations

import copy
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
REPORT_PATH = ROOT / "reports/synth/Q25_A5_S11B_S8_RETRY_NATURAL_RUNTIME_E2E_20261108.json"
DATA_ROOT = ROOT / "data/derived_scenario/q25_a5_s11b_s8_retry"
PROFILE_ROOT = ROOT / "config/validation_only/q25_a5_s11b_s8_retry"
STRATEGY = "track8_macro_regime_monthly_strangle"

from verification.generate_q25_a5_s09_s8_exit_scenarios_20261107 import (
    build_rows, validate_rows, TRADING_DAYS, MULTIPLIER,
)

SCENARIOS = {
    "retry_success": {
        "scenario_id": "Q25_A5_S11B_S8_RETRY_SUCCESS_20261108",
        "group_id": "S8_A5_S11B_RETRY_SUCCESS_20261119",
        "event_marks": {
            ("2026-11-05", "09:00:00"): {"CALL": Decimal("1.00"), "PUT": Decimal("1.00")},
            ("2026-11-05", "09:10:00"): {"CALL": Decimal("1.00"), "PUT": Decimal("1.00")},
            ("2026-11-05", "09:20:00"): {"CALL": Decimal("1.00"), "PUT": Decimal("1.00")},
        },
        "expectation": {"call_retries": 1, "put_retries": 1, "expected_open_lots": 2},
        "mode": "success",
    },
    "retry_exhausted": {
        "scenario_id": "Q25_A5_S11B_S8_RETRY_EXHAUSTED_20261108",
        "group_id": "S8_A5_S11B_RETRY_EXHAUSTED_20261119",
        "event_marks": {
            ("2026-11-05", "09:00:00"): {"CALL": Decimal("1.00"), "PUT": Decimal("1.00")},
            ("2026-11-05", "09:10:00"): {"CALL": Decimal("1.00"), "PUT": Decimal("1.00")},
            ("2026-11-05", "09:20:00"): {"CALL": Decimal("1.00"), "PUT": Decimal("1.00")},
            ("2026-11-05", "09:30:00"): {"CALL": Decimal("1.00"), "PUT": Decimal("1.00")},
            ("2026-11-05", "09:40:00"): {"CALL": Decimal("1.00"), "PUT": Decimal("1.00")},
        },
        "expectation": {"call_retries": 3, "blocked_reason": "TRACK8_CALL_RETRY_LIMIT_REACHED"},
        "mode": "exhausted",
    },
    "third_day_cutoff": {
        "scenario_id": "Q25_A5_S11B_S8_THIRD_DAY_CUTOFF_20261108",
        "group_id": "S8_A5_S11B_THIRD_DAY_CUTOFF_20261119",
        "event_marks": {
            ("2026-11-05", "09:00:00"): {"CALL": Decimal("1.00"), "PUT": Decimal("1.00")},
            ("2026-11-09", "15:00:00"): {"CALL": Decimal("1.00"), "PUT": Decimal("1.00")},
        },
        "expectation": {"call_retries": 0, "blocked_reason": "TRACK8_RETRY_WINDOW_CLOSED_OR_UNVERIFIED"},
        "mode": "cutoff",
    },
}


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_or_verify(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise FileExistsError(f"Refusing to overwrite differing S11b artifact: {path}")
        return
    with path.open("xb") as handle:
        handle.write(raw)


def plain(value: Any) -> Any:
    if is_dataclass(value):
        return plain(asdict(value))
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list, set)):
        return [plain(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return value.as_posix()
    return value


def build_assets() -> dict[str, dict[str, Any]]:
    if REPORT_PATH.exists():
        raise FileExistsError(f"Refusing to overwrite S11b report: {REPORT_PATH}")
    template_profile = json.loads(
        (ROOT / "config/validation_only/q25_a5_s09_s8_exit_scenarios/stop/risk_profile.json")
        .read_text(encoding="utf-8")
    )
    outputs: dict[str, dict[str, Any]] = {}
    for key, spec in SCENARIOS.items():
        scenario = {
            "key": key, "scenario_id": spec["scenario_id"],
            "group_id": spec["group_id"], "event_marks": spec["event_marks"],
            "expectation": spec["expectation"],
        }
        rows, _raw = build_rows(scenario)
        for row in rows:
            row["tick"]["underlying_source"] = "SYNTHETIC:q25-a5-s11b-s8-retry-generator"
            row["scenario_metadata"]["purpose"] = (
                "S8 retry natural StrategyHub signal to Virtual Runtime E2E; "
                "validation-only synthetic data, not KIS or exchange market data."
            )
            row["scenario_metadata"]["scenario_phase"] = (
                "INITIAL_SUBMISSION" if row["tick"]["timestamp"].endswith("09:00:00+09:00")
                else "RETRY_OR_TERMINAL_OBSERVATION"
            )
        raw = b"".join(
            (json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            for row in rows
        )
        validation = validate_rows(scenario, rows)
        folder = DATA_ROOT / key
        profile_folder = PROFILE_ROOT / key
        dataset_name = "20261108.jsonl"
        dataset_rel = (folder / dataset_name).relative_to(ROOT).as_posix()
        manifest_rel = (folder / "manifest.json").relative_to(ROOT).as_posix()
        profile_rel = (profile_folder / "risk_profile.json").relative_to(ROOT).as_posix()
        dataset_hash = digest(raw)

        profile = copy.deepcopy(template_profile)
        profile["profiles"]["track8_monthly_strangle"]["dataset_manifest"] = manifest_rel
        profile["profiles"]["track8_monthly_strangle"]["entry_policy"] = (
            "No.1169 DTE >= 10 trading days; No.1397 600-second TIMEOUT_10M "
            "plus terminal CANCELLED; max 3 retries per leg; 3-trading-day window "
            "with third-day 15:00:00 KST cutoff."
        )
        profile["profiles"]["track8_monthly_strangle"]["budget_basis"] = (
            "One CALL + one PUT BUY pair, one contract per leg; validation-only premium cap."
        )
        profile_raw = json_bytes(profile)
        profile_hash = digest(profile_raw)
        times = sorted({
            datetime.fromisoformat(row["tick"]["timestamp"]).strftime("%H:%M:%S")
            for row in rows
        })
        manifest = {
            "schema_version": "q25-a2-1-s6-syn-evt-manifest-v1",
            "scenario_id": spec["scenario_id"],
            "strategy_id": "strategy8_monthly",
            "source_type": "DERIVED_SCENARIO",
            "provenance": "DERIVED_SCENARIO",
            "synthetic": True,
            "validation_only": True,
            "runtime_eligible": False,
            "production_runtime_eligible": False,
            "identity_source_status": "BLOCKED_IDENTITY_OWNER_UNRESOLVED",
            "validation_identity_namespace": f"SYNTHETIC_CONTRACT:S8A5S09:{key.upper()}:",
            "expiry_is_authoritative": False,
            "contract_identity_authority": "SYNTHETIC_ONLY",
            "dataset_path": dataset_rel,
            "dataset_sha256": dataset_hash,
            "output_sha256": dataset_hash,
            "output_bytes": len(raw),
            "output_path": dataset_rel,
            "rows": len(rows),
            "groups": [spec["group_id"]],
            "scenario_regime": "NORMAL",
            "scenario_kind": "S8_RETRY_RUNTIME",
            "seed": 20261108,
            "date_start": "2026-11-05",
            "date_end": "2026-11-19",
            "date_end_exclusive": "2026-11-20",
            "trading_calendar": {
                "calendar_id": f"S8_A5_S11B_{key.upper()}_SYNTHETIC_CALENDAR",
                "source_type": "SYNTHETIC",
                "authoritative": False,
                "timezone": "Asia/Seoul",
                "trading_days": TRADING_DAYS,
                "provenance": "Explicit validation-only schedule; not KIS or KRX authoritative calendar.",
            },
            "session_times_kst": times,
            "strategy_policy_inputs": {
                "strategy8_min_entry_dte_trading_days": 10,
                "strategy8_entry_timeout_minutes": 10,
                "strategy8_entry_retry_window_trading_days": 3,
                "strategy8_third_day_cutoff_kst": "15:00:00",
                "strategy8_retry_interval_minutes": None,
                "strategy8_max_retries_per_leg": 3,
                "strategy8_max_attempts_per_leg": 4,
                "strategy8_retry_trigger": "TIMEOUT_10M_AND_TERMINAL_CANCELLED",
                "policy_scope": "VALIDATION_ONLY; No.1397 approved policy replayed with synthetic inputs.",
            },
            "policy_sources": [
                "No.1169: DTE >= 10 trading days; retry window 3 trading days; third-day 15:00 KST cutoff.",
                "No.1397: 600-second unfilled timeout classified TIMEOUT_10M; retry only after terminal CANCELLED; max 3 retries per leg; partial fill, manual cancel, reject and unknown terminal state are not retryable.",
                "No.1398: CALL and PUT each remain one contract for this E2E; multi-contract partial-fill policy is not expanded.",
            ],
            "scenario_expectations": spec["expectation"],
            "scenario_reference_only": {
                "selected_call_strike": "515",
                "selected_put_strike": "485",
                "contract_multiplier": str(MULTIPLIER),
                "entry_reference_is_ask_not_actual_fill": True,
                "actual_virtual_fill_and_retry_state_required": True,
            },
            "risk_profile_path": profile_rel,
            "risk_profile_sha256": profile_hash,
            "market_rule_limitations": [
                "All prices, quotes, contract identity, expiry and calendar values are synthetic validation inputs.",
                "Synthetic contract identity and multiplier are not authoritative KIS/Standard identity.",
                "No KIS, REAL_VTS, Live, account, or real order API evidence is included.",
            ],
        }
        manifest_raw = json_bytes(manifest)
        manifest_hash = digest(manifest_raw)
        data_path = ROOT / dataset_rel
        profile_path = ROOT / profile_rel
        manifest_path = ROOT / manifest_rel
        write_or_verify(data_path, raw)
        write_or_verify(data_path.with_name(data_path.name + ".sha256"),
                        f"{dataset_hash}  {data_path.name}\n".encode("ascii"))
        write_or_verify(profile_path, profile_raw)
        write_or_verify(profile_path.with_name(profile_path.name + ".sha256"),
                        f"{profile_hash}  {profile_path.name}\n".encode("ascii"))
        write_or_verify(manifest_path, manifest_raw)
        write_or_verify(manifest_path.with_name(manifest_path.name + ".sha256"),
                        f"{manifest_hash}  {manifest_path.name}\n".encode("ascii"))

        from environments.high_speed.validation_only_s8_runtime_adapter import S8ValidationOnlyRuntimeAdapter
        adapter = S8ValidationOnlyRuntimeAdapter(
            dataset=folder, manifest_path=manifest_path, risk_profile_path=profile_path
        )
        validation["adapter_manifest_profile_binding"] = "PASS"
        validation["adapter_scenario_id"] = adapter.evidence.scenario_id
        outputs[key] = {
            "dataset_path": dataset_rel,
            "manifest_path": manifest_rel,
            "risk_profile_path": profile_rel,
            "dataset_sha256": dataset_hash,
            "manifest_sha256": manifest_hash,
            "risk_profile_sha256": profile_hash,
            "rows": len(rows),
            "validation": validation,
        }
    return outputs


class ReplayMarketClock:
    def __init__(self, vssf: Any):
        self.vssf = vssf

    def now(self) -> datetime:
        if self.vssf._market_time is None:
            raise RuntimeError("S11B_REPLAY_MARKET_TIME_UNAVAILABLE")
        return self.vssf._market_time

    def monotonic(self) -> float:
        return 0.0

    def sleep_policy(self, seconds: float) -> None:
        raise RuntimeError("S11B_REPLAY_CLOCK_MUST_ADVANCE_ONLY_BY_DATASET_EVENTS")


def report_value(item: Any) -> dict[str, Any]:
    status = getattr(item, "status", "")
    return {
        "client_order_id": getattr(item, "client_order_id", None),
        "leg_id": str(getattr(item, "leg_id", "") or "").lower(),
        "status": str(getattr(status, "value", status)).upper(),
        "filled_quantity": int(getattr(item, "filled_quantity", 0) or 0),
        "remaining_quantity": int(getattr(item, "remaining_quantity", 0) or 0),
        "lifecycle_reason": getattr(item, "lifecycle_reason", None),
        "submitted_at": plain(getattr(item, "submitted_at", None)),
        "execution_timestamp": plain(getattr(item, "execution_timestamp", None)),
        "execution_id": getattr(item, "execution_id", None),
        "execution_price": plain(getattr(item, "execution_price", None)),
        "rejected_reason": getattr(item, "rejected_reason", None),
    }


def build_paths(key: str) -> dict[str, Any]:
    folder = DATA_ROOT / key
    profile_folder = PROFILE_ROOT / key
    return {
        "dataset_path": (folder / "20261108.jsonl").relative_to(ROOT).as_posix(),
        "manifest_path": (folder / "manifest.json").relative_to(ROOT).as_posix(),
        "risk_profile_path": (profile_folder / "risk_profile.json").relative_to(ROOT).as_posix(),
        "dataset_sha256": digest((folder / "20261108.jsonl").read_bytes()),
        "manifest_sha256": digest((folder / "manifest.json").read_bytes()),
        "risk_profile_sha256": digest((profile_folder / "risk_profile.json").read_bytes()),
    }


def run_once(key: str, mode: str) -> dict[str, Any]:
    from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
    from core.strategy.track8_macro_regime_monthly_strangle import Track8MacroRegimeMonthlyStrangle
    from contracts.track7_order_timeout import Track7OrderTimeoutPolicy
    from application.composition.track7_order_timeout_source import Track7OrderTimeoutRuntimeSource
    from environments.virtual.authoritative_vssf.order_book import OrderBook
    from environments.high_speed import virtual_runtime_replay as replay_module
    from environments.high_speed.replay_trace import ReplayLogMode
    from environments.high_speed.virtual_runtime_replay import HighSpeedVirtualRuntimeReplayRunner

    spec = SCENARIOS[key]
    paths = build_paths(key)
    run_id = f"Q25-A5-S11B-{key.upper()}-20261108"
    trace_path = ROOT / "reports/synth" / f"Q25_A5_S11B_{key.upper()}_DETAILED_TRACE_20261108.jsonl"
    if mode == "detailed" and trace_path.exists():
        raise FileExistsError(f"Refusing to overwrite S11b trace: {trace_path}")

    captured: dict[str, Any] = {
        "strategy_signals": [], "strategy_callbacks": [],
        "execution_events": [], "order_match_events": [],
    }
    refs: dict[str, Any] = {}
    original_attach = replay_module.attach_standard_automated_loop
    original_match = OrderBook.match_order
    original_execute = VirtualMultiLegExecutionBridge.execute
    original_evaluate = Track8MacroRegimeMonthlyStrangle.evaluate
    original_callback = Track8MacroRegimeMonthlyStrangle.on_execution_result

    def attach_with_s8_retry_clock(bootstrap: Any, **kwargs: Any):
        loop = original_attach(bootstrap, **kwargs)
        vssf = bootstrap.bundle.execution._authoritative_execute.__self__.vssf_runtime
        vssf.clock = None
        vssf.timeout_source = Track7OrderTimeoutRuntimeSource(
            ReplayMarketClock(vssf),
            Track7OrderTimeoutPolicy(Decimal("600"), "S8_VALIDATION_ONLY_10M"),
        )
        refs.update({"loop": loop, "vssf": vssf, "bridge": loop.multi_leg_bridge})
        return loop

    first_blocked_id: dict[str, str] = {}

    def controlled_match(order_book: Any, command: Any) -> float:
        track = str(getattr(command, "track_id", "") or getattr(command, "strategy_id", "") or "")
        side_value = getattr(command, "side", "")
        side = str(getattr(side_value, "value", side_value)).upper()
        leg = str(getattr(command, "leg_id", "") or "").lower()
        client_id = str(getattr(command, "client_order_id", "") or "")
        suppress = False
        if track == STRATEGY and side == "BUY" and leg in {"call", "put"}:
            if spec["mode"] == "success":
                if leg not in first_blocked_id:
                    first_blocked_id[leg] = client_id
                    suppress = True
                elif first_blocked_id[leg] == client_id:
                    suppress = True
            elif spec["mode"] in {"exhausted", "cutoff"} and leg == "call":
                suppress = True
        if track == STRATEGY:
            captured["order_match_events"].append({
                "client_order_id": client_id,
                "leg_id": leg,
                "side": side,
                "timestamp": plain(getattr(refs.get("vssf"), "_market_time", None)),
                "suppressed_for_timeout_scenario": suppress,
            })
        return 0.0 if suppress else original_match(order_book, command)

    def capture_execute(bridge: Any, plan: Any, *args: Any, **kwargs: Any):
        result = original_execute(bridge, plan, *args, **kwargs)
        if getattr(plan, "strategy_id", None) == STRATEGY:
            captured["execution_events"].append({
                "purpose": str(getattr(plan, "purpose", "") or ""),
                "group_id": getattr(plan, "group_id", None),
                "attempt_id": getattr(plan, "attempt_id", None),
                "plan_legs": [{
                    "leg_id": leg.leg_id, "side": leg.side,
                    "option_type": leg.option_type, "quantity": leg.quantity,
                    "strike": str(leg.strike),
                } for leg in plan.legs],
                "reports": [report_value(item) for item in getattr(result, "reports", ())],
                "group_complete": bool(getattr(result, "group_complete", False)),
                "position_flat": bool(getattr(result, "position_flat", False)),
                "pending_legs": int(getattr(result, "pending_legs", 0) or 0),
            })
        return result

    def capture_evaluate(strategy: Any, context: Any):
        signals = original_evaluate(strategy, context)
        if getattr(context, "strategy_id", None) == STRATEGY:
            refs["strategy"] = strategy
            captured["strategy_signals"].append({
                "timestamp": plain(getattr(getattr(context, "analytics", None), "as_of", None)),
                "entry_stage": getattr(strategy.state, "entry_stage", None),
                "signals": [{
                    "reason": signal.reason,
                    "proposal": {
                        "tag_id": getattr(signal.execution_proposal, "tag_id", None),
                        "side": getattr(signal.execution_proposal, "side", None),
                        "option_type": getattr(signal.execution_proposal, "option_type", None),
                        "quantity": getattr(signal.execution_proposal, "proposed_quantity", None),
                    } if getattr(signal, "execution_proposal", None) is not None else None,
                } for signal in signals],
            })
        return signals

    def capture_callback(strategy: Any, purpose: str, result: Any):
        before = plain(strategy.state)
        original_callback(strategy, purpose, result)
        captured["strategy_callbacks"].append({
            "purpose": purpose,
            "before": before,
            "after": plain(strategy.state),
            "reports": [report_value(item) for item in getattr(result, "reports", ())],
            "group_complete": bool(getattr(result, "group_complete", False)),
            "position_flat": bool(getattr(result, "position_flat", False)),
        })

    replay_module.attach_standard_automated_loop = attach_with_s8_retry_clock
    OrderBook.match_order = controlled_match
    VirtualMultiLegExecutionBridge.execute = capture_execute
    Track8MacroRegimeMonthlyStrangle.evaluate = capture_evaluate
    Track8MacroRegimeMonthlyStrangle.on_execution_result = capture_callback
    try:
        runner = HighSpeedVirtualRuntimeReplayRunner(
            ROOT / paths["dataset_path"].rsplit("/", 1)[0],
            run_id=run_id,
            validation_only_synthetic=True,
            validation_only_synthetic_manifest=ROOT / paths["manifest_path"],
            validation_only_s8_risk_profile=ROOT / paths["risk_profile_path"],
            strategy_keys=((STRATEGY, "2.0"),),
            log_mode=ReplayLogMode.DETAILED if mode == "detailed" else ReplayLogMode.FAST,
            trace_output=trace_path if mode == "detailed" else None,
        )
        report = runner.run()
    finally:
        replay_module.attach_standard_automated_loop = original_attach
        OrderBook.match_order = original_match
        VirtualMultiLegExecutionBridge.execute = original_execute
        Track8MacroRegimeMonthlyStrangle.evaluate = original_evaluate
        Track8MacroRegimeMonthlyStrangle.on_execution_result = original_callback

    bridge, vssf = refs["bridge"], refs["vssf"]
    strategy = refs.get("strategy")
    groups = bridge.position_groups.all()
    snapshot = {
        "open_lots": plain(bridge.position_lot_store.open_lots()),
        "position_groups": plain(groups),
        "group_snapshots": {
            group_id: plain(bridge.position_groups.snapshot(group_id)) for group_id in groups
        },
        "account_positions": plain(vssf.account.positions),
        "realized_pnl": plain(vssf.account.realized_pnl),
        "unrealized_pnl": plain(vssf.account.unrealized_pnl),
        "net_pnl": plain(vssf.account.realized_pnl + vssf.account.unrealized_pnl),
        "execution_reports": plain(vssf.execution_engine.reports),
    }
    return {
        "scenario": key,
        "mode": mode,
        "report": {
            "events": report.events, "signals": report.signals,
            "approved": report.approved, "routed": report.routed,
            "filled": report.filled, "rejected": report.rejected,
            "execution_ids": list(report.execution_ids),
            "exhausted": report.exhausted,
            "realized_pnl": plain(report.realized_pnl),
            "unrealized_pnl": plain(report.unrealized_pnl),
            "net_pnl": plain(report.net_pnl),
            "strategy_signal_counts": plain(report.strategy_signal_counts),
            "strategy_status": plain(report.strategy_status),
        },
        "strategy_signals": captured["strategy_signals"],
        "strategy_callbacks": captured["strategy_callbacks"],
        "execution_events": captured["execution_events"],
        "order_match_events": captured["order_match_events"],
        "strategy_state": plain(strategy.state) if strategy is not None else None,
        "final_runtime_snapshot": snapshot,
        "risk_audit_records": plain(runner.s8_validation_runtime_adapter.risk_audit_records),
        "manifest_sha256": paths["manifest_sha256"],
        "dataset_sha256": paths["dataset_sha256"],
        "risk_profile_sha256": paths["risk_profile_sha256"],
    }


def semantic_projection(result: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "report", "strategy_signals", "strategy_callbacks", "execution_events",
        "order_match_events", "strategy_state", "final_runtime_snapshot",
        "risk_audit_records", "manifest_sha256", "dataset_sha256", "risk_profile_sha256",
    )
    return {key: result[key] for key in keys}


def order_latest(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for event in events:
        for item in event["reports"]:
            if item.get("client_order_id"):
                latest[item["client_order_id"]] = item
    return latest


def verify(key: str, fast: dict[str, Any], detailed: dict[str, Any]) -> dict[str, Any]:
    equal = json.dumps(semantic_projection(fast), sort_keys=True, separators=(",", ":")) == json.dumps(
        semantic_projection(detailed), sort_keys=True, separators=(",", ":")
    )
    state = fast["strategy_state"] or {}
    orders = order_latest(fast["execution_events"])
    call_orders = [item for item in orders.values() if item["leg_id"] == "call"]
    put_orders = [item for item in orders.values() if item["leg_id"] == "put"]
    retry_ids = [event["attempt_id"] for event in fast["execution_events"] if event["attempt_id"]]
    open_lots = fast["final_runtime_snapshot"]["open_lots"]
    signals = [signal for batch in fast["strategy_signals"] for signal in batch["signals"]]
    timeout_orders = [
        item for item in orders.values()
        if item["status"] == "CANCELLED" and item["lifecycle_reason"] == "TIMEOUT_10M"
    ]
    if key == "retry_success":
        ok = (
            equal
            and state.get("is_active") is True and state.get("entry_pending") is False
            and state.get("call_open") is True and state.get("put_open") is True
            and state.get("qty_call") == 1 and state.get("qty_put") == 1
            and state.get("call_retry_count") == 1 and state.get("put_retry_count") == 1
            and len(call_orders) == 2 and len(put_orders) == 2
            and len(timeout_orders) == 2
            and {"CALL-RETRY-1", "PUT-RETRY-1"}.issubset(set(retry_ids))
            and all(item["status"] in {"CANCELLED", "FILLED"} for item in call_orders + put_orders)
            and len(open_lots) == 2 and fast["report"]["rejected"] == 0
            and fast["report"]["filled"] == 2
            and any("RETRY:1" in str(item.get("reason", "")) for item in signals)
        )
    elif key == "retry_exhausted":
        ok = (
            equal and state.get("entry_stage") == "BLOCKED"
            and state.get("entry_block_reason") == "TRACK8_CALL_RETRY_LIMIT_REACHED"
            and state.get("call_retry_count") == 3
            and len(call_orders) == 4 and len(timeout_orders) == 4
            and {"CALL-RETRY-1", "CALL-RETRY-2", "CALL-RETRY-3"}.issubset(set(retry_ids))
            and fast["report"]["filled"] == 0 and len(open_lots) == 0
        )
    else:
        ok = (
            equal and state.get("entry_stage") == "BLOCKED"
            and state.get("entry_block_reason") == "TRACK8_RETRY_WINDOW_CLOSED_OR_UNVERIFIED"
            and state.get("call_retry_count") == 0
            and len(call_orders) == 1 and len(timeout_orders) == 1
            and not any("RETRY:" in str(item.get("reason", "")) for item in signals)
            and fast["report"]["filled"] == 0 and len(open_lots) == 0
        )
    return {
        "scenario": key, "status": "PASS" if ok else "FAIL",
        "fast_detailed_semantic_equivalence": equal,
        "strategy_state": state,
        "call_order_count": len(call_orders), "put_order_count": len(put_orders),
        "timeout_terminal_cancel_count": len(timeout_orders),
        "retry_attempt_ids": retry_ids, "open_lot_count": len(open_lots),
        "report_counts": fast["report"],
    }


def main() -> None:
    assets = build_assets()
    results = []
    for key in SCENARIOS:
        fast = run_once(key, "fast")
        detailed = run_once(key, "detailed")
        results.append({
            "scenario": key, "assets": assets[key],
            "fast": fast, "detailed": detailed,
            "verification": verify(key, fast, detailed),
        })
    all_pass = all(item["verification"]["status"] == "PASS" for item in results)
    report = {
        "report_id": "Q25_A5_S11B_S8_RETRY_NATURAL_RUNTIME_E2E_20261108",
        "stage": "S11b",
        "status": "PSB_PASS_VALIDATION_ONLY_SYNTHETIC" if all_pass else "PSB_FAIL_OR_UNVERIFIED",
        "provenance": "DERIVED_SCENARIO",
        "validation_only": True,
        "runtime_eligible": False,
        "production_runtime_eligible": False,
        "scenario_count": len(results),
        "scenario_results": results,
        "plumbing_promotion_mapping": [
            {"item": "No.1395 timeout/callback", "result": "PROMOTE_TO_PSB_PASS_VALIDATION_ONLY", "basis": "Natural StrategyHub signal through 600-second timeout, terminal CANCELLED callback and retry decision."},
            {"item": "No.1396 retry calendar", "result": "PROMOTE_TO_PSB_PASS_VALIDATION_ONLY", "basis": "Natural Runtime timeout at third trading day 15:00 KST blocks retry."},
            {"item": "No.1397 retry execution", "result": "PROMOTE_TO_PSB_PASS_VALIDATION_ONLY", "basis": "CALL and PUT retry orders use distinct attempt IDs and fill through Virtual execution."},
            {"item": "No.1398 multi-contract partial fill", "result": "RETAIN_PLUMBING_ONLY", "basis": "This E2E retains one contract per CALL/PUT; multi-contract partial-fill policy and natural-signal E2E remain outside scope."},
            {"item": "No.1402 PositionGroup MTM", "result": "ALREADY_PROMOTED", "basis": "Existing S11 mapping."},
            {"item": "No.1405 expiry cash settlement", "result": "ALREADY_PROMOTED_VALIDATION_ONLY", "basis": "Existing S11 mapping; not authoritative KIS settlement."},
            {"item": "No.1423 S10 exits", "result": "ALREADY_PROMOTED_VALIDATION_ONLY", "basis": "Existing natural-signal STOP/TRAILING/EXPIRY exit E2E."},
        ],
        "policy": {
            "timeout_seconds": 600, "timeout_reason": "TIMEOUT_10M",
            "retry_requires_terminal_cancelled": True, "max_retries_per_leg": 3,
            "trading_day_window_includes_submission_day": True,
            "third_day_cutoff_kst": "15:00:00",
            "partial_fill_retry": False, "manual_cancel_retry": False,
            "reject_retry": False, "unknown_terminal_retry": False,
            "call_quantity": 1, "put_quantity": 1,
        },
        "limitations": [
            "Only synthetic DERIVED_SCENARIO quotes, synthetic option identity, non-authoritative multiplier and explicit validation-only calendar were used.",
            "The replay-only OrderBook match control deliberately leaves first CALL/PUT orders pending in the success case and all CALL attempts pending in guard cases; Virtual VSSF timeout/cancel/query/bridge/StrategyHub/OMS/Risk/Position path remains active.",
            "No.1398 multi-contract partial-fill behavior remains PLUMBING_ONLY and is not promoted.",
            "S8 policy readiness, authoritative contract identity, operational risk limits, fees and production eligibility remain blocked/unapproved.",
            "This result is not REAL_VTS, Live, real-account or production readiness evidence.",
        ],
        "safety": {
            "kis_api_called": False, "real_vts_used": False, "live_used": False,
            "real_account_used": False, "real_order_api_called": False,
            "operational_risk_config_changed": False,
            "original_s09_dataset_modified": False,
            "original_dirty_worktree_modified": False,
        },
    }
    raw = json_bytes(report)
    write_or_verify(REPORT_PATH, raw)
    report_hash = digest(raw)
    write_or_verify(REPORT_PATH.with_name(REPORT_PATH.name + ".sha256"),
                    f"{report_hash}  {REPORT_PATH.name}\n".encode("ascii"))
    print(json.dumps({
        "status": report["status"],
        "report_path": REPORT_PATH.relative_to(ROOT).as_posix(),
        "report_sha256": report_hash,
        "scenario_verifications": [item["verification"] for item in results],
        "plumbing_promotion_mapping": report["plumbing_promotion_mapping"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
