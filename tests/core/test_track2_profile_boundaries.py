from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.risk.option_hedge_risk_config import (
    DEFAULT_CONFIG_PATH,
    load_option_hedge_risk_config,
)
from core.risk.track2_synthetic_scenario_profile import (
    DEFAULT_TRACK2_SYNTHETIC_SCENARIO_PROFILE,
    Track2SyntheticScenarioProfileError,
    load_track2_synthetic_scenario_profile,
)
from core.risk.track2_validation_profile import (
    DEFAULT_TRACK2_VALIDATION_PROFILE,
    EXPECTED_TRACK2_RISK_LIMIT_KEYS,
    Track2ValidationProfileError,
    load_track2_validation_profile,
)


STRATEGY_ID = "track2_asymmetric_trap"


def test_validation_profile_is_null_and_non_executable_while_scenario_profile_has_separate_fixture_values():
    validation = load_track2_validation_profile()
    scenario = load_track2_synthetic_scenario_profile()

    assert set(validation.risk_limit_keys) == EXPECTED_TRACK2_RISK_LIMIT_KEYS
    assert len(validation.profile_sha256) == 64
    assert validation.numeric_limits_resolved is False
    assert validation.execution_enabled is False
    assert validation.order_submission_enabled is False
    assert validation.live_api_enabled is False
    assert validation.real_vts_api_enabled is False

    assert scenario.risk_limits["account_capital_krw"] == 100_000_000
    assert scenario.execution_enabled is False
    assert scenario.order_submission_enabled is False
    assert scenario.live_api_enabled is False
    assert scenario.real_vts_api_enabled is False


def test_synthetic_scenario_profile_cannot_be_loaded_as_validation_risk_profile():
    with pytest.raises(Track2ValidationProfileError, match="IDENTITY_INVALID"):
        load_track2_validation_profile(DEFAULT_TRACK2_SYNTHETIC_SCENARIO_PROFILE)


def test_validation_risk_profile_cannot_be_loaded_as_synthetic_scenario_profile():
    with pytest.raises(Track2SyntheticScenarioProfileError, match="IDENTITY_INVALID"):
        load_track2_synthetic_scenario_profile(DEFAULT_TRACK2_VALIDATION_PROFILE)


def test_operational_profile_cannot_be_loaded_as_either_validation_profile():
    with pytest.raises(Track2ValidationProfileError, match="IDENTITY_INVALID"):
        load_track2_validation_profile(DEFAULT_CONFIG_PATH)
    with pytest.raises(Track2SyntheticScenarioProfileError, match="IDENTITY_INVALID"):
        load_track2_synthetic_scenario_profile(DEFAULT_CONFIG_PATH)


def test_synthetic_scenario_profile_cannot_be_loaded_as_operational_risk_config():
    with pytest.raises(ValueError, match="CURRENCY_UNSUPPORTED"):
        load_option_hedge_risk_config(DEFAULT_TRACK2_SYNTHETIC_SCENARIO_PROFILE)


def test_validation_profile_rejects_missing_limit_key_and_duplicate_policy_dependency(
    tmp_path: Path,
):
    raw = json.loads(DEFAULT_TRACK2_VALIDATION_PROFILE.read_text(encoding="utf-8-sig"))
    raw["risk_limits"].pop("fee_model_version")
    path = tmp_path / "missing-risk-limit.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(Track2ValidationProfileError, match="LIMITS_MUST_REMAIN_NULL"):
        load_track2_validation_profile(path)

    raw = json.loads(DEFAULT_TRACK2_VALIDATION_PROFILE.read_text(encoding="utf-8-sig"))
    raw["unresolved_policy_dependencies"].append("S2-U17")
    path = tmp_path / "duplicate-dependency.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(Track2ValidationProfileError, match="POLICY_REGISTER_MISMATCH"):
        load_track2_validation_profile(path)


def test_disabled_operational_profile_masks_configured_strategy_enablement():
    config = load_option_hedge_risk_config()
    configured = config.strategies[STRATEGY_ID]

    assert config.activation_mode == "DISABLED_UNTIL_RUNTIME_INTEGRATION"
    assert configured.enabled is True  # retained as a configured validation reference
    assert config.operational_enforcement_enabled is False
    assert config.is_strategy_operationally_enabled(STRATEGY_ID) is False
    assert config.live_order_submission_permitted is False


def test_enforced_risk_mode_still_cannot_submit_live_orders(tmp_path: Path):
    raw = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8-sig"))
    raw["activation_mode"] = "ENFORCED"
    path = tmp_path / "enforced-risk-reference.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    config = load_option_hedge_risk_config(path)
    assert config.operational_enforcement_enabled is True
    assert config.is_strategy_operationally_enabled(STRATEGY_ID) is True
    assert config.live_order_submission_permitted is False
    assert config.allow_live_orders is False
