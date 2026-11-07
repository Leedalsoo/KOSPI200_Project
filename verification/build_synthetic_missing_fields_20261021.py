from __future__ import annotations
import hashlib, json, math
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATE = "20261021"
DATA = ROOT / "data" / "kis_market_data_restart" / DATE
SOURCE = DATA / "kis_vts_websocket_canonical_20261021_54cf62fa.observations.jsonl"
RAW = DATA / "kis_vts_websocket_raw.jsonl"
RAW_MANIFEST = DATA / "kis_vts_websocket_raw.jsonl.manifest.json"
CANONICAL_MANIFEST = next(DATA.glob("kis_vts_websocket_canonical_manifest_*.json"))
OUTDIR = ROOT / "data" / "synthetic_market_data" / "20261022_ws_missing_fields_from_20261021"
OUT = OUTDIR / f"{DATE}.jsonl"
MANIFEST = OUTDIR / "manifest.json"
SYNTHETIC_FIELDS = ["repaired_bid_ask_ladder", "underlying_price", "underlying_symbol", "last_price", "volume", "contract_multiplier", "implied_volatility", "delta", "gamma", "theta", "vega"]

def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def positive(v):
    try:
        return v is not None and float(v) > 0
    except (TypeError, ValueError):
        return False

def stamp(obs):
    raw = obs.get("observed_at") or obs.get("collected_at")
    if not raw:
        raise ValueError("SOURCE_TIMESTAMP_MISSING")
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))

def top(obs):
    book = obs.get("order_book") or {}
    bids = book.get("bids") or []
    asks = book.get("asks") or []
    bid = next((x for x in bids if x.get("level") == 1), {})
    ask = next((x for x in asks if x.get("level") == 1), {})
    return bid, ask

def main():
    if not SOURCE.is_file() or not RAW.is_file() or not RAW_MANIFEST.is_file() or not CANONICAL_MANIFEST.is_file():
        raise SystemExit("SOURCE_OR_MANIFEST_MISSING")
    for p in (OUTDIR, OUT, MANIFEST):
        if p.exists():
            raise SystemExit(f"REFUSE_OVERWRITE_EXISTING_PATH:{p}")
    rm = json.loads(RAW_MANIFEST.read_text(encoding="utf-8"))
    cm = json.loads(CANONICAL_MANIFEST.read_text(encoding="utf-8"))
    raw_hash, source_hash = sha(RAW), sha(SOURCE)
    if rm.get("trading_date") != DATE or rm.get("source") != "KIS_VTS_WEBSOCKET_RAW" or rm.get("file_sha256") != raw_hash:
        raise SystemExit("RAW_PROVENANCE_OR_HASH_CHECK_FAILED")
    if cm.get("trading_date") != DATE or cm.get("canonical_file_sha256") != source_hash or cm.get("canonical_source") != "kis_vts_websocket":
        raise SystemExit("CANONICAL_PROVENANCE_OR_HASH_CHECK_FAILED")
    rows = []
    donors = {}
    invalid = []
    with SOURCE.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            obs = row.get("observation") or {}
            contract = obs.get("contract") or {}
            symbol = str(contract.get("symbol") or contract.get("instrument_id") or "")
            if not symbol:
                raise SystemExit(f"CONTRACT_SYMBOL_MISSING_AT_LINE:{line_no}")
            bid, ask = top(obs)
            bid_price, ask_price = bid.get("price"), ask.get("price")
            valid = positive(bid_price) and positive(ask_price) and float(ask_price) >= float(bid_price)
            item = (line_no, row, stamp(obs), symbol)
            rows.append(item)
            if valid:
                donors.setdefault(symbol, []).append(item)
            else:
                invalid.append(item)
    if not invalid:
        raise SystemExit("NO_INVALID_QUOTES_TO_SCENARIO_TEST")
    out_rows = []
    unresolved = []
    max_distance = 0.0
    for seq, (line_no, target_row, target_time, symbol) in enumerate(invalid, 1):
        candidates = donors.get(symbol, [])
        if not candidates:
            unresolved.append(f"{line_no}:{symbol}")
            continue
        donor_line, donor_row, donor_time, _ = min(candidates, key=lambda x: abs((x[2] - target_time).total_seconds()))
        target = target_row["observation"]
        donor = donor_row["observation"]
        bid, ask = top(donor)
        if not (positive(bid.get("price")) and positive(ask.get("price")) and float(ask["price"]) >= float(bid["price"])):
            unresolved.append(f"DONOR_INVALID:{donor_line}:{symbol}")
            continue
        contract = target.get("contract") or {}
        try:
            strike = float(contract["strike"])
            opt = str(contract["option_type"]).upper()
            if opt not in ("CALL", "PUT"):
                raise ValueError
        except Exception:
            unresolved.append(f"CONTRACT_FIELDS_INVALID:{line_no}:{symbol}")
            continue
        spot = 900.0 + 1.75 * math.sin(seq / 7.0) + 0.025 * seq
        intrinsic = max(0.0, spot - strike) if opt == "CALL" else max(0.0, strike - spot)
        time_value = 2.0 + (seq % 13) * 0.17 + abs(math.sin(seq / 5.0)) * 0.8
        last = round(max(0.05, intrinsic * 0.12 + time_value), 2)
        ts = target.get("observed_at") or target.get("collected_at")
        tick = {
            "timestamp": ts,
            "partition_date": DATE,
            "underlying_price": round(spot, 4),
            "underlying_symbol": "SYNTHETIC-KOSPI200",
            "underlying_observed_hour": datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%Y%m%d%H"),
            "underlying_source": "SYNTHETIC:scenario-underlying-v1",
            "strike_price": strike,
            "option_type": opt,
            "contract_multiplier": 250000.0,
            "bid_price": float(bid["price"]),
            "ask_price": float(ask["price"]),
            "last_price": last,
            "volume": 100 + (seq * 37) % 1900,
            "seq_id": seq,
            "expiry": str(contract.get("expiry") or ""),
            "symbol": symbol,
            "instrument_id": str(contract.get("instrument_id") or symbol),
            "option_source": "SYNTHETIC",
            "implied_volatility": round(0.18 + abs(strike - spot) / max(spot, 1.0) * 0.015, 6),
            "delta": round((0.5 if opt == "CALL" else -0.5) + max(-0.4, min(0.4, (spot - strike) / max(spot, 1.0))), 6),
            "gamma": 0.01,
            "theta": -0.01,
            "vega": 0.2,
        }
        distance = abs((donor_time - target_time).total_seconds())
        max_distance = max(max_distance, distance)
        out_rows.append({
            "schema": "reference-canonical-market-tick-v1",
            "provenance": "SYNTHETIC",
            "tick": tick,
            "scenario_metadata": {
                "scenario_id": "WS_20261021_MISSING_FIELDS_BOUNDARY",
                "source_type": "SYNTHETIC",
                "runtime_eligible": False,
                "validation_only": True,
                "source_partition_date": DATE,
                "source_canonical_sha256": source_hash,
                "source_raw_sha256": raw_hash,
                "source_observation_id": target.get("observation_id"),
                "source_line_number": line_no,
                "donor_observation_id": donor.get("observation_id"),
                "donor_line_number": donor_line,
                "donor_time_distance_seconds": distance,
                "synthetic_fields": SYNTHETIC_FIELDS,
                "assumptions": {"underlying": "bounded deterministic scenario, not historical truth", "last_price": "scenario premium, not a recovered trade", "volume": "scenario-only integer", "contract_multiplier": "test assumption, not authoritative KIS multiplier", "analytics": "scenario-only values"},
                "guardrails": ["Never merge with REAL_VTS data", "Never use as production/runtime market data", "No KIS API or order/account call", "Source timestamps and identity provenance are preserved separately from synthetic fields"],
            },
        })
    if unresolved:
        raise SystemExit("UNRESOLVED_SYNTHETIC_TARGETS:" + ";".join(unresolved[:10]))
    if len(out_rows) != len(invalid):
        raise SystemExit(f"OUTPUT_COUNT_MISMATCH:{len(out_rows)}:{len(invalid)}")
    OUTDIR.mkdir(parents=True, exist_ok=False)
    with OUT.open("x", encoding="utf-8", newline="\n") as f:
        for row in out_rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    manifest = {
        "schema_version": "synthetic-missing-fields-manifest-v1",
        "source_type": "SYNTHETIC",
        "runtime_eligible": False,
        "validation_only": True,
        "trading_date": DATE,
        "source_canonical_path": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "source_canonical_sha256": source_hash,
        "source_canonical_rows": len(rows),
        "source_raw_path": str(RAW.relative_to(ROOT)).replace("\\", "/"),
        "source_raw_sha256": raw_hash,
        "source_raw_rows": int(rm["record_count"]),
        "invalid_quote_targets": len(invalid),
        "synthetic_rows": len(out_rows),
        "unresolved_targets": 0,
        "synthetic_fields": SYNTHETIC_FIELDS,
        "dataset_path": str(OUT.relative_to(ROOT)).replace("\\", "/"),
        "dataset_sha256": sha(OUT),
        "max_donor_time_distance_seconds": max_distance,
        "master_snapshot_sha256": cm.get("target_master_sha256"),
        "master_snapshot_fetched_at": cm.get("target_master_fetched_at"),
        "limitations": ["This fixture repairs invalid quote targets using a same-symbol donor and creates scenario-only trade/underlying/risk fields.", "It validates input assembly and fail-closed boundaries only; it is not a historical reconstruction or strategy-performance evidence.", "The full original REAL_VTS partition remains unchanged and separate."],
    }
    with MANIFEST.open("x", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps({"status": "PASS_SYNTHETIC_FIXTURE_CREATED", "date": DATE, "source_rows": len(rows), "invalid_quote_targets": len(invalid), "synthetic_rows": len(out_rows), "unresolved": 0, "runtime_eligible": False, "validation_only": True, "dataset": str(OUT.relative_to(ROOT)), "dataset_sha256": sha(OUT), "manifest": str(MANIFEST.relative_to(ROOT)), "manifest_sha256": sha(MANIFEST), "max_donor_time_distance_seconds": max_distance}, ensure_ascii=False))

if __name__ == "__main__":
    main()