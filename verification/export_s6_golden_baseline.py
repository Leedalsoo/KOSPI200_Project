from __future__ import annotations

import argparse
import dataclasses
from collections.abc import Mapping
import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT) )
DEFAULT_STORE = ROOT / "data" / "kis_market_data_restart" / "2026-10-02" / "historical_market_observations.jsonl.observations.jsonl"
DEFAULT_MASTER = ROOT / "fo_idx_code_mts.mst"
DEFAULT_MANIFEST = ROOT / "config" / "strategies" / "strategy-manifest.v1.json"
DEFAULT_OUTPUT = ROOT / "verification" / "baseline" / "pre_unification_20261010"
STRATEGY_ID = "track6_daily_tail_insurance"
STRATEGY_VERSION = "1.0"
INITIAL_CAPITAL = 250_000_000.0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_value(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def jsonable(value: Any, *, depth: int = 0) -> Any:
    if depth > 20:
        return {"_serialization": "MAX_DEPTH"}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: jsonable(getattr(value, field.name), depth=depth + 1)
            for field in dataclasses.fields(value)
        }
    if isinstance(value, Mapping):
        return {
            str(key): jsonable(item, depth=depth + 1)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list, set, frozenset)):
        values = [jsonable(item, depth=depth + 1) for item in value]
        return sorted(values, key=lambda item: canonical_json(item)) if isinstance(value, (set, frozenset)) else values
    if hasattr(value, "value") and isinstance(getattr(value, "value"), (str, int, float, bool)):
        return jsonable(value.value, depth=depth + 1)
    if hasattr(value, "__dict__") and value.__class__.__module__.startswith(
        ("contracts.", "core.", "application.", "environments.")
    ):
        return {
            key: jsonable(item, depth=depth + 1)
            for key, item in sorted(vars(value).items())
            if not key.startswith("_") and not callable(item)
        }
    return {"_type": f"{value.__class__.__module__}.{value.__class__.__qualname__}"}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class EventCollector:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.current_tick: dict[str, Any] | None = None
        self._event_sequence = 0

    def tick_ref(self, market: Any | None = None) -> dict[str, Any] | None:
        tick = None
        if market is not None:
            tick = getattr(market, "last_tick", None)
        if tick is None:
            tick = self.current_tick
        if tick is None:
            return None
        return {
            "seq_id": getattr(tick, "seq_id", None),
            "timestamp": getattr(tick, "timestamp", None),
        }

    def add(self, event_type: str, payload: dict[str, Any], *, market: Any | None = None) -> None:
        self._event_sequence += 1
        self.events.append({
            "event_sequence": self._event_sequence,
            "tick": self.tick_ref(market),
            "event_type": event_type,
            "payload": jsonable(payload),
        })


def make_session(store_path: Path, master_path: Path, run_id: str):
    from application.composition.option_master_factory import create_virtual_option_master
    from application.run_hub.contracts import RunContextFactory
    from application.run_hub.virtual_session_factory import create_virtual_run_session

    option_master = create_virtual_option_master(historical_source_path=str(master_path))
    context = RunContextFactory().create(
        run_id=run_id,
        environment="virtual",
        historical_source="kis_vts_rest",
        historical_store_path=str(store_path),
        strategy_keys=((STRATEGY_ID, STRATEGY_VERSION),),
        initial_capital=INITIAL_CAPITAL,
    )
    return create_virtual_run_session(context, option_master)


def install_observers(session: Any, collector: EventCollector) -> None:
    loop = session.runtime_hub.loop
    market = session.bundle.market

    original_strategy_run = loop.strategy_hub.run

    def observed_strategy_run(contexts, selected=None):
        result = original_strategy_run(contexts, selected=selected)
        s6_context = contexts.get(STRATEGY_ID) if isinstance(contexts, dict) else None
        collector.add(
            "strategy_evaluation",
            {
                "strategy_id": STRATEGY_ID,
                "context": {
                    "strategy_id": getattr(s6_context, "strategy_id", None),
                    "input": getattr(s6_context, "input", None),
                    "analytics": getattr(s6_context, "analytics", None),
                    "market_state": getattr(s6_context, "market_state", None),
                } if s6_context is not None else None,
                "signals": [
                    signal for signal in result.signals
                    if str(getattr(signal, "strategy_id", "")) == STRATEGY_ID
                ],
                "failures": [
                    failure for failure in result.failures
                    if str(getattr(failure, "strategy_id", "")) == STRATEGY_ID
                ],
                "config_provenance": [
                    row for row in result.config_provenance
                    if row and str(row[0]) == STRATEGY_ID
                ],
            },
            market=market,
        )
        return result

    loop.strategy_hub.run = observed_strategy_run

    original_arbitrate = loop.strategy_to_decision.arbitrate

    def observed_arbitrate(*args, **kwargs):
        result = original_arbitrate(*args, **kwargs)
        canonical = list(getattr(result, "canonical_signals", ()))
        approved_ids = {
            str(getattr(item, "signal_id", "")) for item in
            getattr(getattr(result, "arbitration", None), "approved_signals", ())
        }
        rejected = [
            {"signal": item, "reason": reason}
            for item, reason in getattr(getattr(result, "arbitration", None), "rejected_signals", ())
        ]
        plans = [
            plan for plan in getattr(result, "execution_plans", ())
            if str(getattr(plan, "strategy_id", "")) == STRATEGY_ID
        ]
        s6_canonical = [
            item for item in canonical
            if str(getattr(item, "track_id", "")) == STRATEGY_ID
        ]
        s6_rejected = [
            item for item in rejected
            if str(getattr(item["signal"], "track_id", "")) == STRATEGY_ID
        ]
        s6_approved = [
            item for item in s6_canonical
            if str(getattr(item, "signal_id", "")) in approved_ids
        ]
        if s6_canonical or s6_rejected or plans:
            collector.add(
                "decision",
                {
                    "canonical_signals": s6_canonical,
                    "approved_signals": s6_approved,
                    "rejected_signals": s6_rejected,
                    "execution_plans": plans,
                    "cancel_requests": [
                        request for request in getattr(result, "cancel_requests", ())
                        if str(getattr(request, "strategy_id", "")) == STRATEGY_ID
                    ],
                },
                market=market,
            )
        return result

    loop.strategy_to_decision.arbitrate = observed_arbitrate

    # Capture order intents and the authoritative Virtual execution report at the broker boundary.
    broker = session.bundle.broker
    original_submit = broker.submit

    def observed_submit(command, *args, **kwargs):
        report = original_submit(command, *args, **kwargs)
        if str(getattr(command, "strategy_id", "") or getattr(command, "track_id", "")) == STRATEGY_ID:
            collector.add("order_and_execution_report", {"command": command, "report": report}, market=market)
        return report

    broker.submit = observed_submit

    original_cancel = broker.cancel

    def observed_cancel(order_id, *args, **kwargs):
        report = original_cancel(order_id, *args, **kwargs)
        collector.add("cancel_report", {"order_id": order_id, "report": report}, market=market)
        return report

    broker.cancel = observed_cancel

    # Capture risk/router outcomes that do not necessarily reach the broker.
    import application.composition.automated_virtual_trading_loop as loop_module
    original_route = loop_module.route_from_runtime_authoritative_sources

    def observed_route(command, *args, **kwargs):
        result = original_route(command, *args, **kwargs)
        if str(getattr(command, "track_id", "")) == STRATEGY_ID:
            collector.add(
                "single_order_risk_route",
                {
                    "command": command,
                    "routed": getattr(result, "routed", None),
                    "decision": getattr(result, "decision", None),
                    "approved": getattr(result, "approved", None),
                    "rejection_reason": getattr(result, "rejection_reason", None),
                    "result": result,
                },
                market=market,
            )
        return result

    loop_module.route_from_runtime_authoritative_sources = observed_route

    original_multi_execute = loop.multi_leg_executor

    def observed_multi_execute(plan, *args, **kwargs):
        result = original_multi_execute(plan, *args, **kwargs)
        if str(getattr(plan, "strategy_id", "")) == STRATEGY_ID:
            collector.add("multi_leg_execution", {"plan": plan, "result": result}, market=market)
        return result

    loop.multi_leg_executor = observed_multi_execute

    original_pending = loop.pending_multi_leg_processor

    if callable(original_pending):
        def observed_pending(*args, **kwargs):
            result = original_pending(*args, **kwargs)
            for item in result if isinstance(result, (tuple, list)) else ():
                if str(getattr(item, "strategy_id", "")) == STRATEGY_ID:
                    collector.add("pending_multi_leg_execution", {"result": item}, market=market)
            return result
        loop.pending_multi_leg_processor = observed_pending

    # Expose the original functions for restoration before session shutdown.
    collector._restore = [
        (loop.strategy_hub, "run", original_strategy_run),
        (loop.strategy_to_decision, "arbitrate", original_arbitrate),
        (broker, "submit", original_submit),
        (broker, "cancel", original_cancel),
        (loop_module, "route_from_runtime_authoritative_sources", original_route),
        (loop, "multi_leg_executor", original_multi_execute),
    ]
    if callable(original_pending):
        collector._restore.append((loop, "pending_multi_leg_processor", original_pending))


def snapshot_after_tick(session: Any, collector: EventCollector, processed: int) -> dict[str, Any]:
    market = session.bundle.market
    tick = getattr(market, "last_tick", None)
    loop = session.runtime_hub.loop
    bridge = getattr(loop, "multi_leg_bridge", None)
    account_snapshot = session.bundle.account.snapshot()
    lots = tuple(bridge.position_lot_store.open_lots()) if bridge is not None else ()
    s6_lots = [lot for lot in lots if str(getattr(lot, "strategy_id", "")) == STRATEGY_ID]
    group_snapshots: list[Any] = []
    strategy_group_ids: list[str] = []
    if bridge is not None:
        for group_id, group in sorted(bridge.position_groups.all().items()):
            if str(getattr(group, "strategy_id", "")) != STRATEGY_ID:
                continue
            strategy_group_ids.append(str(group_id))
            snap = bridge.position_groups.snapshot(group_id)
            if snap is not None:
                group_snapshots.append(snap)
    pnl = {
        "attribution_source": "VirtualMultiLegExecutionBridge.position_groups.snapshot",
        "status": "AVAILABLE" if group_snapshots else "UNAVAILABLE_NO_S6_GROUP_SNAPSHOT",
        "group_snapshots": group_snapshots,
        "group_snapshot_aggregate": {
            "realized_pnl": str(sum((Decimal(str(getattr(item, "realized_pnl", 0))) for item in group_snapshots), Decimal("0"))),
            "unrealized_pnl": str(sum((Decimal(str(getattr(item, "unrealized_pnl", 0))) for item in group_snapshots), Decimal("0"))),
            "total_pnl": str(sum((Decimal(str(getattr(item, "total_pnl", 0))) for item in group_snapshots), Decimal("0"))),
        } if group_snapshots else None,
        "note": "Aggregated only from available S6 position-group snapshots; not inferred from the global account P&L.",
    }
    snapshot = {
        "processed_tick_index": processed,
        "tick": {
            "seq_id": getattr(tick, "seq_id", None),
            "timestamp": getattr(tick, "timestamp", None),
            "symbol": getattr(tick, "symbol", None),
            "underlying_price": getattr(tick, "underlying_price", None),
            "bid_price": getattr(tick, "bid_price", None),
            "ask_price": getattr(tick, "ask_price", None),
            "volume": getattr(tick, "volume", None),
        } if tick is not None else None,
        "last_result": session.runtime_hub.last_result,
        "strategy_status": [
            status for status in session.runtime_hub.last_strategy_status
            if str(getattr(status, "strategy_id", "")) == STRATEGY_ID
        ],
        "open_lots": s6_lots,
        "position_lot_history": [lot for lot in bridge.position_lot_store.history() if str(getattr(lot, "strategy_id", "")) == STRATEGY_ID] if bridge is not None else [],
        "position_lot_close_events": [event for event in bridge.position_lot_store.close_events()] if bridge is not None else [],
        "strategy_pnl": pnl,
        "account_pnl_global_not_strategy_attributed": {
            key: value for key, value in getattr(account_snapshot, "balances", {}).items()
            if key in {"realized_pnl", "unrealized_pnl", "cash", "available_cash", "margin_used"}
        },
        "strategy_group_ids": strategy_group_ids,
    }
    collector.add("tick_state_snapshot", snapshot, market=market)
    return jsonable(snapshot)


def run_once(*, store_path: Path, master_path: Path, ticks: int, run_id: str) -> dict[str, Any]:
    collector = EventCollector()
    session = make_session(store_path, master_path, run_id)
    try:
        install_observers(session, collector)
        processed = 0
        replay_errors: list[str] = []
        while processed < ticks:
            try:
                tick = session.bundle.market.replay_next()
            except Exception as exc:
                replay_errors.append(f"{type(exc).__name__}: {exc}")
                collector.add("replay_error", {"error_type": type(exc).__name__, "message": str(exc)}, market=session.bundle.market)
                break
            if tick is None:
                break
            processed += 1
            collector.current_tick = tick
            snapshot_after_tick(session, collector, processed)

        if processed == 0:
            replay_errors.append("NO_TICKS_PROCESSED")
        if processed < ticks and not replay_errors:
            replay_errors.append(f"INPUT_EXHAUSTED_BEFORE_REQUESTED_TICKS:{processed}/{ticks}")

        semantic = {
            "requested_ticks": ticks,
            "processed_ticks": processed,
            "events": collector.events,
            "replay_errors": replay_errors,
        }
        semantic_hash = hashlib.sha256(canonical_json(semantic).encode("utf-8")).hexdigest()
        event_types: dict[str, int] = {}
        for event in collector.events:
            event_types[event["event_type"]] = event_types.get(event["event_type"], 0) + 1
        result = {
            "run_id": run_id,
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "strategy": {"strategy_id": STRATEGY_ID, "version": STRATEGY_VERSION},
            "requested_ticks": ticks,
            "processed_ticks": processed,
            "event_count": len(collector.events),
            "event_counts_by_type": dict(sorted(event_types.items())),
            "replay_errors": replay_errors,
            "semantic_sha256": semantic_hash,
            "semantic_events": collector.events,
        }
        return result
    finally:
        for obj, name, original in reversed(getattr(collector, "_restore", [])):
            setattr(obj, name, original)
        session.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bounded S6 Golden baseline exporter with semantic event and determinism evidence."
    )
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    parser.add_argument("--master", type=Path, default=DEFAULT_MASTER)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--ticks", type=int, default=5000)
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    if args.ticks <= 0 or args.ticks > 5000:
        parser.error("--ticks must be in the bounded range 1..5000")
    if args.runs != 2:
        parser.error("--runs must be 2 for the required deterministic comparison")
    for path in (args.store, args.master, args.manifest):
        if not path.is_file():
            parser.error(f"required input file not found: {path}")
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        parser.error(f"refusing to overwrite non-empty output directory: {args.output_dir}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    run_id = "S6-GOLDEN-20261011"
    metadata = {
        "schema_version": "s6-golden-baseline-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "strategy": {"strategy_id": STRATEGY_ID, "version": STRATEGY_VERSION},
        "source_revision": git_value("rev-parse", "HEAD"),
        "source_worktree_status": git_value("status", "--short", "--branch"),
        "baseline_tag": "baseline-current-implementation-20261011",
        "baseline_tag_revision": git_value("rev-parse", "baseline-current-implementation-20261011^{commit}"),
        "inputs": {
            "historical_store": {"path": str(args.store.resolve()), "size_bytes": args.store.stat().st_size, "sha256": sha256_file(args.store)},
            "option_master": {"path": str(args.master.resolve()), "size_bytes": args.master.stat().st_size, "sha256": sha256_file(args.master)},
            "strategy_manifest": {"path": str(args.manifest.resolve()), "size_bytes": args.manifest.stat().st_size, "sha256": sha256_file(args.manifest)},
            "exporter": {"path": str(Path(__file__).resolve()), "sha256": sha256_file(Path(__file__).resolve())},
        },
        "runtime": {
            "python_version": sys.version,
            "platform": platform.platform(),
            "ticks": args.ticks,
            "runs": args.runs,
            "initial_capital": INITIAL_CAPITAL,
            "environment": "virtual",
            "historical_source": "kis_vts_rest",
        },
    }
    (args.output_dir / "MANIFEST.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    reports = []
    for index in range(1, args.runs + 1):
        report = run_once(store_path=args.store, master_path=args.master, ticks=args.ticks, run_id=run_id)
        reports.append(report)
        (args.output_dir / f"run_{index}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if report["replay_errors"]:
            metadata["status"] = "BLOCKED"
            metadata["blocker"] = report["replay_errors"]
            (args.output_dir / "MANIFEST.json").write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            blocked = {
                "status": "BLOCKED",
                "reason": report["replay_errors"],
                "run_report": f"run_{index}.json",
                "processed_ticks": report["processed_ticks"],
                "requested_ticks": args.ticks,
                "event_counts": report["event_counts_by_type"],
                "semantic_sha256": report["semantic_sha256"],
                "note": "Partial diagnostic evidence only; this is not a Golden baseline and must not be used for equivalence claims.",
            }
            (args.output_dir / "BLOCKED_REPORT.json").write_text(
                json.dumps(blocked, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(json.dumps(blocked, ensure_ascii=False, indent=2))
            return 2

    comparison = {
        "schema_version": "s6-golden-determinism-v1",
        "run_1_semantic_sha256": reports[0]["semantic_sha256"],
        "run_2_semantic_sha256": reports[1]["semantic_sha256"],
        "same_semantic_hash": reports[0]["semantic_sha256"] == reports[1]["semantic_sha256"],
        "same_processed_ticks": reports[0]["processed_ticks"] == reports[1]["processed_ticks"],
        "same_event_counts": reports[0]["event_counts_by_type"] == reports[1]["event_counts_by_type"],
        "run_1_processed_ticks": reports[0]["processed_ticks"],
        "run_2_processed_ticks": reports[1]["processed_ticks"],
        "run_1_event_counts": reports[0]["event_counts_by_type"],
        "run_2_event_counts": reports[1]["event_counts_by_type"],
    }
    comparison["determinism_verdict"] = (
        "PASS" if comparison["same_semantic_hash"] and comparison["same_processed_ticks"] and comparison["same_event_counts"]
        else "FAIL"
    )
    (args.output_dir / "DETERMINISM.json").write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "output_dir": str(args.output_dir.resolve()),
        "source_revision": metadata["source_revision"],
        "input_sha256": metadata["inputs"]["historical_store"]["sha256"],
        "run_1_sha256": reports[0]["semantic_sha256"],
        "run_2_sha256": reports[1]["semantic_sha256"],
        "determinism_verdict": comparison["determinism_verdict"],
        "event_counts": reports[0]["event_counts_by_type"],
        "processed_ticks": reports[0]["processed_ticks"],
    }, ensure_ascii=False, indent=2))
    return 0 if comparison["determinism_verdict"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
