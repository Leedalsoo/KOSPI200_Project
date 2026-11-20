from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

from application.composition.validation_only_account_snapshot_u19_reconciler import (
    _compose_account_expected_group_manifest,
)
from application.composition.track2_u19_recovery import ValidationOnlyTrack2U19RecoveryCoordinator
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
