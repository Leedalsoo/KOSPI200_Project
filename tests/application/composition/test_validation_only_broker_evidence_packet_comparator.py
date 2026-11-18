from copy import deepcopy
from datetime import datetime, timezone

import pytest

from application.composition.validation_only_broker_evidence_packet import (
    ValidationOnlyBrokerEvidencePacketValidator,
)
from application.composition.validation_only_broker_evidence_packet_comparator import (
    ValidationOnlyBrokerEvidencePacketComparator,
)


AS_OF = datetime(2026, 11, 18, 7, 0, tzinfo=timezone.utc)


def valid_packet(packet_id="PACKET-A"):
    return {
        "packet_id": packet_id,
        "source_namespace": "VALIDATION_ONLY:SYNTHETIC:FRESH46",
        "provider_ref": "VALIDATION_ONLY:SOURCE_FIXTURE",
        "source_as_of": "2026-11-18T06:55:00+00:00",
        "collected_at": "2026-11-18T06:56:00+00:00",
        "snapshots": {
            "orders": {"snapshot_id": f"{packet_id}-ORDERS", "payload_sha256": "a" * 64, "complete": True},
            "executions": {"snapshot_id": f"{packet_id}-EXECUTIONS", "payload_sha256": "b" * 64, "complete": True},
            "positions": {"snapshot_id": f"{packet_id}-POSITIONS", "payload_sha256": "c" * 64, "complete": True},
        },
        "identity_crosswalk": [{
            "source_identity": {"source_execution_ref": f"SRC-{packet_id}"},
            "internal_identity": {"execution_id": "SYNTHETIC:EXEC-1", "scope_key": "__runtime_bootstrap__"},
            "evidence_ref": f"VALIDATION_ONLY:CROSSWALK:{packet_id}",
        }],
        "conflict_links": [{
            "execution_id": "SYNTHETIC:EXEC-1",
            "scope_key": "__runtime_bootstrap__",
            "original_payload_sha256": "d" * 64,
            "incoming_payload_sha256": "e" * 64,
            "source_record_refs": [f"SRC-{packet_id}"],
        }],
    }


def comparator():
    return ValidationOnlyBrokerEvidencePacketComparator(validation_only=True)


def test_two_packet_variants_are_preserved_without_deduplication_or_gate_release():
    first = valid_packet("PACKET-A")
    second = deepcopy(first)
    second["packet_id"] = "PACKET-B"
    for kind in ("orders", "executions", "positions"):
        second["snapshots"][kind]["snapshot_id"] = f"PACKET-B-{kind.upper()}"
        second["snapshots"][kind]["payload_sha256"] = "f" * 64
    second["identity_crosswalk"][0]["source_identity"]["source_execution_ref"] = "SRC-PACKET-B"
    second["identity_crosswalk"][0]["evidence_ref"] = "VALIDATION_ONLY:CROSSWALK:PACKET-B"
    second["conflict_links"][0]["source_record_refs"] = ["SRC-PACKET-B"]

    result = comparator().compare(packets=(first, second), as_of=AS_OF)
    assert result.is_comparable
    assert len(result.report["append_only_observations"]) == 2
    assert {item["packet_id"] for item in result.report["append_only_observations"]} == {
        "PACKET-A", "PACKET-B"
    }
    assert result.report["conflict_comparisons"][0]["payload_pair_count"] == 1
    assert result.gate_release_permitted is False
    assert result.authoritative is False
    assert result.mutation_applied is False


def test_conflicting_payload_hashes_are_reported_not_selected():
    first = valid_packet("PACKET-A")
    second = valid_packet("PACKET-B")
    second["conflict_links"][0]["incoming_payload_sha256"] = "9" * 64
    result = comparator().compare(packets=(first, second), as_of=AS_OF)
    assert result.status == "RECONCILIATION_REQUIRED"
    assert "BROKER_EVIDENCE_CONFLICT_PAYLOAD_DISAGREEMENT:SYNTHETIC:EXEC-1:__runtime_bootstrap__" in result.issues
    assert result.report["conflict_comparisons"][0]["requires_manual_review"] is True
    assert result.gate_release_permitted is False


def test_conflicting_identity_crosswalks_are_reported_not_overwritten():
    first = valid_packet("PACKET-A")
    second = valid_packet("PACKET-B")
    second["identity_crosswalk"][0]["internal_identity"]["account_ref"] = "OTHER-ACCOUNT"
    result = comparator().compare(packets=(first, second), as_of=AS_OF)
    assert result.status == "RECONCILIATION_REQUIRED"
    assert "BROKER_EVIDENCE_CONFLICT_IDENTITY_DISAGREEMENT:SYNTHETIC:EXEC-1:__runtime_bootstrap__" in result.issues


def test_invalid_packet_is_preserved_as_an_observation_and_requires_reconciliation():
    first = valid_packet("PACKET-A")
    second = valid_packet("PACKET-B")
    second["snapshots"].pop("positions")
    result = comparator().compare(packets=(first, second), as_of=AS_OF)
    assert result.status == "RECONCILIATION_REQUIRED"
    assert len(result.report["append_only_observations"]) == 2
    assert result.report["append_only_observations"][1]["packet_status"] == "RECONCILIATION_REQUIRED"


def test_comparator_requires_validation_only_opt_in_and_two_packets():
    with pytest.raises(ValueError, match="BROKER_EVIDENCE_COMPARATOR_VALIDATION_ONLY_OPT_IN_REQUIRED"):
        ValidationOnlyBrokerEvidencePacketComparator()
    result = comparator().compare(packets=(valid_packet(),), as_of=AS_OF)
    assert result.status == "RECONCILIATION_REQUIRED"
    assert "BROKER_EVIDENCE_COMPARISON_REQUIRES_AT_LEAST_TWO_PACKETS" in result.issues
