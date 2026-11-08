"""Build a manifest-bound S15b option quote supplement from preserved KIS evidence.

Synthetic records are validation-only scenarios anchored to observed KIS last prices.
They are never market observations and never establish production freshness.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "verification/evidence/kis_s5_option_contract_quote_probe_20261022.json"
OUT = ROOT / "data/derived_scenario/q25_a5_s15b_option_quote_supplement"
DATASET = OUT / "events.jsonl"
MANIFEST = ROOT / "config/validation_only/q25_a5_s15b_option_quote_supplement/manifest.json"
REPORT = ROOT / "reports/synth/Q25_A5_S15B_OPTION_QUOTE_SUPPLEMENT_20261109.json"
ANCHOR = datetime(2026, 11, 6, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))
MASTER_SHA256 = "96912b73fcf0fa549cb67cd03299b13afcbaaf229d5c03fdafefa1b5646aaf9e"
EXPIRY_EVIDENCE_SHA256 = "ea61ae622cca57ad80ea068fc65d227b4ba0be46c0fe2c60703f5d945fb8dcad"
GENERATOR_VERSION = "q25-a5-s15b-option-quote-supplement-v1"
SEED = 20261109
HALF_SPREAD_BPS = Decimal("50")
MAX_AGE_SECONDS = 600

CONTRACTS = (
    {"symbol": "B01611885", "option_type": "CALL", "strike": "885.00", "expiry": "20261112"},
    {"symbol": "B01611887", "option_type": "CALL", "strike": "887.50", "expiry": "20261112"},
    {"symbol": "C01611880", "option_type": "PUT", "strike": "880.00", "expiry": "20261112"},
    {"symbol": "C01611882", "option_type": "PUT", "strike": "882.50", "expiry": "20261112"},
    {"symbol": "B01611880", "option_type": "CALL", "strike": "880.00", "expiry": "20261112"},
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def build() -> dict[str, object]:
    source_bytes = SOURCE.read_bytes()
    source_hash = sha256_bytes(source_bytes)
    probe = json.loads(source_bytes)
    observed_by_symbol = {row["symbol"]: row for row in probe["quotes"]}
    records: list[dict[str, object]] = []

    for contract in CONTRACTS:
        observed = observed_by_symbol.get(contract["symbol"])
        if observed is None:
            records.append({
                "record_id": f"OBSERVED_MISSING:{contract['symbol']}",
                "record_type": "OBSERVATION_GAP",
                "provenance": "MISSING",
                "synthetic": False,
                "validation_only": True,
                "symbol": contract["symbol"],
                "instrument_id": contract["symbol"],
                "option_type": contract["option_type"],
                "strike": contract["strike"],
                "expiry": contract["expiry"],
                "master_sha256": MASTER_SHA256,
                "expiry_evidence_set_sha256": EXPIRY_EVIDENCE_SHA256,
                "quote": {"bid": None, "ask": None, "last": None},
                "source_timestamp": None,
                "received_at": None,
                "freshness_expected": "UNAVAILABLE",
                "gap_reason": "NO_PRESERVED_QUOTE_OBSERVATION_FOR_EXACT_CONTRACT",
            })
            continue

        price = Decimal(str(observed["price_observation"]["last_price"]))
        price_obs = observed["price_observation"]
        book = observed["order_book_observation"]
        records.append({
            "record_id": f"OBSERVED:{contract['symbol']}:20261021",
            "record_type": "PRESERVED_SOURCE_ANCHOR",
            "provenance": "OBSERVED_KIS_VTS",
            "synthetic": False,
            "validation_only": True,
            "symbol": contract["symbol"],
            "instrument_id": contract["symbol"],
            "option_type": contract["option_type"],
            "strike": contract["strike"],
            "expiry": contract["expiry"],
            "master_sha256": MASTER_SHA256,
            "expiry_evidence_set_sha256": EXPIRY_EVIDENCE_SHA256,
            "quote": {
                "bid": book["top5_bids"][0]["price"],
                "ask": book["top5_asks"][0]["price"],
                "last": str(price),
                "accumulated_volume": price_obs.get("accumulated_volume"),
            },
            "source_timestamp": price_obs.get("source_timestamp_raw"),
            "received_at": price_obs["received_at_utc"],
            "source_environment": probe["environment"],
            "source_endpoint": "/uapi/domestic-futureoption/v1/quotations/inquire-price",
            "price_response_sha256": price_obs["raw_response_sha256"],
            "order_book_response_sha256": book["raw_response_sha256"],
            "freshness_expected": "UNKNOWN",
            "quality_notes": [
                "Original KIS response preserved without modification.",
                "Source timestamp is absent on price observation.",
                "Top ask is zero; this is not a valid two-sided quote.",
                "Historical observation is not fresh for the 2026-11-06 scenario anchor.",
            ],
        })

        bid = price * (Decimal("1") - HALF_SPREAD_BPS / Decimal("10000"))
        ask = price * (Decimal("1") + HALF_SPREAD_BPS / Decimal("10000"))
        synthetic_book = {"bid": money(bid), "ask": money(ask), "last": str(price)}
        source_time = ANCHOR
        synthetic_definitions = (
            ("fresh_two_sided", source_time, source_time + timedelta(milliseconds=100), contract["symbol"], synthetic_book, "FRESH"),
            ("stale_two_sided", source_time - timedelta(seconds=MAX_AGE_SECONDS + 60), source_time, contract["symbol"], synthetic_book, "STALE"),
            ("missing_source_time", None, source_time, contract["symbol"], synthetic_book, "UNKNOWN"),
            ("future_source_time", source_time + timedelta(seconds=5), source_time, contract["symbol"], synthetic_book, "UNKNOWN"),
            ("identity_conflict", source_time, source_time, "SYNTHETIC:WRONG-CONTRACT", synthetic_book, "IDENTITY_CONFLICT"),
            ("one_sided_book", source_time, source_time, contract["symbol"], {"bid": money(bid), "ask": "0.00", "last": str(price)}, "UNAVAILABLE"),
        )
        for scenario_id, src_time, received_at, instrument_id, quote, expected in synthetic_definitions:
            body = {
                "scenario_id": scenario_id,
                "symbol": contract["symbol"],
                "instrument_id": instrument_id,
                "quote": quote,
                "source_timestamp": src_time.isoformat() if src_time else None,
                "received_at": received_at.isoformat(),
                "source_anchor_sha256": source_hash,
                "seed": SEED,
                "generator_version": GENERATOR_VERSION,
            }
            records.append({
                "record_id": f"SYNTHETIC:{contract['symbol']}:{scenario_id}",
                "record_type": "VALIDATION_SCENARIO",
                "provenance": "SYNTHETIC:DERIVED_SCENARIO",
                "synthetic": True,
                "validation_only": True,
                "production_runtime_eligible": False,
                "orders_allowed": False,
                "symbol": contract["symbol"],
                "instrument_id": instrument_id,
                "option_type": contract["option_type"],
                "strike": contract["strike"],
                "expiry": contract["expiry"],
                "master_sha256": MASTER_SHA256,
                "expiry_evidence_set_sha256": EXPIRY_EVIDENCE_SHA256,
                "quote": quote,
                "source_timestamp": body["source_timestamp"],
                "received_at": body["received_at"],
                "source_anchor_sha256": source_hash,
                "seed": SEED,
                "generator_version": GENERATOR_VERSION,
                "scenario_id": scenario_id,
                "freshness_expected": expected,
                "scenario_config": {
                    "half_spread_bps": str(HALF_SPREAD_BPS),
                    "max_age_seconds": MAX_AGE_SECONDS,
                    "price_basis": "PRESERVED_OBSERVED_LAST_PRICE_ONLY",
                    "synthetic_bid_ask": True,
                },
                "payload_sha256": sha256_bytes(canonical_bytes(body)),
            })

    jsonl = b"".join(canonical_bytes(row) + b"\n" for row in records)
    dataset_hash = sha256_bytes(jsonl)
    OUT.mkdir(parents=True, exist_ok=True)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    DATASET.write_bytes(jsonl)

    manifest = {
        "schema": "q25-a5-s15b-option-quote-supplement-manifest-v1",
        "dataset_id": "Q25_A5_S15B_OPTION_QUOTE_SUPPLEMENT_20261109",
        "dataset_path": "data/derived_scenario/q25_a5_s15b_option_quote_supplement/events.jsonl",
        "dataset_sha256": dataset_hash,
        "event_count": len(records),
        "observed_anchor_count": sum(r["record_type"] == "PRESERVED_SOURCE_ANCHOR" for r in records),
        "synthetic_scenario_count": sum(r["synthetic"] for r in records),
        "observation_gap_count": sum(r["record_type"] == "OBSERVATION_GAP" for r in records),
        "source_probe_path": "verification/evidence/kis_s5_option_contract_quote_probe_20261022.json",
        "source_probe_sha256": source_hash,
        "target_kis_master_sha256": MASTER_SHA256,
        "expiry_evidence_set_sha256": EXPIRY_EVIDENCE_SHA256,
        "generator_version": GENERATOR_VERSION,
        "seed": SEED,
        "anchor_time": ANCHOR.isoformat(),
        "freshness_max_age_seconds": MAX_AGE_SECONDS,
        "synthetic_spread_half_bps": str(HALF_SPREAD_BPS),
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
        "limitations": [
            "Synthetic fresh timestamps and two-sided books are scenario fixtures, not newly observed market data.",
            "Synthetic bid/ask are generated around preserved observed last prices with a fixed test-only half-spread assumption.",
            "Three candidate contracts have no preserved quote anchor; no price is fabricated for them and they remain UNAVAILABLE.",
            "The observed source quote remains historical, has no source timestamp, and has a zero top ask.",
            "The S15a strike-scale mismatch is not corrected by this dataset.",
        ],
    }
    MANIFEST.write_bytes(canonical_bytes(manifest) + b"\n")
    manifest_hash = sha256_bytes(MANIFEST.read_bytes())
    report = {
        "schema": "q25-a5-stage-report-v1",
        "stage": "S15b_SYNTHETIC_OPTION_QUOTE_DATA_SUPPLEMENT",
        "title": "S15b validation-only option quote data supplement",
        "date": "2026-11-09",
        "verdict": "PSB_UNVERIFIED_DATASET_GENERATED",
        "dataset": {
            "path": manifest["dataset_path"],
            "sha256": dataset_hash,
            "event_count": len(records),
            "manifest_path": "config/validation_only/q25_a5_s15b_option_quote_supplement/manifest.json",
            "manifest_sha256": manifest_hash,
        },
        "counts": {
            "observed_anchors": manifest["observed_anchor_count"],
            "synthetic_scenarios": manifest["synthetic_scenario_count"],
            "unavailable_contracts": manifest["observation_gap_count"],
        },
        "source_integrity": {
            "probe_sha256": source_hash,
            "source_probe_unchanged": True,
            "s15a_unchanged": True,
        },
        "limitations": manifest["limitations"],
        "execution": {
            "runtime_e2e": "NOT_RUN",
            "kis_api_called": False,
            "real_vts_api_called": False,
            "live_api_called": False,
            "account_api_called": False,
            "order_api_called": False,
        },
    }
    REPORT.write_bytes(canonical_bytes(report) + b"\n")
    (REPORT.with_suffix(REPORT.suffix + ".sha256")).write_text(
        sha256_bytes(REPORT.read_bytes()) + "\n", encoding="ascii"
    )
    return {"manifest": manifest, "report": report}


if __name__ == "__main__":
    result = build()
    print(json.dumps({
        "dataset_sha256": result["manifest"]["dataset_sha256"],
        "event_count": result["manifest"]["event_count"],
        "observed_anchors": result["manifest"]["observed_anchor_count"],
        "synthetic_scenarios": result["manifest"]["synthetic_scenario_count"],
        "observation_gaps": result["manifest"]["observation_gap_count"],
    }, sort_keys=True))
