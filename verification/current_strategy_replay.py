from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from application.composition.option_master_factory import create_virtual_option_master
from application.run_hub.contracts import RunContextFactory
from application.run_hub.virtual_session_factory import create_virtual_run_session


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STORE = ROOT / "data" / "kis_market_data_restart" / "2026-10-02" / "historical_market_observations.jsonl.observations.jsonl"
DEFAULT_MASTER = ROOT / "fo_idx_code_mts.mst"


def run_strategy(strategy_id: str, version: str, store_path: Path, ticks: int) -> dict:
    option_master = create_virtual_option_master(historical_source_path=str(DEFAULT_MASTER))
    context = RunContextFactory().create(
        run_id=f"CURRENT-{strategy_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        environment="virtual",
        historical_source="kis_vts_rest",
        historical_store_path=str(store_path),
        strategy_keys=((strategy_id, version),),
        initial_capital=250_000_000.0,
    )
    session = create_virtual_run_session(context, option_master)
    processed = 0
    errors: list[str] = []
    try:
        while processed < ticks:
            try:
                tick = session.bundle.market.replay_next()
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")
                break
            if tick is None:
                break
            processed += 1
        result = session.runtime_hub.last_result
        statuses = {}
        for status in session.runtime_hub.last_strategy_status:
            statuses[status.strategy_id] = {
                "reaction_signals": status.reaction_signals,
                "execution_signals": status.execution_signals,
                "non_execution_signals": status.non_execution_signals,
                "approved": status.approved,
                "decision_rejected": status.decision_rejected,
                "risk_rejected": status.risk_rejected,
                "routed": status.routed,
                "filled_quantity": status.filled_quantity,
                "unavailable": status.unavailable,
                "runtime_failures": status.runtime_failures,
            }
        return {
            "strategy_id": strategy_id,
            "version": version,
            "source": context.historical_source,
            "store_path": str(store_path),
            "requested_ticks": ticks,
            "processed_ticks": processed,
            "last_tick": None if session.bundle.market.last_tick is None else {
                "timestamp": session.bundle.market.last_tick.timestamp,
                "seq_id": session.bundle.market.last_tick.seq_id,
                "symbol": session.bundle.market.last_tick.symbol,
            },
            "result": None if result is None else {
                "signals": result.signals,
                "approved": result.approved,
                "routed": result.routed,
                "filled": result.filled,
                "rejected": result.rejected,
                "execution_ids": list(result.execution_ids),
            },
            "strategy_status": statuses,
            "errors": errors,
            "verdict": "BLOCKED" if errors else "OBSERVED",
        }
    finally:
        session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Current-baseline strategy replay; independent of legacy tests.")
    parser.add_argument("--strategy-id", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    parser.add_argument("--ticks", type=int, default=5000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = run_strategy(args.strategy_id, args.version, args.store, args.ticks)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    print(payload)
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    return 0 if report["verdict"] != "BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
