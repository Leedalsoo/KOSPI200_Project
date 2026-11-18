"""Read-only comparison of multiple validation-only broker evidence packets."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping, Sequence

from application.composition.validation_only_broker_evidence_packet import (
    ValidationOnlyBrokerEvidencePacketValidator,
)


@dataclass(frozen=True)
class ValidationOnlyBrokerEvidenceComparisonResult:
    status: str
    issues: tuple[str, ...]
    report: Mapping[str, Any]
    report_sha256: str | None
    gate_release_permitted: bool = False
    authoritative: bool = False
    mutation_applied: bool = False

    @property
    def is_comparable(self) -> bool:
        return self.status == "VALIDATION_ONLY_EVIDENCE_COMPARISON_RECORDED"


class ValidationOnlyBrokerEvidencePacketComparator:
    """Preserve every packet observation and surface disagreements without resolving them."""

    REPORT_VERSION = "Q25-A8-VALIDATION-ONLY-EVIDENCE-COMPARISON-v1"

    def __init__(self, *, validation_only: bool = False) -> None:
        if validation_only is not True:
            raise ValueError("BROKER_EVIDENCE_COMPARATOR_VALIDATION_ONLY_OPT_IN_REQUIRED")
        self._validator = ValidationOnlyBrokerEvidencePacketValidator(validation_only=True)

    def compare(
        self,
        *,
        packets: Sequence[Mapping[str, Any]],
        as_of,
        max_source_age_seconds: int | None = None,
    ) -> ValidationOnlyBrokerEvidenceComparisonResult:
        issues: list[str] = []
        observations: list[dict[str, Any]] = []
        conflict_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}

        if not isinstance(packets, (list, tuple)) or len(packets) < 2:
            issues.append("BROKER_EVIDENCE_COMPARISON_REQUIRES_AT_LEAST_TWO_PACKETS")

        for index, packet in enumerate(packets if isinstance(packets, (list, tuple)) else ()):
            result = self._validator.validate(
                packet=packet,
                as_of=as_of,
                max_source_age_seconds=max_source_age_seconds,
            )
            packet_id = str(packet.get("packet_id") or "") if isinstance(packet, Mapping) else ""
            observations.append({
                "observation_index": index,
                "packet_id": packet_id,
                "packet_manifest_sha256": result.manifest_sha256,
                "packet_status": result.status,
                "packet_issues": list(result.issues),
                "source_as_of": result.manifest.get("source_as_of"),
                "collected_at": result.manifest.get("collected_at"),
                "snapshots": result.manifest.get("snapshots", {}),
                "identity_crosswalk": result.manifest.get("identity_crosswalk", []),
                "conflict_links": result.manifest.get("conflict_links", []),
            })
            if not result.is_valid:
                issues.extend(
                    f"PACKET[{index}]:{issue}" for issue in result.issues
                )
                continue
            for link in result.manifest.get("conflict_links", []):
                key = (link["execution_id"], link["scope_key"])
                crosswalk_rows = [
                    row for row in result.manifest.get("identity_crosswalk", [])
                    if row.get("internal_identity", {}).get("execution_id") == key[0]
                    and row.get("internal_identity", {}).get("scope_key") == key[1]
                ]
                conflict_groups.setdefault(key, []).append({
                    "packet_id": packet_id,
                    "original_payload_sha256": link["original_payload_sha256"],
                    "incoming_payload_sha256": link["incoming_payload_sha256"],
                    "internal_identity_variants": [
                        row.get("internal_identity", {}) for row in crosswalk_rows
                    ],
                })

        conflict_comparisons: list[dict[str, Any]] = []
        for (execution_id, scope_key), rows in sorted(conflict_groups.items()):
            payload_pairs = {
                (row["original_payload_sha256"], row["incoming_payload_sha256"])
                for row in rows
            }
            identity_variants = {
                json.dumps(item, sort_keys=True, separators=(",", ":"))
                for row in rows for item in row["internal_identity_variants"]
            }
            if len(payload_pairs) > 1:
                issues.append(
                    f"BROKER_EVIDENCE_CONFLICT_PAYLOAD_DISAGREEMENT:{execution_id}:{scope_key}"
                )
            if len(identity_variants) > 1:
                issues.append(
                    f"BROKER_EVIDENCE_CONFLICT_IDENTITY_DISAGREEMENT:{execution_id}:{scope_key}"
                )
            conflict_comparisons.append({
                "execution_id": execution_id,
                "scope_key": scope_key,
                "observations": rows,
                "payload_pair_count": len(payload_pairs),
                "identity_variant_count": len(identity_variants),
                "requires_manual_review": len(payload_pairs) > 1 or len(identity_variants) > 1,
            })

        report: dict[str, Any] = {
            "report_version": self.REPORT_VERSION,
            "append_only_observations": observations,
            "conflict_comparisons": conflict_comparisons,
            "issues": sorted(set(issues)),
            "authority_claimed": False,
            "gate_release_permitted": False,
            "mutation_applied": False,
        }
        encoded = json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        status = (
            "VALIDATION_ONLY_EVIDENCE_COMPARISON_RECORDED"
            if not issues and len(observations) >= 2
            else "RECONCILIATION_REQUIRED"
        )
        return ValidationOnlyBrokerEvidenceComparisonResult(
            status=status,
            issues=tuple(sorted(set(issues))),
            report=report,
            report_sha256=digest,
        )
