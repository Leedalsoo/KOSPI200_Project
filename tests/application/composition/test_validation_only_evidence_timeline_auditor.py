from copy import deepcopy
from datetime import datetime, timezone

import pytest

from application.composition.validation_only_evidence_timeline_auditor import (
    ValidationOnlyEvidenceTimelineAuditor,
)


AS_OF = datetime(2026, 11, 18, 8, 0, tzinfo=timezone.utc)


def make_packet(packet_id, source_as_of, base_minute):
    from datetime import timedelta

    start = datetime(2026, 11, 18, 7, 0 + base_minute, tzinfo=timezone.utc)
    middle = start + timedelta(seconds=10)
    end = start + timedelta(seconds=20)
    collected = end + timedelta(seconds=2)
    snapshots = {}
    events = []
    for index, kind in enumerate(("orders", "executions", "positions")):
        snapshot_id = f"{packet_id}-{kind}"
        snapshots[kind] = {
            "snapshot_id": snapshot_id,
            "snapshot_as_of": end.isoformat(),
            "coverage_start": start.isoformat(),
            "coverage_end": end.isoformat(),
            "event_count": 1,
        }
        events.append({
            "event_id": f"{packet_id}-EVENT-{kind}",
            "event_time": (start + timedelta(seconds=index * 10)).isoformat(),
            "received_at": (start + timedelta(seconds=index * 10 + 1)).isoformat(),
            "snapshot_kind": kind,
            "snapshot_id": snapshot_id,
            "payload_sha256": str(index + 1) * 64,
        })
    return {
        "packet_id": packet_id,
        "source_as_of": source_as_of,
        "collected_at": collected.isoformat(),
        "snapshots": snapshots,
        "event_observations": events,
    }


def auditor():
    return ValidationOnlyEvidenceTimelineAuditor(validation_only=True)


def test_same_timestamp_and_ordered_distinct_timestamps_are_valid_and_covered():
    first = make_packet("P1", "2026-11-18T07:00:20+00:00", 0)
    second = make_packet("P2", "2026-11-18T07:00:20+00:00", 0)
    # Equal packet source timestamps are valid; packet event times remain monotonic.
    result = auditor().audit(packets=(first, second), as_of=AS_OF)
    assert result.is_valid
    assert result.report["packet_source_order"][0]["source_as_of"] == result.report["packet_source_order"][1]["source_as_of"]
    assert all(result.report["snapshot_coverage"][kind]["windows"] for kind in ("orders", "executions", "positions"))
    assert result.gate_release_permitted is False
    assert result.authoritative is False
    assert result.mutation_applied is False


def test_distinct_packet_source_timestamps_in_ascending_order_are_valid():
    first = make_packet("P1", "2026-11-18T07:00:20+00:00", 0)
    second = make_packet("P2", "2026-11-18T07:01:20+00:00", 1)
    result = auditor().audit(packets=(first, second), as_of=AS_OF)
    assert result.is_valid


def test_reversed_packet_and_event_timestamps_require_reconciliation():
    first = make_packet("P1", "2026-11-18T07:01:20+00:00", 0)
    second = make_packet("P2", "2026-11-18T07:00:20+00:00", 0)
    second["event_observations"][1], second["event_observations"][2] = (
        second["event_observations"][2], second["event_observations"][1]
    )
    result = auditor().audit(packets=(first, second), as_of=AS_OF)
    assert result.status == "RECONCILIATION_REQUIRED"
    assert any(issue.startswith("PACKET_SOURCE_TIME_ORDER_REVERSED") for issue in result.issues)
    assert any("EVENT_TIME_ORDER_REVERSED" in issue for issue in result.issues)
    assert result.report["packet_source_order"][0]["packet_id"] == "P1"
    assert result.gate_release_permitted is False


def test_snapshot_coverage_gap_and_missing_event_are_not_hidden():
    first = make_packet("P1", "2026-11-18T07:00:20+00:00", 0)
    second = make_packet("P2", "2026-11-18T07:01:20+00:00", 2)
    required = {
        "orders": {"start": "2026-11-18T07:00:00+00:00", "end": "2026-11-18T07:02:00+00:00"},
        "executions": {"start": "2026-11-18T07:00:00+00:00", "end": "2026-11-18T07:02:00+00:00"},
        "positions": {"start": "2026-11-18T07:00:00+00:00", "end": "2026-11-18T07:02:00+00:00"},
    }
    second["event_observations"] = second["event_observations"][:2]
    result = auditor().audit(packets=(first, second), as_of=AS_OF, required_coverage=required)
    assert result.status == "RECONCILIATION_REQUIRED"
    assert any("SNAPSHOT_EVENT_COUNT_MISMATCH" in issue for issue in result.issues)
    assert any("REQUIRED_COVERAGE_NOT_MET" in issue for issue in result.issues)
    assert all(result.gate_release_permitted is False for _ in (0,))


def test_future_or_unreceived_event_time_is_reconciliation_required():
    first = make_packet("P1", "2026-11-18T07:00:20+00:00", 0)
    second = make_packet("P2", "2026-11-18T07:01:20+00:00", 1)
    second["event_observations"][0]["event_time"] = "2026-11-18T07:59:00+00:00"
    result = auditor().audit(packets=(first, second), as_of=AS_OF)
    assert result.status == "RECONCILIATION_REQUIRED"
    assert any("EVENT_TIME_AFTER_RECEIVED_AT" in issue for issue in result.issues)
    assert any("EVENT_OUTSIDE_SNAPSHOT_COVERAGE" in issue for issue in result.issues)


def test_cross_packet_duplicate_event_payload_disagreement_is_reported():
    first = make_packet("P1", "2026-11-18T07:00:20+00:00", 0)
    second = make_packet("P2", "2026-11-18T07:01:20+00:00", 1)
    second["event_observations"][0]["event_id"] = first["event_observations"][0]["event_id"]
    second["event_observations"][0]["payload_sha256"] = "f" * 64
    result = auditor().audit(packets=(first, second), as_of=AS_OF)
    assert result.status == "RECONCILIATION_REQUIRED"
    assert "CROSS_PACKET_EVENT_PAYLOAD_DISAGREEMENT:P1-EVENT-orders" in result.issues
    assert result.report["duplicate_event_observations"][0]["payload_disagreement"] is True


def test_same_duplicate_event_payload_is_preserved_without_false_conflict():
    first = make_packet("P1", "2026-11-18T07:00:20+00:00", 0)
    second = make_packet("P2", "2026-11-18T07:01:20+00:00", 1)
    second["event_observations"][0]["event_id"] = first["event_observations"][0]["event_id"]
    second["event_observations"][0]["payload_sha256"] = first["event_observations"][0]["payload_sha256"]
    result = auditor().audit(packets=(first, second), as_of=AS_OF)
    assert result.is_valid
    assert result.report["duplicate_event_observations"][0]["payload_disagreement"] is False


def test_deterministic_report_hash_and_timezone_requirement():
    first = make_packet("P1", "2026-11-18T07:00:20+00:00", 0)
    second = make_packet("P2", "2026-11-18T07:01:20+00:00", 1)
    one = auditor().audit(packets=(first, second), as_of=AS_OF)
    two = ValidationOnlyEvidenceTimelineAuditor(validation_only=True).audit(
        packets=(first, second), as_of=AS_OF
    )
    assert one.report_sha256 == two.report_sha256
    bad = deepcopy(second)
    bad["event_observations"][0]["event_time"] = "2026-11-18T07:01:00"
    invalid = auditor().audit(packets=(first, bad), as_of=AS_OF)
    assert invalid.status == "RECONCILIATION_REQUIRED"
    assert any("TIMEZONE_REQUIRED" in issue for issue in invalid.issues)


def test_auditor_requires_explicit_validation_only_opt_in():
    with pytest.raises(ValueError, match="EVIDENCE_TIMELINE_VALIDATION_ONLY_OPT_IN_REQUIRED"):
        ValidationOnlyEvidenceTimelineAuditor()
