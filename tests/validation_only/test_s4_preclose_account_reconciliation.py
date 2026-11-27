from datetime import UTC, datetime
from types import SimpleNamespace

from application.composition.validation_only_s4_preclose_reconciler import (
    ValidationOnlyS4PrecloseReconciler,
)

AS_OF = datetime(2026, 11, 27, 9, 10, tzinfo=UTC)


def _evidence(*, broker=None, ledger=None, pending=(), lots=None, as_of=AS_OF):
    return SimpleNamespace(
        account_id="SYNTHETIC:ACCOUNT-1",
        run_id="SYNTHETIC:RUN-1",
        candidate_id="SYNTHETIC:CANDIDATE-1",
        as_of=as_of,
        source="SYNTHETIC:ACCOUNT_SNAPSHOT",
        broker_positions=broker if broker is not None else {"MINI-1": -4},
        ledger_positions=ledger if ledger is not None else {"MINI-1": -4},
        position_lots=lots if lots is not None else (
            SimpleNamespace(account_id="SYNTHETIC:ACCOUNT-1", run_id="SYNTHETIC:RUN-1", candidate_id="SYNTHETIC:CANDIDATE-1", strategy_id="S4", group_id="G1", instrument_id="MINI-1", signed_quantity=-4),
        ),
        pending_orders=pending,
    )


def test_preclose_passes_when_account_snapshot_ledger_and_all_lots_reconcile():
    result = ValidationOnlyS4PrecloseReconciler().reconcile(
        evidence=_evidence(), strategy_id="S4", group_id="G1", instrument_id="MINI-1"
    )
    assert result.status == "PRE_CLOSE_RECONCILED"
    assert result.group_signed_quantity == -4
    assert result.close_quantity == 4
    assert result.account_signed_quantity == -4


def test_preclose_rejects_broker_ledger_position_mismatch():
    result = ValidationOnlyS4PrecloseReconciler().reconcile(
        evidence=_evidence(ledger={"MINI-1": -5}), strategy_id="S4", group_id="G1", instrument_id="MINI-1"
    )
    assert result.status == "RECONCILIATION_REQUIRED"
    assert "BROKER_LEDGER_POSITION_MISMATCH" in result.issues
    assert result.close_quantity == 0


def test_preclose_rejects_account_aggregate_mismatch_against_position_lots():
    result = ValidationOnlyS4PrecloseReconciler().reconcile(
        evidence=_evidence(broker={"MINI-1": -3}), strategy_id="S4", group_id="G1", instrument_id="MINI-1"
    )
    assert "BROKER_POSITION_LOT_AGGREGATE_MISMATCH" in result.issues
    assert result.close_quantity == 0


def test_preclose_blocks_unknown_or_pending_order_without_netting_it():
    pending = (SimpleNamespace(status="UNKNOWN", account_id="SYNTHETIC:ACCOUNT-1", run_id="SYNTHETIC:RUN-1", candidate_id="SYNTHETIC:CANDIDATE-1", strategy_id="S4", group_id="G1", instrument_id="MINI-1", remaining_quantity=2),)
    result = ValidationOnlyS4PrecloseReconciler().reconcile(
        evidence=_evidence(pending=pending), strategy_id="S4", group_id="G1", instrument_id="MINI-1"
    )
    assert result.status == "RECONCILIATION_REQUIRED"
    assert "PENDING_OR_UNKNOWN_ORDER_REQUIRES_RECONCILIATION" in result.issues
    assert result.close_quantity == 0


def test_preclose_aggregates_other_groups_before_comparing_account_position():
    lots = (
        SimpleNamespace(account_id="SYNTHETIC:ACCOUNT-1", run_id="SYNTHETIC:RUN-1", candidate_id="SYNTHETIC:CANDIDATE-1", strategy_id="S4", group_id="G1", instrument_id="MINI-1", signed_quantity=-4),
        SimpleNamespace(account_id="SYNTHETIC:ACCOUNT-1", run_id="SYNTHETIC:RUN-1", candidate_id="SYNTHETIC:CANDIDATE-1", strategy_id="S3", group_id="G2", instrument_id="MINI-1", signed_quantity=1),
    )
    result = ValidationOnlyS4PrecloseReconciler().reconcile(
        evidence=_evidence(broker={"MINI-1": -3}, ledger={"MINI-1": -3}, lots=lots),
        strategy_id="S4", group_id="G1", instrument_id="MINI-1"
    )
    assert result.status == "PRE_CLOSE_RECONCILED"
    assert result.account_signed_quantity == -3
    assert result.group_signed_quantity == -4
    assert result.close_quantity == 4


def test_preclose_rejects_scope_mismatch_and_naive_snapshot_time():
    bad_lot = SimpleNamespace(account_id="SYNTHETIC:OTHER", run_id="SYNTHETIC:RUN-1", candidate_id="SYNTHETIC:CANDIDATE-1", strategy_id="S4", group_id="G1", instrument_id="MINI-1", signed_quantity=-4)
    result = ValidationOnlyS4PrecloseReconciler().reconcile(
        evidence=_evidence(lots=(bad_lot,)), strategy_id="S4", group_id="G1", instrument_id="MINI-1"
    )
    assert "POSITION_LOT_SCOPE_MISMATCH" in result.issues
    naive = datetime.fromisoformat("2026-11-27T09:10:00")
    result = ValidationOnlyS4PrecloseReconciler().reconcile(
        evidence=_evidence(as_of=naive), strategy_id="S4", group_id="G1", instrument_id="MINI-1"
    )
    assert "SNAPSHOT_AS_OF_TIME_INVALID" in result.issues

