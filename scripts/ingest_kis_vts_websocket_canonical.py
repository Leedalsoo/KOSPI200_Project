
from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from environments.virtual.market.historical_market_store import HistoricalMarketStore
from infrastructure.kis.kis_vts_weekday_collector import _kis_option_resolver_for_day
from infrastructure.kis.kis_websocket_market_observation_normalizer import (
    KISWebSocketMarketObservationNormalizer,
    WebSocketUnderlyingContext,
)


ROOT = Path(__file__).resolve().parents[1]


def _latest_underlying_context(
    observations: list,
    *,
    symbol: str,
    received_at: datetime,
) -> WebSocketUnderlyingContext | None:
    candidates = [
        item for item in observations
        if item.contract.symbol == symbol
        and item.underlying_price is not None
        and item.collected_at <= received_at
    ]
    if not candidates:
        return None
    item = max(candidates, key=lambda value: value.collected_at)
    return WebSocketUnderlyingContext(
        price=Decimal(str(item.underlying_price)),
        symbol=item.underlying_symbol,
        observed_hour=item.underlying_observed_hour,
        source=item.underlying_source,
    )


def ingest_day(day: date, *, raw_filename: str = "kis_vts_websocket_raw.jsonl") -> tuple[int, int, int]:
    day_dir = ROOT / "data" / "kis_market_data_restart" / day.isoformat()
    raw_path = day_dir / raw_filename
    canonical_path = day_dir / "historical_market_observations.jsonl"

    if not raw_path.is_file():
        raise FileNotFoundError(raw_path)

    store = HistoricalMarketStore(canonical_path)
    existing = store.load_observations()
    existing_ids = {item.observation_id for item in existing}
    resolver = _kis_option_resolver_for_day(day)
    normalizer = KISWebSocketMarketObservationNormalizer(resolver)

    raw_count = canonical_count = skipped = 0
    for line in raw_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("tr_id") != "H0IOCNT0":
            continue
        raw_count += 1
        received_at = datetime.fromisoformat(record["received_at"])
        underlying = _latest_underlying_context(
            existing,
            symbol=str(record["instrument"]),
            received_at=received_at,
        )
        observations = normalizer.normalize_frame(
            str(record["payload"]),
            received_at=received_at,
            run_id=f"vts-ws-daily-{day.isoformat()}",
            raw_id=f"{day.isoformat()}:{record['sequence']}",
            raw_content_hash=record.get("payload_sha256"),
            underlying=underlying,
        )
        for observation in observations:
            if observation.observation_id in existing_ids:
                skipped += 1
                continue
            store.append_observation(observation)
            existing_ids.add(observation.observation_id)
            existing.append(observation)
            canonical_count += 1

    return raw_count, canonical_count, skipped


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--raw-file", default="kis_vts_websocket_raw.jsonl")
    args = parser.parse_args()
    day = date.fromisoformat(args.date)
    raw_count, canonical_count, skipped = ingest_day(day, raw_filename=args.raw_file)
    print(
        f"WS_CANONICAL_INGEST_OK date={day.isoformat()} "
        f"raw_frames={raw_count} canonical_appended={canonical_count} skipped_existing={skipped}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
