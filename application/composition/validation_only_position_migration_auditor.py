"""Read-only validation of quantity-changing account baseline migrations.

This auditor never mutates the settlement store or applies a baseline migration.
It proves only opening-position -> execution-ledger -> target-quantity lineage.
Average cost, contract authority and real-account truth remain outside its scope.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import re
from typing import Any, Mapping


@dataclass(frozen=True)
class ValidationOnlyPositionMigrationResult:
    status: str
    issues: tuple[str, ...]
    manifest: Mapping[str, Any]
    manifest_sha256: str | None
    quantity_delta: tuple[Mapping[str, Any], ...]
    cost_basis_status: str = "UNVERIFIED"
    migration_applied: bool = False

    @property
    def is_quantity_reconciled(self) -> bool:
        return self.status == "VALIDATION_ONLY_QUANTITY_MIGRATION_RECONCILED"


class ValidationOnlyPositionMigrationAuditor:
    """Cross-check a changed position snapshot against its previous baseline and U19."""

    MANIFEST_VERSION = "Q25-A8-VALIDATION-ONLY-POSITION-MIGRATION-v1"

    def __init__(self, settlement_store: Any, *, validation_only: bool = False) -> None:
        if validation_only is not True:
            raise ValueError("POSITION_MIGRATION_VALIDATION_ONLY_OPT_IN_REQUIRED")
        self.settlement_store = settlement_store

    @staticmethod
    def _signed(side: str, quantity: Any) -> int:
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 0:
            raise ValueError("POSITION_QUANTITY_INVALID")
        normalized = str(side or "").upper()
        if quantity == 0 and normalized in {"", "FLAT", "NONE"}:
            return 0
        if normalized in {"LONG", "BUY"}:
            return quantity
        if normalized in {"SHORT", "SELL"}:
            return -quantity
        raise ValueError("POSITION_SIDE_INVALID")

    @classmethod
    def _position_map(cls, rows, *, quantity_key: str) -> dict[str, int]:
        result: dict[str, int] = {}
        for row in rows:
            instrument = str(row.get("instrument_id") or "").strip()
            if not instrument or instrument in result:
                raise ValueError("POSITION_IDENTITY_MISSING_OR_DUPLICATE")
            result[instrument] = cls._signed(row.get("side"), row.get(quantity_key))
        return {key: value for key, value in result.items() if value != 0}

    def audit(self, *, bundle, validation, reconciliation) -> ValidationOnlyPositionMigrationResult:
        issues: list[str] = []
        baseline = self.settlement_store.authoritative_baseline_evidence()
        if not isinstance(baseline, dict):
            issues.append("POSITION_MIGRATION_PREVIOUS_BASELINE_REQUIRED")
        elif not str(baseline.get("source") or "").startswith("VALIDATION_ONLY:"):
            issues.append("POSITION_MIGRATION_VALIDATION_ONLY_BASELINE_REQUIRED")
        previous_hash = str((baseline or {}).get("payload_sha256") or "").lower()
        if re.fullmatch(r"[0-9a-f]{64}", previous_hash) is None:
            issues.append("POSITION_MIGRATION_PREVIOUS_BASELINE_HASH_INVALID")

        if not getattr(validation, "is_valid", False) or not getattr(validation, "evidence_sha256", None):
            issues.append("POSITION_MIGRATION_SNAPSHOT_VALIDATION_REQUIRED")
        if not getattr(reconciliation, "is_valid", False) or getattr(reconciliation, "issues", ()):
            issues.append("POSITION_MIGRATION_U19_RECONCILIATION_REQUIRED")
        if any(getattr(reconciliation, name, None) is None for name in (
            "ledger_snapshot", "projected_ledger_snapshot", "broker_snapshot", "recovery_decision"
        )):
            issues.append("POSITION_MIGRATION_COMPLETE_U19_EVIDENCE_REQUIRED")

        try:
            opening = self._position_map(bundle.opening_positions.rows, quantity_key="quantity")
            previous_rows = (baseline or {}).get("positions", ())
            previous = self._position_map(previous_rows, quantity_key="qty")
            target = self._position_map(validation.normalized_positions, quantity_key="qty")
            if opening != previous:
                issues.append("POSITION_MIGRATION_OPENING_BASELINE_CROSSWALK_MISMATCH")
        except (AttributeError, TypeError, ValueError) as exc:
            opening, previous, target = {}, {}, {}
            issues.append(f"POSITION_MIGRATION_POSITION_CROSSWALK_UNVERIFIABLE:{exc}")

        ledger = getattr(reconciliation, "ledger_snapshot", None)
        projected = getattr(reconciliation, "projected_ledger_snapshot", None)
        broker = getattr(reconciliation, "broker_snapshot", None)
        decision = getattr(reconciliation, "recovery_decision", None)
        if all(item is not None for item in (ledger, projected, broker, decision)):
            if projected.positions != broker.positions:
                issues.append("POSITION_MIGRATION_U19_PROJECTED_BROKER_MISMATCH")
            projected_map = {
                item.instrument_id: int(item.signed_quantity)
                for item in projected.positions if item.signed_quantity != 0
            }
            if projected_map != target:
                issues.append("POSITION_MIGRATION_U19_TARGET_QUANTITY_MISMATCH")
            if getattr(decision, "new_entry_enabled", True) or getattr(decision, "order_submission_enabled", True):
                issues.append("POSITION_MIGRATION_ORDER_SUBMISSION_MUST_REMAIN_DISABLED")
            if getattr(decision, "status", None) not in {"RESTORE_ALLOWED", "FLAT_CONFIRMED"} and getattr(getattr(decision, "status", None), "value", None) not in {"RESTORE_ALLOWED", "FLAT_CONFIRMED"}:
                issues.append("POSITION_MIGRATION_U19_RECOVERY_NOT_ALLOWED")
            if getattr(ledger, "pending_order_ids", ()):
                issues.append("POSITION_MIGRATION_PENDING_ORDERS_PRESENT")

        unresolved = self.settlement_store.unresolved_reconciliations()
        if unresolved:
            issues.append("POSITION_MIGRATION_UNRESOLVED_RECONCILIATION_SCOPES_PRESENT")
        if self.settlement_store.reconciliation_status("__startup_reconciliation__") == "CONFLICT":
            issues.append("POSITION_MIGRATION_STARTUP_CONFLICT_REQUIRES_MANUAL_REVIEW")

        provenance = getattr(bundle, "provenance", None)
        namespace = str(getattr(provenance, "namespace", "") or "")
        rule_id = str(getattr(provenance, "deterministic_rule_id", "") or "")
        manifest_hash = str(getattr(provenance, "manifest_sha256", "") or "").lower()
        if not namespace.startswith(("SYNTHETIC:", "SYNTHETIC_CONTRACT:")):
            issues.append("POSITION_MIGRATION_SYNTHETIC_NAMESPACE_REQUIRED")
        if not rule_id:
            issues.append("POSITION_MIGRATION_DETERMINISTIC_RULE_REQUIRED")
        if re.fullmatch(r"[0-9a-f]{64}", manifest_hash) is None:
            issues.append("POSITION_MIGRATION_SOURCE_MANIFEST_SHA256_REQUIRED")
        anchor_refs = tuple(str(value).strip() for value in getattr(provenance, "source_anchor_refs", ()) if str(value).strip())
        anchor_as_of = getattr(provenance, "source_anchor_as_of", None)
        scenario_timestamp = getattr(provenance, "scenario_timestamp", None)
        if not anchor_refs or anchor_as_of is None or scenario_timestamp is None:
            issues.append("POSITION_MIGRATION_SOURCE_ANCHOR_PROVENANCE_REQUIRED")
        elif (anchor_as_of.tzinfo is None or anchor_as_of.utcoffset() is None
              or scenario_timestamp.tzinfo is None or scenario_timestamp.utcoffset() is None):
            issues.append("POSITION_MIGRATION_SOURCE_ANCHOR_TIMEZONE_REQUIRED")
        elif anchor_as_of.astimezone(timezone.utc) > scenario_timestamp.astimezone(timezone.utc):
            issues.append("POSITION_MIGRATION_FUTURE_SOURCE_ANCHOR_REJECTED")
        if not getattr(validation, "snapshot_ids", ()) or not getattr(validation, "as_of", None):
            issues.append("POSITION_MIGRATION_SNAPSHOT_LINEAGE_REQUIRED")
        elif validation.as_of.tzinfo is None or validation.as_of.utcoffset() is None:
            issues.append("POSITION_MIGRATION_AS_OF_MUST_BE_TIMEZONE_AWARE")

        delta = tuple(
            {"instrument_id": key, "previous_signed_quantity": previous.get(key, 0),
             "target_signed_quantity": target.get(key, 0),
             "delta_signed_quantity": target.get(key, 0) - previous.get(key, 0)}
            for key in sorted(set(previous) | set(target))
            if previous.get(key, 0) != target.get(key, 0)
        )
        manifest = {
            "manifest_version": self.MANIFEST_VERSION,
            "previous_baseline_sha256": previous_hash or None,
            "snapshot_evidence_sha256": getattr(validation, "evidence_sha256", None),
            "snapshot_ids": list(getattr(validation, "snapshot_ids", ())),
            "as_of": validation.as_of.astimezone(timezone.utc).isoformat() if getattr(validation, "as_of", None) and validation.as_of.tzinfo else None,
            "synthetic_namespace": namespace,
            "deterministic_rule_id": rule_id,
            "source_manifest_sha256": manifest_hash,
            "source_anchor_refs": list(anchor_refs),
            "source_anchor_as_of": anchor_as_of.astimezone(timezone.utc).isoformat() if anchor_as_of is not None and anchor_as_of.tzinfo else None,
            "scenario_timestamp": scenario_timestamp.astimezone(timezone.utc).isoformat() if scenario_timestamp is not None and scenario_timestamp.tzinfo else None,
            "u19_ledger_sha256": getattr(ledger, "payload_sha256", None),
            "u19_projected_sha256": getattr(projected, "payload_sha256", None),
            "u19_broker_sha256": getattr(broker, "payload_sha256", None),
            "quantity_delta": list(delta),
            "cost_basis_status": "UNVERIFIED",
            "migration_applied": False,
        }
        digest = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        unique_issues = tuple(dict.fromkeys(issues))
        return ValidationOnlyPositionMigrationResult(
            status="VALIDATION_ONLY_QUANTITY_MIGRATION_RECONCILED" if not unique_issues else "RECONCILIATION_REQUIRED",
            issues=unique_issues,
            manifest=manifest,
            manifest_sha256=digest if not unique_issues else None,
            quantity_delta=delta,
        )
