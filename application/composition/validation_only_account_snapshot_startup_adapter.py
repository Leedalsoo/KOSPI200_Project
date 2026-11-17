"""Validation-only startup reconciliation adapter for isolated account fixtures.

This module never queries KIS or enables orders. It only validates normalized
synthetic evidence before delegating to the settlement store's existing gate.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone
import hashlib
import json
import re

from application.composition.validation_only_account_snapshot_assembler import (
    validate_account_snapshot_bundle,
)
from environments.live.settlement.sqlite_settlement_store import SettlementStoreError


@dataclass(frozen=True)
class ValidationOnlyStartupReconciliationResult:
    status: str
    issues: tuple[str, ...]
    evidence_sha256: str | None = None
    resolved: bool = False

    @property
    def is_valid(self) -> bool:
        return self.status in {
            "VALIDATION_ONLY_STARTUP_RECONCILED",
            "VALIDATION_ONLY_STARTUP_ALREADY_RECONCILED",
        }


class ValidationOnlyAccountSnapshotStartupAdapter:
    """Reconcile the startup gate only from complete validation-only evidence."""

    SOURCE = "VALIDATION_ONLY:ACCOUNT_U19_STARTUP_RECONCILIATION"

    def __init__(self, settlement_store, *, validation_only: bool = False) -> None:
        if validation_only is not True:
            raise ValueError("VALIDATION_ONLY_STARTUP_OPT_IN_REQUIRED")
        self.settlement_store = settlement_store

    def reconcile_startup(self, *, bundle, validation, reconciliation, baseline_import):
        issues: list[str] = []
        if not validation.is_valid or validation.as_of is None or not validation.evidence_sha256:
            return self._pending("ACCOUNT_SNAPSHOT_VALIDATION_REQUIRED")
        current = validate_account_snapshot_bundle(bundle)
        if (
            not current.is_valid
            or current.evidence_sha256 != validation.evidence_sha256
            or current.snapshot_ids != validation.snapshot_ids
            or current.as_of != validation.as_of
        ):
            return self._pending("ACCOUNT_SNAPSHOT_VALIDATION_STALE_OR_MISMATCHED")
        if not getattr(baseline_import, "is_valid", False):
            return self._pending("VALIDATION_ONLY_BASELINE_IMPORT_REQUIRED")
        if getattr(baseline_import, "startup_gate_status", None) != "PENDING":
            return self._pending("STARTUP_GATE_MUST_BE_PENDING_BEFORE_RECONCILIATION")
        if getattr(baseline_import, "source", None) != "VALIDATION_ONLY:ACCOUNT_U19_BASELINE_IMPORT":
            return self._pending("VALIDATION_ONLY_BASELINE_SOURCE_MISMATCH")
        if re.fullmatch(r"[0-9a-f]{64}", str(getattr(baseline_import, "evidence_sha256", "")).lower()) is None:
            return self._pending("VALIDATION_ONLY_BASELINE_EVIDENCE_HASH_INVALID")
        if not getattr(reconciliation, "is_valid", False) or reconciliation.issues:
            return self._pending("ACCOUNT_U19_RECONCILIATION_REQUIRED")
        if any(item is None for item in (
            reconciliation.ledger_snapshot,
            reconciliation.projected_ledger_snapshot,
            reconciliation.broker_snapshot,
            reconciliation.recovery_decision,
        )):
            return self._pending("ACCOUNT_U19_COMPLETE_EVIDENCE_REQUIRED")

        decision = reconciliation.recovery_decision
        decision_status = getattr(decision.status, "value", str(decision.status))
        if decision_status not in {"RESTORE_ALLOWED", "FLAT_CONFIRMED"}:
            return self._pending(f"ACCOUNT_U19_RECOVERY_NOT_RECONCILED:{decision_status}")
        if decision.new_entry_enabled or decision.order_submission_enabled:
            return self._pending("VALIDATION_ONLY_RECOVERY_MUST_NOT_ENABLE_ORDERS")

        ledger = reconciliation.ledger_snapshot
        projected = reconciliation.projected_ledger_snapshot
        broker = reconciliation.broker_snapshot
        snapshots = (ledger, projected, broker, *reconciliation.group_ledger_snapshots)
        expected_as_of = validation.as_of.astimezone(timezone.utc)
        for snapshot in snapshots:
            if (
                snapshot.as_of.tzinfo is None
                or snapshot.as_of.utcoffset() is None
                or snapshot.as_of.astimezone(timezone.utc) != expected_as_of
            ):
                issues.append(f"U19_SNAPSHOT_AS_OF_MISMATCH:{snapshot.snapshot_id}")
            if not str(snapshot.source).startswith("VALIDATION_ONLY:"):
                issues.append(f"U19_NON_VALIDATION_SOURCE:{snapshot.snapshot_id}")
            if re.fullmatch(r"[0-9a-f]{64}", str(snapshot.payload_sha256).lower()) is None:
                issues.append(f"U19_SNAPSHOT_SHA256_INVALID:{snapshot.snapshot_id}")
            if getattr(snapshot, "pending_order_ids", ()):
                issues.append(f"U19_PENDING_ORDERS:{snapshot.snapshot_id}")
        if projected.positions != broker.positions:
            issues.append("ACCOUNT_U19_PROJECTED_BROKER_POSITION_MISMATCH")
        if issues:
            return ValidationOnlyStartupReconciliationResult(
                status="RECONCILIATION_REQUIRED", issues=tuple(issues),
            )

        provenance = bundle.provenance
        if provenance.namespace not in {"SYNTHETIC:DERIVED_SCENARIO", "SYNTHETIC_CONTRACT:VALIDATION"}:
            return self._pending("ACCOUNT_SNAPSHOT_SYNTHETIC_NAMESPACE_REQUIRED")
        if not str(provenance.deterministic_rule_id or "").strip():
            return self._pending("ACCOUNT_SNAPSHOT_DETERMINISTIC_RULE_REQUIRED")
        if re.fullmatch(r"[0-9a-f]{64}", str(provenance.manifest_sha256 or "").lower()) is None:
            return self._pending("ACCOUNT_SNAPSHOT_MANIFEST_SHA256_REQUIRED")
        if not str(getattr(baseline_import, "evidence_sha256", "")):
            return self._pending("VALIDATION_ONLY_BASELINE_EVIDENCE_HASH_REQUIRED")

        store = self.settlement_store
        startup = next((
            item for item in store.unresolved_reconciliations()
            if item["scope_key"] == "__startup_reconciliation__"
        ), None)
        if startup is None:
            return self._pending("STARTUP_RECONCILIATION_GATE_NOT_PENDING")
        if startup["status"] == "CONFLICT":
            return self._pending("STARTUP_GATE_CONFLICT_REQUIRES_MANUAL_REVIEW")
        if startup["status"] != "PENDING":
            return self._pending(f"STARTUP_GATE_NOT_PENDING:{startup['status']}")

        inbox = store.open_reconciliation_events()
        if inbox:
            return ValidationOnlyStartupReconciliationResult(
                status="RECONCILIATION_REQUIRED",
                issues=tuple(
                    f"OPEN_RECONCILIATION_INBOX:{item['execution_id']}:{item['status']}"
                    for item in inbox
                ),
            )
        unresolved = tuple(
            item for item in store.unresolved_reconciliations()
            if item["scope_key"] != "__startup_reconciliation__"
        )
        if unresolved:
            return ValidationOnlyStartupReconciliationResult(
                status="RECONCILIATION_REQUIRED",
                issues=tuple(
                    f"OTHER_UNRESOLVED_RECONCILIATION:{item['scope_key']}:{item['status']}"
                    for item in unresolved
                ),
            )

        evidence = {
            "adapter": "validation-only-account-startup-v1",
            "source": self.SOURCE,
            "snapshot_ids": [bundle.orders.snapshot_id, bundle.executions.snapshot_id, bundle.positions.snapshot_id],
            "snapshot_hashes": [bundle.orders.payload_sha256, bundle.executions.payload_sha256, bundle.positions.payload_sha256],
            "as_of": expected_as_of.isoformat(),
            "validation_evidence_sha256": validation.evidence_sha256,
            "baseline_import_evidence_sha256": baseline_import.evidence_sha256,
            "namespace": provenance.namespace,
            "deterministic_rule_id": provenance.deterministic_rule_id,
            "manifest_sha256": provenance.manifest_sha256,
            "source_anchor_refs": list(provenance.source_anchor_refs),
            "source_anchor_as_of": (
                provenance.source_anchor_as_of.astimezone(timezone.utc).isoformat()
                if provenance.source_anchor_as_of is not None else None
            ),
            "u19_snapshot_hashes": [snapshot.payload_sha256 for snapshot in snapshots],
            "u19_group_snapshot_ids": [snapshot.snapshot_id for snapshot in reconciliation.group_ledger_snapshots],
            "recovery_status": decision_status,
            "open_inbox_count": 0,
            "other_unresolved_count": 0,
        }
        digest = hashlib.sha256(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        try:
            resolved = store.resolve_startup_reconciliation(
                orders_snapshot_id=bundle.orders.snapshot_id,
                executions_snapshot_id=bundle.executions.snapshot_id,
                positions_snapshot_id=bundle.positions.snapshot_id,
                as_of=validation.as_of,
                source=self.SOURCE,
                payload_sha256=digest,
                authoritative_evidence_ref=f"VALIDATION_ONLY:STARTUP:{digest}",
            )
        except (SettlementStoreError, ValueError) as exc:
            return self._pending(f"STARTUP_GATE_REQUIRES_RECONCILIATION:{exc}", digest)

        return ValidationOnlyStartupReconciliationResult(
            status=(
                "VALIDATION_ONLY_STARTUP_RECONCILED"
                if resolved else "VALIDATION_ONLY_STARTUP_ALREADY_RECONCILED"
            ),
            issues=(), evidence_sha256=digest, resolved=resolved,
        )

    @staticmethod
    def _pending(issue: str, evidence_sha256: str | None = None):
        return ValidationOnlyStartupReconciliationResult(
            status="RECONCILIATION_REQUIRED", issues=(issue,), evidence_sha256=evidence_sha256,
        )
