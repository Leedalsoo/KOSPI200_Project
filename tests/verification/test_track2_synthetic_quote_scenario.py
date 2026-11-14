from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json

import pytest

from verification.track2_synthetic_quote_scenario import (
    Track2SyntheticQuoteScenarioError,
    build_track2_synthetic_quote_scenario,
    validate_quote_snapshot,
)

PROFILE = "config/validation_only/track2/synthetic_scenario_profile.v1.json"


def _inputs(tmp_path):
    dataset = tmp_path / "runtime_v2"
    dataset.mkdir()
    payload = b'{"source":"preserve-me"}\n'
    (dataset / "20261012.jsonl").write_bytes(payload)
    manifest = {
        "schema_version": "accepted-market-data-runtime-v2",
        "registry_id": "KOSPI200_ACCEPTED_MARKET_DATA_20261114",
        "acceptance": "ACCEPTED_FOR_PROJECT_VERIFICATION",
        "rows_total": 1,
        "days": [{"date": "20261012", "rows": 1, "sha256": sha256(payload).hexdigest()}],
    }
    manifest_path = dataset / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    candidate = [{
        "candidate_id": "candidate-001",
        "observed_at": "2026-10-12T09:26:00+09:00",
        "expiry": "20261112",
        "underlying_price": "1035.0",
        "source_observation_id": "accepted-observation-001",
        "legs": [
            {"role": "inner_put", "option_type": "PUT", "strike": "1032.5"},
            {"role": "inner_call", "option_type": "CALL", "strike": "1037.5"},
            {"role": "outer_put", "option_type": "PUT", "strike": "1027.5"},
            {"role": "outer_call", "option_type": "CALL", "strike": "1042.5"},
        ],
    }]
    candidates = tmp_path / "candidates.json"
    candidates.write_text(json.dumps(candidate), encoding="utf-8")
    return dataset, manifest_path, candidates


def _build(tmp_path, name="scenario-v1"):
    dataset, manifest, candidates = _inputs(tmp_path)
    return build_track2_synthetic_quote_scenario(
        base_dataset=dataset, base_manifest=manifest, profile_path=PROFILE,
        candidates_path=candidates, output_dir=tmp_path / name,
    ), dataset, candidates


def test_builds_four_manifest_bound_synthetic_quotes_without_mutating_source(tmp_path):
    result, dataset, _ = _build(tmp_path)
    manifest = json.loads((tmp_path / "scenario-v1" / "manifest.json").read_text())
    rows = [json.loads(line) for line in (tmp_path / "scenario-v1" / "four_leg_quotes.jsonl").read_text().splitlines()]

    assert result.candidates == 1 and result.quote_rows == 4
    assert [row["leg_role"] for row in rows] == ["inner_put", "inner_call", "outer_put", "outer_call"]
    assert all(row["instrument_id"].startswith("SYNTHETIC_CONTRACT:S2:") for row in rows)
    assert all(row["source"] == "SYNTHETIC:DERIVED_SCENARIO" for row in rows)
    assert all(row["contract_multiplier"] == "250000" for row in rows)
    assert all(row["contract_product_family"] == "STANDARD" for row in rows)
    assert all(row["contract_cycle"] == "MONTHLY" for row in rows)
    assert all(row["contract_multiplier_provenance"] == "KIS_OFFICIAL_PRODUCT_SPEC" for row in rows)
    assert manifest["contract_specification"]["multiplier"] == "250000"
    assert manifest["contract_specification"]["source_url"].endswith("TF03bd010100.jsp")
    assert manifest["schema_version"].endswith("v2")
    assert manifest["u21"] == {"max_age_seconds": "5", "max_spread": "0.20", "tick_size": "0.05"}
    assert (dataset / "20261012.jsonl").read_bytes() == b'{"source":"preserve-me"}\n'


def test_generation_is_deterministic_and_refuses_existing_output(tmp_path):
    first, _, candidates = _build(tmp_path, "scenario-a")
    dataset = tmp_path / "runtime_v2"
    manifest = dataset / "manifest.json"
    candidates = tmp_path / "candidates.json"
    second = build_track2_synthetic_quote_scenario(
        base_dataset=dataset, base_manifest=manifest, profile_path=PROFILE,
        candidates_path=candidates, output_dir=tmp_path / "scenario-b",
    )
    assert first.quotes_sha256 == second.quotes_sha256
    with pytest.raises(Track2SyntheticQuoteScenarioError, match="OUTPUT_MUST_BE_NEW"):
        build_track2_synthetic_quote_scenario(
            base_dataset=dataset, base_manifest=manifest, profile_path=PROFILE,
            candidates_path=candidates, output_dir=tmp_path / "scenario-a",
        )


def test_rejects_non_four_leg_candidate(tmp_path):
    dataset, manifest, candidates = _inputs(tmp_path)
    data = json.loads(candidates.read_text())
    data[0]["legs"].pop()
    candidates.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(Track2SyntheticQuoteScenarioError, match="EXACTLY_FOUR_LEGS"):
        build_track2_synthetic_quote_scenario(
            base_dataset=dataset, base_manifest=manifest, profile_path=PROFILE,
            candidates_path=candidates, output_dir=tmp_path / "scenario-invalid",
        )


def test_u21_validator_rejects_stale_and_wide_quotes():
    base = {
        "source": "SYNTHETIC:DERIVED_SCENARIO", "provenance": "SYNTHETIC",
        "instrument_id": "SYNTHETIC_CONTRACT:S2:test",
        "timestamp": "2026-10-12T09:25:54+09:00", "bid": "1.00", "ask": "1.10",
    }
    observed = datetime.fromisoformat("2026-10-12T09:26:00+09:00")
    with pytest.raises(Track2SyntheticQuoteScenarioError, match="U21_QUOTE_AGE_BLOCKED"):
        validate_quote_snapshot(base, observed_at=observed)
    wide = {**base, "timestamp": observed.isoformat(), "ask": "1.25"}
    with pytest.raises(Track2SyntheticQuoteScenarioError, match="U21_QUOTE_SPREAD_BLOCKED"):
        validate_quote_snapshot(wide, observed_at=observed)
