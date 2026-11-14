from __future__ import annotations

import json
from decimal import Decimal

import pytest

from core.risk.track2_synthetic_scenario_profile import (
    Track2SyntheticScenarioProfileError,
    load_track2_synthetic_scenario_profile,
)


def test_loads_separate_synthetic_only_profile_with_hash_and_disabled_external_execution():
    profile = load_track2_synthetic_scenario_profile()

    assert profile.profile_id == "S2-SYNTHETIC-SCENARIO-ONLY-v1"
    assert len(profile.profile_sha256) == 64
    assert profile.execution_enabled is False
    assert profile.order_submission_enabled is False
    assert profile.live_api_enabled is False
    assert profile.real_vts_api_enabled is False
    assert profile.risk_limits["group_max_loss_krw"] == 625000
    assert profile.u20_entry_policy["sequence"] == ["inner_put", "inner_call", "outer_put", "outer_call"]


def test_rejects_profile_that_enables_any_external_execution_flag(tmp_path):
    source = load_track2_synthetic_scenario_profile()
    payload = {
        "schema_version": "1.0.0",
        "profile_id": source.profile_id,
        "profile_type": "SYNTHETIC_SCENARIO_ONLY",
        "strategy_id": "track2_asymmetric_trap",
        "execution_enabled": True,
        "order_submission_enabled": False,
        "live_api_enabled": False,
        "real_vts_api_enabled": False,
        "risk_limits": source.risk_limits,
    }
    path = tmp_path / "unsafe.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(Track2SyntheticScenarioProfileError, match="MUST_NOT_ENABLE_EXECUTION"):
        load_track2_synthetic_scenario_profile(path)


def test_track2_plan_signal_can_cross_canonical_boundary_without_fake_single_contract():
    from core.strategy.canonical_signal_adapter import RuntimeSignalContext, signal_to_canonical
    from core.strategy.contracts import Signal
    from core.strategy.strategy_execution_proposal import StrategyExecutionProposal

    signal = Signal(
        "track2_asymmetric_trap", "LONG", 1.0, "ASYMMETRIC_TRAP_ENTRY",
        execution_proposal=StrategyExecutionProposal(
            proposed_quantity=1, asset_type="OPTION", requested_price=None,
            side="SELL", track_id="track2_asymmetric_trap", tag_id="TRAP_PLAN",
            option_type="PUT", strike=Decimal("1025.0"),
        ),
    )
    canonical = signal_to_canonical(
        signal,
        RuntimeSignalContext("s2-signal-1", "track2_asymmetric_trap", 40.0, "2026-10-12T09:02:26+09:00"),
    )

    assert canonical.identity_source == "MULTI_LEG_PLAN_IDENTITY_RESOLVED_BY_PLAN_RESOLVER"
    assert canonical.option_type is None
    assert canonical.expiry == ""
    assert canonical.instrument_id == ""
    assert canonical.strike == 1025.0
