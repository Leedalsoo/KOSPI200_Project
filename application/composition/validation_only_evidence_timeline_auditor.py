"""Validation-only event-time ordering and snapshot-coverage audit for evidence packets."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class ValidationOnlyEvidenceTimelineResult:
    status: str
    issues: tuple[str, ...]
    report: Mapping[str, Any]
    report_sha256: str
    gate_release_permitted: bool = False
    authoritative: bool = False
    mutation_applied: bool = False

    @property
    def is_valid(self) -> bool:
        return self.status == "VALIDATION_ONLY_TIMELINE_AUDIT_PASS"


class ValidationOnlyEvidenceTimelineAuditor:
    """Audits event-time order and declared snapshot coverage without mutating ledgers."""

    REPORT_VERSION = "Q25-A8-VALIDATION-ONLY-EVIDENCE-TIMELINE-v1"
    SNAPSHOT_KINDS = ("orders", "executions", "positions")

    def __init__(self, *, validation_only: bool = False) -> None:
        if validation_only is not True:
            raise ValueError("EVIDENCE_TIMELINE_VALIDATION_ONLY_OPT_IN_REQUIRED")

    @staticmethod
    def _time(value: Any, label: str) -> datetime:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(f"{label}_INVALID") from exc
        else:
            raise ValueError(f"{label}_INVALID")
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{label}_TIMEZONE_REQUIRED")
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _canonical_hash(value: Mapping[str, Any]) -> str:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def audit(
        self,
        *,
        packets: Sequence[Mapping[str, Any]],
        as_of: datetime | str,
        required_coverage: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> ValidationOnlyEvidenceTimelineResult:
        issues: list[str] = []
        observations: list[dict[str, Any]] = []
        packet_times: list[tuple[str, datetime]] = []
        coverage: dict[str, list[tuple[datetime, datetime, str]]] = {
            kind: [] for kind in self.SNAPSHOT_KINDS
        }
        event_fingerprints: dict[str, list[dict[str, str]]] = {}
        equal_time_groups: list[dict[str, Any]] = []

        try:
            validation_time = self._time(as_of, "VALIDATION_AS_OF")
        except ValueError as exc:
            validation_time = None
            issues.append(str(exc))

        if not isinstance(packets, (list, tuple)) or len(packets) < 2:
            issues.append("EVIDENCE_TIMELINE_REQUIRES_AT_LEAST_TWO_PACKETS")
            packet_iterable = packets if isinstance(packets, (list, tuple)) else ()
        else:
            packet_iterable = packets

        for packet_index, packet in enumerate(packet_iterable):
            if not isinstance(packet, Mapping):
                issues.append(f"PACKET_MAPPING_REQUIRED:{packet_index}")
                observations.append({"packet_index": packet_index, "packet_status": "INVALID"})
                continue

            packet_id = str(packet.get("packet_id") or f"PACKET-{packet_index}")
            packet_issues: list[str] = []
            try:
                source_as_of = self._time(packet.get("source_as_of"), "SOURCE_AS_OF")
                collected_at = self._time(packet.get("collected_at"), "COLLECTED_AT")
                if source_as_of > collected_at:
                    packet_issues.append("SOURCE_AS_OF_AFTER_COLLECTION")
                if validation_time is not None and collected_at > validation_time:
                    packet_issues.append("COLLECTION_AFTER_VALIDATION_AS_OF")
                packet_times.append((packet_id, source_as_of))
            except ValueError as exc:
                source_as_of = collected_at = None
                packet_issues.append(str(exc))

            raw_snapshots = packet.get("snapshots")
            if not isinstance(raw_snapshots, Mapping):
                raw_snapshots = {}
                packet_issues.append("SNAPSHOT_SET_REQUIRED")

            normalized_snapshots: dict[str, dict[str, Any]] = {}
            snapshot_ids: dict[str, str] = {}
            for kind in self.SNAPSHOT_KINDS:
                raw = raw_snapshots.get(kind)
                if not isinstance(raw, Mapping):
                    packet_issues.append(f"{kind.upper()}_SNAPSHOT_REQUIRED")
                    continue
                snapshot_id = str(raw.get("snapshot_id") or "").strip()
                if not snapshot_id:
                    packet_issues.append(f"{kind.upper()}_SNAPSHOT_ID_REQUIRED")
                snapshot_ids[kind] = snapshot_id
                try:
                    snap_as_of = self._time(raw.get("snapshot_as_of"), f"{kind.upper()}_SNAPSHOT_AS_OF")
                    start = self._time(raw.get("coverage_start"), f"{kind.upper()}_COVERAGE_START")
                    end = self._time(raw.get("coverage_end"), f"{kind.upper()}_COVERAGE_END")
                    if start > end:
                        packet_issues.append(f"{kind.upper()}_COVERAGE_WINDOW_REVERSED")
                    if end > snap_as_of:
                        packet_issues.append(f"{kind.upper()}_COVERAGE_AFTER_SNAPSHOT_AS_OF")
                    if source_as_of is not None and snap_as_of > source_as_of:
                        packet_issues.append(f"{kind.upper()}_SNAPSHOT_AFTER_PACKET_SOURCE_AS_OF")
                    if collected_at is not None and snap_as_of > collected_at:
                        packet_issues.append(f"{kind.upper()}_SNAPSHOT_AFTER_COLLECTION")
                    coverage[kind].append((start, end, packet_id))
                    normalized_snapshots[kind] = {
                        "snapshot_id": snapshot_id,
                        "snapshot_as_of": snap_as_of.isoformat(),
                        "coverage_start": start.isoformat(),
                        "coverage_end": end.isoformat(),
                        "declared_event_count": raw.get("event_count"),
                    }
                except ValueError as exc:
                    packet_issues.append(str(exc))

            events = packet.get("event_observations")
            if not isinstance(events, (list, tuple)) or not events:
                events = ()
                packet_issues.append("EVENT_OBSERVATIONS_REQUIRED")

            previous_event_time: datetime | None = None
            event_counts = {kind: 0 for kind in self.SNAPSHOT_KINDS}
            packet_events: list[dict[str, Any]] = []
            for event_index, event in enumerate(events):
                if not isinstance(event, Mapping):
                    packet_issues.append(f"EVENT_ROW_INVALID:{event_index}")
                    continue
                event_id = str(event.get("event_id") or "").strip()
                payload_hash = str(event.get("payload_sha256") or "").strip().lower()
                kind = str(event.get("snapshot_kind") or "").strip()
                snapshot_id = str(event.get("snapshot_id") or "").strip()
                if not event_id:
                    packet_issues.append(f"EVENT_ID_REQUIRED:{event_index}")
                if len(payload_hash) != 64 or any(ch not in "0123456789abcdef" for ch in payload_hash):
                    packet_issues.append(f"EVENT_PAYLOAD_HASH_INVALID:{event_index}")
                if kind not in self.SNAPSHOT_KINDS:
                    packet_issues.append(f"EVENT_SNAPSHOT_KIND_INVALID:{event_index}")
                elif snapshot_ids.get(kind) != snapshot_id:
                    packet_issues.append(f"EVENT_SNAPSHOT_LINK_MISMATCH:{event_index}")
                try:
                    event_time = self._time(event.get("event_time"), f"EVENT_TIME_{event_index}")
                    received_at = self._time(event.get("received_at"), f"EVENT_RECEIVED_AT_{event_index}")
                    if event_time > received_at:
                        packet_issues.append(f"EVENT_TIME_AFTER_RECEIVED_AT:{event_index}")
                    if collected_at is not None and received_at > collected_at:
                        packet_issues.append(f"EVENT_RECEIVED_AFTER_COLLECTION:{event_index}")
                    if validation_time is not None and event_time > validation_time:
                        packet_issues.append(f"FUTURE_EVENT_TIME:{event_index}")
                    if previous_event_time is not None and event_time < previous_event_time:
                        packet_issues.append(f"EVENT_TIME_ORDER_REVERSED:{event_index}")
                    if previous_event_time == event_time:
                        equal_time_groups.append({
                            "packet_id": packet_id,
                            "event_time": event_time.isoformat(),
                            "event_id": event_id,
                        })
                    previous_event_time = event_time
                    if kind in self.SNAPSHOT_KINDS and kind in normalized_snapshots:
                        snap = normalized_snapshots[kind]
                        if event_time < self._time(snap["coverage_start"], "COVERAGE_START") or event_time > self._time(snap["coverage_end"], "COVERAGE_END"):
                            packet_issues.append(f"EVENT_OUTSIDE_SNAPSHOT_COVERAGE:{event_index}")
                    if kind in event_counts:
                        event_counts[kind] += 1
                    if event_id and payload_hash:
                        event_fingerprints.setdefault(event_id, []).append({
                            "packet_id": packet_id,
                            "payload_sha256": payload_hash,
                        })
                    packet_events.append({
                        "event_id": event_id,
                        "event_time": event_time.isoformat(),
                        "received_at": received_at.isoformat(),
                        "snapshot_kind": kind,
                        "snapshot_id": snapshot_id,
                        "payload_sha256": payload_hash,
                    })
                except ValueError as exc:
                    packet_issues.append(str(exc))

            for kind, snap in normalized_snapshots.items():
                declared = snap.get("declared_event_count")
                actual = event_counts[kind]
                if not isinstance(declared, int) or isinstance(declared, bool) or declared != actual or actual == 0:
                    packet_issues.append(f"{kind.upper()}_SNAPSHOT_EVENT_COUNT_MISMATCH:{declared}:{actual}")

            observations.append({
                "packet_index": packet_index,
                "packet_id": packet_id,
                "source_as_of": source_as_of.isoformat() if source_as_of else None,
                "collected_at": collected_at.isoformat() if collected_at else None,
                "snapshots": normalized_snapshots,
                "event_observations": packet_events,
                "event_counts": event_counts,
                "packet_issues": sorted(set(packet_issues)),
                "packet_status": "RECONCILIATION_REQUIRED" if packet_issues else "TIMELINE_VALID",
            })
            issues.extend(f"PACKET[{packet_index}]:{item}" for item in packet_issues)

        for index in range(1, len(packet_times)):
            previous_id, previous_time = packet_times[index - 1]
            current_id, current_time = packet_times[index]
            if current_time < previous_time:
                issues.append(f"PACKET_SOURCE_TIME_ORDER_REVERSED:{previous_id}:{current_id}")

        duplicate_events: list[dict[str, Any]] = []
        for event_id, rows in sorted(event_fingerprints.items()):
            hashes = sorted({row["payload_sha256"] for row in rows})
            if len(rows) > 1:
                duplicate_events.append({
                    "event_id": event_id,
                    "observations": rows,
                    "payload_hash_count": len(hashes),
                    "payload_disagreement": len(hashes) > 1,
                })
            if len(hashes) > 1:
                issues.append(f"CROSS_PACKET_EVENT_PAYLOAD_DISAGREEMENT:{event_id}")

        coverage_report: dict[str, Any] = {}
        for kind, windows in coverage.items():
            ordered = sorted(windows, key=lambda row: (row[0], row[1], row[2]))
            merged: list[list[Any]] = []
            for start, end, packet_id in ordered:
                if not merged or start > merged[-1][1]:
                    merged.append([start, end, [packet_id]])
                else:
                    if end > merged[-1][1]:
                        merged[-1][1] = end
                    merged[-1][2].append(packet_id)

            required = (required_coverage or {}).get(kind)
            required_result: dict[str, Any] | None = None
            if required is not None:
                try:
                    required_start = self._time(required.get("start"), f"{kind.upper()}_REQUIRED_START")
                    required_end = self._time(required.get("end"), f"{kind.upper()}_REQUIRED_END")
                    covered = (
                        len(merged) == 1
                        and merged[0][0] <= required_start
                        and merged[0][1] >= required_end
                    )
                    if required_start > required_end:
                        issues.append(f"{kind.upper()}_REQUIRED_COVERAGE_WINDOW_REVERSED")
                        covered = False
                    if not covered:
                        issues.append(f"{kind.upper()}_REQUIRED_COVERAGE_NOT_MET")
                    required_result = {
                        "start": required_start.isoformat(),
                        "end": required_end.isoformat(),
                        "covered": covered,
                    }
                except (ValueError, AttributeError) as exc:
                    issues.append(str(exc) if isinstance(exc, ValueError) else f"{kind.upper()}_REQUIRED_COVERAGE_INVALID")
            coverage_report[kind] = {
                "windows": [
                    {"start": start.isoformat(), "end": end.isoformat(), "packet_ids": packet_ids}
                    for start, end, packet_ids in merged
                ],
                "required": required_result,
            }

        report: dict[str, Any] = {
            "report_version": self.REPORT_VERSION,
            "packet_observations": observations,
            "packet_source_order": [
                {"packet_id": packet_id, "source_as_of": timestamp.isoformat()}
                for packet_id, timestamp in packet_times
            ],
            "equal_event_time_observations": equal_time_groups,
            "duplicate_event_observations": duplicate_events,
            "snapshot_coverage": coverage_report,
            "issues": sorted(set(issues)),
            "authority_claimed": False,
            "gate_release_permitted": False,
            "mutation_applied": False,
        }
        digest = self._canonical_hash(report)
        status = "VALIDATION_ONLY_TIMELINE_AUDIT_PASS" if not issues else "RECONCILIATION_REQUIRED"
        return ValidationOnlyEvidenceTimelineResult(
            status=status,
            issues=tuple(sorted(set(issues))),
            report=report,
            report_sha256=digest,
        )
