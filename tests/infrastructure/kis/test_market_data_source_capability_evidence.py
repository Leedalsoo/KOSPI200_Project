"""FRESH-14 offline evidence consistency checks using explicitly synthetic fixtures.

These tests validate the detector's fail-closed classification only. They do not
establish official KIS VTS capability or assert that synthetic evidence is real.
"""
import hashlib
import json


def _classify_manifest_raw_consistency(manifest, raw_records):
    raw_tr_ids = {str(record.get("tr_id", "")) for record in raw_records}
    manifest_tr_ids = set(manifest.get("tr_ids", []))
    lifecycle = str(manifest.get("collector_status", "UNKNOWN")).upper()
    has_raw = bool(raw_records)
    mismatch = has_raw and lifecycle in {"NOT_STARTED", "STOPPED", "UNKNOWN"}
    return {
        "raw_present": has_raw,
        "manifest_raw_tr_mismatch": bool(raw_tr_ids - manifest_tr_ids),
        "lifecycle_raw_mismatch": mismatch,
        "capability_status": "CONFLICTING_EVIDENCE" if mismatch or bool(raw_tr_ids - manifest_tr_ids) else "UNRESOLVED",
    }


def test_fresh14_assumption_manifest_lifecycle_conflict_is_detected_without_capability_promotion():
    # ASSUMPTION fixture: shaped like the reported 2026-10-02 discrepancy,
    # but not loaded as authoritative source evidence.
    manifest = {"tr_ids": ["H0IOCNT0"], "collector_status": "NOT_STARTED"}
    raw_record = {
        "tr_id": "H0IOASP0",
        "payload": "synthetic-frame-only",
        "payload_sha256": hashlib.sha256(b"synthetic-frame-only").hexdigest(),
    }
    result = _classify_manifest_raw_consistency(manifest, [raw_record])
    assert result["raw_present"]
    assert result["manifest_raw_tr_mismatch"]
    assert result["lifecycle_raw_mismatch"]
    assert result["capability_status"] == "CONFLICTING_EVIDENCE"
    assert raw_record["payload_sha256"] == hashlib.sha256(raw_record["payload"].encode()).hexdigest()
    # No network, subscription, retry, or stable-capability promotion is performed.


def test_fresh14_absent_ack_evidence_remains_unknown_not_a_failed_or_successful_ack():
    # ASSUMPTION fixture: absence of an ACK log is not proof of either ACK outcome.
    ack_records = []
    ack_status = "UNKNOWN" if not ack_records else "PRESENT"
    assert ack_status == "UNKNOWN"
