from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re

from contracts.kis_index_option_market_ws_adapter import KISIndexOptionMarketWebSocketAdapter

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "underlying_reference": "2026-10-21T00:00:30.582860+00:00",
    "underlying_signal": "2026-10-21T00:01:14.429652+00:00",
    "option_orderbook": "2026-10-21T00:01:16.106074+00:00",
}
QUOTE_MANIFEST = ROOT / "config/validation_only/q25_a5_s15b_option_quote_supplement/manifest.json"
QUOTE_PROBE = ROOT / "verification/evidence/kis_s5_option_contract_quote_probe_20261022.json"
DATA_RELATIVE = Path("data/derived_scenario/q25_a5_s15b_observed_s1_call_alignment/events.jsonl")
MANIFEST_RELATIVE = Path("config/validation_only/q25_a5_s15b_observed_s1_call_alignment/manifest.json")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _record_index(record: dict, *, expected_instrument: str) -> tuple[str, str, Decimal]:
    parts = str(record["payload"]).split("|")
    if len(parts) != 4 or parts[1] != "H0UPCNT0" or parts[2] != "001":
        raise ValueError("S15B_OBSERVED_INDEX_FRAME_INVALID")
    fields = parts[3].split("^")
    if len(fields) < 3 or fields[0] != expected_instrument:
        raise ValueError("S15B_OBSERVED_INDEX_IDENTITY_INVALID")
    return fields[0], fields[1], Decimal(fields[2])


def _find_records(source: Path) -> tuple[dict, dict, dict, str]:
    raw = source.read_bytes()
    raw_sha = _sha256(raw)
    found: dict[str, dict] = {}
    expected_by_time = {value: key for key, value in EXPECTED.items()}
    for line in raw.decode("utf-8").splitlines():
        if not line:
            continue
        row = json.loads(line)
        key = expected_by_time.get(row.get("received_at"))
        if key is not None:
            if key in found:
                raise ValueError(f"S15B_OBSERVED_DUPLICATE_SOURCE_RECORD:{key}")
            found[key] = row
    missing = sorted(set(EXPECTED) - set(found))
    if missing:
        raise ValueError(f"S15B_OBSERVED_SOURCE_RECORD_MISSING:{','.join(missing)}")
    for key in ("underlying_reference", "underlying_signal"):
        row = found[key]
        if row.get("tr_id") != "H0UPCNT0" or row.get("instrument") != "2001":
            raise ValueError(f"S15B_OBSERVED_INDEX_SOURCE_MISMATCH:{key}")
        if _sha256(str(row["payload"]).encode("utf-8")) != row.get("payload_sha256"):
            raise ValueError(f"S15B_OBSERVED_INDEX_PAYLOAD_HASH_MISMATCH:{key}")
    book = found["option_orderbook"]
    if book.get("tr_id") != "H0IOASP0" or book.get("instrument") != "B01611887":
        raise ValueError("S15B_OBSERVED_ORDERBOOK_SOURCE_MISMATCH")
    if _sha256(str(book["payload"]).encode("utf-8")) != book.get("payload_sha256"):
        raise ValueError("S15B_OBSERVED_ORDERBOOK_PAYLOAD_HASH_MISMATCH")
    return found["underlying_reference"], found["underlying_signal"], book, raw_sha


def generate(source: Path, *, output_root: Path = ROOT) -> dict:
    source = source.resolve()
    data_path = output_root / DATA_RELATIVE
    manifest_path = output_root / MANIFEST_RELATIVE
    if data_path.exists() or manifest_path.exists():
        raise FileExistsError("S15B_OBSERVED_ALIGNMENT_OUTPUT_EXISTS_NO_OVERWRITE")

    quote_manifest = json.loads(QUOTE_MANIFEST.read_text(encoding="utf-8"))
    probe_bytes = QUOTE_PROBE.read_bytes()
    probe = json.loads(probe_bytes)
    probe_sha = _sha256(probe_bytes)
    if probe_sha != quote_manifest.get("source_probe_sha256"):
        raise ValueError("S15B_OBSERVED_PROBE_HASH_MISMATCH")
    if probe.get("requested_underlying_open") != "878.83":
        raise ValueError("S15B_OBSERVED_REFERENCE_ANCHOR_MISMATCH")
    selection_rule = str(probe.get("selection_rule") or "")
    match = re.search(r"nearest strike ([0-9]+(?:\.[0-9]+)?)", selection_rule)
    if not match or Decimal(match.group(1)) != Decimal("880.0"):
        raise ValueError("S15B_OBSERVED_REFERENCE_SELECTION_RULE_MISSING")
    candidate = probe.get("candidate_master_rows", {}).get("B01611887", {})
    if (candidate.get("option_type") != "CALL" or candidate.get("strike") != "887.50"
            or candidate.get("master_sha256") != probe.get("master_sha256")):
        raise ValueError("S15B_OBSERVED_PROBE_CONTRACT_MISMATCH")

    reference_row, signal_row, book_row, raw_sha = _find_records(source)
    ref_symbol, ref_time, ref_price = _record_index(reference_row, expected_instrument="2001")
    signal_symbol, signal_time, signal_price = _record_index(signal_row, expected_instrument="2001")
    if ref_price != Decimal("878.83") or signal_price != Decimal("876.54"):
        raise ValueError("S15B_OBSERVED_UNDERLYING_PRICE_MISMATCH")

    book_observation = KISIndexOptionMarketWebSocketAdapter().adapt(str(book_row["payload"]))
    book = book_observation.order_book
    if book is None or book.symbol != "B01611887" or not book.is_complete():
        raise ValueError("S15B_OBSERVED_ORDERBOOK_INCOMPLETE")
    asks = [(level.price, level.quantity) for level in book.ask_levels]
    bids = [(level.price, level.quantity) for level in book.bid_levels]
    if (len(asks) != 5 or len(bids) != 5
            or any(price <= 0 or qty <= 0 for price, qty in (*asks, *bids))
            or any(a[0] >= b[0] for a, b in zip(asks, asks[1:]))
            or any(a[0] <= b[0] for a, b in zip(bids, bids[1:]))
            or bids[0][0] >= asks[0][0]):
        raise ValueError("S15B_OBSERVED_ORDERBOOK_STRICT_GATE_FAILED")

    reference_received = datetime.fromisoformat(reference_row["received_at"])
    signal_received = datetime.fromisoformat(signal_row["received_at"])
    book_received = datetime.fromisoformat(book_row["received_at"])
    book_lag_ms = int((book_received - signal_received).total_seconds() * 1000)
    if book_lag_ms < 0 or book_lag_ms > 10_000:
        raise ValueError("S15B_OBSERVED_ORDERBOOK_SIGNAL_TIME_WINDOW_INVALID")

    expected_strike = Decimal("880.0") + Decimal("7.5")
    if expected_strike != Decimal("887.50"):
        raise ValueError("S15B_OBSERVED_SIGNAL_STRIKE_CALCULATION_INVALID")
    mark = (bids[0][0] + asks[0][0]) / Decimal("2")
    master_sha = str(quote_manifest["target_kis_master_sha256"])
    expiry_set_sha = str(quote_manifest["expiry_evidence_set_sha256"])

    source_ref = {
        "raw_file_sha256": raw_sha,
        "payload_sha256": reference_row["payload_sha256"],
        "received_at": reference_row["received_at"],
        "tr_id": reference_row["tr_id"],
        "instrument": reference_row["instrument"],
        "payload": reference_row["payload"],
    }
    source_signal = {
        "raw_file_sha256": raw_sha,
        "payload_sha256": signal_row["payload_sha256"],
        "received_at": signal_row["received_at"],
        "tr_id": signal_row["tr_id"],
        "instrument": signal_row["instrument"],
        "payload": signal_row["payload"],
    }
    source_book = {
        "raw_file_sha256": raw_sha,
        "payload_sha256": book_row["payload_sha256"],
        "received_at": book_row["received_at"],
        "tr_id": book_row["tr_id"],
        "instrument": book_row["instrument"],
        "payload": book_row["payload"],
    }
    events = [
        {
            "schema": "q25-a5-s15b-observed-signal-event-v1",
            "event_id": "UNDERLYING_REFERENCE_ANCHOR",
            "event_type": "UNDERLYING_ANCHOR",
            "provenance": "OBSERVED_KIS_VTS",
            "source": source_ref,
            "value": {"symbol": ref_symbol, "observed_hour": ref_time, "price": str(ref_price)},
            "validation_only": True,
        },
        {
            "schema": "q25-a5-s15b-observed-signal-event-v1",
            "event_id": "TRACK1_UNDERLYING_SIGNAL_EVENT",
            "event_type": "UNDERLYING_MARKET_EVENT",
            "provenance": "OBSERVED_KIS_VTS",
            "source": source_signal,
            "value": {"symbol": signal_symbol, "observed_hour": signal_time, "price": str(signal_price)},
            "validation_only": True,
        },
        {
            "schema": "q25-a5-s15b-observed-signal-event-v1",
            "event_id": "OPTION_ORDERBOOK_B01611887",
            "event_type": "OPTION_ORDERBOOK",
            "provenance": "OBSERVED_KIS_VTS",
            "source": source_book,
            "contract": {
                "scenario_contract_key": "S1_SHORT_CALL_887_5",
                "symbol": "B01611887",
                "option_type": "CALL",
                "strike": "887.50",
                "expiry": "20261112",
                "master_sha256": master_sha,
            },
            "order_book": {
                "source": "KIS:H0IOASP0",
                "observed_hour_candidate": book.observed_hour,
                "ask_levels": [{"price": str(price), "quantity": str(qty)} for price, qty in asks],
                "bid_levels": [{"price": str(price), "quantity": str(qty)} for price, qty in bids],
            },
            "validation_only": True,
        },
        {
            "schema": "q25-a5-s15b-observed-signal-event-v1",
            "event_id": "TRACK1_EXPECTED_NATURAL_SIGNAL",
            "event_type": "STRATEGY_SIGNAL_SCENARIO",
            "provenance": "SYNTHETIC:DERIVED_SCENARIO",
            "scenario_id": "S15B_OBSERVED_S1_CALL_887_5",
            "strategy": {
                "strategy_id": "TRACK1_TAIL_DEFENSE",
                "code_version": "1.2.0",
                "initial_reference_point": "880.0",
                "reference_point_basis": "KIS_PROBE_NEAREST_LISTED_STRIKE_FROM_OBSERVED_OPEN_878.83",
                "short_step_points": "2.5",
                "short_offset_points": "7.5",
                "days_to_expiry_test_value": 21,
                "open_short_quantity_test_value": 0,
                "pending_short_quantity_test_value": 0,
                "runtime_config_verified_test_only": True,
                "risk_limits_available_test_only": True,
                "strike_rounding_changed_value": False,
            },
            "expected_proposal": {
                "asset_type": "OPTION",
                "side": "SELL",
                "option_type": "CALL",
                "strike": "887.50",
                "quantity": 1,
                "tag_id": "S1_SHORT_ACCUMULATION_CALL_000001",
            },
            "validation_only": True,
            "runtime_eligible": False,
            "production_runtime_eligible": False,
            "execution_enabled": False,
        },
        {
            "schema": "q25-a5-s15b-observed-signal-event-v1",
            "event_id": "SYNTHETIC_MARK_FROM_OBSERVED_BOOK",
            "event_type": "SYNTHETIC_MARK_PRICE",
            "provenance": "SYNTHETIC:DERIVED_SCENARIO",
            "scenario_id": "S15B_OBSERVED_S1_CALL_887_5",
            "symbol": "B01611887",
            "mark_price": str(mark),
            "derivation": "midpoint_of_observed_best_bid_and_best_ask",
            "source_orderbook_payload_sha256": book_row["payload_sha256"],
            "actual_trade_price": None,
            "validation_only": True,
            "runtime_eligible": False,
            "production_runtime_eligible": False,
            "execution_enabled": False,
        },
    ]
    dataset_bytes = b"".join(
        (json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        for row in events
    )
    manifest = {
        "schema": "q25-a5-s15b-observed-s1-call-alignment-manifest-v1",
        "dataset_id": "Q25_A5_S15B_OBSERVED_S1_CALL_ALIGNMENT_20261109",
        "dataset_path": DATA_RELATIVE.as_posix(),
        "dataset_sha256": _sha256(dataset_bytes),
        "event_count": len(events),
        "provenance": "DERIVED_SCENARIO",
        "synthetic": True,
        "validation_only": True,
        "signal_generation_only": False,
        "runtime_eligible": False,
        "production_runtime_eligible": False,
        "execution_enabled": False,
        "orders_allowed": False,
        "allow_kis_api": False,
        "allow_live_orders": False,
        "allow_real_account": False,
        "original_source_mutated": False,
        "s15a_mutated": False,
        "target_kis_master_sha256": master_sha,
        "expiry_evidence_set_sha256": expiry_set_sha,
        "source_probe_path": "verification/evidence/kis_s5_option_contract_quote_probe_20261022.json",
        "source_probe_sha256": probe_sha,
        "source_raw_file_date": "20261021",
        "source_raw_file_sha256": raw_sha,
        "source_record_payload_sha256s": {
            "underlying_reference": reference_row["payload_sha256"],
            "underlying_signal": signal_row["payload_sha256"],
            "option_orderbook": book_row["payload_sha256"],
        },
        "source_tr_ids": ["H0UPCNT0", "H0IOASP0"],
        "scenario_ids": ["S15B_OBSERVED_S1_CALL_887_5"],
        "scenario_contract_mapping": {
            "S1_SHORT_CALL_887_5": {
                "symbol": "B01611887",
                "option_type": "CALL",
                "strike": "887.50",
                "expiry": "20261112",
                "product_series": "MONTHLY",
                "product_class": "STANDARD",
                "master_sha256": master_sha,
            }
        },
        "underlying_reference": {
            "symbol": "2001",
            "name": "KOSPI200",
            "observed_open": str(ref_price),
            "observed_open_received_at": reference_row["received_at"],
            "initial_reference_point": "880.0",
            "reference_point_basis": "KIS_PROBE_NEAREST_LISTED_STRIKE_FROM_OBSERVED_OPEN_878.83",
            "source_probe_selection_rule": selection_rule,
        },
        "signal_observation": {
            "underlying_price": str(signal_price),
            "received_at": signal_row["received_at"],
            "signal_to_orderbook_received_lag_ms": book_lag_ms,
            "expected_signal": "SELL CALL 887.50 x 1",
            "strategy_code_version": "1.2.0",
            "strategy_parameters_status": "VALIDATION_ONLY_TEST_INPUT; NOT_PRODUCTION_APPROVAL",
        },
        "freshness_policy": {
            "version": "S15B_OBSERVED_COLLECTOR_RECEIVE_TIME_VALIDATION_ONLY",
            "max_age_seconds": 600,
            "timestamp_basis": "COLLECTOR_RECEIVED_AT_ONLY",
            "kis_h0ioasp0_observed_hour_semantics_verified": False,
            "production_freshness_eligible": False,
        },
        "synthetic_mark_profile": {
            "value": str(mark),
            "basis": "midpoint_of_observed_best_bid_and_best_ask",
            "actual_trade_price_available": False,
        },
        "multiplier_profile": {
            "value": "250000",
            "unit": "KRW_PER_OPTION_POINT",
            "product_class": "STANDARD",
            "source": "KRX_KOSPI200_STANDARD_OPTION_PRODUCT_SPECIFICATION",
            "source_url": "https://open.krx.co.kr/contents/OPN/01/01040202/OPN01040202.jsp",
            "validation_only_non_authoritative_runtime_profile": True,
            "production_runtime_eligible": False,
        },
        "limitations": [
            "The underlying reference point 880.0 is derived from the observed 878.83 open using the KIS probe's nearest-listed-strike selection rule.",
            "The 876.54 index event and 887.5 CALL order book are preserved KIS VTS observations from 2026-10-21; this is historical offline replay only.",
            "H0IOASP0 observed_hour is retained as an unverified candidate; validation freshness uses collector received_at only.",
            "No option trade price was present in the H0IOASP0 record; the mark price is a synthetic midpoint, not an observed trade or fill.",
            "Only the S1 short CALL 887.5 proposal is covered. Base strangle legs and other contracts remain outside this scenario.",
            "S1 2.5-point step and 7.5-point offset are exercised as validation inputs; this does not approve production strategy policy.",
        ],
    }

    data_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_bytes(dataset_bytes)
    manifest_path.write_bytes(json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8") + bytes([10]))
    return {
        "dataset_path": DATA_RELATIVE.as_posix(),
        "dataset_sha256": manifest["dataset_sha256"],
        "manifest_path": MANIFEST_RELATIVE.as_posix(),
        "manifest_sha256": _sha256(manifest_path.read_bytes()),
        "source_raw_file_sha256": raw_sha,
        "signal_to_orderbook_received_lag_ms": book_lag_ms,
        "observed_book": {
            "asks": [{"price": str(p), "quantity": str(q)} for p, q in asks],
            "bids": [{"price": str(p), "quantity": str(q)} for p, q in bids],
        },
        "synthetic_mark_price": str(mark),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a new S15b observed-signal alignment dataset without modifying source data.")
    parser.add_argument("--source-raw", required=True, type=Path, help="Read-only archived KIS VTS WebSocket JSONL source")
    args = parser.parse_args()
    print(json.dumps(generate(args.source_raw), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
