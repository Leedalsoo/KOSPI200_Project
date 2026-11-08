from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUOTE_MANIFEST = ROOT / "config/validation_only/q25_a5_s15b_option_quote_supplement/manifest.json"
QUOTE_DATA = ROOT / "data/derived_scenario/q25_a5_s15b_option_quote_supplement/events.jsonl"
MANIFEST_PATH = ROOT / "config/validation_only/q25_a5_s15b_option_orderbook_supplement/manifest.json"
DATA_PATH = ROOT / "data/derived_scenario/q25_a5_s15b_option_orderbook_supplement/events.jsonl"
REPORT_PATH = ROOT / "reports/synth/Q25_A5_S15B_ORDERBOOK_SYNTHETIC_SUPPLEMENT_20261109.json"
SEED = 20261109
PRICE_STEP = Decimal("0.01")  # test-only ladder spacing; not an exchange tick-size claim
QUANTITIES = (3, 5, 2, 4, 1)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def levels(best: Decimal, side: str, count: int = 5) -> list[dict[str, str]]:
    result = []
    for i in range(count):
        price = best + PRICE_STEP * i if side == "ask" else best - PRICE_STEP * i
        result.append({"price": format(price, "f"), "quantity": str(QUANTITIES[i])})
    return result


def main() -> None:
    quote_manifest = json.loads(QUOTE_MANIFEST.read_text(encoding="utf-8"))
    quote_bytes = QUOTE_DATA.read_bytes()
    quote_hash = sha256(quote_bytes)
    if quote_hash != quote_manifest["dataset_sha256"]:
        raise SystemExit("QUOTE_SUPPLEMENT_HASH_MISMATCH")
    rows = load_rows(QUOTE_DATA)
    generated: list[dict] = []

    for symbol in ("B01611885", "B01611887"):
        observed = next(r for r in rows if r.get("symbol") == symbol and r.get("record_type") == "PRESERVED_SOURCE_ANCHOR")
        fresh = next(r for r in rows if r.get("symbol") == symbol and r.get("scenario_id") == "fresh_two_sided")
        stale = next(r for r in rows if r.get("symbol") == symbol and r.get("scenario_id") == "stale_two_sided")
        if observed.get("provenance") != "OBSERVED_KIS_VTS" or Decimal(observed["quote"]["last"]) <= 0:
            raise SystemExit(f"INVALID_OBSERVED_ANCHOR:{symbol}")
        if fresh.get("provenance") != "SYNTHETIC:DERIVED_SCENARIO" or stale.get("provenance") != "SYNTHETIC:DERIVED_SCENARIO":
            raise SystemExit(f"INVALID_QUOTE_SCENARIO:{symbol}")

        bid = Decimal(fresh["quote"]["bid"])
        ask = Decimal(fresh["quote"]["ask"])
        stale_bid = Decimal(stale["quote"]["bid"])
        stale_ask = Decimal(stale["quote"]["ask"])
        source_time = fresh["source_timestamp"]
        received_at = fresh["received_at"]
        stale_source_time = stale["source_timestamp"]
        stale_received_at = stale["received_at"]

        scenarios = [
            ("fresh_two_sided", levels(ask, "ask"), levels(bid, "bid"), source_time, received_at),
            ("stale_two_sided", levels(stale_ask, "ask"), levels(stale_bid, "bid"), stale_source_time, stale_received_at),
            ("one_sided_book", [], levels(bid, "bid"), source_time, received_at),
            ("zero_quantity", [dict(x) for x in levels(ask, "ask")], levels(bid, "bid"), source_time, received_at),
            ("crossed_book", levels(ask, "ask"), levels(ask + PRICE_STEP, "bid"), source_time, received_at),
            ("insufficient_depth", levels(ask, "ask", 4), levels(bid, "bid", 4), source_time, received_at),
            ("nonfinite_price", levels(ask, "ask"), levels(bid, "bid"), source_time, received_at),
        ]
        for scenario_id, asks, bids, src_time, recv_time in scenarios:
            asks = [dict(x) for x in asks]
            bids = [dict(x) for x in bids]
            if scenario_id == "zero_quantity":
                asks[0]["quantity"] = "0"
            if scenario_id == "nonfinite_price":
                asks[0]["price"] = "NaN"
            generated.append({
                "schema": "q25-a5-s15b-orderbook-event-v1",
                "record_id": f"SYNTHETIC:{symbol}:{scenario_id}",
                "record_type": "VALIDATION_SCENARIO",
                "symbol": symbol,
                "instrument_id": symbol,
                "scenario_id": scenario_id,
                "option_type": observed["option_type"],
                "strike": observed["strike"],
                "expiry": observed["expiry"],
                "master_sha256": quote_manifest["target_kis_master_sha256"],
                "quote_dataset_sha256": quote_hash,
                "source_anchor_record_id": observed["record_id"],
                "source_anchor_last": observed["quote"]["last"],
                "source_anchor_sha256": quote_manifest["source_probe_sha256"],
                "quote_scenario_id": "stale_two_sided" if scenario_id == "stale_two_sided" else "fresh_two_sided",
                "ask_levels": asks,
                "bid_levels": bids,
                "source_timestamp": src_time,
                "received_at": recv_time,
                "observed_hour": "10:00:00",
                "provenance": "SYNTHETIC:DERIVED_SCENARIO",
                "synthetic": True,
                "validation_only": True,
                "production_runtime_eligible": False,
                "orders_allowed": False,
                "generator_version": "q25-a5-s15b-option-orderbook-supplement-v1",
                "seed": SEED,
                "scenario_config": {
                    "depth": 5,
                    "price_basis": "EXISTING_SYNTHETIC_QUOTE_BID_ASK",
                    "price_step": str(PRICE_STEP),
                    "price_step_semantics": "TEST_ONLY_LADDER_SPACING_NOT_EXCHANGE_TICK",
                    "quantity_profile": list(QUANTITIES),
                    "quantities_synthetic": True,
                    "timestamps_inherited_from_quote_scenario": True,
                },
            })

    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    data_bytes = ("\n".join(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in generated) + "\n").encode("utf-8")
    DATA_PATH.write_bytes(data_bytes)
    manifest = {
        "schema": "q25-a5-s15b-option-orderbook-supplement-manifest-v1",
        "dataset_id": "Q25_A5_S15B_OPTION_ORDERBOOK_SYNTHETIC_SUPPLEMENT_20261109",
        "dataset_path": str(DATA_PATH.relative_to(ROOT)).replace("\\", "/"),
        "dataset_sha256": sha256(data_bytes),
        "event_count": len(generated),
        "contract_count": 2,
        "scenario_count_per_contract": 7,
        "scenario_ids": ["fresh_two_sided", "stale_two_sided", "one_sided_book", "zero_quantity", "crossed_book", "insufficient_depth", "nonfinite_price"],
        "seed": SEED,
        "generator_version": "q25-a5-s15b-option-orderbook-supplement-v1",
        "provenance": "DERIVED_SCENARIO",
        "synthetic": True,
        "validation_only": True,
        "runtime_eligible": False,
        "production_runtime_eligible": False,
        "execution_enabled": False,
        "orders_allowed": False,
        "allow_kis_api": False,
        "allow_live_orders": False,
        "allow_real_account": False,
        "original_source_mutated": False,
        "s15a_mutated": False,
        "source_quote_manifest_path": str(QUOTE_MANIFEST.relative_to(ROOT)).replace("\\", "/"),
        "source_quote_manifest_sha256": sha256(QUOTE_MANIFEST.read_bytes()),
        "source_quote_dataset_path": str(QUOTE_DATA.relative_to(ROOT)).replace("\\", "/"),
        "source_quote_dataset_sha256": quote_hash,
        "target_kis_master_sha256": quote_manifest["target_kis_master_sha256"],
        "source_probe_sha256": quote_manifest["source_probe_sha256"],
        "anchor_time": quote_manifest["anchor_time"],
        "depth": 5,
        "test_only_price_step": str(PRICE_STEP),
        "test_only_price_step_semantics": "NOT_AN_EXCHANGE_TICK_SIZE",
        "quantity_profile": list(QUANTITIES),
        "limitations": [
            "Every order-book level and quantity is synthetic validation input, not observed market depth.",
            "Prices are derived from the existing synthetic quote scenarios, themselves anchored only to preserved historical last prices.",
            "The 0.01 ladder spacing is a test-only structural assumption and is not an authoritative exchange tick-size claim.",
            "Only B01611885 and B01611887 have preserved last-price anchors; the three no-anchor contracts remain UNAVAILABLE.",
            "No claim is made about real liquidity, queue position, executable depth, fill probability, or profitability."
        ],
    }
    manifest_bytes = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_bytes(manifest_bytes)
    report = {
        "report_id": "Q25_A5_S15B_ORDERBOOK_SYNTHETIC_SUPPLEMENT_20261109",
        "date": "2026-11-09",
        "stage": "S15B_VALIDATION_ONLY_SYNTHETIC_ORDERBOOK_DATASET",
        "verdict": "PSB_UNVERIFIED_DATASET_GENERATED",
        "dataset": {
            "path": str(DATA_PATH.relative_to(ROOT)).replace("\\", "/"),
            "sha256": sha256(data_bytes),
            "event_count": len(generated),
            "manifest_path": str(MANIFEST_PATH.relative_to(ROOT)).replace("\\", "/"),
            "manifest_sha256": sha256(manifest_bytes),
        },
        "coverage": {
            "contracts": ["B01611885", "B01611887"],
            "scenarios_per_contract": 7,
            "valid_full_depth_cases": 2,
            "negative_cases": 5,
            "no_anchor_contracts_left_unavailable": ["C01611880", "C01611882", "B01611880"],
        },
        "limitations": manifest["limitations"],
        "safety": {
            "validation_only": True,
            "production_runtime_eligible": False,
            "orders_allowed": False,
            "kis_api_called": False,
            "real_vts_live_account_order_api_called": False,
            "original_source_mutated": False,
            "s15a_mutated": False,
        },
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (REPORT_PATH.with_suffix(REPORT_PATH.suffix + ".sha256")).write_text(sha256(REPORT_PATH.read_bytes()) + "\n", encoding="ascii")
    print(json.dumps({
        "event_count": len(generated),
        "dataset_sha256": manifest["dataset_sha256"],
        "manifest_sha256": sha256(manifest_bytes),
        "report_path": str(REPORT_PATH.relative_to(ROOT)),
        "report_sha256": sha256(REPORT_PATH.read_bytes()),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
