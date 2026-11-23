from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from types import SimpleNamespace

import pytest

from application.composition.track2_u16_runtime_coordinator import ValidationOnlyU16RuntimeCoordinator
from application.composition.track2_u19_recovery import ValidationOnlyTrack2U19RecoveryCoordinator
from core.oms.track2_u19_recovery import (
    U19BrokerPositionSnapshot,
    U19ExecutionEvent,
    U19ExecutionLedgerSnapshot,
    U19Position,
    U19RecoveryStatus,
)
from core.strategy.track2_u16_repair_lifecycle import U16Fill, U16QuotePolicy, U16RepairInput, U16RepairState
from environments.virtual.position.track2_u16_runtime_store import SqliteTrack2U16RuntimeStore
from environments.virtual.position.track2_u19_recovery_store import SqliteTrack2U19RecoveryStore


T0 = datetime(2026, 11, 23, 9, 0, tzinfo=timezone(timedelta(hours=9)))
GROUP_ID = "S4-MINI-SYNTHETIC-GROUP-01"
LEG_ID = "s4-mini-futures-hedge"
INSTRUMENT_ID = "SYNTHETIC_CONTRACT:S4_MINI_FUTURES_NEAR"
POLICY = U16QuotePolicy(
    validated=True,
    side_to_book_rule="VALIDATION_ONLY",
    max_quote_age_seconds=5,
    max_spread="0.1",
    spread_unit="PRICE",
    fallback_formula="VALIDATION_ONLY",
    fallback_priority="VALIDATION_ONLY",
    tick_rounding_rule="VALIDATION_ONLY",
    retry_interval_seconds=30,
)


def _repair_input(*, now=T0):
    return U16RepairInput(
        group_id=GROUP_ID,
        leg_id=LEG_ID,
        target_quantity=5,
        original_order_terminal=True,
        original_order_cancelled_or_closed=True,
        original_order_status="CANCELLED",
        fills=(U16Fill("S4-EXECUTION-001", 2),),
        position_quantity=2,
        now=now,
        quote_policy=POLICY,
        quote_present=True,
        quote_fresh=True,
        quote_spread_within_policy=True,
    )


def _recovery_snapshots(*, broker_quantity=Decimal("-2"), ledger_quantity=Decimal("-2")):
    as_of = T0 + timedelta(seconds=1)
    broker_positions = (U19Position(INSTRUMENT_ID, broker_quantity),)
    ledger_positions = (U19Position(INSTRUMENT_ID, ledger_quantity),)
    event = U19ExecutionEvent(
        "S4-EXECUTION-001",
        sha256(b"S4-EXECUTION-001|SELL|2|1000").hexdigest(),
    )
    broker = U19BrokerPositionSnapshot(
        group_id=GROUP_ID,
        snapshot_id="S4-U19-BROKER-RESTART",
        as_of=as_of,
        source="VALIDATION_ONLY:BROKER_EXCHANGE",
        positions=broker_positions,
        complete=True,
        capability_verified=True,
        payload_sha256=sha256(b"S4-BROKER-POSITIONS").hexdigest(),
    )
    ledger = U19ExecutionLedgerSnapshot(
        group_id=GROUP_ID,
        snapshot_id="S4-U19-LEDGER-RESTART",
        as_of=as_of,
        source="VALIDATION_ONLY:EXECUTION_LEDGER",
        positions=ledger_positions,
        complete=True,
        payload_sha256=sha256(b"S4-LEDGER-POSITIONS").hexdigest(),
        execution_events=(event,),
        pending_order_ids=(),
    )
    return broker, ledger


def test_s4_group_u16_retry_state_restores_only_after_real_u19_and_never_blind_retries(tmp_path):
    u16_store = SqliteTrack2U16RuntimeStore(tmp_path / "s4-u16.sqlite3")
    first_submissions = []
    first = ValidationOnlyU16RuntimeCoordinator(
        validation_only=True,
        submit_repair=lambda group, leg, qty, client_id, now: (
            first_submissions.append((group, leg, qty, client_id))
            or SimpleNamespace(client_order_id="S4-U16-REPAIR-001", terminal=False, reconciled=False)
        ),
        submit_flatten=lambda *args: pytest.fail("unexpected S4 flatten"),
        state_store=u16_store,
    )
    initial = first.process(_repair_input())
    assert initial.action == "REPAIR_SUBMITTED"
    assert initial.submitted_quantity == 3
    assert first_submissions[0][:3] == (GROUP_ID, LEG_ID, 3)

    restarted_submissions = []
    restarted = ValidationOnlyU16RuntimeCoordinator(
        validation_only=True,
        submit_repair=lambda *args: (
            restarted_submissions.append(args)
            or SimpleNamespace(client_order_id=args[3], terminal=True, reconciled=True)
        ),
        submit_flatten=lambda *args: pytest.fail("unexpected S4 flatten"),
        state_store=u16_store,
    )
    broker, ledger = _recovery_snapshots()
    recovery = ValidationOnlyTrack2U19RecoveryCoordinator(
        SqliteTrack2U19RecoveryStore(tmp_path / "s4-u19.sqlite3")
    )
    decision, restored = recovery.recover_and_restore_u16_runtime(
        group_id=GROUP_ID,
        broker_snapshot=broker,
        ledger_snapshot=ledger,
        u16_runtime=restarted,
    )
    assert decision.status is U19RecoveryStatus.RESTORE_ALLOWED
    assert decision.restore_allowed is True
    assert decision.strategy_resume_allowed is True
    assert decision.new_entry_enabled is False
    assert decision.order_submission_enabled is False
    assert restored is True

    waiting = restarted.process(_repair_input(now=T0 + timedelta(seconds=30)))
    assert waiting.action == "NO_SUBMISSION"
    assert waiting.evaluation.state is U16RepairState.REPAIR_WAITING
    assert restarted_submissions == []

    restarted.record_repair_reconciliation(GROUP_ID, LEG_ID, terminal=True, reconciled=True)
    retry = restarted.process(_repair_input(now=T0 + timedelta(seconds=30)))
    assert retry.action == "REPAIR_SUBMITTED"
    assert retry.submitted_quantity == 3
    assert len(restarted_submissions) == 1
    assert restarted_submissions[0][0:3] == (GROUP_ID, LEG_ID, 3)


def test_s4_u16_restore_is_denied_when_u19_broker_and_ledger_positions_conflict(tmp_path):
    u16_store = SqliteTrack2U16RuntimeStore(tmp_path / "s4-u16-conflict.sqlite3")
    first = ValidationOnlyU16RuntimeCoordinator(
        validation_only=True,
        submit_repair=lambda group, leg, qty, client_id, now: SimpleNamespace(
            client_order_id="S4-U16-REPAIR-001", terminal=False, reconciled=False
        ),
        submit_flatten=lambda *args: pytest.fail("unexpected S4 flatten"),
        state_store=u16_store,
    )
    assert first.process(_repair_input()).action == "REPAIR_SUBMITTED"

    restarted = ValidationOnlyU16RuntimeCoordinator(
        validation_only=True,
        submit_repair=lambda *args: pytest.fail("U19 conflict must prevent restore"),
        submit_flatten=lambda *args: pytest.fail("unexpected S4 flatten"),
        state_store=u16_store,
    )
    broker, ledger = _recovery_snapshots(
        broker_quantity=Decimal("-2"), ledger_quantity=Decimal("-1")
    )
    recovery = ValidationOnlyTrack2U19RecoveryCoordinator(
        SqliteTrack2U19RecoveryStore(tmp_path / "s4-u19-conflict.sqlite3")
    )
    decision, restored = recovery.recover_and_restore_u16_runtime(
        group_id=GROUP_ID,
        broker_snapshot=broker,
        ledger_snapshot=ledger,
        u16_runtime=restarted,
    )
    assert decision.status is not U19RecoveryStatus.RESTORE_ALLOWED
    assert decision.restore_allowed is False
    assert restored is False
    assert restarted.snapshot() == {}