import shutil
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from application.composition.validation_only_account_snapshot_u19_reconciler import (
    _compose_account_expected_group_manifest,
)
from application.composition.track2_u19_recovery import ValidationOnlyTrack2U19RecoveryCoordinator
from application.composition.validation_only_s2_scenario_alternative_provider import (
    ValidationOnlyS2ScenarioAlternativeProvider,
)
from core.oms.track2_u19_recovery import (
    U19BrokerPositionSnapshot,
    U19ExecutionLedgerSnapshot,
    U19ExpectedGroupManifest,
    U19Position,
    U19RecoveryStatus,
    _expected_group_manifest_digest,
)
from environments.virtual.position.track2_u19_recovery_store import SqliteTrack2U19RecoveryStore


def _child(group_id: str, instrument_id: str, identity_digest: str):
    manifest = U19ExpectedGroupManifest(
        group_id=group_id,
        manifest_id=f"SYNTHETIC:{group_id}",
        source="VALIDATION_ONLY:EXPECTED_GROUP_MANIFEST",
        provenance=f"VALIDATION_ONLY:S2:IDENTITY_REGISTRY={identity_digest}",
        leg_instrument_ids=(instrument_id,),
        expected_positions=(U19Position(instrument_id, Decimal("1")),),
        payload_sha256="0" * 64,
    )
    return replace(manifest, payload_sha256=_expected_group_manifest_digest(manifest))


def _aggregate(children):
    return _compose_account_expected_group_manifest(
        group_manifests=tuple(children),
        group_ids=("GROUP-A", "GROUP-B"),
        aggregate_group_id="SYNTHETIC:ACCOUNT:IDENTITY-REGISTRY-TEST",
        opening_positions=(),
        opening_evidence_sha256="a" * 64,
    )


def test_account_aggregate_digest_binds_child_identity_registry_digests_and_is_order_independent():
    child_a = _child("GROUP-A", "SYNTHETIC:OPTION:A", "1" * 64)
    child_b = _child("GROUP-B", "SYNTHETIC:OPTION:B", "2" * 64)

    baseline = _aggregate((child_a, child_b))
    reversed_children = _aggregate((child_b, child_a))
    changed_identity = _aggregate((_child("GROUP-A", "SYNTHETIC:OPTION:A", "3" * 64), child_b))

    assert baseline is not None
    assert reversed_children is not None
    assert changed_identity is not None
    assert baseline.payload_sha256 == reversed_children.payload_sha256
    assert baseline.provenance == reversed_children.provenance
    assert baseline.payload_sha256 != changed_identity.payload_sha256
    assert baseline.provenance != changed_identity.provenance


def test_account_aggregate_rejects_child_payload_tamper_duplicate_and_missing_groups():
    child_a = _child("GROUP-A", "SYNTHETIC:OPTION:A", "1" * 64)
    child_b = _child("GROUP-B", "SYNTHETIC:OPTION:B", "2" * 64)

    tampered = replace(child_a, provenance=child_a.provenance + ":TAMPERED")
    duplicate = replace(child_b, group_id="GROUP-A")

    assert _aggregate((tampered, child_b)) is None
    assert _aggregate((child_a, duplicate)) is None
    assert _aggregate((child_a,)) is None


def test_identity_registry_digest_reaches_recovery_checkpoint_and_restart_replay(tmp_path):
    as_of = datetime(2026, 11, 20, 9, 30, tzinfo=timezone.utc)
    children = (
        _child("GROUP-A", "SYNTHETIC:OPTION:A", "1" * 64),
        _child("GROUP-B", "SYNTHETIC:OPTION:B", "2" * 64),
    )
    aggregate = _aggregate(children)
    changed_aggregate = _aggregate((
        _child("GROUP-A", "SYNTHETIC:OPTION:A", "3" * 64),
        children[1],
    ))
    assert aggregate is not None and changed_aggregate is not None
    positions = aggregate.expected_positions
    broker = U19BrokerPositionSnapshot(
        group_id=aggregate.group_id,
        snapshot_id="SYNTHETIC:AGGREGATE:BROKER",
        as_of=as_of,
        source="VALIDATION_ONLY:BROKER_EXCHANGE",
        positions=positions,
        complete=True,
        capability_verified=True,
        payload_sha256="b" * 64,
    )
    ledger = U19ExecutionLedgerSnapshot(
        group_id=aggregate.group_id,
        snapshot_id="SYNTHETIC:AGGREGATE:LEDGER",
        as_of=as_of,
        source="VALIDATION_ONLY:EXECUTION_LEDGER",
        positions=positions,
        complete=True,
        payload_sha256="c" * 64,
    )
    path = tmp_path / "u19-identity-checkpoint.sqlite3"
    store = SqliteTrack2U19RecoveryStore(path)
    coordinator = ValidationOnlyTrack2U19RecoveryCoordinator(
        store, require_expected_group_manifest=True
    )

    first = coordinator.recover(
        group_id=aggregate.group_id,
        broker_snapshot=broker,
        ledger_snapshot=ledger,
        expected_group_manifest=aggregate,
    )
    assert first.status is U19RecoveryStatus.RESTORE_ALLOWED
    checkpoint = store.load_latest(aggregate.group_id)
    assert checkpoint["expected_group_manifest_id"] == aggregate.manifest_id
    assert checkpoint["expected_group_manifest_sha256"] == aggregate.payload_sha256
    assert checkpoint["expected_group_manifest_sha256"] != changed_aggregate.payload_sha256

    restarted_store = SqliteTrack2U19RecoveryStore(path)
    restarted = ValidationOnlyTrack2U19RecoveryCoordinator(
        restarted_store, require_expected_group_manifest=True
    ).recover(
        group_id=aggregate.group_id,
        broker_snapshot=broker,
        ledger_snapshot=ledger,
        expected_group_manifest=aggregate,
    )
    assert restarted.checkpoint_id == first.checkpoint_id
    assert restarted_store.load_latest(aggregate.group_id)["expected_group_manifest_sha256"] == aggregate.payload_sha256

    changed = ValidationOnlyTrack2U19RecoveryCoordinator(
        restarted_store, require_expected_group_manifest=True
    ).recover(
        group_id=changed_aggregate.group_id,
        broker_snapshot=broker,
        ledger_snapshot=ledger,
        expected_group_manifest=changed_aggregate,
    )
    assert changed.status is U19RecoveryStatus.RESTORE_ALLOWED
    assert changed.expected_group_manifest_sha256 == changed_aggregate.payload_sha256
    assert changed.checkpoint_id != first.checkpoint_id


def test_source_sidecar_hash_change_after_checkpoint_does_not_advance_recovery(tmp_path):
    original_root = Path(__file__).resolve().parents[3].parent / "Q25_A8_R10"
    if not original_root.is_dir():
        raise AssertionError("Read-only exact original source root is required for this validation test")
    source_root = tmp_path / "original-source"
    relative_files = (
        "data/accepted_market_data/runtime_v2/manifest.json",
        "data/accepted_market_data/runtime_v2/20261012.jsonl",
        "data/accepted_market_data/runtime_v2/20261013.jsonl",
        "data/derived_scenario/q25_a8_p2_recovered_track2_four_leg_quotes_v3_market_calibrated_r3_20261115/manifest.json",
        "data/derived_scenario/q25_a8_p2_recovered_track2_four_leg_quotes_v3_market_calibrated_r3_20261115/four_leg_quotes.jsonl",
        "data/derived_scenario/q25_a8_p2_recovered_track2_four_leg_quotes_v3_market_calibrated_r3_20261115/candidate_inputs.json",
        "config/validation_only/track2/synthetic_scenario_profile.market_calibrated.v2.json",
    )
    for relative in relative_files:
        target = source_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original_root / relative, target)
        target.chmod(0o666)

    provider = ValidationOnlyS2ScenarioAlternativeProvider(
        project_root=tmp_path / "empty-project",
        run_id="SYNTHETIC:U19:SOURCE-RESTART-GATE",
        vssf_adapter=object(),
        source_roots=(source_root,),
    )
    evidence = provider.build_option_identity_evidence()
    registry_digest = provider._hash_json([
        {"leg_role": item.leg_role, "derived_identity_digest": item.derived_identity_digest}
        for item in evidence
    ])
    child_a = _child("GROUP-A", evidence[0].identity.instrument_id, registry_digest)
    child_b = _child("GROUP-B", "SYNTHETIC:OPTION:B", "2" * 64)
    aggregate = _aggregate((child_a, child_b))
    assert aggregate is not None

    as_of = datetime(2026, 11, 20, 9, 30, tzinfo=timezone.utc)
    positions = aggregate.expected_positions
    broker = U19BrokerPositionSnapshot(
        group_id=aggregate.group_id,
        snapshot_id="SYNTHETIC:SOURCE-GATE:BROKER",
        as_of=as_of,
        source="VALIDATION_ONLY:BROKER_EXCHANGE",
        positions=positions,
        complete=True,
        capability_verified=True,
        payload_sha256="d" * 64,
    )
    ledger = U19ExecutionLedgerSnapshot(
        group_id=aggregate.group_id,
        snapshot_id="SYNTHETIC:SOURCE-GATE:LEDGER",
        as_of=as_of,
        source="VALIDATION_ONLY:EXECUTION_LEDGER",
        positions=positions,
        complete=True,
        payload_sha256="e" * 64,
    )
    store = SqliteTrack2U19RecoveryStore(tmp_path / "u19-source-gate.sqlite3")
    coordinator = ValidationOnlyTrack2U19RecoveryCoordinator(
        store, require_expected_group_manifest=True
    )
    decision = coordinator.recover(
        group_id=aggregate.group_id,
        broker_snapshot=broker,
        ledger_snapshot=ledger,
        expected_group_manifest=aggregate,
    )
    assert decision.status is U19RecoveryStatus.RESTORE_ALLOWED
    checkpoint_before = store.load_latest(aggregate.group_id)

    quote_path = source_root / relative_files[4]
    quote_path.write_bytes(quote_path.read_bytes() + b"\n")
    restarted_provider = ValidationOnlyS2ScenarioAlternativeProvider(
        project_root=tmp_path / "empty-project",
        run_id="SYNTHETIC:U19:SOURCE-RESTART-GATE",
        vssf_adapter=object(),
        source_roots=(source_root,),
    )
    try:
        restarted_provider.build_option_identity_evidence()
    except ValueError as exc:
        assert str(exc).startswith("T7_SOURCE_HASH_MISMATCH:quotes:")
    else:
        raise AssertionError("Changed sidecar hash was accepted after restart")

    assert store.load_latest(aggregate.group_id) == checkpoint_before


def test_rehydration_from_different_source_roots_reproduces_same_u19_checkpoint(tmp_path):
    original_root = Path(__file__).resolve().parents[3].parent / "Q25_A8_R10"
    if not original_root.is_dir():
        raise AssertionError("Read-only exact original S2 source root is required for this validation test")
    relative_files = (
        "data/accepted_market_data/runtime_v2/manifest.json",
        "data/accepted_market_data/runtime_v2/20261012.jsonl",
        "data/accepted_market_data/runtime_v2/20261013.jsonl",
        "data/derived_scenario/q25_a8_p2_recovered_track2_four_leg_quotes_v3_market_calibrated_r3_20261115/manifest.json",
        "data/derived_scenario/q25_a8_p2_recovered_track2_four_leg_quotes_v3_market_calibrated_r3_20261115/four_leg_quotes.jsonl",
        "data/derived_scenario/q25_a8_p2_recovered_track2_four_leg_quotes_v3_market_calibrated_r3_20261115/candidate_inputs.json",
        "config/validation_only/track2/synthetic_scenario_profile.market_calibrated.v2.json",
    )
    source_roots = (tmp_path / "source-root-a", tmp_path / "source-root-b")
    for root in source_roots:
        for relative in relative_files:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original_root / relative, target)

    provider_a = ValidationOnlyS2ScenarioAlternativeProvider(
        project_root=source_roots[0],
        run_id="SYNTHETIC:U19:ROOT-INDEPENDENT-REPLAY",
        vssf_adapter=object(),
    )
    provider_b = ValidationOnlyS2ScenarioAlternativeProvider(
        project_root=tmp_path / "empty-project-b",
        run_id="SYNTHETIC:U19:ROOT-INDEPENDENT-REPLAY",
        vssf_adapter=object(),
        source_roots=(source_roots[1],),
    )
    evidence_a = provider_a.build_option_identity_evidence()
    evidence_b = provider_b.build_option_identity_evidence()
    registry_a = provider_a._hash_json([
        {"leg_role": item.leg_role, "derived_identity_digest": item.derived_identity_digest}
        for item in evidence_a
    ])
    registry_b = provider_b._hash_json([
        {"leg_role": item.leg_role, "derived_identity_digest": item.derived_identity_digest}
        for item in evidence_b
    ])
    assert registry_a == registry_b
    assert provider_a.last_source_resolution["scenario_manifest"] == "PROJECT_ROOT"
    assert provider_b.last_source_resolution["scenario_manifest"] == "ORIGINAL_SOURCE_ROOT:0"

    child_a1 = _child("GROUP-A", evidence_a[0].identity.instrument_id, registry_a)
    child_b1 = _child("GROUP-B", evidence_a[1].identity.instrument_id, "2" * 64)
    child_a2 = _child("GROUP-A", evidence_b[0].identity.instrument_id, registry_b)
    child_b2 = _child("GROUP-B", evidence_b[1].identity.instrument_id, "2" * 64)
    aggregate_a = _aggregate((child_a1, child_b1))
    aggregate_b = _aggregate((child_a2, child_b2))
    assert aggregate_a is not None and aggregate_b is not None
    assert aggregate_a.payload_sha256 == aggregate_b.payload_sha256
    assert aggregate_a.manifest_id == aggregate_b.manifest_id

    as_of = datetime(2026, 11, 20, 9, 30, tzinfo=timezone.utc)
    positions = aggregate_a.expected_positions
    broker = U19BrokerPositionSnapshot(
        group_id=aggregate_a.group_id,
        snapshot_id="SYNTHETIC:ROOT-INDEPENDENT:BROKER",
        as_of=as_of,
        source="VALIDATION_ONLY:BROKER_EXCHANGE",
        positions=positions,
        complete=True,
        capability_verified=True,
        payload_sha256="f" * 64,
    )
    ledger = U19ExecutionLedgerSnapshot(
        group_id=aggregate_a.group_id,
        snapshot_id="SYNTHETIC:ROOT-INDEPENDENT:LEDGER",
        as_of=as_of,
        source="VALIDATION_ONLY:EXECUTION_LEDGER",
        positions=positions,
        complete=True,
        payload_sha256="0" * 64,
    )
    path = tmp_path / "u19-root-independent.sqlite3"
    first_store = SqliteTrack2U19RecoveryStore(path)
    first = ValidationOnlyTrack2U19RecoveryCoordinator(
        first_store, require_expected_group_manifest=True
    ).recover(
        group_id=aggregate_a.group_id,
        broker_snapshot=broker,
        ledger_snapshot=ledger,
        expected_group_manifest=aggregate_a,
    )
    assert first.status is U19RecoveryStatus.RESTORE_ALLOWED

    restarted_store = SqliteTrack2U19RecoveryStore(path)
    replay = ValidationOnlyTrack2U19RecoveryCoordinator(
        restarted_store, require_expected_group_manifest=True
    ).recover(
        group_id=aggregate_b.group_id,
        broker_snapshot=broker,
        ledger_snapshot=ledger,
        expected_group_manifest=aggregate_b,
    )
    assert replay.checkpoint_id == first.checkpoint_id
    assert replay.expected_group_manifest_sha256 == first.expected_group_manifest_sha256
    assert restarted_store.load_latest(aggregate_b.group_id)["expected_group_manifest_sha256"] == aggregate_b.payload_sha256


def test_cross_candidate_child_digest_reuse_changes_account_checkpoint_identity(tmp_path):
    original_root = Path(__file__).resolve().parents[3].parent / "Q25_A8_R10"
    if not original_root.is_dir():
        raise AssertionError("Read-only exact original S2 source root is required for this validation test")

    candidate_children = []
    candidate_digests = {}
    for candidate_id, group_id in (
        ("S2-CANDIDATE-001", "GROUP-A"),
        ("S2-CANDIDATE-002", "GROUP-B"),
    ):
        provider = ValidationOnlyS2ScenarioAlternativeProvider(
            project_root=Path(__file__).resolve().parents[3],
            run_id=f"SYNTHETIC:CROSS-CANDIDATE:{candidate_id}",
            vssf_adapter=object(),
            candidate_id=candidate_id,
            source_roots=(original_root,),
        )
        evidence = provider.build_option_identity_evidence()
        registry_digest = provider._hash_json([
            {"leg_role": item.leg_role, "derived_identity_digest": item.derived_identity_digest}
            for item in evidence
        ])
        candidate_digests[candidate_id] = registry_digest
        positions = tuple(
            U19Position(
                item.identity.instrument_id,
                Decimal("1") if item.leg_role in {"inner_put", "inner_call"} else Decimal("-1"),
            )
            for item in evidence
        )
        manifest = U19ExpectedGroupManifest(
            group_id=group_id,
            manifest_id=f"{candidate_id}:POST_ENTRY:2026-10-12T09:26:00+09:00",
            source="VALIDATION_ONLY:EXPECTED_GROUP_MANIFEST",
            provenance=f"VALIDATION_ONLY:S2:CANDIDATE={candidate_id}:IDENTITY_REGISTRY={registry_digest}",
            leg_instrument_ids=tuple(sorted(item.identity.instrument_id for item in evidence)),
            expected_positions=tuple(sorted(positions, key=lambda item: item.instrument_id)),
            payload_sha256="0" * 64,
        )
        candidate_children.append(
            replace(manifest, payload_sha256=_expected_group_manifest_digest(manifest))
        )

    assert candidate_digests["S2-CANDIDATE-001"] != candidate_digests["S2-CANDIDATE-002"]
    child_a, child_b = candidate_children
    aggregate = _compose_account_expected_group_manifest(
        group_manifests=(child_a, child_b),
        group_ids=("GROUP-A", "GROUP-B"),
        aggregate_group_id="SYNTHETIC:ACCOUNT:CROSS-CANDIDATE",
        opening_positions=(),
        opening_evidence_sha256="a" * 64,
    )
    assert aggregate is not None

    reused_child_b = replace(
        child_b,
        provenance=child_b.provenance.replace(
            candidate_digests["S2-CANDIDATE-002"],
            candidate_digests["S2-CANDIDATE-001"],
        ),
        payload_sha256="0" * 64,
    )
    reused_child_b = replace(
        reused_child_b,
        payload_sha256=_expected_group_manifest_digest(reused_child_b),
    )
    reused_aggregate = _compose_account_expected_group_manifest(
        group_manifests=(child_a, reused_child_b),
        group_ids=("GROUP-A", "GROUP-B"),
        aggregate_group_id="SYNTHETIC:ACCOUNT:CROSS-CANDIDATE",
        opening_positions=(),
        opening_evidence_sha256="a" * 64,
    )
    assert reused_aggregate is not None
    assert reused_aggregate.payload_sha256 != aggregate.payload_sha256

    as_of = datetime(2026, 11, 20, 9, 30, tzinfo=timezone.utc)
    broker = U19BrokerPositionSnapshot(
        group_id=aggregate.group_id,
        snapshot_id="SYNTHETIC:CROSS-CANDIDATE:BROKER",
        as_of=as_of,
        source="VALIDATION_ONLY:BROKER_EXCHANGE",
        positions=aggregate.expected_positions,
        complete=True,
        capability_verified=True,
        payload_sha256="a" * 64,
    )
    ledger = U19ExecutionLedgerSnapshot(
        group_id=aggregate.group_id,
        snapshot_id="SYNTHETIC:CROSS-CANDIDATE:LEDGER",
        as_of=as_of,
        source="VALIDATION_ONLY:EXECUTION_LEDGER",
        positions=aggregate.expected_positions,
        complete=True,
        payload_sha256="b" * 64,
    )
    path = tmp_path / "u19-cross-candidate.sqlite3"
    store = SqliteTrack2U19RecoveryStore(path)
    coordinator = ValidationOnlyTrack2U19RecoveryCoordinator(
        store, require_expected_group_manifest=True
    )
    correct = coordinator.recover(
        group_id=aggregate.group_id,
        broker_snapshot=broker,
        ledger_snapshot=ledger,
        expected_group_manifest=aggregate,
    )
    assert correct.status is U19RecoveryStatus.RESTORE_ALLOWED

    restarted_store = SqliteTrack2U19RecoveryStore(path)
    restarted_coordinator = ValidationOnlyTrack2U19RecoveryCoordinator(
        restarted_store, require_expected_group_manifest=True
    )
    reused = restarted_coordinator.recover(
        group_id=reused_aggregate.group_id,
        broker_snapshot=broker,
        ledger_snapshot=ledger,
        expected_group_manifest=reused_aggregate,
    )
    assert reused.status is U19RecoveryStatus.RESTORE_ALLOWED
    assert reused.checkpoint_id != correct.checkpoint_id
    assert reused.expected_group_manifest_sha256 != correct.expected_group_manifest_sha256

    correct_replay = ValidationOnlyTrack2U19RecoveryCoordinator(
        SqliteTrack2U19RecoveryStore(path), require_expected_group_manifest=True
    ).recover(
        group_id=aggregate.group_id,
        broker_snapshot=broker,
        ledger_snapshot=ledger,
        expected_group_manifest=aggregate,
    )
    assert correct_replay.checkpoint_id == correct.checkpoint_id
    assert correct_replay.expected_group_manifest_sha256 == aggregate.payload_sha256


def test_same_run_id_multiple_candidates_have_distinct_u19_group_and_checkpoint_keys(tmp_path):
    original_root = Path(__file__).resolve().parents[3].parent / "Q25_A8_R10"
    if not original_root.is_dir():
        raise AssertionError("Read-only exact original S2 source root is required for this validation test")

    class _CaptureVssf:
        def build_candidate(self, **kwargs):
            self.kwargs = kwargs
            return kwargs

    run_id = "SYNTHETIC:SAME-RUN:MULTI-CANDIDATE"
    captures = {}
    manifests = {}
    for candidate_id in ("S2-CANDIDATE-001", "S2-CANDIDATE-002"):
        capture = _CaptureVssf()
        provider = ValidationOnlyS2ScenarioAlternativeProvider(
            project_root=Path(__file__).resolve().parents[3],
            run_id=run_id,
            vssf_adapter=capture,
            candidate_id=candidate_id,
            source_roots=(original_root,),
        )
        _source_manifest, candidate, _profile, _quotes, _hashes = provider._load_verified_sources()
        provider(SimpleNamespace(
            timestamp=candidate["observed_at"],
            underlying_price=candidate["underlying_price"],
        ))
        captures[candidate_id] = capture
        manifests[candidate_id] = capture.kwargs["expected_group_manifest"]

    manifest_a = manifests["S2-CANDIDATE-001"]
    manifest_b = manifests["S2-CANDIDATE-002"]
    assert manifest_a.group_id != manifest_b.group_id
    assert manifest_a.manifest_id != manifest_b.manifest_id

    store = SqliteTrack2U19RecoveryStore(tmp_path / "same-run-multi-candidate.sqlite3")
    coordinator = ValidationOnlyTrack2U19RecoveryCoordinator(
        store, require_expected_group_manifest=True
    )
    child_decisions = {}
    child_snapshots = {}
    for index, candidate_id in enumerate(("S2-CANDIDATE-001", "S2-CANDIDATE-002")):
        capture = captures[candidate_id]
        broker = capture.kwargs["broker_snapshot"]
        ledger = U19ExecutionLedgerSnapshot(
            group_id=broker.group_id,
            snapshot_id=f"SYNTHETIC:SAME-RUN:LEDGER:{candidate_id}",
            as_of=broker.as_of,
            source="VALIDATION_ONLY:EXECUTION_LEDGER",
            positions=broker.positions,
            complete=True,
            payload_sha256=f"{index + 1}" * 64,
        )
        decision = coordinator.recover(
            group_id=broker.group_id,
            broker_snapshot=broker,
            ledger_snapshot=ledger,
            expected_group_manifest=manifests[candidate_id],
        )
        assert decision.status in {U19RecoveryStatus.FLAT_CONFIRMED, U19RecoveryStatus.RESTORE_ALLOWED}
        child_decisions[candidate_id] = decision
        child_snapshots[candidate_id] = (broker, ledger)

    account_aggregate = _compose_account_expected_group_manifest(
        group_manifests=(manifest_a, manifest_b),
        group_ids=(manifest_a.group_id, manifest_b.group_id),
        aggregate_group_id=f"VALIDATION_ONLY:ACCOUNT:{run_id}",
        opening_positions=(),
        opening_evidence_sha256="f" * 64,
    )
    assert account_aggregate is not None
    account_as_of = datetime(2026, 11, 20, 9, 30, tzinfo=timezone.utc)
    account_broker = U19BrokerPositionSnapshot(
        group_id=account_aggregate.group_id,
        snapshot_id="SYNTHETIC:SAME-RUN:ACCOUNT:BROKER",
        as_of=account_as_of,
        source="VALIDATION_ONLY:BROKER_EXCHANGE",
        positions=account_aggregate.expected_positions,
        complete=True,
        capability_verified=True,
        payload_sha256="c" * 64,
    )
    account_ledger = U19ExecutionLedgerSnapshot(
        group_id=account_aggregate.group_id,
        snapshot_id="SYNTHETIC:SAME-RUN:ACCOUNT:LEDGER",
        as_of=account_as_of,
        source="VALIDATION_ONLY:EXECUTION_LEDGER",
        positions=account_aggregate.expected_positions,
        complete=True,
        payload_sha256="d" * 64,
    )
    account_decision = coordinator.recover(
        group_id=account_aggregate.group_id,
        broker_snapshot=account_broker,
        ledger_snapshot=account_ledger,
        expected_group_manifest=account_aggregate,
    )
    assert account_decision.status is U19RecoveryStatus.FLAT_CONFIRMED

    latest_a = store.load_latest(manifest_a.group_id)
    latest_b = store.load_latest(manifest_b.group_id)
    assert latest_a["expected_group_manifest_id"] == manifest_a.manifest_id
    assert latest_b["expected_group_manifest_id"] == manifest_b.manifest_id
    assert latest_a["checkpoint_id"] != latest_b["checkpoint_id"]
    latest_account = store.load_latest(account_aggregate.group_id)
    assert latest_account["expected_group_manifest_id"] == account_aggregate.manifest_id

    restarted_store = SqliteTrack2U19RecoveryStore(tmp_path / "same-run-multi-candidate.sqlite3")
    restarted = ValidationOnlyTrack2U19RecoveryCoordinator(
        restarted_store, require_expected_group_manifest=True
    )
    for candidate_id in ("S2-CANDIDATE-001", "S2-CANDIDATE-002"):
        broker, ledger = child_snapshots[candidate_id]
        replay = restarted.recover(
            group_id=broker.group_id,
            broker_snapshot=broker,
            ledger_snapshot=ledger,
            expected_group_manifest=manifests[candidate_id],
        )
        assert replay.checkpoint_id == child_decisions[candidate_id].checkpoint_id
    account_replay = restarted.recover(
        group_id=account_aggregate.group_id,
        broker_snapshot=account_broker,
        ledger_snapshot=account_ledger,
        expected_group_manifest=account_aggregate,
    )
    assert account_replay.checkpoint_id == account_decision.checkpoint_id
    assert restarted_store.load_latest(manifest_a.group_id)["expected_group_manifest_id"] == manifest_a.manifest_id
    assert restarted_store.load_latest(manifest_b.group_id)["expected_group_manifest_id"] == manifest_b.manifest_id
    assert restarted_store.load_latest(account_aggregate.group_id)["expected_group_manifest_id"] == account_aggregate.manifest_id
