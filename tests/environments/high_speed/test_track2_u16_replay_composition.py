from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.risk.track2_synthetic_scenario_profile import load_track2_synthetic_scenario_profile
from environments.high_speed.virtual_runtime_replay import (
    _build_validation_only_track2_u16_runtime_inputs,
)


def _market_calibrated_profile():
    root = Path(__file__).resolve().parents[3]
    return load_track2_synthetic_scenario_profile(
        root / "config/validation_only/track2/synthetic_scenario_profile.market_calibrated.v2.json"
    )


def test_track2_replay_builds_u16_policy_from_validation_profile():
    profile = _market_calibrated_profile()
    policy, resolver = _build_validation_only_track2_u16_runtime_inputs(
        SimpleNamespace(profile=profile)
    )

    assert policy.is_resolved()
    assert policy.retry_interval_seconds == 30
    assert policy.max_quote_age_seconds == 5
    assert policy.max_spread == "4.70"
    assert resolver(None, SimpleNamespace(side="BUY"), None,
                    {"bid": "1.00", "ask": "1.01"}, policy, None) == Decimal("1.05")
    assert resolver(None, SimpleNamespace(side="SELL"), None,
                    {"bid": "1.04", "ask": "1.05"}, policy, None) == Decimal("1.00")


def test_track2_replay_rejects_nonuniform_u16_retry_schedule():
    profile = _market_calibrated_profile()
    invalid_profile = SimpleNamespace(
        u16_quote_policy={
            **profile.u16_quote_policy,
            "retry_schedule_seconds_after_t0": [30, 75, 90],
        },
        u21_quote_policy=profile.u21_quote_policy,
    )

    with pytest.raises(ValueError, match="TRACK2_U16_VALIDATION_PROFILE_POLICY_INCONSISTENT"):
        _build_validation_only_track2_u16_runtime_inputs(
            SimpleNamespace(profile=invalid_profile)
        )


def test_track2_replay_without_validation_adapter_does_not_enable_u16():
    assert _build_validation_only_track2_u16_runtime_inputs(None) == (None, None)
