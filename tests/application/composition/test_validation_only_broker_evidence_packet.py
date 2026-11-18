from datetime import datetime, timezone

import pytest

from application.composition.validation_only_broker_evidence_packet import (
    ValidationOnlyBrokerEvidencePacketValidator,
)


AS_OF = datetime(2026, 11, 18, 7, 0, tzinfo=timezone.utc)


def packet():
    return {
        "packet_id": "FRESH43-PACKET-001",
        "source_namespace": "VALIDATION_ONLY:SYNTHETIC:FRESH43",
        "provider_ref": "VALIDATION_ONLY:SOURCE_FIXTURE",
        "source_as_of": "2026-11-18T06:55:00+00:00",
        "collected_at": "2026-11-18T06:56:00+00:00",
        "snapshots": {
            "orders": {"snapshot_id": "ORDERS-1", "payload_sha256": "a" * 64, "complete": True},
            "executions": {"snapshot_id": "EXECUTIONS-1", "payload_sha256": "b" * 64, "complete": True},
            "positions": {"snapshot_id": "POSITIONS-1", "payload_sha256": "c" * 64, "complete": True},
        },
        "identity_crosswalk": [{
            "source_identity": {"source_order_ref": "SRC-ORDER-1", "source_execution_ref": "SRC-EXEC-1"},
            "internal_identity": {"client_order_id": "SYNTHETIC:CLIENT-1", "execution_id": "SYNTHETIC:EXEC-1"},
            "evidence_ref": "VALIDATION_ONLY:CROSSWALK:1",
        }],
        "conflict_links": [{
            "execution_id": "SYNTHETIC:EXEC-1",
            "scope_key": "__runtime_bootstrap__",
            "original_payload_sha256": "d" * 64,
            "incoming_payload_sha256": "e" * 64,
            "source_record_refs": ["SRC-EXEC-1", "SRC-ORDER-1"],
        }],
    }


def validator():
    return ValidationOnlyBrokerEvidencePacketValidator(validation_only=True)


def test_valid_packet_builds_deterministic_manifest_without_authority_or_gate_release():
    first = validator().validate(packet=packet(), as_of=AS_OF)
    second = validator().validate(packet=packet(), as_of=AS_OF)
    assert first.is_valid
    assert first.manifest_sha256 == second.manifest_sha256
    assert first.gate_release_permitted is False
    assert first.authoritative is False
    assert first.mutation_applied is False
    assert first.manifest["authority_claimed"] is False


def test_validator_requires_explicit_validation_only_opt_in():
    with pytest.raises(ValueError, match="BROKER_EVIDENCE_PACKET_VALIDATION_ONLY_OPT_IN_REQUIRED"):
        ValidationOnlyBrokerEvidencePacketValidator()


def test_missing_incomplete_snapshot_and_duplicate_ids_require_reconciliation():
    value = packet()
    value["snapshots"]["executions"]["complete"] = False
    value["snapshots"]["positions"]["snapshot_id"] = "ORDERS-1"
    result = validator().validate(packet=value, as_of=AS_OF)
    assert result.status == "RECONCILIATION_REQUIRED"
    assert "BROKER_EVIDENCE_EXECUTIONS_SNAPSHOT_COMPLETENESS_UNVERIFIED" in result.issues
    assert "BROKER_EVIDENCE_SNAPSHOT_IDS_NOT_DISTINCT" in result.issues
    assert result.gate_release_permitted is False


def test_future_source_anchor_and_collection_after_as_of_are_rejected():
    value = packet()
    value["source_as_of"] = "2026-11-18T07:03:00+00:00"
    value["collected_at"] = "2026-11-18T07:02:00+00:00"
    result = validator().validate(packet=value, as_of=AS_OF)
    assert result.status == "RECONCILIATION_REQUIRED"
    assert "BROKER_EVIDENCE_SOURCE_AS_OF_AFTER_COLLECTION" in result.issues
    assert "BROKER_EVIDENCE_COLLECTION_AFTER_VALIDATION_AS_OF" in result.issues


def test_timezone_naive_source_time_is_not_accepted():
    value = packet()
    value["source_as_of"] = "2026-11-18T06:55:00"
    result = validator().validate(packet=value, as_of=AS_OF)
    assert result.status == "RECONCILIATION_REQUIRED"
    assert "SOURCE_AS_OF_TIMEZONE_REQUIRED" in result.issues


def test_missing_identity_crosswalk_and_conflict_linkage_require_reconciliation():
    value = packet()
    value["identity_crosswalk"] = []
    value["conflict_links"][0]["source_record_refs"] = []
    result = validator().validate(packet=value, as_of=AS_OF)
    assert result.status == "RECONCILIATION_REQUIRED"
    assert "BROKER_EVIDENCE_IDENTITY_CROSSWALK_REQUIRED" in result.issues
    assert "BROKER_EVIDENCE_CONFLICT_SOURCE_RECORD_REFS_REQUIRED:0" in result.issues


def test_non_validation_namespace_never_becomes_authoritative():
    value = packet()
    value["source_namespace"] = "KIS_LIVE"
    result = validator().validate(packet=value, as_of=AS_OF)
    assert result.status == "RECONCILIATION_REQUIRED"
    assert "BROKER_EVIDENCE_VALIDATION_ONLY_NAMESPACE_REQUIRED" in result.issues
    assert result.authoritative is False
    assert result.gate_release_permitted is False


def test_duplicate_conflict_links_and_invalid_payload_hashes_are_rejected():
    value = packet()
    value["conflict_links"].append(dict(value["conflict_links"][0]))
    value["conflict_links"][0]["incoming_payload_sha256"] = "not-a-hash"
    result = validator().validate(packet=value, as_of=AS_OF)
    assert result.status == "RECONCILIATION_REQUIRED"
    assert any(issue.startswith("BROKER_EVIDENCE_CONFLICT_PAYLOAD_HASH_INVALID") for issue in result.issues)
    assert any(issue.startswith("BROKER_EVIDENCE_CONFLICT_LINK_DUPLICATE") for issue in result.issues)
