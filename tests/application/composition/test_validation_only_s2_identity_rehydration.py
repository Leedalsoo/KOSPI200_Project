from pathlib import Path
from types import SimpleNamespace

from application.composition.validation_only_s2_scenario_alternative_provider import (
    ValidationOnlyS2ScenarioAlternativeProvider,
)
from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge


def _provider(root):
    return ValidationOnlyS2ScenarioAlternativeProvider(
        project_root=root,
        run_id="S2-IDENTITY-REHYDRATION-TEST",
        vssf_adapter=object(),
        candidate_id="S2-CANDIDATE-001",
        position_phase="PRE_ENTRY",
    )


def test_s2_identity_registry_rehydrates_four_exact_validation_only_identities_after_restart():
    project_root = Path(__file__).resolve().parents[3]
    first = _provider(project_root).build_option_identity_evidence()
    restarted = _provider(project_root).build_option_identity_evidence()

    assert len(first) == 4
    assert [item.leg_role for item in first] == [
        "inner_put", "inner_call", "outer_put", "outer_call"
    ]
    assert len({item.identity.instrument_id for item in first}) == 4
    assert first == restarted
    for item in first:
        identity = item.identity
        assert item.candidate_id == "S2-CANDIDATE-001"
        assert item.contract_identity_authority == "SYNTHETIC_ONLY_NOT_KIS_MASTER"
        assert item.contract_multiplier_provenance == "KIS_OFFICIAL_PRODUCT_SPEC"
        assert identity.identity_source == "SYNTHETIC:DERIVED_SCENARIO"
        assert identity.symbol == identity.instrument_id
        assert identity.instrument_id.startswith("SYNTHETIC_CONTRACT:")
        assert item.accepted_manifest_sha256 == "7657c90f13a81a7f98a8ccd075a259c8ec9795477a2a0541366094cd87e0360f"
        assert item.scenario_manifest_sha256 == "13580e010c34c74a1787bffb6b6b72adebdc4964f848937c0894bfa0fd4918b7"
        assert item.quote_sidecar_sha256 == "466c796c536d48a91fd548e6c61c597da4bde558bd56a079cc8956a9f882786e"
        assert item.profile_sha256 == "c0607c405abba4d2500bd8d5572db0270a9bdc61ab7e4943b1fd3c73d6181b18"
        assert len(item.derived_identity_digest) == 64
        plan = SimpleNamespace(strategy_id="S2_SYNTHETIC_REHYDRATION")
        leg = SimpleNamespace(
            instrument_identity=identity,
            option_type=identity.option_type,
            strike=identity.strike,
        )
        assert VirtualMultiLegExecutionBridge.identity_for_leg(_bridge(), plan, leg) is identity


def _bridge():
    return object.__new__(VirtualMultiLegExecutionBridge)
