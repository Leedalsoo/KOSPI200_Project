from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from application.composition.validation_only_s2_scenario_alternative_provider import (
    ValidationOnlyS2ScenarioAlternativeProvider,
)
from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge


ORIGINAL_ROOT = Path(__file__).resolve().parents[3].parent / "Q25_A8_R10"


def _provider(root, vssf_adapter=None, source_roots=()):
    return ValidationOnlyS2ScenarioAlternativeProvider(
        project_root=root,
        run_id="S2-IDENTITY-REHYDRATION-TEST",
        vssf_adapter=vssf_adapter if vssf_adapter is not None else object(),
        candidate_id="S2-CANDIDATE-001",
        position_phase="PRE_ENTRY",
        source_roots=source_roots,
    )


def test_s2_identity_registry_rehydrates_four_exact_validation_only_identities_after_restart():
    if not ORIGINAL_ROOT.is_dir():
        pytest.skip("read-only exact original S2 source root is not mounted")
    project_root = Path(__file__).resolve().parents[3]
    source_roots = (ORIGINAL_ROOT,) if ORIGINAL_ROOT.is_dir() else ()
    first_provider = _provider(project_root, source_roots=source_roots)
    restarted_provider = _provider(project_root, source_roots=source_roots)
    first = first_provider.build_option_identity_evidence()
    restarted = restarted_provider.build_option_identity_evidence()
    if source_roots:
        assert first_provider.last_source_resolution["scenario_manifest"] == "ORIGINAL_SOURCE_ROOT:0"
        assert first_provider.last_source_resolution["quotes"] == "ORIGINAL_SOURCE_ROOT:0"

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


def test_u19_expected_group_manifest_hash_binds_rehydrated_identity_registry():
    if not ORIGINAL_ROOT.is_dir():
        pytest.skip("read-only exact original S2 source root is not mounted")
    project_root = Path(__file__).resolve().parents[3]

    class _CaptureVssf:
        def build_candidate(self, **kwargs):
            self.kwargs = kwargs
            return kwargs

    capture = _CaptureVssf()
    provider = _provider(project_root, vssf_adapter=capture, source_roots=(ORIGINAL_ROOT,) if ORIGINAL_ROOT.is_dir() else ())
    tick = SimpleNamespace(
        timestamp="2026-10-12T09:26:00+09:00",
        underlying_price=1034.62,
    )
    result = provider(tick)
    identity_evidence = provider.build_option_identity_evidence()
    registry_digest = provider._hash_json([
        {"leg_role": item.leg_role, "derived_identity_digest": item.derived_identity_digest}
        for item in identity_evidence
    ])
    expected = capture.kwargs["expected_group_manifest"]

    assert result is capture.kwargs
    assert f"IDENTITY_REGISTRY={registry_digest}" in expected.provenance
    assert capture.kwargs["source_manifest_sha256"] == identity_evidence[0].scenario_manifest_sha256
    assert any(
        ref.startswith(f"s2_scenario_manifest#sha256={identity_evidence[0].scenario_manifest_sha256}:identity_registry_sha256={registry_digest}")
        for ref in capture.kwargs["source_anchor_refs"]
    )
    assert f"s2_identity_registry#sha256={registry_digest}" in capture.kwargs["evidence_refs"]
    expected_payload = {
        "group_id": expected.group_id,
        "manifest_id": expected.manifest_id,
        "source": expected.source,
        "provenance": expected.provenance,
        "leg_instrument_ids": list(expected.leg_instrument_ids),
        "expected_positions": [
            {"instrument_id": item.instrument_id, "signed_quantity": str(item.signed_quantity)}
            for item in expected.expected_positions
        ],
    }
    assert expected.payload_sha256 == provider._hash_json(expected_payload)


def test_source_rehydration_prefers_hash_exact_original_when_local_copy_is_tampered(tmp_path):
    if not ORIGINAL_ROOT.is_dir():
        pytest.skip("read-only exact original S2 source root is not mounted")
    project_root = tmp_path / "project"
    scenario = project_root / "data" / "derived_scenario" / (
        "q25_a8_p2_recovered_track2_four_leg_quotes_v3_market_calibrated_r3_20261115"
    )
    scenario.mkdir(parents=True)
    (scenario / "manifest.json").write_bytes(
        (ORIGINAL_ROOT / "data" / "derived_scenario" / scenario.name / "manifest.json").read_bytes() + b"\n"
    )
    profile = project_root / "config" / "validation_only" / "track2"
    profile.mkdir(parents=True)
    profile_source = Path(__file__).resolve().parents[3] / "config" / "validation_only" / "track2" / "synthetic_scenario_profile.market_calibrated.v2.json"
    profile.joinpath(profile_source.name).write_bytes(profile_source.read_bytes())

    provider = _provider(project_root, source_roots=(ORIGINAL_ROOT,))
    evidence = provider.build_option_identity_evidence()

    assert len(evidence) == 4
    assert provider.last_source_resolution["scenario_manifest"] == "ORIGINAL_SOURCE_ROOT:0"
    assert provider.last_source_resolution["quotes"] == "ORIGINAL_SOURCE_ROOT:0"
    assert provider.last_source_resolution["profile"] == "PROJECT_ROOT"


def test_source_rehydration_does_not_accept_hash_mismatch_without_exact_alternative(tmp_path):
    if not ORIGINAL_ROOT.is_dir():
        pytest.skip("read-only exact original S2 source root is not mounted")
    project_root = tmp_path / "project"
    scenario_name = "q25_a8_p2_recovered_track2_four_leg_quotes_v3_market_calibrated_r3_20261115"
    source = ORIGINAL_ROOT
    files = {
        "accepted_manifest": ("data/accepted_market_data/runtime_v2/manifest.json", "data/accepted_market_data/runtime_v2/manifest.json"),
        "scenario_manifest": (f"data/derived_scenario/{scenario_name}/manifest.json", f"data/derived_scenario/{scenario_name}/manifest.json"),
        "quotes": (f"data/derived_scenario/{scenario_name}/four_leg_quotes.jsonl", f"data/derived_scenario/{scenario_name}/four_leg_quotes.jsonl"),
        "candidate_inputs": (f"data/derived_scenario/{scenario_name}/candidate_inputs.json", f"data/derived_scenario/{scenario_name}/candidate_inputs.json"),
        "profile": ("config/validation_only/track2/synthetic_scenario_profile.market_calibrated.v2.json", "config/validation_only/track2/synthetic_scenario_profile.market_calibrated.v2.json"),
    }
    for _, (relative, _) in files.items():
        target = project_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((source / relative).read_bytes())
    quote_path = project_root / files["quotes"][0]
    quote_path.write_bytes(quote_path.read_bytes() + b"\n")

    provider = _provider(project_root)
    try:
        provider.build_option_identity_evidence()
    except ValueError as exc:
        assert str(exc).startswith("T7_SOURCE_HASH_MISMATCH:quotes:")
    else:
        raise AssertionError("Modified source was accepted without a hash-exact alternative")


def test_source_rehydration_reports_missing_source_separately_from_hash_mismatch(tmp_path):
    provider = _provider(tmp_path / "empty-project")
    try:
        provider.build_option_identity_evidence()
    except FileNotFoundError as exc:
        assert str(exc).startswith("T7_SOURCE_FILE_MISSING:accepted_manifest")
    else:
        raise AssertionError("Missing source was not reported")


def test_source_rehydration_resolves_missing_manifest_partitions_from_original_root(tmp_path):
    if not ORIGINAL_ROOT.is_dir():
        raise AssertionError("Read-only exact original source root is required for this validation test")
    project_root = tmp_path / "project"
    accepted_manifest = project_root / "data" / "accepted_market_data" / "runtime_v2" / "manifest.json"
    accepted_manifest.parent.mkdir(parents=True)
    accepted_manifest.write_bytes(
        (ORIGINAL_ROOT / "data" / "accepted_market_data" / "runtime_v2" / "manifest.json").read_bytes()
    )
    profile = project_root / "config" / "validation_only" / "track2"
    profile.mkdir(parents=True)
    profile_source = Path(__file__).resolve().parents[3] / "config" / "validation_only" / "track2" / "synthetic_scenario_profile.market_calibrated.v2.json"
    profile.joinpath(profile_source.name).write_bytes(profile_source.read_bytes())

    provider = _provider(project_root, source_roots=(ORIGINAL_ROOT,))
    evidence = provider.build_option_identity_evidence()

    assert len(evidence) == 4
    assert provider.last_source_resolution["accepted_manifest"] == "PROJECT_ROOT"
    assert provider.last_source_resolution["accepted_partition:20261012"] == "ORIGINAL_SOURCE_ROOT:0"
    assert provider.last_source_resolution["accepted_partition:20261013"] == "ORIGINAL_SOURCE_ROOT:0"


@pytest.mark.parametrize(
    ("tamper", "expected_error"),
    (
        ("candidate_id", "T7_S2_IDENTITY_CANDIDATE_ID_MISMATCH"),
        ("quote_candidate_id", "T7_S2_IDENTITY_CANDIDATE_ID_MISMATCH:inner_put"),
        ("candidate_role", "T7_S2_IDENTITY_ROLE_OR_INSTRUMENT_SET_MISMATCH"),
        ("duplicate_role", "T7_S2_IDENTITY_ROLE_OR_INSTRUMENT_SET_MISMATCH"),
        ("duplicate_instrument", "T7_S2_IDENTITY_ROLE_OR_INSTRUMENT_SET_MISMATCH"),
        ("authority", "T7_S2_IDENTITY_AUTHORITY_NOT_VALIDATION_ONLY:inner_put"),
        ("source", "T7_S2_IDENTITY_AUTHORITY_NOT_VALIDATION_ONLY:inner_put"),
        ("multiplier_provenance", "T7_S2_IDENTITY_AUTHORITY_NOT_VALIDATION_ONLY:inner_put"),
        ("option_type", "T7_S2_IDENTITY_CONTRACT_FIELDS_MISMATCH:inner_put"),
        ("strike", "T7_S2_IDENTITY_CONTRACT_FIELDS_MISMATCH:inner_put"),
        ("expiry", "T7_S2_IDENTITY_CONTRACT_FIELDS_MISMATCH:inner_put"),
        ("multiplier", "T7_S2_IDENTITY_CONTRACT_FIELDS_MISMATCH:inner_put"),
        ("malformed_multiplier", "T7_S2_IDENTITY_CONTRACT_FIELDS_INVALID:inner_put"),
        ("instrument_id", "T7_S2_IDENTITY_CONTRACT_FIELDS_MISMATCH:inner_put"),
    ),
)
def test_hash_verified_source_with_in_memory_candidate_or_leg_crosswalk_tamper_is_rejected_before_u19_build(
    tamper, expected_error
):
    if not ORIGINAL_ROOT.is_dir():
        pytest.skip("read-only exact original S2 source root is not mounted")

    class _CaptureVssf:
        calls = 0

        def build_candidate(self, **kwargs):
            self.calls += 1
            return kwargs

    class _TamperedProvider(ValidationOnlyS2ScenarioAlternativeProvider):
        def _load_verified_sources(self):
            manifest, candidate, profile, quotes, hashes = super()._load_verified_sources()
            if tamper == "candidate_id":
                candidate["candidate_id"] = "S2-CANDIDATE-OTHER"
            elif tamper == "quote_candidate_id":
                quotes[0]["candidate_id"] = "S2-CANDIDATE-OTHER"
            elif tamper == "candidate_role":
                candidate["legs"][0]["role"] = "unknown_role"
            elif tamper == "duplicate_role":
                quotes[1]["leg_role"] = quotes[0]["leg_role"]
            elif tamper == "duplicate_instrument":
                quotes[1]["instrument_id"] = quotes[0]["instrument_id"]
            elif tamper == "authority":
                quotes[0]["contract_identity_authority"] = "KIS_MASTER"
            elif tamper == "source":
                quotes[0]["source"] = "KIS:OPTION"
            elif tamper == "multiplier_provenance":
                quotes[0]["contract_multiplier_provenance"] = ""
            elif tamper == "option_type":
                quotes[0]["option_type"] = "CALL"
            elif tamper == "strike":
                quotes[0]["strike"] = str(Decimal(str(quotes[0]["strike"])) + Decimal("50"))
            elif tamper == "expiry":
                quotes[0]["expiry"] = "20261210"
            elif tamper == "multiplier":
                quotes[0]["contract_multiplier"] = "0"
            elif tamper == "malformed_multiplier":
                quotes[0]["contract_multiplier"] = "not-a-number"
            elif tamper == "instrument_id":
                quotes[0]["instrument_id"] = "KIS:NOT-A-SYNTHETIC-ID"
            return manifest, candidate, profile, quotes, hashes

    capture = _CaptureVssf()
    provider = _TamperedProvider(
        project_root=Path(__file__).resolve().parents[3],
        run_id="S2-IDENTITY-TAMPER-MATRIX",
        vssf_adapter=capture,
        source_roots=(ORIGINAL_ROOT,),
    )
    tick = SimpleNamespace(
        timestamp="2026-10-12T09:26:00+09:00",
        underlying_price=1034.62,
    )

    with pytest.raises(ValueError, match=expected_error):
        provider(tick)
    assert capture.calls == 0
