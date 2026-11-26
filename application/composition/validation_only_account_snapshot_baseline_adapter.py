"""Validation-only bridge from reconciled account snapshots to SQLite baseline import.

This adapter is intentionally not wired into Live composition. Synthetic evidence
may exercise the bootstrap importer, but it must never resolve the per-startup gate.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone
from decimal import Decimal
import hashlib
import json
import re

from application.composition.validation_only_account_snapshot_assembler import (
    validate_account_snapshot_bundle,
)


class ValidationOnlyBaselineImportError(ValueError):
    """Raised when a validation-only snapshot cannot safely seed an isolated baseline."""


@dataclass(frozen=True)
class ValidationOnlyBaselineImportResult:
    status: str
    evidence_sha256: str
    imported_position_count: int
    startup_gate_status: str
    source: str = "VALIDATION_ONLY:ACCOUNT_U19_BASELINE_IMPORT"

    @property
    def is_valid(self) -> bool:
        return self.status in {
            "VALIDATION_ONLY_BASELINE_IMPORTED_STARTUP_PENDING",
            "VALIDATION_ONLY_BASELINE_ALREADY_IMPORTED",
            "VALIDATION_ONLY_BASELINE_GENERATION_REPLACED_STARTUP_PENDING",
        }


class ValidationOnlyAccountSnapshotBaselineAdapter:
    """Explicit opt-in adapter for isolated synthetic validation stores only."""

    SOURCE = "VALIDATION_ONLY:ACCOUNT_U19_BASELINE_IMPORT"

    def __init__(self, settlement_store, *, validation_only: bool = False) -> None:
        if validation_only is not True:
            raise ValidationOnlyBaselineImportError("VALIDATION_ONLY_BASELINE_OPT_IN_REQUIRED")
        self.settlement_store = settlement_store

    def import_reconciled_snapshot(
        self, *, bundle, validation, reconciliation,
        expected_previous_evidence_sha256: str | None = None,
        reset_reason: str | None = None,
    ) -> ValidationOnlyBaselineImportResult:
        if not validation.is_valid or validation.as_of is None or not validation.evidence_sha256:
            raise ValidationOnlyBaselineImportError("ACCOUNT_SNAPSHOT_VALIDATION_REQUIRED")
        current_validation = validate_account_snapshot_bundle(bundle)
        if (
            not current_validation.is_valid
            or current_validation.evidence_sha256 != validation.evidence_sha256
            or current_validation.snapshot_ids != validation.snapshot_ids
            or current_validation.as_of != validation.as_of
        ):
            raise ValidationOnlyBaselineImportError("ACCOUNT_SNAPSHOT_VALIDATION_STALE_OR_MISMATCHED")
        if not reconciliation.is_valid or reconciliation.issues:
            raise ValidationOnlyBaselineImportError("ACCOUNT_U19_RECONCILIATION_REQUIRED")
        if any(item is None for item in (
            reconciliation.ledger_snapshot,
            reconciliation.projected_ledger_snapshot,
            reconciliation.broker_snapshot,
            reconciliation.recovery_decision,
        )):
            raise ValidationOnlyBaselineImportError("ACCOUNT_U19_COMPLETE_EVIDENCE_REQUIRED")

        decision = reconciliation.recovery_decision
        decision_status = getattr(decision.status, "value", str(decision.status))
        if decision_status not in {"RESTORE_ALLOWED", "FLAT_CONFIRMED"}:
            raise ValidationOnlyBaselineImportError("ACCOUNT_U19_RECOVERY_NOT_RECONCILED")
        if decision.new_entry_enabled or decision.order_submission_enabled:
            raise ValidationOnlyBaselineImportError("VALIDATION_ONLY_RECOVERY_MUST_NOT_ENABLE_ORDERS")

        ledger = reconciliation.ledger_snapshot
        projected = reconciliation.projected_ledger_snapshot
        broker = reconciliation.broker_snapshot
        if projected.positions != broker.positions:
            raise ValidationOnlyBaselineImportError("ACCOUNT_U19_PROJECTED_BROKER_POSITION_MISMATCH")

        expected_bundle_positions: dict[str, Decimal] = {}
        for row in validation.normalized_positions:
            instrument_id = str(row["instrument_id"])
            quantity = Decimal(str(row["qty"]))
            side = str(row.get("side") or "").upper()
            if side == "LONG":
                signed_quantity = quantity
            elif side == "SHORT":
                signed_quantity = -quantity
            else:
                signed_quantity = Decimal(0)
            if signed_quantity:
                expected_bundle_positions[instrument_id] = signed_quantity

        for positions in (
            projected.positions,
            broker.positions,
            decision.positions,
        ):
            observed_positions: dict[str, Decimal] = {}
            for position in positions:
                if position.instrument_id in observed_positions:
                    raise ValidationOnlyBaselineImportError("ACCOUNT_U19_BUNDLE_POSITION_MISMATCH")
                observed_positions[position.instrument_id] = position.signed_quantity
            if observed_positions != expected_bundle_positions:
                raise ValidationOnlyBaselineImportError("ACCOUNT_U19_BUNDLE_POSITION_MISMATCH")

        expected_as_of = validation.as_of.astimezone(timezone.utc)
        if any(
            item.as_of.tzinfo is None
            or item.as_of.utcoffset() is None
            or item.as_of.astimezone(timezone.utc) != expected_as_of
            for item in (ledger, projected, broker)
        ):
            raise ValidationOnlyBaselineImportError("ACCOUNT_U19_BASELINE_AS_OF_MISMATCH")

        provenance = bundle.provenance
        namespace = str(provenance.namespace or "")
        if not namespace.startswith(("SYNTHETIC:", "SYNTHETIC_CONTRACT:")):
            raise ValidationOnlyBaselineImportError("ACCOUNT_SNAPSHOT_SYNTHETIC_NAMESPACE_REQUIRED")
        sections = (bundle.orders, bundle.executions, bundle.positions, bundle.opening_positions)
        if any(not str(section.source or "").startswith("VALIDATION_ONLY:") for section in sections):
            raise ValidationOnlyBaselineImportError("ACCOUNT_SNAPSHOT_NON_VALIDATION_SOURCE_REJECTED")
        if re.fullmatch(r"[0-9a-f]{64}", str(provenance.manifest_sha256 or "").lower()) is None:
            raise ValidationOnlyBaselineImportError("ACCOUNT_SNAPSHOT_MANIFEST_SHA256_REQUIRED")
        if not str(provenance.deterministic_rule_id or "").strip():
            raise ValidationOnlyBaselineImportError("ACCOUNT_SNAPSHOT_DETERMINISTIC_RULE_REQUIRED")

        evidence_payload = {
            "adapter": "validation-only-account-baseline-v1",
            "validation_evidence_sha256": validation.evidence_sha256,
            "snapshot_ids": list(validation.snapshot_ids),
            "as_of": expected_as_of.isoformat(),
            "namespace": namespace,
            "deterministic_rule_id": provenance.deterministic_rule_id,
            "manifest_sha256": str(provenance.manifest_sha256).lower(),
            "source_anchor_refs": list(provenance.source_anchor_refs),
            "source_anchor_as_of": (
                provenance.source_anchor_as_of.astimezone(timezone.utc).isoformat()
                if provenance.source_anchor_as_of is not None else None
            ),
            "u19_ledger_sha256": ledger.payload_sha256,
            "u19_projected_ledger_sha256": projected.payload_sha256,
            "u19_broker_snapshot_sha256": broker.payload_sha256,
            "u19_group_ledger_sha256": [item.payload_sha256 for item in reconciliation.group_ledger_snapshots],
            "u19_recovery_status": decision_status,
        }
        evidence_sha256 = hashlib.sha256(
            json.dumps(evidence_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        positions_payload = validation.baseline_positions_payload()

        store = self.settlement_store
        existing = store.authoritative_baseline_evidence()
        if existing is not None:
            same_evidence = (
                existing.get("source") == self.SOURCE
                and existing.get("payload_sha256") == evidence_sha256
                and existing.get("orders_snapshot_id") == bundle.orders.snapshot_id
                and existing.get("executions_snapshot_id") == bundle.executions.snapshot_id
                and existing.get("positions_snapshot_id") == bundle.positions.snapshot_id
                and existing.get("as_of") == validation.as_of.isoformat()
            )
            if not same_evidence:
                if not expected_previous_evidence_sha256 or not str(reset_reason or "").strip():
                    raise ValidationOnlyBaselineImportError(
                        "BASELINE_EVIDENCE_IDEMPOTENCY_CONFLICT"
                    )
                try:
                    store.replace_validation_only_baseline_snapshot(
                        positions_payload=positions_payload,
                        orders_snapshot_id=bundle.orders.snapshot_id,
                        executions_snapshot_id=bundle.executions.snapshot_id,
                        positions_snapshot_id=bundle.positions.snapshot_id,
                        as_of=validation.as_of,
                        source=self.SOURCE,
                        payload_sha256=evidence_sha256,
                        authoritative_evidence_ref=f"VALIDATION_ONLY:ACCOUNT_U19_BASELINE:{evidence_sha256}",
                        expected_previous_payload_sha256=expected_previous_evidence_sha256,
                        reset_reason=reset_reason,
                    )
                except Exception as exc:
                    raise ValidationOnlyBaselineImportError(str(exc)) from exc
                return ValidationOnlyBaselineImportResult(
                    status="VALIDATION_ONLY_BASELINE_GENERATION_REPLACED_STARTUP_PENDING",
                    evidence_sha256=evidence_sha256,
                    imported_position_count=len(positions_payload),
                    startup_gate_status="PENDING",
                )
            if expected_previous_evidence_sha256 is not None or reset_reason is not None:
                raise ValidationOnlyBaselineImportError(
                    "BASELINE_RESET_NOT_REQUIRED_FOR_IDENTICAL_EVIDENCE"
                )
            startup_status = store.reconciliation_status("__startup_reconciliation__")
            return ValidationOnlyBaselineImportResult(
                status="VALIDATION_ONLY_BASELINE_ALREADY_IMPORTED",
                evidence_sha256=evidence_sha256,
                imported_position_count=len(positions_payload),
                startup_gate_status=startup_status or "UNREGISTERED",
            )

        if expected_previous_evidence_sha256 is not None or reset_reason is not None:
            raise ValidationOnlyBaselineImportError(
                "BASELINE_RESET_REQUIRES_EXISTING_BASELINE_EVIDENCE"
            )
        store.ensure_authoritative_baseline_gate()
        unresolved = store.unresolved_reconciliations()
        if any(
            item["scope_key"] == "__startup_reconciliation__" and item["status"] == "CONFLICT"
            for item in unresolved
        ):
            raise ValidationOnlyBaselineImportError("STARTUP_GATE_CONFLICT_REQUIRES_MANUAL_REVIEW")

        store.establish_authoritative_baseline_snapshot(
            positions_payload=positions_payload,
            orders_snapshot_id=bundle.orders.snapshot_id,
            executions_snapshot_id=bundle.executions.snapshot_id,
            positions_snapshot_id=bundle.positions.snapshot_id,
            as_of=validation.as_of,
            source=self.SOURCE,
            payload_sha256=evidence_sha256,
            authoritative_evidence_ref=f"VALIDATION_ONLY:ACCOUNT_U19_BASELINE:{evidence_sha256}",
        )
        # Bootstrap is imported for fixture validation; the distinct startup gate stays pending.
        store.mark_startup_reconciliation_pending()
        startup = next((
            item for item in store.unresolved_reconciliations()
            if item["scope_key"] == "__startup_reconciliation__"
        ), None)
        if startup is None or startup["status"] != "PENDING":
            raise ValidationOnlyBaselineImportError("STARTUP_GATE_NOT_PENDING_AFTER_VALIDATION_IMPORT")

        return ValidationOnlyBaselineImportResult(
            status="VALIDATION_ONLY_BASELINE_IMPORTED_STARTUP_PENDING",
            evidence_sha256=evidence_sha256,
            imported_position_count=len(positions_payload),
            startup_gate_status="PENDING",
        )
