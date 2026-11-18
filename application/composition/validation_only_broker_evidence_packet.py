"""Source-neutral validation-only schema checks for external broker evidence packets."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Mapping


@dataclass(frozen=True)
class ValidationOnlyBrokerEvidencePacketResult:
    status: str
    issues: tuple[str, ...]
    manifest: Mapping[str, Any]
    manifest_sha256: str | None
    gate_release_permitted: bool = False
    authoritative: bool = False
    mutation_applied: bool = False

    @property
    def is_valid(self) -> bool:
        return self.status == "VALIDATION_ONLY_EVIDENCE_PACKET_VALID"


class ValidationOnlyBrokerEvidencePacketValidator:
    """Validate evidence lineage without asserting broker authority or resolving gates."""

    MANIFEST_VERSION = "Q25-A8-VALIDATION-ONLY-BROKER-EVIDENCE-v1"
    SNAPSHOT_KINDS = ("orders", "executions", "positions")

    def __init__(self, *, validation_only: bool = False) -> None:
        if validation_only is not True:
            raise ValueError("BROKER_EVIDENCE_PACKET_VALIDATION_ONLY_OPT_IN_REQUIRED")

    @staticmethod
    def _timestamp(value: Any, label: str) -> datetime:
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
    def _required_text(value: Any, label: str) -> str:
        result = str(value or "").strip()
        if not result:
            raise ValueError(f"{label}_REQUIRED")
        return result

    @staticmethod
    def _valid_hash(value: Any) -> bool:
        return re.fullmatch(r"[0-9a-f]{64}", str(value or "").strip().lower()) is not None

    def validate(
        self, *, packet: Mapping[str, Any], as_of: datetime | str,
        max_source_age_seconds: int | None = None,
    ) -> ValidationOnlyBrokerEvidencePacketResult:
        issues: list[str] = []
        manifest: dict[str, Any] = {"manifest_version": self.MANIFEST_VERSION}

        if not isinstance(packet, Mapping):
            return ValidationOnlyBrokerEvidencePacketResult(
                "RECONCILIATION_REQUIRED",
                ("BROKER_EVIDENCE_PACKET_MAPPING_REQUIRED",),
                manifest,
                None,
            )

        try:
            packet_id = self._required_text(packet.get("packet_id"), "PACKET_ID")
            source_namespace = self._required_text(packet.get("source_namespace"), "SOURCE_NAMESPACE")
            provider_ref = self._required_text(packet.get("provider_ref"), "PROVIDER_REF")
            if not source_namespace.startswith("VALIDATION_ONLY:"):
                issues.append("BROKER_EVIDENCE_VALIDATION_ONLY_NAMESPACE_REQUIRED")

            validated_at = self._timestamp(as_of, "VALIDATION_AS_OF")
            source_as_of = self._timestamp(packet.get("source_as_of"), "SOURCE_AS_OF")
            collected_at = self._timestamp(packet.get("collected_at"), "COLLECTED_AT")
            if source_as_of > collected_at:
                issues.append("BROKER_EVIDENCE_SOURCE_AS_OF_AFTER_COLLECTION")
            if collected_at > validated_at:
                issues.append("BROKER_EVIDENCE_COLLECTION_AFTER_VALIDATION_AS_OF")
            if source_as_of > validated_at:
                issues.append("BROKER_EVIDENCE_FUTURE_SOURCE_AS_OF")
            if max_source_age_seconds is not None:
                if not isinstance(max_source_age_seconds, int) or isinstance(max_source_age_seconds, bool) or max_source_age_seconds <= 0:
                    issues.append("BROKER_EVIDENCE_VALIDATION_SOURCE_AGE_LIMIT_INVALID")
                elif collected_at >= source_as_of and (collected_at - source_as_of).total_seconds() > max_source_age_seconds:
                    issues.append("BROKER_EVIDENCE_SOURCE_AGE_EXCEEDS_VALIDATION_LIMIT")
        except ValueError as exc:
            packet_id = str(packet.get("packet_id") or "")
            source_namespace = str(packet.get("source_namespace") or "")
            provider_ref = str(packet.get("provider_ref") or "")
            validated_at = source_as_of = collected_at = None
            issues.append(str(exc))

        snapshots = packet.get("snapshots")
        normalized_snapshots: dict[str, dict[str, Any]] = {}
        snapshot_ids: list[str] = []
        if not isinstance(snapshots, Mapping):
            issues.append("BROKER_EVIDENCE_SNAPSHOT_SET_REQUIRED")
            snapshots = {}
        for kind in self.SNAPSHOT_KINDS:
            raw = snapshots.get(kind)
            if not isinstance(raw, Mapping):
                issues.append(f"BROKER_EVIDENCE_{kind.upper()}_SNAPSHOT_REQUIRED")
                continue
            snapshot_id = str(raw.get("snapshot_id") or "").strip()
            digest = str(raw.get("payload_sha256") or "").strip().lower()
            complete = raw.get("complete")
            if not snapshot_id:
                issues.append(f"BROKER_EVIDENCE_{kind.upper()}_SNAPSHOT_ID_REQUIRED")
            else:
                snapshot_ids.append(snapshot_id)
            if not self._valid_hash(digest):
                issues.append(f"BROKER_EVIDENCE_{kind.upper()}_SNAPSHOT_HASH_INVALID")
            if complete is not True:
                issues.append(f"BROKER_EVIDENCE_{kind.upper()}_SNAPSHOT_COMPLETENESS_UNVERIFIED")
            normalized_snapshots[kind] = {
                "snapshot_id": snapshot_id,
                "payload_sha256": digest,
                "complete": complete is True,
            }
        if len(snapshot_ids) != len(set(snapshot_ids)):
            issues.append("BROKER_EVIDENCE_SNAPSHOT_IDS_NOT_DISTINCT")

        crosswalk = packet.get("identity_crosswalk")
        normalized_crosswalk: list[dict[str, Any]] = []
        if not isinstance(crosswalk, (list, tuple)) or not crosswalk:
            issues.append("BROKER_EVIDENCE_IDENTITY_CROSSWALK_REQUIRED")
            crosswalk = ()
        for index, item in enumerate(crosswalk):
            if not isinstance(item, Mapping):
                issues.append(f"BROKER_EVIDENCE_CROSSWALK_ROW_INVALID:{index}")
                continue
            source_identity = item.get("source_identity")
            internal_identity = item.get("internal_identity")
            evidence_ref = str(item.get("evidence_ref") or "").strip()
            if not isinstance(source_identity, Mapping) or not source_identity:
                issues.append(f"BROKER_EVIDENCE_SOURCE_IDENTITY_REQUIRED:{index}")
            if not isinstance(internal_identity, Mapping) or not internal_identity:
                issues.append(f"BROKER_EVIDENCE_INTERNAL_IDENTITY_REQUIRED:{index}")
            if not evidence_ref:
                issues.append(f"BROKER_EVIDENCE_CROSSWALK_EVIDENCE_REF_REQUIRED:{index}")
            normalized_crosswalk.append({
                "source_identity": dict(source_identity) if isinstance(source_identity, Mapping) else {},
                "internal_identity": dict(internal_identity) if isinstance(internal_identity, Mapping) else {},
                "evidence_ref": evidence_ref,
            })

        conflicts = packet.get("conflict_links")
        normalized_conflicts: list[dict[str, Any]] = []
        seen_conflicts: set[tuple[str, str]] = set()
        if not isinstance(conflicts, (list, tuple)) or not conflicts:
            issues.append("BROKER_EVIDENCE_CONFLICT_LINKS_REQUIRED")
            conflicts = ()
        for index, item in enumerate(conflicts):
            if not isinstance(item, Mapping):
                issues.append(f"BROKER_EVIDENCE_CONFLICT_ROW_INVALID:{index}")
                continue
            execution_id = str(item.get("execution_id") or "").strip()
            scope_key = str(item.get("scope_key") or "").strip()
            original_hash = str(item.get("original_payload_sha256") or "").strip().lower()
            incoming_hash = str(item.get("incoming_payload_sha256") or "").strip().lower()
            refs = item.get("source_record_refs")
            if not execution_id or not scope_key:
                issues.append(f"BROKER_EVIDENCE_CONFLICT_IDENTITY_REQUIRED:{index}")
            if not self._valid_hash(original_hash) or not self._valid_hash(incoming_hash):
                issues.append(f"BROKER_EVIDENCE_CONFLICT_PAYLOAD_HASH_INVALID:{index}")
            if not isinstance(refs, (list, tuple)) or not refs or any(not str(ref).strip() for ref in refs):
                issues.append(f"BROKER_EVIDENCE_CONFLICT_SOURCE_RECORD_REFS_REQUIRED:{index}")
                refs = ()
            key = (execution_id, scope_key)
            if key in seen_conflicts:
                issues.append(f"BROKER_EVIDENCE_CONFLICT_LINK_DUPLICATE:{execution_id}:{scope_key}")
            seen_conflicts.add(key)
            normalized_conflicts.append({
                "execution_id": execution_id,
                "scope_key": scope_key,
                "original_payload_sha256": original_hash,
                "incoming_payload_sha256": incoming_hash,
                "source_record_refs": [str(ref).strip() for ref in refs],
            })

        for conflict in normalized_conflicts:
            matched_crosswalk = any(
                row.get("internal_identity", {}).get("execution_id") == conflict["execution_id"]
                and row.get("internal_identity", {}).get("scope_key") == conflict["scope_key"]
                for row in normalized_crosswalk
            )
            if not matched_crosswalk:
                issues.append(
                    "BROKER_EVIDENCE_CONFLICT_IDENTITY_CROSSWALK_MISSING:"
                    + conflict["execution_id"] + ":" + conflict["scope_key"]
                )

        manifest.update({
            "packet_id": packet_id,
            "source_namespace": source_namespace,
            "provider_ref": provider_ref,
            "source_as_of": source_as_of.isoformat() if source_as_of else None,
            "collected_at": collected_at.isoformat() if collected_at else None,
            "validated_as_of": validated_at.isoformat() if validated_at else None,
            "max_source_age_seconds": max_source_age_seconds,
            "snapshots": normalized_snapshots,
            "identity_crosswalk": normalized_crosswalk,
            "conflict_links": normalized_conflicts,
            "authority_claimed": False,
            "gate_release_permitted": False,
            "mutation_applied": False,
        })
        encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        status = "VALIDATION_ONLY_EVIDENCE_PACKET_VALID" if not issues else "RECONCILIATION_REQUIRED"
        return ValidationOnlyBrokerEvidencePacketResult(
            status=status,
            issues=tuple(issues),
            manifest=manifest,
            manifest_sha256=digest,
        )
