import hashlib
import json
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from application.bootstrap import create_live_runtime_bootstrap
from application.composition.automated_virtual_runtime_factory import (
    attach_standard_automated_loop,
)
from environments.high_speed.synthetic_runtime_sources import (
    SyntheticEventRiskSource,
    SyntheticRuntimeSources,
    SyntheticTrack6VolatilitySource,
)
from environments.high_speed.virtual_runtime_replay import (
    _resolve_validation_only_provider_context,
)


def test_synthetic_runtime_source_is_explicitly_validation_only():
    source = SyntheticRuntimeSources(
        source_manifest_sha256="A" * 64, scenario_id="T1-BOUNDARY-FIXTURE",
    )
    assert source.validation_only is True
    assert source.provenance == "DERIVED_SCENARIO"
    assert source.production_runtime_eligible is False
    assert source.identity_authority == "SYNTHETIC_ONLY"
    assert source.source_manifest_sha256 == "a" * 64
    assert source.scenario_id == "T1-BOUNDARY-FIXTURE"
    assert source.provider_context_kind == "MANIFEST_BOUND"


def test_synthetic_runtime_source_rejects_malformed_manifest_hash():
    with pytest.raises(ValueError, match="SYNTHETIC_RUNTIME_SOURCE_MANIFEST_SHA256_INVALID"):
        SyntheticRuntimeSources(source_manifest_sha256="not-a-sha256")


def test_virtual_factory_rejects_unmarked_synthetic_runtime_source():
    unmarked = SimpleNamespace(source_name="SYNTHETIC:test")
    with pytest.raises(ValueError, match="SYNTHETIC_RUNTIME_SOURCE_MUST_BE_VALIDATION_ONLY"):
        attach_standard_automated_loop(None, synthetic_runtime_sources=unmarked)


def test_virtual_factory_rejects_unmarked_synthetic_greeks_provider():
    unmarked = SimpleNamespace(source_name="SYNTHETIC:test")
    with pytest.raises(ValueError, match="TRACK4_GREEKS_PROVIDER_SYNTHETIC_PROVIDER_MUST_BE_VALIDATION_ONLY"):
        attach_standard_automated_loop(None, track4_greeks_provider=unmarked)


def test_live_bootstrap_rejects_synthetic_runtime_provider_before_live_composition():
    with pytest.raises(ValueError, match="LIVE_RUNTIME_VALIDATION_ONLY_PROVIDER_FORBIDDEN"):
        create_live_runtime_bootstrap(synthetic_runtime_sources=SyntheticRuntimeSources())


def test_live_bootstrap_rejects_any_validation_only_adapter_injection():
    with pytest.raises(ValueError, match="LIVE_RUNTIME_VALIDATION_ONLY_PROVIDER_FORBIDDEN"):
        create_live_runtime_bootstrap(validation_only_synthetic_manifest="manifest.json")


def test_replay_provider_context_binds_manifest_hash_and_single_scenario(tmp_path):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    manifest = dataset / "manifest.json"
    manifest.write_text(json.dumps({"scenario_ids": ["T1-SCENARIO"]}), encoding="utf-8")
    digest, scenario_id = _resolve_validation_only_provider_context(dataset, (None, manifest))
    assert digest == hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert scenario_id == "T1-SCENARIO"


def test_replay_provider_context_is_fixture_only_without_manifest(tmp_path):
    digest, scenario_id = _resolve_validation_only_provider_context(tmp_path, (None, tmp_path / "missing.json"))
    assert digest is None
    assert scenario_id is None


def test_synthetic_runtime_source_wrappers_preserve_validation_only_provenance():
    source = SyntheticRuntimeSources(source_manifest_sha256="b" * 64, scenario_id="T1-WRAPPER")
    option_master = object()
    for provider in (
        SyntheticTrack6VolatilitySource(source, option_master),
        SyntheticEventRiskSource(source),
    ):
        assert provider.validation_only is True
        assert provider.provenance == "DERIVED_SCENARIO"
        assert provider.production_runtime_eligible is False
        assert provider.identity_authority == "SYNTHETIC_ONLY"
        assert provider.source_manifest_sha256 == "b" * 64
        assert provider.scenario_id == "T1-WRAPPER"

@dataclass
class _RecordingValidationAdapter:
    bound_run_ids: list[str] = field(default_factory=list)
    applied_strategy_ids: list[str] = field(default_factory=list)

    def bind_run_id(self, run_id):
        self.bound_run_ids.append(str(run_id))

    def apply_to_strategy(self, strategy, *, synthetic_sources):
        self.applied_strategy_ids.append(str(strategy.strategy_id))


_VALIDATION_ADAPTERS = {
    "s7": "validation_only_s7_runtime_adapter",
    "s8": "validation_only_s8_runtime_adapter",
    "s9": "validation_only_s9_runtime_adapter",
}
_VALIDATION_STRATEGY_KEYS = {
    "s7": ("track7_volatility_skew_weekly_insurance", "1.0"),
    "s8": ("track8_macro_regime_monthly_strangle", "2.0"),
    "s9": ("track9_event_overnight_insurance", "3.0"),
}


@pytest.mark.parametrize(
    "adapter_pair",
    (("s7", "s8"), ("s7", "s9"), ("s8", "s9")),
)
def test_factory_rejects_multiple_strategy_validation_adapters_before_any_adapter_mutation(adapter_pair):
    adapters = {name: _RecordingValidationAdapter() for name in adapter_pair}
    kwargs = {
        _VALIDATION_ADAPTERS[name]: adapter
        for name, adapter in adapters.items()
    }
    # Select a strategy accepted by the adapter that currently runs first.
    strategy_name = "s8" if adapter_pair == ("s7", "s8") else "s9"
    strategy_key = _VALIDATION_STRATEGY_KEYS[strategy_name]
    with pytest.raises(ValueError, match="S7_S8_S9_VALIDATION_ADAPTERS_MUST_BE_ISOLATED"):
        attach_standard_automated_loop(
            None,
            strategy_keys=(strategy_key,),
            run_id="SYNTHETIC-ADAPTER-CONFLICT",
            synthetic_runtime_sources=SyntheticRuntimeSources(
                source_manifest_sha256="a" * 64,
                scenario_id="SYNTHETIC-ADAPTER-CONFLICT",
            ),
            **kwargs,
        )
    assert all(not adapter.bound_run_ids for adapter in adapters.values())
    assert all(not adapter.applied_strategy_ids for adapter in adapters.values())


@pytest.mark.parametrize("adapter_name", ("s7", "s8", "s9"))
def test_factory_rejects_strategy_adapter_with_track6_lifecycle_before_adapter_mutation(adapter_name):
    adapter = _RecordingValidationAdapter()
    with pytest.raises(ValueError, match="S7_S8_S9_VALIDATION_ADAPTER_CANNOT_SHARE_TRACK6_GATES"):
        attach_standard_automated_loop(
            None,
            strategy_keys=(_VALIDATION_STRATEGY_KEYS[adapter_name],),
            run_id=f"SYNTHETIC-{adapter_name.upper()}-TRACK6-LIFECYCLE-CONFLICT",
            synthetic_runtime_sources=SyntheticRuntimeSources(
                source_manifest_sha256="b" * 64,
                scenario_id=f"SYNTHETIC-{adapter_name.upper()}-TRACK6-LIFECYCLE-CONFLICT",
            ),
            validation_only_track6_lifecycle_config=object(),
            **{_VALIDATION_ADAPTERS[adapter_name]: adapter},
        )
    assert adapter.bound_run_ids == []
    assert adapter.applied_strategy_ids == []


@pytest.mark.parametrize("adapter_name", ("s7", "s8", "s9"))
def test_factory_rejects_strategy_adapter_with_track6_signal_mode_before_adapter_mutation(adapter_name):
    adapter = _RecordingValidationAdapter()
    with pytest.raises(ValueError, match="S7_S8_S9_VALIDATION_ADAPTER_CANNOT_SHARE_TRACK6_GATES"):
        attach_standard_automated_loop(
            None,
            strategy_keys=(_VALIDATION_STRATEGY_KEYS[adapter_name],),
            run_id=f"SYNTHETIC-{adapter_name.upper()}-TRACK6-SIGNAL-CONFLICT",
            synthetic_runtime_sources=SyntheticRuntimeSources(
                source_manifest_sha256="c" * 64,
                scenario_id=f"SYNTHETIC-{adapter_name.upper()}-TRACK6-SIGNAL-CONFLICT",
            ),
            validation_only_track6_signal_mode=True,
            **{_VALIDATION_ADAPTERS[adapter_name]: adapter},
        )
    assert adapter.bound_run_ids == []
    assert adapter.applied_strategy_ids == []

@pytest.mark.parametrize("adapter_name", ("s7", "s8", "s9"))
def test_factory_rejects_strategy_adapter_with_track6_execution_gate_before_adapter_mutation(adapter_name):
    adapter = _RecordingValidationAdapter()
    with pytest.raises(ValueError, match="S7_S8_S9_VALIDATION_ADAPTER_CANNOT_SHARE_TRACK6_GATES"):
        attach_standard_automated_loop(
            None,
            strategy_keys=(_VALIDATION_STRATEGY_KEYS[adapter_name],),
            run_id=f"SYNTHETIC-{adapter_name.upper()}-TRACK6-EXECUTION-CONFLICT",
            synthetic_runtime_sources=SyntheticRuntimeSources(
                source_manifest_sha256="d" * 64,
                scenario_id=f"SYNTHETIC-{adapter_name.upper()}-TRACK6-EXECUTION-CONFLICT",
            ),
            validation_only_track6_execution_gate=object(),
            **{_VALIDATION_ADAPTERS[adapter_name]: adapter},
        )
    assert adapter.bound_run_ids == []
    assert adapter.applied_strategy_ids == []
