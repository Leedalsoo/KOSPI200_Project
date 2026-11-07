from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "data" / "kis_market_data_restart" / "20261020" / "kis_vts_websocket_canonical_20261020_9d63ef65.observations.jsonl"
DEFAULT_OUT = ROOT / "data" / "synthetic_market_data" / "20261020" / "synthetic_quote_repairs_20261020.jsonl"
EXPECTED_SOURCE_SHA256 = "8bd9f30857364f760045336e4d64769122764e2481f33259ce6c38e2a6806010"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def valid_price(value: Any) -> bool:
    try:
        return value is not None and float(value) > 0
    except (TypeError, ValueError):
        return False


def valid_top_book(obs: dict[str, Any]) -> bool:
    book = obs.get("order_book") or {}
    bids, asks = book.get("bids") or [], book.get("asks") or []
    bid1 = next((level for level in bids if level.get("level") == 1), {})
    ask1 = next((level for level in asks if level.get("level") == 1), {})
    return valid_price(bid1.get("price")) and valid_price(ask1.get("price"))


def timestamp(obs: dict[str, Any]) -> datetime:
    value = obs.get("collected_at") or obs.get("observed_at")
    if not value:
        raise ValueError("OBSERVATION_TIMESTAMP_MISSING")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def invalid_quote(obs: dict[str, Any]) -> bool:
    book = obs.get("order_book") or {}
    asks = book.get("asks") or []
    no_valid_ask = not any(valid_price(level.get("price")) for level in asks)
    return no_valid_ask and not valid_top_book(obs)


def read_rows(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if line.strip():
                yield line_number, json.loads(line)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create explicitly synthetic, offline-only quote-repair scenarios from KIS VTS canonical observations.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--allow-source-hash-change", action="store_true")
    args = parser.parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"CANONICAL_SOURCE_MISSING:{source}")
    source_hash = sha256(source)
    if source_hash != EXPECTED_SOURCE_SHA256 and not args.allow_source_hash_change:
        raise RuntimeError(f"CANONICAL_SOURCE_HASH_MISMATCH:expected={EXPECTED_SOURCE_SHA256}:actual={source_hash}")
    if output.exists():
        raise FileExistsError(f"REFUSE_OVERWRITE_SYNTHETIC_OUTPUT:{output}")
    manifest_path = output.with_suffix(".manifest.json")
    if manifest_path.exists():
        raise FileExistsError(f"REFUSE_OVERWRITE_SYNTHETIC_MANIFEST:{manifest_path}")

    invalid: list[tuple[int, dict[str, Any]]] = []
    valid_by_symbol: dict[str, list[tuple[datetime, dict[str, Any]]]] = defaultdict(list)
    input_count = 0
    for line_number, row in read_rows(source):
        input_count += 1
        obs = row.get("observation") or {}
        symbol = (obs.get("contract") or {}).get("symbol") or (obs.get("contract") or {}).get("instrument_id")
        if not symbol:
            continue
        if invalid_quote(obs):
            invalid.append((line_number, row))
        elif valid_top_book(obs):
            valid_by_symbol[str(symbol)].append((timestamp(obs), row))

    if input_count != 180958:
        raise RuntimeError(f"UNEXPECTED_CANONICAL_ROW_COUNT:{input_count}")
    if len(invalid) != 155:
        raise RuntimeError(f"UNEXPECTED_INVALID_QUOTE_COUNT:{len(invalid)}")
    for values in valid_by_symbol.values():
        values.sort(key=lambda item: item[0])

    output.parent.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for sequence, (line_number, target_row) in enumerate(invalid, 1):
        target = target_row["observation"]
        contract = target.get("contract") or {}
        symbol = str(contract.get("symbol") or contract.get("instrument_id") or "")
        candidates = valid_by_symbol.get(symbol, [])
        if not candidates:
            unresolved.append(str(target.get("observation_id", f"line-{line_number}")))
            continue
        target_time = timestamp(target)
        donor_time, donor_row = min(candidates, key=lambda item: abs((item[0] - target_time).total_seconds()))
        donor = donor_row["observation"]
        donor_book = donor.get("order_book") or {}
        donor_bid = next((x for x in donor_book.get("bids", []) if x.get("level") == 1), {})
        donor_ask = next((x for x in donor_book.get("asks", []) if x.get("level") == 1), {})
        if not (valid_price(donor_bid.get("price")) and valid_price(donor_ask.get("price"))):
            unresolved.append(str(target.get("observation_id", f"line-{line_number}")))
            continue
        synthetic = json.loads(json.dumps(target_row))
        obs = synthetic["observation"]
        obs["observation_id"] = f"SYNTHETIC-QUOTE-REPAIR-{sequence:03d}-{target.get('observation_id', 'unknown')}"
        obs["run_id"] = "SYNTHETIC-QUOTE-REPAIR-20261020"
        obs["source"] = "SYNTHETIC"
        obs["provider"] = "SyntheticQuoteRepairGenerator"
        obs["quote"] = {
            "last": None,
            "bid": donor.get("quote", {}).get("bid") if valid_price(donor.get("quote", {}).get("bid")) else donor_bid.get("price"),
            "ask": donor.get("quote", {}).get("ask") if valid_price(donor.get("quote", {}).get("ask")) else donor_ask.get("price"),
            "volume": None,
        }
        obs["order_book"] = json.loads(json.dumps(donor_book))
        obs["provenance"] = {
            "source_type": "SYNTHETIC",
            "synthetic": True,
            "runtime_eligible": False,
            "validation_only": True,
            "method": "nearest_same_symbol_valid_two_sided_kis_vts_canonical_order_book",
            "target_observation_id": target.get("observation_id"),
            "target_source": target.get("source"),
            "target_raw_reference": target.get("raw_reference"),
            "donor_observation_id": donor.get("observation_id"),
            "donor_collected_at": donor.get("collected_at"),
            "donor_time_distance_seconds": abs((donor_time - target_time).total_seconds()),
            "source_canonical_sha256": source_hash,
            "source_line_number": line_number,
            "donor_source": donor.get("source"),
            "donor_tr_ids": (donor.get("provenance") or {}).get("tr_ids", []),
            "limitations": [
                "Synthetic quote ladder copied from a valid observation for the same KIS symbol.",
                "This is not a recovered historical quote and must not be used as REAL_VTS, production runtime input, or evidence of executable prices.",
                "Trade last price and volume remain null; no trade fields are inferred."
            ],
        }
        records.append(synthetic)

    if unresolved:
        raise RuntimeError(f"UNRESOLVED_TARGETS_WITHOUT_SAME_SYMBOL_DONOR:{len(unresolved)}:{','.join(unresolved[:5])}")
    if len(records) != 155:
        raise RuntimeError(f"SYNTHETIC_OUTPUT_COUNT_MISMATCH:{len(records)}")

    with output.open("x", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    output_hash = sha256(output)
    manifest = {
        "schema_version": "synthetic-quote-repair-manifest-v1",
        "source_type": "SYNTHETIC",
        "runtime_eligible": False,
        "validation_only": True,
        "trading_date": "20261020",
        "purpose": "offline strategy/replay input-boundary and resilience validation only",
        "source_canonical_path": str(source.relative_to(ROOT)),
        "source_canonical_sha256": source_hash,
        "source_canonical_rows": input_count,
        "invalid_quote_targets": len(invalid),
        "synthetic_rows_written": len(records),
        "unresolved_targets": 0,
        "output_path": str(output.relative_to(ROOT)),
        "output_sha256": output_hash,
        "generator": str(Path(__file__).resolve().relative_to(ROOT)),
        "method": "For each invalid quote, copy the nearest valid two-sided top-of-book ladder from another canonical observation of the exact same KIS symbol. Preserve target identity/timestamps and record donor ID and time distance.",
        "guardrails": [
            "Original canonical/raw files are read-only and unmodified.",
            "Synthetic rows are stored under data/synthetic_market_data/ and marked source_type=SYNTHETIC.",
            "Never merge synthetic rows into REAL_VTS canonical data or production runtime input.",
            "last price and volume remain null; neither is derived from bid/ask or order-book quantities.",
            "Synthetic values are not historical truth and are not executable quote evidence."
        ],
        "max_donor_time_distance_seconds": max(float(r["observation"]["provenance"]["donor_time_distance_seconds"]) for r in records),
        "mean_donor_time_distance_seconds": sum(float(r["observation"]["provenance"]["donor_time_distance_seconds"]) for r in records) / len(records),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS_SYNTHETIC_GENERATION",
        "source_rows": input_count,
        "invalid_targets": len(invalid),
        "synthetic_rows": len(records),
        "unresolved": 0,
        "source_sha256": source_hash,
        "output_sha256": output_hash,
        "manifest": str(manifest_path),
        "max_donor_time_distance_seconds": manifest["max_donor_time_distance_seconds"],
        "mean_donor_time_distance_seconds": manifest["mean_donor_time_distance_seconds"],
        "runtime_eligible": False,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())