from datetime import datetime, timedelta, timezone
from decimal import Decimal
import sqlite3

import pytest

from application.composition.track2_u19_recovery import ValidationOnlyTrack2U19RecoveryCoordinator
from core.oms.track2_u19_recovery import (
    U19BrokerPositionSnapshot,
    U19ExecutionEvent,
    U19ExecutionLedgerSnapshot,
    U19Position,
    U19RecoveryStatus,
    evaluate_u19_recovery,
)
from environments.virtual.position.track2_u19_recovery_store import SqliteTrack2U19RecoveryStore


AS_OF = datetime(2026, 11, 11, 10, 0, tzinfo=timezone.utc)
GROUP = "s2-group-001"


def broker(*, positions=None, as_of=AS_OF, source="VALIDATION_ONLY:BROKER_EXCHANGE",
           complete=True, capability=True, digest="a", snapshot_id="broker-snap-1", group_id=GROUP):
    return U19BrokerPositionSnapshot(
        group_id=group_id, snapshot_id=snapshot_id, as_of=as_of, source=source,
        positions=tuple(positions if positions is not None else (
            U19Position("OPT-PUT-1", Decimal("-1")),
            U19Position("OPT-CALL-1", Decimal("1")),
        )),
        complete=complete, capability_verified=capability, payload_sha256=digest * 64,
    )


def ledger(*, positions=None, as_of=AS_OF, source="VALIDATION_ONLY:EXECUTION_LEDGER",
           complete=True, digest="b", snapshot_id="ledger-snap-1", group_id=GROUP,
           events=(), pending=()):
    return U19ExecutionLedgerSnapshot(
        group_id=group_id, snapshot_id=snapshot_id, as_of=as_of, source=source,
        positions=tuple(positions if positions is not None else (
            U19Position("OPT-PUT-1", Decimal("-1")),
            U19Position("OPT-CALL-1", Decimal("1")),
        )),
        complete=complete, payload_sha256=digest * 64,
        execution_events=tuple(events), pending_order_ids=tuple(pending),
    )


def test_broker_positions_are_primary_and_matching_ledger_allows_restore():
    result = evaluate_u19_recovery(group_id=GROUP, broker_snapshot=broker(), ledger_snapshot=ledger())
    assert result.status is U19RecoveryStatus.RESTORE_ALLOWED
    assert result.position_basis == "BROKER_EXCHANGE"
    assert result.restore_allowed is True
    assert result.strategy_resume_allowed is True
    assert result.new_entry_enabled is False
    assert result.order_submission_enabled is False
    assert result.runtime_restore_performed is False
    assert result.positions == broker().positions


def test_both_sources_confirming_empty_positions_is_flat():
    empty_broker = broker(positions=())
    empty_ledger = ledger(positions=())
    result = evaluate_u19_recovery(group_id=GROUP, broker_snapshot=empty_broker, ledger_snapshot=empty_ledger)
    assert result.status is U19RecoveryStatus.FLAT_CONFIRMED
    assert result.restore_allowed is True
    assert result.order_submission_enabled is False


def test_broker_ledger_mismatch_blocks_without_auto_adjustment():
    authoritative = broker(positions=(U19Position("OPT-CALL-1", Decimal("2")),))
    stored = ledger(positions=(U19Position("OPT-CALL-1", Decimal("1")),))
    result = evaluate_u19_recovery(group_id=GROUP, broker_snapshot=authoritative, ledger_snapshot=stored)
    assert result.status is U19RecoveryStatus.POSITION_LEDGER_MISMATCH
    assert result.restore_allowed is False
    assert result.strategy_resume_allowed is False
    assert result.positions == authoritative.positions
    assert result.order_submission_enabled is False


def test_broker_snapshot_is_required_and_never_replaced_by_ledger():
    result = evaluate_u19_recovery(group_id=GROUP, broker_snapshot=None, ledger_snapshot=ledger())
    assert result.status is U19RecoveryStatus.BROKER_POSITION_UNAVAILABLE
    assert result.position_basis == "UNAVAILABLE"
    assert result.restore_allowed is False


@pytest.mark.parametrize("snapshot", [
    broker(source="KIS_LIVE"),
    broker(complete=False),
    broker(capability=False),
    broker(as_of=AS_OF.replace(tzinfo=None)),
    broker(digest="z"),
    broker(snapshot_id=""),
    broker(group_id="other-group"),
])
def test_unverified_broker_snapshot_blocks(snapshot):
    result = evaluate_u19_recovery(group_id=GROUP, broker_snapshot=snapshot, ledger_snapshot=ledger())
    assert result.status is U19RecoveryStatus.BROKER_SNAPSHOT_UNVERIFIED
    assert result.restore_allowed is False


@pytest.mark.parametrize("snapshot", [
    ledger(source="LIVE_LEDGER"),
    ledger(complete=False),
    ledger(as_of=AS_OF.replace(tzinfo=None)),
    ledger(digest="z"),
    ledger(snapshot_id=""),
    ledger(group_id="other-group"),
])
def test_unverified_execution_ledger_blocks(snapshot):
    result = evaluate_u19_recovery(group_id=GROUP, broker_snapshot=broker(), ledger_snapshot=snapshot)
    assert result.status is U19RecoveryStatus.LEDGER_SNAPSHOT_UNVERIFIED
    assert result.restore_allowed is False


def test_missing_execution_ledger_blocks():
    result = evaluate_u19_recovery(group_id=GROUP, broker_snapshot=broker(), ledger_snapshot=None)
    assert result.status is U19RecoveryStatus.LEDGER_UNAVAILABLE


def test_snapshot_time_skew_blocks_without_inventing_a_tolerance():
    result = evaluate_u19_recovery(
        group_id=GROUP, broker_snapshot=broker(),
        ledger_snapshot=ledger(as_of=AS_OF + timedelta(seconds=1)),
    )
    assert result.status is U19RecoveryStatus.SNAPSHOT_AS_OF_MISMATCH


def test_pending_or_unknown_order_blocks_for_late_fill_reconciliation():
    result = evaluate_u19_recovery(
        group_id=GROUP, broker_snapshot=broker(),
        ledger_snapshot=ledger(pending=("client-order-pending",)),
    )
    assert result.status is U19RecoveryStatus.PENDING_ORDER_RECONCILIATION_REQUIRED
    assert result.restore_allowed is False


def test_duplicate_execution_id_with_same_fingerprint_is_idempotent():
    events = (U19ExecutionEvent("exec-1", "fill-fingerprint"), U19ExecutionEvent("exec-1", "fill-fingerprint"))
    result = evaluate_u19_recovery(group_id=GROUP, broker_snapshot=broker(), ledger_snapshot=ledger(events=events))
    assert result.status is U19RecoveryStatus.RESTORE_ALLOWED


def test_duplicate_execution_id_with_conflicting_fingerprint_blocks():
    events = (U19ExecutionEvent("exec-1", "fingerprint-a"), U19ExecutionEvent("exec-1", "fingerprint-b"))
    result = evaluate_u19_recovery(group_id=GROUP, broker_snapshot=broker(), ledger_snapshot=ledger(events=events))
    assert result.status is U19RecoveryStatus.EXECUTION_ID_CONFLICT


def test_duplicate_instrument_rows_and_zero_or_non_finite_quantities_block():
    cases = (
        (U19Position("OPT-1", Decimal("1")), U19Position("OPT-1", Decimal("1"))),
        (U19Position("OPT-1", Decimal("0")),),
        (U19Position("OPT-1", Decimal("NaN")),),
    )
    for positions in cases:
        result = evaluate_u19_recovery(
            group_id=GROUP, broker_snapshot=broker(positions=positions),
            ledger_snapshot=ledger(positions=positions),
        )
        assert result.status is U19RecoveryStatus.POSITION_SNAPSHOT_INVALID


def test_checkpoint_is_durable_across_coordinator_and_store_recreation(tmp_path):
    path = tmp_path / "u19-validation.sqlite3"
    first_store = SqliteTrack2U19RecoveryStore(path)
    first = ValidationOnlyTrack2U19RecoveryCoordinator(first_store).recover(
        group_id=GROUP, broker_snapshot=broker(), ledger_snapshot=ledger(),
    )
    reopened_store = SqliteTrack2U19RecoveryStore(path)
    restored = reopened_store.load_latest(GROUP)
    assert restored is not None
    assert restored["checkpoint_id"] == first.checkpoint_id
    assert restored["status"] == U19RecoveryStatus.RESTORE_ALLOWED.value
    assert restored["position_basis"] == "BROKER_EXCHANGE"
    assert restored["order_submission_enabled"] is False


def test_blocked_reconciliation_is_also_durably_recorded(tmp_path):
    store = SqliteTrack2U19RecoveryStore(tmp_path / "u19-blocked.sqlite3")
    result = ValidationOnlyTrack2U19RecoveryCoordinator(store).recover(
        group_id=GROUP, broker_snapshot=broker(),
        ledger_snapshot=ledger(positions=(U19Position("OPT-CALL-1", Decimal("9")),)),
    )
    persisted = store.load_latest(GROUP)
    assert result.status is U19RecoveryStatus.POSITION_LEDGER_MISMATCH
    assert persisted["restore_allowed"] is False
    assert persisted["reason"] == result.reason


def test_checkpoint_save_is_idempotent_but_id_conflict_is_rejected(tmp_path):
    store = SqliteTrack2U19RecoveryStore(tmp_path / "u19-idempotent.sqlite3")
    result = evaluate_u19_recovery(group_id=GROUP, broker_snapshot=broker(), ledger_snapshot=ledger())
    payload = result.to_checkpoint()
    store.save(payload)
    store.save(payload)
    conflict = dict(payload, reason="changed reason")
    with pytest.raises(ValueError, match="TRACK2_U19_CHECKPOINT_ID_CONFLICT"):
        store.save(conflict)


@pytest.mark.parametrize("statement", [
    "UPDATE track2_u19_recovery_checkpoint SET payload_json='{}'",
    "DELETE FROM track2_u19_recovery_checkpoint",
])
def test_checkpoint_store_is_append_only(tmp_path, statement):
    path = tmp_path / "u19-append-only.sqlite3"
    store = SqliteTrack2U19RecoveryStore(path)
    result = evaluate_u19_recovery(group_id=GROUP, broker_snapshot=broker(), ledger_snapshot=ledger())
    store.save(result.to_checkpoint())
    with sqlite3.connect(path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="TRACK2_U19_CHECKPOINT_APPEND_ONLY"):
            connection.execute(statement)


def test_coordinator_persists_no_order_or_new_entry_authority(tmp_path):
    store = SqliteTrack2U19RecoveryStore(tmp_path / "u19-authority.sqlite3")
    result = ValidationOnlyTrack2U19RecoveryCoordinator(store).recover(
        group_id=GROUP, broker_snapshot=broker(), ledger_snapshot=ledger(),
    )
    assert result.strategy_resume_allowed is True
    assert result.new_entry_enabled is False
    assert result.order_submission_enabled is False



def test_checkpoint_payload_tampering_is_detected(tmp_path):
    path = tmp_path / "u19-tamper.sqlite3"
    store = SqliteTrack2U19RecoveryStore(path)
    result = evaluate_u19_recovery(group_id=GROUP, broker_snapshot=broker(), ledger_snapshot=ledger())
    store.save(result.to_checkpoint())
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER track2_u19_checkpoint_no_update")
        connection.execute(
            "UPDATE track2_u19_recovery_checkpoint SET payload_json='{}' WHERE checkpoint_id=?",
            (result.checkpoint_id,),
        )
    with pytest.raises(ValueError, match="TRACK2_U19_CHECKPOINT_INTEGRITY_FAILURE"):
        store.load_latest(GROUP)



def test_checkpoint_persists_both_position_views_and_execution_dedup_state(tmp_path):
    path = tmp_path / "u19-full-state.sqlite3"
    store = SqliteTrack2U19RecoveryStore(path)
    events = (U19ExecutionEvent("exec-a", "fingerprint-a"), U19ExecutionEvent("exec-b", "fingerprint-b"))
    pending = ("client-order-unknown",)
    broker_view = broker()
    ledger_view = ledger(events=events, pending=pending)
    decision = ValidationOnlyTrack2U19RecoveryCoordinator(store).recover(
        group_id=GROUP, broker_snapshot=broker_view, ledger_snapshot=ledger_view,
    )
    persisted = SqliteTrack2U19RecoveryStore(path).load_latest(GROUP)
    assert persisted["broker_snapshot_id"] == broker_view.snapshot_id
    assert persisted["ledger_snapshot_id"] == ledger_view.snapshot_id
    assert persisted["broker_positions"] == [
        {"instrument_id": "OPT-CALL-1", "signed_quantity": "1"},
        {"instrument_id": "OPT-PUT-1", "signed_quantity": "-1"},
    ]
    assert persisted["ledger_positions"] == persisted["broker_positions"]
    assert persisted["execution_events"] == [
        {"execution_id": "exec-a", "fingerprint": "fingerprint-a"},
        {"execution_id": "exec-b", "fingerprint": "fingerprint-b"},
    ]
    assert persisted["pending_order_ids"] == list(pending)
    assert decision.status is U19RecoveryStatus.PENDING_ORDER_RECONCILIATION_REQUIRED



def test_fractional_contract_quantity_blocks():
    fractional = (U19Position("OPT-1", Decimal("0.5")),)
    result = evaluate_u19_recovery(
        group_id=GROUP, broker_snapshot=broker(positions=fractional),
        ledger_snapshot=ledger(positions=fractional),
    )
    assert result.status is U19RecoveryStatus.POSITION_SNAPSHOT_INVALID


def test_group_identity_mismatch_blocks():
    result = evaluate_u19_recovery(
        group_id=GROUP, broker_snapshot=broker(),
        ledger_snapshot=ledger(group_id="different-group"),
    )
    assert result.status is U19RecoveryStatus.LEDGER_SNAPSHOT_UNVERIFIED
