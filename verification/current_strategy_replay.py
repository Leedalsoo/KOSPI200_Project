from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any
import sys


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from application.composition.option_master_factory import (
    create_production_trading_calendar,
    create_virtual_option_master,
)
from application.run_hub.contracts import RunContextFactory
from application.run_hub.virtual_session_factory import create_virtual_run_session
from core.option.option_master import create_default_option_master
from infrastructure.kis.auth import KISAuthManager
from infrastructure.kis.kis_websocket_option_identity_resolver import (
    KISWebSocketOptionIdentityResolver,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STORE = ROOT / "data" / "kis_market_data_restart" / "2026-10-02" / "historical_market_observations.jsonl.observations.jsonl"
DEFAULT_MASTER = ROOT / "fo_idx_code_mts.mst"
WEBSOCKET_SOURCE = "kis_vts_websocket"


def _parse_date(value: str | date | None, store_path: Path) -> date:
    if isinstance(value, date):
        return value
    if value:
        raw = str(value).strip()
        if re.fullmatch(r"\d{8}", raw):
            return datetime.strptime(raw, "%Y%m%d").date()
        return date.fromisoformat(raw)
    for candidate in (store_path.parent.name, store_path.stem):
        if re.fullmatch(r"\d{8}", candidate):
            return datetime.strptime(candidate, "%Y%m%d").date()
    raise ValueError("WS_REPLAY_TRADING_DATE_REQUIRED")


def build_websocket_option_master(trading_date: date):
    resolver = KISWebSocketOptionIdentityResolver.for_trading_date(
        trading_date, project_root=ROOT
    )
    auth = KISAuthManager(is_vts=True)
    calendar = create_production_trading_calendar(
        auth_manager=auth,
        auto_load_kis=False,
        strict_mode=False,
        target_year=trading_date.year,
    )

    def resolve_expiry(symbol: str, master_sha256: str):
        if master_sha256 != resolver.target_snapshot.archive_sha256:
            return None
        return resolver.get_expiry_record(symbol)

    master = create_default_option_master(
        calendar=calendar,
        auto_load_kis=True,
        master_source_loader=lambda: resolver.target_snapshot,
        expiry_resolver=resolve_expiry,
    )
    return master, resolver


def run_strategy(
    strategy_id: str,
    version: str,
    store_path: Path,
    ticks: int,
    *,
    historical_source: str = "kis_vts_rest",
    trading_date: date | str | None = None,
    option_master: Any | None = None,
    identity_summary: dict[str, Any] | None = None,
) -> dict:
    resolved_date: date | None = None
    if historical_source == WEBSOCKET_SOURCE:
        if not store_path.is_file() or not store_path.name.endswith(".observations.jsonl"):
            raise FileNotFoundError(f"WS_CANONICAL_OBSERVATION_STORE_REQUIRED:{store_path}")
        resolved_date = _parse_date(trading_date, store_path)
        if option_master is None:
            option_master, resolver = build_websocket_option_master(resolved_date)
            identity_summary = resolver.summary()
        with store_path.open("r", encoding="utf-8") as handle:
            first_line = next((line for line in handle if line.strip()), "")
        if not first_line:
            raise RuntimeError("WS_CANONICAL_OBSERVATION_STORE_EMPTY")
        first_record = json.loads(first_line)
        first_observation = first_record.get("observation", {})
        if first_record.get("schema") != "canonical-market-observation-v1":
            raise RuntimeError("WS_CANONICAL_OBSERVATION_SCHEMA_INVALID")
        if first_observation.get("source") != WEBSOCKET_SOURCE:
            raise RuntimeError("WS_REPLAY_SOURCE_NOT_WEBSOCKET")
    elif historical_source == "kis_vts_rest":
        option_master = option_master or create_virtual_option_master(
            historical_source_path=str(DEFAULT_MASTER)
        )
    else:
        raise ValueError(f"REPLAY_HISTORICAL_SOURCE_UNSUPPORTED:{historical_source}")

    context = RunContextFactory().create(
        run_id=f"CURRENT-{strategy_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        environment="virtual",
        historical_source=historical_source,
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
        quote_only_events = list(getattr(session.runtime_hub.loop, "quote_only_events", ()))
        projection_errors = list(getattr(session.bundle.market.replay, "projection_errors", ()))
        if (quote_only_events or projection_errors) and not statuses:
            statuses[strategy_id] = {
                "status": "BLOCKED",
                "reason": "LEGACY_STRATEGY_CONTEXT_REQUIRES_TRADE_TICK",
                "quote_only_events": len(quote_only_events),
                "invalid_observations_skipped": len(projection_errors),
            }
        return {
            "strategy_id": strategy_id,
            "version": version,
            "source": context.historical_source,
            "store_path": str(store_path),
            "trading_date": resolved_date.strftime("%Y%m%d") if resolved_date else None,
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
            "quote_only_event_count": len(quote_only_events),
            "quote_only_event_sample": quote_only_events[:3],
            "invalid_observation_count": len(projection_errors),
            "invalid_observation_sample": projection_errors[:3],
            "errors": errors,
            "identity_resolution": identity_summary,
            "verdict": "BLOCKED" if errors or processed == 0 or quote_only_events or projection_errors else "OBSERVED",
        }
    finally:
        session.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replay one strategy against a pinned historical store."
    )
    parser.add_argument("--strategy-id", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    parser.add_argument("--source", choices=("kis_vts_rest", WEBSOCKET_SOURCE), default="kis_vts_rest")
    parser.add_argument("--date", help="Trading date YYYYMMDD; required for a nonstandard store path.")
    parser.add_argument("--ticks", type=int, default=5000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = run_strategy(
        args.strategy_id,
        args.version,
        args.store,
        args.ticks,
        historical_source=args.source,
        trading_date=args.date,
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    print(payload)
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    return 0 if report["verdict"] != "BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
