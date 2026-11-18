import hashlib
import json
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
