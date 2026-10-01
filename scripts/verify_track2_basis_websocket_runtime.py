from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from application.composition.virtual_runtime_data_provider import VirtualRuntimeDataProvider
from contracts.kis_index_futures_market_ws_adapter import KISIndexFuturesMarketWebSocketAdapter
from environments.virtual.market.canonical import ReferenceCanonicalMarketTick
from environments.virtual.market.simulator_runtime import VirtualMarketSimulatorRuntime
from infrastructure.kis.basis_source import KISBasisSource
from infrastructure.kis.websocket_index_price_source import KISWebSocketIndexPriceSource

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    day = date.fromisoformat(args.date)
    raw_path = ROOT / "data" / "kis_market_data_restart" / day.isoformat() / "kis_vts_websocket_raw.jsonl"
    if not raw_path.is_file():
        raise FileNotFoundError(raw_path)

    futures_adapter = KISIndexFuturesMarketWebSocketAdapter()
    index_source = KISWebSocketIndexPriceSource(session_date=day)
    futures = []
    index_count = 0
    for line in raw_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        received_at = datetime.fromisoformat(record["received_at"])
        if record.get("tr_id") == "H0IFCNT0" and record.get("instrument") == "A05610":
            observations = futures_adapter.adapt_many(record["payload"])
            for observation in observations:
                observed_at = datetime.combine(day, datetime.strptime(observation.observed_hour, "%H%M%S").time())
                futures.append((observed_at, observation, received_at))
        elif record.get("tr_id") == "H0UPCNT0" and record.get("instrument") == "2001":
            index_source.update_frame(record["payload"], received_at=received_at)
            index_count += 1

    index = index_source.get_latest()
    if index is None or not futures:
        raise RuntimeError("TRACK2_BASIS_WEBSOCKET_EVIDENCE_UNAVAILABLE")
    overlap = [(observed_at, obs, received) for observed_at, obs, received in futures if observed_at == index.observed_at]
    if not overlap:
        raise RuntimeError("TRACK2_BASIS_WEBSOCKET_PAIR_UNAVAILABLE")
    observed_at, future, future_received = overlap[-1]
    basis = KISBasisSource(max_time_delta_seconds=2.0)
    basis.update_futures_observation(future, session_date=day)
    basis.update_index(index)
    value = basis.get_basis("KOSPI200")
    if value is None:
        raise RuntimeError("TRACK2_BASIS_WEBSOCKET_FRESHNESS_FAILED")

    market = VirtualMarketSimulatorRuntime()
    tick = ReferenceCanonicalMarketTick(
        timestamp=observed_at.isoformat(), underlying_price=float(index.price),
        strike_price=float(index.price), option_type="CALL", bid_price=3.0,
        ask_price=3.1, last_price=3.05, volume=100, seq_id=1,
        expiry="202610", symbol="KOSPI200",
    )
    market._recent_ticks.append(tick)
    provider = VirtualRuntimeDataProvider(market, basis_source=basis)
    runtime = provider.snapshot(tick)
    if runtime.basis != value or not runtime.status["basis"].available:
        raise RuntimeError("TRACK2_BASIS_RUNTIME_INPUT_UNAVAILABLE")

    lag_ms = (future_received.astimezone(index.collected_at.tzinfo) - index.collected_at).total_seconds() * 1000
    print(f"TRACK2_BASIS_WEBSOCKET_RUNTIME_PASS date={day.isoformat()}")
    print(f"futures_observed_at={observed_at.isoformat()} futures_received_at={future_received.isoformat()}")
    print(f"index_observed_at={index.observed_at.isoformat()} index_collected_at={index.collected_at.isoformat()}")
    print(f"source_time_delta_seconds={abs((observed_at-index.observed_at).total_seconds()):.3f}")
    print(f"index_frames={index_count} futures_frames={len(futures)}")
    print(f"basis={value} runtime_basis={runtime.basis} status_available={runtime.status['basis'].available}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
