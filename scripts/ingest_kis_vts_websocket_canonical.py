from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from environments.virtual.market.historical_market_store import HistoricalMarketStore
from infrastructure.kis.kis_websocket_market_observation_normalizer import (
    KISWebSocketMarketObservationNormalizer,
    WebSocketUnderlyingContext,
)
from infrastructure.kis.kis_websocket_option_identity_resolver import (
    KISWebSocketOptionIdentityResolver,
)
from infrastructure.kis.websocket_index_price_source import KISWebSocketIndexPriceSource


ROOT = Path(__file__).resolve().parents[1]
RAW_FILENAME = "kis_vts_websocket_raw.jsonl"
SUPPORTED_OPTION_TR_IDS = {"H0IOCNT0", "H0IOASP0"}
UNDERLYING_TR_ID = "H0UPCNT0"


def format_trading_date(day: date) -> str:
    return day.strftime("%Y%m%d")


def parse_trading_date(value: str) -> date:
    raw = str(value).strip()
    if len(raw) == 8 and raw.isdigit():
        return datetime.strptime(raw, "%Y%m%d").date()
    return date.fromisoformat(raw)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"UNSUPPORTED_CANONICAL_VALUE:{type(value).__name__}")


def _load_raw_manifest(raw_path: Path, day: date) -> dict[str, Any]:
    manifest_path = raw_path.with_name(raw_path.name + ".manifest.json")
    if not manifest_path.is_file():
        raise RuntimeError("WS_RAW_MANIFEST_REQUIRED")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "kis-realtime-raw-manifest-v1":
        raise RuntimeError("WS_RAW_MANIFEST_SCHEMA_INVALID")
    if manifest.get("source") != "KIS_VTS_WEBSOCKET_RAW":
        raise RuntimeError("WS_RAW_SOURCE_NOT_AUTHORITATIVE")
    if manifest.get("trading_date") != format_trading_date(day):
        raise RuntimeError("WS_RAW_MANIFEST_DATE_MISMATCH")
    if Path(str(manifest.get("file") or "")).name != raw_path.name:
        raise RuntimeError("WS_RAW_MANIFEST_FILE_MISMATCH")
    digest = _sha256_file(raw_path)
    if digest != manifest.get("file_sha256"):
        raise RuntimeError("WS_RAW_FILE_HASH_MISMATCH")
    line_count = sum(1 for line in raw_path.open("rb") if line.strip())
    if line_count != int(manifest.get("record_count", -1)):
        raise RuntimeError("WS_RAW_RECORD_COUNT_MISMATCH")
    return manifest


def _new_underlying_source(day: date) -> KISWebSocketIndexPriceSource:
    return KISWebSocketIndexPriceSource(session_date=day)


def _scan_source(
    raw_path: Path,
    day: date,
    normalizer: KISWebSocketMarketObservationNormalizer,
    resolver: KISWebSocketOptionIdentityResolver,
    *,
    run_id: str,
) -> tuple[dict[str, int], dict[str, int], set[str]]:
    frame_counts: Counter[str] = Counter()
    quality: Counter[str] = Counter()
    quote_symbols: set[str] = set()
    underlying_source = _new_underlying_source(day)
    latest_underlying: WebSocketUnderlyingContext | None = None
    latest_underlying_received_at: datetime | None = None
    previous_received_at: datetime | None = None

    with raw_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            tr_id = str(record.get("tr_id") or "")
            frame_counts[tr_id] += 1
            received_at = datetime.fromisoformat(str(record["received_at"]))
            if received_at.tzinfo is None:
                raise RuntimeError(f"WS_RAW_RECEIVED_AT_NOT_TIMEZONE_AWARE:{line_number}")
            if previous_received_at is not None and received_at < previous_received_at:
                quality["raw_receive_time_out_of_order"] += 1
            previous_received_at = received_at
            payload = str(record.get("payload") or "")

            if tr_id == UNDERLYING_TR_ID:
                try:
                    underlying_observation = underlying_source.update_frame(
                        payload, received_at=received_at
                    )
                except Exception:
                    quality["underlying_frame_invalid"] += 1
                    latest_underlying = None
                    latest_underlying_received_at = received_at
                    continue
                if (
                    latest_underlying_received_at is None
                    or received_at >= latest_underlying_received_at
                ):
                    latest_underlying = WebSocketUnderlyingContext(
                        price=underlying_observation.price,
                        symbol=underlying_observation.underlying_symbol,
                        observed_hour=underlying_observation.observed_at.strftime("%H%M%S"),
                        source=underlying_observation.source,
                    )
                    latest_underlying_received_at = received_at
                    quality["underlying_frame_valid"] += 1
                continue

            if tr_id not in SUPPORTED_OPTION_TR_IDS:
                quality["unsupported_frame_skipped"] += 1
                continue

            instrument = str(record.get("instrument") or "")
            if tr_id == "H0IOASP0":
                quote_symbols.add(instrument)
                quality["quote_frames_seen"] += 1
            else:
                quality["trade_frames_seen"] += 1

            context = (
                latest_underlying
                if latest_underlying_received_at is not None
                and latest_underlying_received_at <= received_at
                else None
            )
            observations = normalizer.normalize_frame(
                payload,
                received_at=received_at,
                run_id=run_id,
                raw_id=f"{format_trading_date(day)}:{record['sequence']}",
                raw_content_hash=record.get("payload_sha256"),
                underlying=context,
            )
            for observation in observations:
                quality["normalized_option_observations"] += 1
                if observation.underlying_price is not None:
                    quality["option_observations_with_underlying"] += 1
                bids, asks = observation.order_book.bids, observation.order_book.asks
                bid = bids[0].price if bids else None
                ask = asks[0].price if asks else None
                if bid is not None and bid > 0:
                    quality["best_bid_positive"] += 1
                if ask is not None and ask > 0:
                    quality["best_ask_positive"] += 1
                if bid is not None and bid > 0 and ask is not None and ask > 0:
                    quality["two_sided_best_quote"] += 1
                    if bid > ask:
                        quality["crossed_best_quote"] += 1
                    elif bid == ask:
                        quality["locked_best_quote"] += 1
                if any(level.quantity is not None and level.quantity > 0 for level in (*bids, *asks)):
                    quality["any_depth_quantity_positive"] += 1
                if not any(level.price is not None for level in (*bids, *asks)):
                    quality["empty_price_ladder"] += 1
    return dict(frame_counts), dict(quality), quote_symbols


def ingest_day(
    day: date,
    *,
    raw_filename: str = RAW_FILENAME,
    output_base: str | None = None,
) -> dict[str, Any]:
    data_root = ROOT / "data" / "kis_market_data_restart"
    canonical_day_dir = data_root / format_trading_date(day)
    legacy_day_dir = data_root / day.isoformat()
    raw_path = canonical_day_dir / raw_filename
    if not raw_path.is_file():
        legacy_raw_path = legacy_day_dir / raw_filename
        if legacy_raw_path.is_file():
            raw_path = legacy_raw_path
    if not raw_path.is_file():
        raise FileNotFoundError(raw_path)

    raw_manifest = _load_raw_manifest(raw_path, day)
    resolver = KISWebSocketOptionIdentityResolver.for_trading_date(day, project_root=ROOT)
    normalizer = KISWebSocketMarketObservationNormalizer(resolver)
    raw_hash = str(raw_manifest["file_sha256"])
    run_id = f"vts-ws-canonical-{format_trading_date(day)}-{raw_hash[:8]}"

    # Preflight every source frame before creating a canonical output file.
    frame_counts, quality, quote_symbols = _scan_source(
        raw_path, day, normalizer, resolver, run_id=run_id
    )
    if not quote_symbols:
        raise RuntimeError("WS_QUOTE_SYMBOL_COVERAGE_EMPTY")
    identity_summary = resolver.summary(sorted(quote_symbols))
    if identity_summary["resolved_symbols"] != len(quote_symbols):
        raise RuntimeError("WS_EXACT_EXPIRY_IDENTITY_COVERAGE_INCOMPLETE")

    output_dir = canonical_day_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    base_name = output_base or f"kis_vts_websocket_canonical_{format_trading_date(day)}_{raw_hash[:8]}"
    store = HistoricalMarketStore(output_dir / base_name)
    observation_path = store.observation_path
    existing_manifest_matches = list(
        output_dir.glob(f"kis_vts_websocket_canonical_manifest_{format_trading_date(day)}_{raw_hash[:8]}_*.json")
    )
    matching_manifests = []
    for manifest_path in existing_manifest_matches:
        candidate = json.loads(manifest_path.read_text(encoding="utf-8"))
        if candidate.get("canonical_file") == observation_path.name:
            matching_manifests.append(candidate)
    if observation_path.exists():
        if not matching_manifests:
            raise RuntimeError("WS_CANONICAL_OUTPUT_EXISTS_WITHOUT_VERIFIED_MANIFEST")
        current_file_hash = _sha256_file(observation_path)
        if not any(
            candidate.get("canonical_file_sha256") == current_file_hash
            and candidate.get("raw_file_sha256") == raw_hash
            and candidate.get("target_master_sha256") == resolver.target_snapshot.archive_sha256
            for candidate in matching_manifests
        ):
            raise RuntimeError("WS_CANONICAL_EXISTING_OUTPUT_HASH_OR_PROVENANCE_MISMATCH")
    elif matching_manifests:
        raise RuntimeError("WS_CANONICAL_MANIFEST_WITHOUT_OUTPUT_FILE")

    existing = store.load_observations() if observation_path.is_file() else []
    if any(item.source != KISWebSocketMarketObservationNormalizer.SOURCE for item in existing):
        raise RuntimeError("WS_CANONICAL_STORE_SOURCE_MIXED")
    if any(
        dict(item.provenance.metadata).get("master_snapshot_sha256")
        != resolver.target_snapshot.archive_sha256
        for item in existing
    ):
        raise RuntimeError("WS_CANONICAL_MASTER_HASH_MISMATCH")
    existing_ids = {item.observation_id for item in existing}
    canonical_appended = skipped_existing = 0

    underlying_source = _new_underlying_source(day)
    latest_underlying: WebSocketUnderlyingContext | None = None
    latest_underlying_received_at: datetime | None = None
    previous_received_at: datetime | None = None
    observation_path.parent.mkdir(parents=True, exist_ok=True)
    with raw_path.open("r", encoding="utf-8") as raw_handle, observation_path.open(
        "a", encoding="utf-8", newline="\n"
    ) as canonical_handle:
        for line_number, line in enumerate(raw_handle, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            tr_id = str(record.get("tr_id") or "")
            received_at = datetime.fromisoformat(str(record["received_at"]))
            if previous_received_at is not None and received_at < previous_received_at:
                # Preserve raw event order; do not silently reorder timestamps.
                pass
            previous_received_at = received_at
            payload = str(record.get("payload") or "")
            if tr_id == UNDERLYING_TR_ID:
                try:
                    underlying_observation = underlying_source.update_frame(
                        payload, received_at=received_at
                    )
                except Exception:
                    latest_underlying = None
                    latest_underlying_received_at = received_at
                    continue
                if (
                    latest_underlying_received_at is None
                    or received_at >= latest_underlying_received_at
                ):
                    latest_underlying = WebSocketUnderlyingContext(
                        price=underlying_observation.price,
                        symbol=underlying_observation.underlying_symbol,
                        observed_hour=underlying_observation.observed_at.strftime("%H%M%S"),
                        source=underlying_observation.source,
                    )
                    latest_underlying_received_at = received_at
                continue
            if tr_id not in SUPPORTED_OPTION_TR_IDS:
                continue
            context = (
                latest_underlying
                if latest_underlying_received_at is not None
                and latest_underlying_received_at <= received_at
                else None
            )
            observations = normalizer.normalize_frame(
                payload,
                received_at=received_at,
                run_id=run_id,
                raw_id=f"{format_trading_date(day)}:{record['sequence']}",
                raw_content_hash=record.get("payload_sha256"),
                underlying=context,
            )
            for observation in observations:
                if observation.observation_id in existing_ids:
                    skipped_existing += 1
                    continue
                canonical_handle.write(
                    json.dumps(
                        {
                            "schema": "canonical-market-observation-v1",
                            "observation": asdict(observation),
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                        default=_json_default,
                    )
                    + "\n"
                )
                existing_ids.add(observation.observation_id)
                canonical_appended += 1

    canonical_hash = _sha256_file(observation_path)
    canonical_record_count = sum(1 for line in observation_path.open("rb") if line.strip())
    manifest = {
        "schema_version": "kis-vts-websocket-canonical-manifest-v1",
        "source": "KIS_VTS_WEBSOCKET_CANONICAL",
        "trading_date": format_trading_date(day),
        "raw_file": raw_path.name,
        "raw_file_sha256": raw_hash,
        "raw_record_count": int(raw_manifest["record_count"]),
        "raw_tr_ids": raw_manifest.get("tr_ids", []),
        "canonical_file": observation_path.name,
        "canonical_file_sha256": canonical_hash,
        "canonical_record_count": canonical_record_count,
        "canonical_source": KISWebSocketMarketObservationNormalizer.SOURCE,
        "canonical_tr_ids": ["H0IOASP0", "H0IOCNT0"],
        "target_master_sha256": resolver.target_snapshot.archive_sha256,
        "target_master_fetched_at": resolver.target_snapshot.fetched_at.isoformat(),
        "identity_summary": identity_summary,
        "frame_counts": frame_counts,
        "quality": quality,
        "strategy_replay_status": "NOT_RUN",
    }
    manifest_path = output_dir / (
        f"kis_vts_websocket_canonical_manifest_{format_trading_date(day)}_"
        f"{raw_hash[:8]}_{canonical_hash[:12]}.json"
    )
    encoded_manifest = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if manifest_path.exists():
        if manifest_path.read_bytes() != encoded_manifest:
            raise RuntimeError("WS_CANONICAL_MANIFEST_APPEND_ONLY_COLLISION")
    else:
        with manifest_path.open("xb") as handle:
            handle.write(encoded_manifest)

    return {
        "status": "PASS_WITH_LIMITATIONS",
        "scope": "offline raw WebSocket canonicalization; not a strategy replay verdict",
        "trading_date": format_trading_date(day),
        "raw_file_sha256": raw_hash,
        "canonical_file": str(observation_path),
        "canonical_file_sha256": canonical_hash,
        "canonical_record_count": canonical_record_count,
        "canonical_appended": canonical_appended,
        "skipped_existing": skipped_existing,
        "manifest_file": str(manifest_path),
        "frame_counts": frame_counts,
        "quality": quality,
        "identity_summary": identity_summary,
        "limitations": [
            "H0IOASP0 HHMMSS is retained as an unverified candidate source timestamp; collected_at remains the authoritative replay ordering timestamp.",
            "Contract multiplier is not populated from the observed KIS index master.",
            "Strategy replay has not yet been run.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert only verified KIS VTS WebSocket frames to a WebSocket-only canonical store."
    )
    parser.add_argument("--date", required=True)
    parser.add_argument("--raw-file", default=RAW_FILENAME)
    parser.add_argument("--output-base")
    args = parser.parse_args()
    report = ingest_day(
        parse_trading_date(args.date),
        raw_filename=args.raw_file,
        output_base=args.output_base,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
