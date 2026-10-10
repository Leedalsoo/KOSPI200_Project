from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.strategy.contracts import ConfiguredStrategyPlugin, StrategyContext, StrategyInput
from core.strategy.definition import load_strategy_manifest
from core.strategy.standard_registry import build_standard_strategy_registry


def test_standard_registry_loads_nine_versioned_strategy_definitions() -> None:
    registry = build_standard_strategy_registry()
    provenance = registry.configuration_provenance()
    assert len(provenance) == 9
    assert all(code_version and config_version for _, code_version, config_version, _ in provenance)
    assert len({config_hash for _, _, _, config_hash in provenance}) == 1
    assert all(len(config_hash) == 64 for _, _, _, config_hash in provenance)

    definitions = registry.definitions_by_strategy_id()
    assert set(definitions) == {
        "TRACK1_TAIL_DEFENSE",
        "track2_asymmetric_trap",
        "Strategy_3_StatArb",
        "track4_gamma_scalping",
        "track5_gap_divergence",
        "track6_daily_tail_insurance",
        "track7_volatility_skew_weekly_insurance",
        "track8_macro_regime_monthly_strangle",
        "track9_event_overnight_insurance",
    }
    for strategy_id, definition in definitions.items():
        strategy = registry.get(strategy_id, definition.code_version)
        assert strategy.config_version == definition.config_version
        assert strategy.config_hash == definition.config_hash
        assert strategy.definition is definition
        assert isinstance(strategy, ConfiguredStrategyPlugin)


def test_manifest_hash_can_pin_a_reproducible_configuration() -> None:
    manifest = load_strategy_manifest()
    registry = build_standard_strategy_registry(expected_sha256=manifest.sha256)
    assert len(registry.configuration_provenance()) == 9
    with pytest.raises(ValueError, match="STRATEGY_MANIFEST_SHA256_MISMATCH"):
        build_standard_strategy_registry(expected_sha256="0" * 64)


def test_one_strategy_configuration_change_is_isolated(tmp_path: Path) -> None:
    manifest = load_strategy_manifest()
    payload = json.loads(manifest.path.read_text(encoding="utf-8"))
    payload["strategies"][0]["parameters"]["profit_target"] = 765432.0
    payload["strategies"][0]["parameters"]["INITIAL_FENCE_DISTANCE"] = 9.0
    changed_path = tmp_path / "strategy-manifest.json"
    changed_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    changed = build_standard_strategy_registry(changed_path)
    baseline = build_standard_strategy_registry()

    assert changed.get("TRACK1_TAIL_DEFENSE", "1.1.0").profit_target == 765432.0
    assert changed.get("TRACK1_TAIL_DEFENSE", "1.1.0").state.fence_distance == 9.0
    assert baseline.get("TRACK1_TAIL_DEFENSE", "1.1.0").profit_target == 500000.0
    assert baseline.get("TRACK1_TAIL_DEFENSE", "1.1.0").state.fence_distance == 7.5
    assert changed.get("track2_asymmetric_trap", "1.0").STOP_LOSS_RATIO == baseline.get(
        "track2_asymmetric_trap", "1.0"
    ).STOP_LOSS_RATIO
    changed_hashes = {row[3] for row in changed.configuration_provenance()}
    baseline_hashes = {row[3] for row in baseline.configuration_provenance()}
    assert len(changed_hashes) == len(baseline_hashes) == 1
    assert changed_hashes != baseline_hashes


def test_execution_contract_and_required_source_metadata_are_declared() -> None:
    registry = build_standard_strategy_registry()
    definitions = registry.definitions_by_strategy_id()
    assert definitions["track2_asymmetric_trap"].execution_contract == "MULTI_LEG_REQUIRED"
    assert definitions["track2_asymmetric_trap"].required_sources
    assert definitions["track2_asymmetric_trap"].required_analytics
    assert definitions["track6_daily_tail_insurance"].execution_contract == "CONDITIONAL_MULTI_LEG"
    assert definitions["track6_daily_tail_insurance"].required_execution_tags == (
        "DAILY_TAIL_INSURANCE_ENTRY",
    )
    assert definitions["track8_macro_regime_monthly_strangle"].required_execution_tags == (
        "MONTHLY_STRANGLE_ENTRY",
    )


def test_declared_source_status_is_fail_closed_when_provided() -> None:
    registry = build_standard_strategy_registry()
    blocked = StrategyContext(
        strategy_id="TRACK1_TAIL_DEFENSE",
        input=StrategyInput(data_status={"market_state.ticks": "UNAVAILABLE"}),
    )
    with pytest.raises(ValueError, match="STRATEGY_REQUIRED_SOURCE_UNAVAILABLE"):
        registry.prepare("TRACK1_TAIL_DEFENSE", "1.1.0", blocked)

    available = StrategyContext(
        strategy_id="TRACK1_TAIL_DEFENSE",
        input=StrategyInput(data_status={"market_state.ticks": "AVAILABLE"}),
    )
    assert registry.prepare("TRACK1_TAIL_DEFENSE", "1.1.0", available).strategy_id == "TRACK1_TAIL_DEFENSE"
