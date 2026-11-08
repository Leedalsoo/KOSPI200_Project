from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

from contracts.market_data_freshness import (
    FreshnessEvidence,
    FreshnessPolicy,
    FreshnessStatus,
    evaluate_freshness,
)

from verification.generate_q25_a5_s15b_option_quote_supplement import (
    DATASET,
    MANIFEST,
    SOURCE,
    build,
)


def test_s15b_quote_supplement_is_deterministic_and_manifest_bound():
    first = build()
    first_bytes = DATASET.read_bytes()
    second = build()
    second_bytes = DATASET.read_bytes()

    assert first_bytes == second_bytes
    assert first["manifest"]["dataset_sha256"] == second["manifest"]["dataset_sha256"]
    assert hashlib.sha256(second_bytes).hexdigest() == second["manifest"]["dataset_sha256"]

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in second_bytes.decode("utf-8").splitlines()]
    assert len(rows) == manifest["event_count"] == 17
    assert manifest["observed_anchor_count"] == 2
    assert manifest["synthetic_scenario_count"] == 12
    assert manifest["observation_gap_count"] == 3
    assert all(row["validation_only"] for row in rows)
    assert not manifest["runtime_eligible"]
    assert not manifest["production_runtime_eligible"]
    assert not manifest["execution_enabled"]
    assert not manifest["orders_allowed"]


def test_synthetic_fresh_quotes_are_anchored_and_never_observed():
    build()
    rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines()]
    fresh = [row for row in rows if row.get("scenario_id") == "fresh_two_sided"]

    assert len(fresh) == 2
    for row in fresh:
        assert row["synthetic"] is True
        assert row["provenance"] == "SYNTHETIC:DERIVED_SCENARIO"
        assert row["source_anchor_sha256"] == hashlib.sha256(SOURCE.read_bytes()).hexdigest()
        assert float(row["quote"]["bid"]) > 0
        assert float(row["quote"]["ask"]) > float(row["quote"]["bid"])
        assert row["freshness_expected"] == "FRESH"


def test_missing_contract_quotes_remain_unavailable_not_fabricated():
    build()
    rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines()]
    gaps = [row for row in rows if row["record_type"] == "OBSERVATION_GAP"]

    assert {row["symbol"] for row in gaps} == {"C01611880", "C01611882", "B01611880"}
    assert all(row["quote"] == {"bid": None, "ask": None, "last": None} for row in gaps)
    assert all(row["freshness_expected"] == "UNAVAILABLE" for row in gaps)


def test_source_probe_and_s15a_input_are_not_modified():
    source_before = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    s15a = Path(__file__).resolve().parents[2] / "data/derived_scenario/q25_a5_s15a_s1_runtime_input/events.jsonl"
    s15a_before = hashlib.sha256(s15a.read_bytes()).hexdigest()

    build()

    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == source_before
    assert hashlib.sha256(s15a.read_bytes()).hexdigest() == s15a_before

def test_synthetic_quote_freshness_scenarios_evaluate_fail_closed():
    build()
    rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines()]
    policy = FreshnessPolicy(
        version="S15B_SYNTHETIC_VALIDATION_ONLY",
        source_age_enabled=True,
        max_age=timedelta(seconds=600),
        max_future_skew=timedelta(seconds=1),
    )
    actual = {}
    for row in rows:
        scenario_id = row.get("scenario_id")
        if not scenario_id:
            continue
        source_time = (
            datetime.fromisoformat(row["source_timestamp"])
            if row.get("source_timestamp") else None
        )
        received_at = datetime.fromisoformat(row["received_at"])
        evidence = FreshnessEvidence(
            source="SYNTHETIC:DERIVED_SCENARIO",
            endpoint="synthetic://s15b-option-quote",
            tr_id="S15B_SYNTHETIC",
            environment="SYNTHETIC",
            instrument_id=row["instrument_id"],
            symbol=row["symbol"],
            raw_source_time=row.get("source_timestamp") or "",
            source_instant=source_time,
            received_at=received_at,
            raw_payload_sha256=row["payload_sha256"],
            source_time_semantics_verified=True,
            capability_verified=True,
            metadata={"synthetic": "true", "validation_only": "true"},
        )
        verdict = evaluate_freshness(
            evidence,
            policy=policy,
            expected_instrument_id=row["symbol"],
            expected_symbol=row["symbol"],
            expected_environment="SYNTHETIC",
        )
        actual[(row["symbol"], scenario_id)] = verdict.status

    for symbol in ("B01611885", "B01611887"):
        assert actual[(symbol, "fresh_two_sided")] is FreshnessStatus.FRESH
        assert actual[(symbol, "stale_two_sided")] is FreshnessStatus.STALE
        assert actual[(symbol, "missing_source_time")] is FreshnessStatus.UNKNOWN
        assert actual[(symbol, "future_source_time")] is FreshnessStatus.UNKNOWN
        assert actual[(symbol, "identity_conflict")] is FreshnessStatus.IDENTITY_CONFLICT
        one_sided = next(
            row for row in rows
            if row.get("symbol") == symbol and row.get("scenario_id") == "one_sided_book"
        )
        assert one_sided["quote"]["ask"] == "0.00"
        assert one_sided["freshness_expected"] == "UNAVAILABLE"
