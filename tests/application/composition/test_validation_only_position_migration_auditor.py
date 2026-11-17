from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from application.composition.validation_only_position_migration_auditor import (
    ValidationOnlyPositionMigrationAuditor,
)


class FakeStore:
    def __init__(self, baseline=None, unresolved=(), startup_status="PENDING"):
        self.baseline = baseline or {
            "source": "VALIDATION_ONLY:BASELINE",
            "payload_sha256": "a" * 64,
            "positions": [{"instrument_id": "OPT_A", "side": "LONG", "qty": 1}],
        }
        self.unresolved = unresolved
        self.startup_status = startup_status

    def authoritative_baseline_evidence(self):
        return self.baseline

    def unresolved_reconciliations(self):
        return self.unresolved

    def reconciliation_status(self, scope):
        return self.startup_status if scope == "__startup_reconciliation__" else None


def make_inputs(*, opening_side="LONG", target_qty=2, projected_qty=2, issues=(), pending=(), namespace="SYNTHETIC:POSITION_MIGRATION"):
    now = datetime(2026, 11, 18, 1, 0, tzinfo=timezone.utc)
    bundle = SimpleNamespace(
        opening_positions=SimpleNamespace(rows=({"instrument_id": "OPT_A", "side": opening_side, "quantity": 1},)),
        provenance=SimpleNamespace(namespace=namespace, deterministic_rule_id="rule-v1", manifest_sha256="b" * 64, source_anchor_refs=("anchor-1",), source_anchor_as_of=now, scenario_timestamp=now),
    )
    validation = SimpleNamespace(
        is_valid=True, evidence_sha256="c" * 64, snapshot_ids=("orders-1", "fills-1", "positions-1"),
        as_of=now, normalized_positions=({"instrument_id": "OPT_A", "side": "LONG", "qty": target_qty},),
    )
    decision = SimpleNamespace(status="RESTORE_ALLOWED", new_entry_enabled=False, order_submission_enabled=False)
    ledger = SimpleNamespace(payload_sha256="d" * 64, pending_order_ids=pending)
    projected = SimpleNamespace(payload_sha256="e" * 64, positions=(SimpleNamespace(instrument_id="OPT_A", signed_quantity=Decimal(projected_qty)),))
    broker = SimpleNamespace(payload_sha256="f" * 64, positions=projected.positions)
    reconciliation = SimpleNamespace(
        is_valid=not issues, issues=issues, ledger_snapshot=ledger,
        projected_ledger_snapshot=projected, broker_snapshot=broker, recovery_decision=decision,
    )
    return bundle, validation, reconciliation


def test_position_migration_audits_opening_execution_target_without_mutating_store():
    store = FakeStore()
    bundle, validation, reconciliation = make_inputs()
    result = ValidationOnlyPositionMigrationAuditor(store, validation_only=True).audit(
        bundle=bundle, validation=validation, reconciliation=reconciliation,
    )
    assert result.is_quantity_reconciled
    assert result.manifest_sha256 and len(result.manifest_sha256) == 64
    assert result.quantity_delta == ({
        "instrument_id": "OPT_A", "previous_signed_quantity": 1,
        "target_signed_quantity": 2, "delta_signed_quantity": 1,
    },)
    assert result.cost_basis_status == "UNVERIFIED"
    assert result.migration_applied is False
    assert store.authoritative_baseline_evidence()["payload_sha256"] == "a" * 64


def test_position_migration_keeps_reconciliation_required_when_opening_baseline_differs():
    store = FakeStore()
    bundle, validation, reconciliation = make_inputs(opening_side="SHORT")
    result = ValidationOnlyPositionMigrationAuditor(store, validation_only=True).audit(
        bundle=bundle, validation=validation, reconciliation=reconciliation,
    )
    assert result.status == "RECONCILIATION_REQUIRED"
    assert "POSITION_MIGRATION_OPENING_BASELINE_CROSSWALK_MISMATCH" in result.issues
    assert result.manifest_sha256 is None


def test_position_migration_requires_u19_target_match_and_no_pending_orders():
    store = FakeStore()
    bundle, validation, reconciliation = make_inputs(projected_qty=3, pending=("ORDER_PENDING",))
    result = ValidationOnlyPositionMigrationAuditor(store, validation_only=True).audit(
        bundle=bundle, validation=validation, reconciliation=reconciliation,
    )
    assert result.status == "RECONCILIATION_REQUIRED"
    assert "POSITION_MIGRATION_U19_TARGET_QUANTITY_MISMATCH" in result.issues
    assert "POSITION_MIGRATION_PENDING_ORDERS_PRESENT" in result.issues


def test_position_migration_rejects_missing_synthetic_provenance_and_unresolved_scopes():
    store = FakeStore(unresolved=({"scope_key": "ORDER_X", "status": "PENDING"},))
    bundle, validation, reconciliation = make_inputs(namespace="")
    result = ValidationOnlyPositionMigrationAuditor(store, validation_only=True).audit(
        bundle=bundle, validation=validation, reconciliation=reconciliation,
    )
    assert result.status == "RECONCILIATION_REQUIRED"
    assert "POSITION_MIGRATION_SYNTHETIC_NAMESPACE_REQUIRED" in result.issues
    assert "POSITION_MIGRATION_UNRESOLVED_RECONCILIATION_SCOPES_PRESENT" in result.issues


def test_position_migration_requires_explicit_validation_only_opt_in():
    try:
        ValidationOnlyPositionMigrationAuditor(FakeStore())
    except ValueError as exc:
        assert str(exc) == "POSITION_MIGRATION_VALIDATION_ONLY_OPT_IN_REQUIRED"
    else:
        raise AssertionError("validation-only opt-in was not enforced")
