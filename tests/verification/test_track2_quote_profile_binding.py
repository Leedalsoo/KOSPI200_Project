from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from verification.track2_quote_profile_binding import bind_validation_only_track2_quote_scenario_profile


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path):
    source_profile = {
        "profile_id": "SOURCE-MARKET-PROFILE-v1",
        "U18_exit_policy": {"stop_loss_ratio": "-0.50", "trailing_activation_ratio": "0.40", "trailing_pullback_ratio": "0.25"},
        "U21_quote_policy": {"max_age_seconds": "5", "max_spread": "4.70", "tick_size": "0.05"},
        "market_calibration": {"pricing_model": "BLACK_SCHOLES_ZERO_RATE_EMPIRICAL_IV_V1"},
        "execution_enabled": False,
        "order_submission_enabled": False,
        "live_api_enabled": False,
        "real_vts_api_enabled": False,
        "limitations": ["validation only"],
    }
    target_profile = copy.deepcopy(source_profile)
    target_profile.update({
        "profile_id": "TARGET-STOP-PROFILE-v1",
        "U18_exit_policy": {"stop_loss_ratio": "-0.40", "trailing_activation_ratio": "0.40", "trailing_pullback_ratio": "0.25"},
        "exit_path_test": {"production_policy_approval": False},
        "limitations": ["validation-only stop-path fixture"],
    })
    source_profile_path = tmp_path / "source-profile.json"
    target_profile_path = tmp_path / "target-profile.json"
    source_profile_path.write_text(json.dumps(source_profile), encoding="utf-8")
    target_profile_path.write_text(json.dumps(target_profile), encoding="utf-8")

    sidecar = tmp_path / "source-sidecar"
    sidecar.mkdir()
    candidate_path = sidecar / "candidate_inputs.json"
    candidate_path.write_text("[]\n", encoding="utf-8")
    row = {
        "timestamp": "2026-10-12T09:26:00+09:00",
        "leg_role": "inner_put",
        "bid": "39.60",
        "ask": "41.50",
        "last": "40.55",
        "scenario_profile_id": source_profile["profile_id"],
        "scenario_profile_sha256": _sha(source_profile_path),
        "market_calibration": {"implied_volatility": 0.34, "source_anchor_max_age_seconds": 833},
    }
    quote_path = sidecar / "quotes.jsonl"
    quote_path.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "profile_id": source_profile["profile_id"],
        "profile_sha256": _sha(source_profile_path),
        "quote_rows": 1,
        "candidate_count": 1,
        "price_model": "BLACK_SCHOLES_ZERO_RATE_EMPIRICAL_IV_V1",
        "u21": {"max_age_seconds": "5", "max_spread": "4.70", "tick_size": "0.05"},
        "quote_file": {"path": quote_path.name, "sha256": _sha(quote_path), "rows": 1},
        "candidate_input_file": {"path": candidate_path.name, "sha256": _sha(candidate_path)},
    }
    manifest_path = sidecar / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return source_profile_path, target_profile_path, manifest_path, quote_path, candidate_path, row


def test_profile_binding_changes_only_profile_metadata_and_preserves_sources(tmp_path):
    source_profile, target_profile, source_manifest, source_quote, source_candidates, original_row = _fixture(tmp_path)
    before = {path: path.read_bytes() for path in (source_profile, target_profile, source_manifest, source_quote, source_candidates)}

    result = bind_validation_only_track2_quote_scenario_profile(
        source_manifest_path=source_manifest,
        source_profile_path=source_profile,
        target_profile_path=target_profile,
        output_dir=tmp_path / "bound-sidecar",
        purpose="U18_STOP_PATH_VALIDATION_ONLY",
    )

    bound_row = json.loads(result.quote_path.read_text(encoding="utf-8").splitlines()[0])
    assert bound_row["bid"] == original_row["bid"]
    assert bound_row["ask"] == original_row["ask"]
    assert bound_row["last"] == original_row["last"]
    assert bound_row["timestamp"] == original_row["timestamp"]
    assert bound_row["market_calibration"] == original_row["market_calibration"]
    assert bound_row["source_scenario_profile_id"] == original_row["scenario_profile_id"]
    assert bound_row["scenario_profile_id"] == "TARGET-STOP-PROFILE-v1"
    assert result.quote_rows == result.candidates == 1
    assert result.candidate_inputs_sha256 == _sha(source_candidates)
    assert result.derived_manifest_sha256 == _sha(result.manifest_path)
    assert result.derived_quote_sha256 == _sha(result.quote_path)
    for path, content in before.items():
        assert path.read_bytes() == content


def test_profile_binding_refuses_changed_market_or_quote_policy(tmp_path):
    source_profile, target_profile, source_manifest, _quote, _candidates, _row = _fixture(tmp_path)
    target = json.loads(target_profile.read_text(encoding="utf-8"))
    target["U21_quote_policy"]["max_age_seconds"] = "10"
    target_profile.write_text(json.dumps(target), encoding="utf-8")

    with pytest.raises(ValueError, match="TARGET_PROFILE_U21_POLICY_MISMATCH"):
        bind_validation_only_track2_quote_scenario_profile(
            source_manifest_path=source_manifest,
            source_profile_path=source_profile,
            target_profile_path=target_profile,
            output_dir=tmp_path / "must-not-exist",
            purpose="U18_STOP_PATH_VALIDATION_ONLY",
        )
    assert not (tmp_path / "must-not-exist").exists()