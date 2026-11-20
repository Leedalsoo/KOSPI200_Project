from dataclasses import replace
from decimal import Decimal

from application.composition.validation_only_account_snapshot_u19_reconciler import (
    _compose_account_expected_group_manifest,
)
from core.oms.track2_u19_recovery import (
    U19ExpectedGroupManifest,
    U19Position,
    _expected_group_manifest_digest,
)


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
