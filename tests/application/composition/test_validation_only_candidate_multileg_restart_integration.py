from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from types import SimpleNamespace

from application.composition.track2_u19_recovery import ValidationOnlyTrack2U19RecoveryCoordinator
from application.composition.validation_only_runtime_ledger_comparator import ValidationOnlyRuntimeLedgerComparator
from contracts.position_provenance import PositionLotProvenance, PositionRole
from contracts.track9_fee_ledger import Track9FeeRecord
from contracts.types import OptionInstrumentIdentity
from core.oms.track2_u19_recovery import (
    U19BrokerPositionSnapshot,
    U19ExecutionEvent,
    U19ExecutionLedgerSnapshot,
    U19Position,
    U19RecoveryStatus,
)
from environments.virtual.authoritative_vssf.firm_runtime import VirtualSecuritiesFirmRuntime
from environments.virtual.authoritative_vssf.track9_fee_ledger import VirtualTrack9FeeLedger
from environments.virtual.clock import VirtualClock
from environments.virtual.position.track2_u19_recovery_store import SqliteTrack2U19RecoveryStore
from environments.virtual.position.virtual_position_lot_store import VirtualPositionLotStore

RUN_ID = "SYNTHETIC:RUN:CANDIDATE-MULTILEG-RESTART"
CANDIDATE_ID = "S2-CANDIDATE-MULTILEG-A"
GROUP_ID = f"VALIDATION_ONLY:RUN:{RUN_ID}:CANDIDATE:{CANDIDATE_ID}"
STAMP = datetime(2026, 11, 20, 1, 0, tzinfo=timezone.utc)
MULTIPLIER = Decimal("10")
FEE = Decimal("0.1")
LEGS = {
    "put": ("SYNTHETIC_CONTRACT:RESTART-PUT", "PUT", Decimal("500")),
    "call": ("SYNTHETIC_CONTRACT:RESTART-CALL", "CALL", Decimal("510")),
}


def _digest(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(payload).hexdigest()


def _command(client_order_id, leg_id, side, quantity, *, candidate_id=CANDIDATE_ID):
    instrument_id, option_type, strike = LEGS[leg_id]
    return SimpleNamespace(
        client_order_id=client_order_id,
        track_id="S2",
        asset_type="OPTION",
        side=side,
        qty=quantity,
        price=Decimal("10"),
        requested_price=Decimal("10"),
        symbol=instrument_id,
        option_type=option_type,
        strike=strike,
        expiry="20261210",
        strategy_id="track2_asymmetric_trap",
        group_id=f"VALIDATION_ONLY:RUN:{RUN_ID}:CANDIDATE:{candidate_id}",
        leg_id=leg_id,
        instrument_id=instrument_id,
        contract_multiplier=MULTIPLIER,
        identity_source="SYNTHETIC:DERIVED_SCENARIO",
    )


def _run_integrated_lifecycle(checkpoint_path):
    clock = VirtualClock(STAMP)
    runtime = VirtualSecuritiesFirmRuntime(
        initial_capital=25_000_000,
        clock=clock,
        validation_run_id=RUN_ID,
        validation_candidate_id=CANDIDATE_ID,
    )
    lots = VirtualPositionLotStore()
    fees = VirtualTrack9FeeLedger()
    original_apply = runtime.account.apply_execution
    original_execute = runtime.execution_engine.execute_order
    event_rows = []
    fee_expectations = []

    def apply_with_candidate_ledgers(report):
        original_apply(report)
        instrument_id, option_type, strike = LEGS[report.leg_id]
        executed_at = datetime.fromisoformat(report.timestamp)
        identity = OptionInstrumentIdentity(
            instrument_id,
            instrument_id,
            "20261210",
            option_type,
            strike,
            MULTIPLIER,
            "SYNTHETIC:DERIVED_SCENARIO",
        )
        lots.apply_execution(PositionLotProvenance(
            run_id=RUN_ID,
            instrument_id=instrument_id,
            strategy_id=report.strategy_id,
            group_id=GROUP_ID,
            leg_id=report.leg_id,
            client_order_id=report.client_order_id,
            execution_id=report.exec_id,
            side=str(report.side),
            opened_quantity=report.executed_qty,
            remaining_quantity=report.executed_qty,
            execution_timestamp=executed_at,
            instrument_identity=identity,
            contract_multiplier=MULTIPLIER,
            identity_source="SYNTHETIC:DERIVED_SCENARIO",
            position_role=PositionRole.NONE,
        ))
        fees.record(Track9FeeRecord(
            run_id=RUN_ID,
            strategy_id=report.strategy_id,
            group_id=GROUP_ID,
            leg_id=report.leg_id,
            client_order_id=report.client_order_id,
            execution_id=report.exec_id,
            instrument_id=instrument_id,
            fee_amount=Decimal(str(report.fee)),
            executed_quantity=report.executed_qty,
            executed_price=Decimal(str(report.executed_price)),
            executed_at=executed_at,
            source="SYNTHETIC:FEE_FIXTURE",
        ))
        event_rows.append({
            "execution_id": report.exec_id,
            "instrument_id": instrument_id,
            "side": str(report.side),
            "quantity": report.executed_qty,
            "price": Decimal(str(report.executed_price)),
            "contract_multiplier": MULTIPLIER,
            "executed_at": executed_at,
            "fee": Decimal(str(report.fee)),
        })
        fee_expectations.append({
            "execution_id": report.exec_id,
            "fee_amount": Decimal(str(report.fee)),
            "quantity": report.executed_qty,
            "price": Decimal(str(report.executed_price)),
        })

    def execute_with_fee(command, price, quantity, *, timestamp):
        report = original_execute(command, price, quantity, timestamp=timestamp)
        report = replace(report, fee=float(FEE))
        runtime.execution_engine.reports[-1] = report
        return report

    runtime.account.apply_execution = apply_with_candidate_ledgers
    runtime.execution_engine.execute_order = execute_with_fee

    def next_time():
        clock.sleep_policy(60)
        return clock.now()

    def submit(command):
        result = runtime.process_order(command)
        assert result is not None and result.status == "NEW"
        return result

    def fill(command, price, quantity):
        return runtime._execute(command, float(price), next_time(), quantity=quantity)

    # Two-leg entry: PUT is partially filled, then the final fill wins the cancel race.
    put_entry = _command("ORDER-PUT-ENTRY", "put", "BUY", 2)
    submit(put_entry)
    fill(put_entry, "10", 1)
    assert runtime.query_order(put_entry.client_order_id).status == "PARTIALLY_FILLED"
    remove_pending = runtime.order_book.remove_pending_order

    def remove_with_late_fill(client_order_id):
        command = remove_pending(client_order_id)
        if command is not None:
            late_report = runtime.execution_engine.execute_order(
                command, 11.0, 1, timestamp=next_time(),
            )
            runtime.account.apply_execution(late_report)
        return command

    runtime.order_book.remove_pending_order = remove_with_late_fill
    cancel_race = runtime.cancel_order(put_entry.client_order_id)
    runtime.order_book.remove_pending_order = remove_pending
    assert cancel_race.status == "FILLED"
    assert cancel_race.executed_qty == 2
    assert len(cancel_race.execution_fills) == 2
    assert runtime.query_order(put_entry.client_order_id).status == "FILLED"
    assert runtime.cancel_order(put_entry.client_order_id).status == "FILLED"

    call_entry = _command("ORDER-CALL-ENTRY", "call", "BUY", 1)
    submit(call_entry)
    fill(call_entry, "20", 1)

    # Multi-leg close in partial slices, then reopen both legs and close again.
    put_close = _command("ORDER-PUT-CLOSE", "put", "SELL", 2)
    submit(put_close)
    fill(put_close, "12", 1)
    fill(put_close, "13", 1)

    call_close = _command("ORDER-CALL-CLOSE", "call", "SELL", 1)
    submit(call_close)
    fill(call_close, "22", 1)

    put_reopen = _command("ORDER-PUT-REOPEN", "put", "BUY", 1)
    submit(put_reopen)
    fill(put_reopen, "9", 1)
    call_reopen = _command("ORDER-CALL-REOPEN", "call", "BUY", 1)
    submit(call_reopen)
    fill(call_reopen, "18", 1)

    put_final_close = _command("ORDER-PUT-FINAL-CLOSE", "put", "SELL", 1)
    submit(put_final_close)
    fill(put_final_close, "10", 1)
    call_final_close = _command("ORDER-CALL-FINAL-CLOSE", "call", "SELL", 1)
    submit(call_final_close)
    fill(call_final_close, "19", 1)

    # Duplicate delivery is idempotent in the PositionLot and Fee ledgers.
    before_history = lots.history()
    before_fees = fees.snapshot(run_id=RUN_ID)
    for lot in before_history:
        lots.apply_execution(lot)
    for fee in before_fees:
        fees.record(fee)
    assert lots.history() == before_history
    assert fees.snapshot(run_id=RUN_ID) == before_fees

    # Fault injection: same execution ID with altered lot provenance must fail
    # without changing any previously reconciled lot or close event.
    before_close_events = lots.close_events()
    conflicting_lot = replace(
        before_history[0],
        opened_quantity=before_history[0].opened_quantity + 1,
    )
    try:
        lots.apply_execution(conflicting_lot)
    except ValueError as exc:
        assert str(exc) == "POSITION_PROVENANCE_DUPLICATE_CONFLICT"
    else:
        raise AssertionError("conflicting execution replay was accepted")
    assert lots.history() == before_history
    assert lots.close_events() == before_close_events

    # Fault injection: same execution ID with a changed fee must also fail
    # without mutating the candidate fee ledger.
    conflicting_fee = replace(
        before_fees[0],
        fee_amount=before_fees[0].fee_amount + Decimal("0.1"),
    )
    try:
        fees.record(conflicting_fee)
    except ValueError as exc:
        assert str(exc) == "TRACK9_FEE_DUPLICATE_CONFLICT"
    else:
        raise AssertionError("conflicting fee replay was accepted")
    assert fees.snapshot(run_id=RUN_ID) == before_fees

    assert runtime.account.positions == {}
    assert runtime.account.realized_pnl == Decimal("80.0")
    assert runtime.account.unrealized_pnl == Decimal("0")
    assert runtime.account.balance == Decimal("24999999.0")
    assert len(runtime.execution_engine.reports) == 10
    assert len(lots.history()) == 5
    assert lots.open_lots() == ()
    assert len(lots.close_events()) == 5
    assert len(fees.snapshot(run_id=RUN_ID)) == 10
    assert fees.total(run_id=RUN_ID) == Decimal("1.0")

    last_time = max(datetime.fromisoformat(rep.timestamp) for rep in runtime.execution_engine.reports)
    execution_events = tuple(
        U19ExecutionEvent(
            execution_id=rep.exec_id,
            fingerprint=_digest({
                "execution_id": rep.exec_id,
                "client_order_id": rep.client_order_id,
                "instrument_id": rep.instrument_id,
                "leg_id": rep.leg_id,
                "side": str(rep.side),
                "quantity": rep.executed_qty,
                "price": str(rep.executed_price),
                "fee": str(rep.fee),
                "timestamp": rep.timestamp,
            }),
        )
        for rep in runtime.execution_engine.reports
    )
    empty_positions = ()
    broker_payload = {"group_id": GROUP_ID, "positions": []}
    ledger_payload = {
        "group_id": GROUP_ID,
        "positions": [],
        "execution_events": [
            (item.execution_id, item.fingerprint) for item in execution_events
        ],
        "pending_order_ids": [],
    }
    broker_snapshot = U19BrokerPositionSnapshot(
        group_id=GROUP_ID,
        snapshot_id="SYNTHETIC:VSSF-ACCOUNT-FLAT",
        as_of=last_time,
        source="VALIDATION_ONLY:BROKER_EXCHANGE",
        positions=empty_positions,
        complete=True,
        capability_verified=True,
        payload_sha256=_digest(broker_payload),
    )
    ledger_snapshot = U19ExecutionLedgerSnapshot(
        group_id=GROUP_ID,
        snapshot_id="SYNTHETIC:POSITIONLOT-LEDGER-FLAT",
        as_of=last_time,
        source="VALIDATION_ONLY:EXECUTION_LEDGER",
        positions=empty_positions,
        complete=True,
        payload_sha256=_digest(ledger_payload),
        execution_events=execution_events,
        pending_order_ids=(),
    )
    recovery = ValidationOnlyTrack2U19RecoveryCoordinator(
        SqliteTrack2U19RecoveryStore(checkpoint_path)
    ).recover(
        group_id=GROUP_ID,
        broker_snapshot=broker_snapshot,
        ledger_snapshot=ledger_snapshot,
    )
    assert recovery.status is U19RecoveryStatus.FLAT_CONFIRMED
    assert recovery.positions == ()
    assert recovery.new_entry_enabled is False
    assert recovery.order_submission_enabled is False
    assert recovery.runtime_restore_performed is False
    persisted = SqliteTrack2U19RecoveryStore(checkpoint_path).load_latest(GROUP_ID)
    assert persisted is not None
    assert persisted["status"] == U19RecoveryStatus.FLAT_CONFIRMED.value
    assert persisted["broker_positions"] == persisted["ledger_positions"] == []
    assert len(persisted["execution_events"]) == 10

    source_manifest = {
        "schema_version": 1,
        "source_namespace": "SYNTHETIC:DERIVED_SCENARIO",
        "run_id": RUN_ID,
        "candidate_id": CANDIDATE_ID,
        "group_id": GROUP_ID,
        "source_decision_refs": ["No.1534", "No.1576", "No.1656"],
        "source_anchor_as_of": STAMP.isoformat(),
        "scenario_timestamp": last_time.isoformat(),
        "deterministic_rule_id": "CANDIDATE-MULTILEG-CLOSE-REOPEN-CANCEL-REPLAY-v1",
        "deterministic_seed": "candidate-multileg-restart-seed-v1",
        "no_future_anchor": True,
        "contract_assumptions": [
            {
                "instrument_id": instrument_id,
                "option_type": option_type,
                "strike": str(strike),
                "expiry": "20261210",
                "contract_multiplier": str(MULTIPLIER),
                "identity_source": "SYNTHETIC:DERIVED_SCENARIO",
            }
            for instrument_id, option_type, strike in LEGS.values()
        ],
        "fee_rule": {"fee_per_execution": str(FEE), "source": "SYNTHETIC:FEE_FIXTURE"},
        "execution_events": [
            {
                "execution_id": row["execution_id"],
                "instrument_id": row["instrument_id"],
                "side": row["side"],
                "quantity": row["quantity"],
                "price": str(row["price"]),
                "executed_at": row["executed_at"].isoformat(),
                "fee": str(row["fee"]),
            }
            for row in event_rows
        ],
    }
    source_manifest_sha256 = _digest(source_manifest)
    comparator = ValidationOnlyRuntimeLedgerComparator().compare(
        opening_lots=(),
        executions=event_rows,
        expected_fee_records=fee_expectations,
        actual_position_lot_history=lots.history(),
        actual_open_position_lots=lots.open_lots(),
        actual_close_events=lots.close_events(),
        actual_fee_records=fees.snapshot(run_id=RUN_ID),
        vssf_positions=runtime.account.positions,
        vssf_realized_pnl_delta=runtime.account.realized_pnl,
        vssf_unrealized_pnl=runtime.account.unrealized_pnl,
        mark_prices={},
        source_namespace="SYNTHETIC:DERIVED_SCENARIO",
        deterministic_rule_id="CANDIDATE-MULTILEG-CLOSE-REOPEN-CANCEL-REPLAY-v1",
        source_manifest_sha256=source_manifest_sha256,
        source_anchor_refs=("No.1534", "No.1576", "No.1656"),
        source_anchor_as_of=STAMP,
        scenario_timestamp=last_time,
        evidence_refs=("TEST:CANDIDATE-MULTILEG-RESTART",),
    )
    assert comparator.status == "VALIDATION_ONLY_RUNTIME_LEDGER_RECONCILED"
    assert comparator.issues == ()
    assert comparator.manifest["expected_vssf_average_cost_realized_pnl"] == "80.0"
    assert comparator.manifest["fifo_realized_pnl"] == "80.0"

    manifest = {
        "run_id": RUN_ID,
        "candidate_id": CANDIDATE_ID,
        "source_manifest_sha256": source_manifest_sha256,
        "group_id": GROUP_ID,
        "execution_ids": [rep.exec_id for rep in runtime.execution_engine.reports],
        "account_realized_pnl": str(runtime.account.realized_pnl),
        "account_unrealized_pnl": str(runtime.account.unrealized_pnl),
        "account_balance": str(runtime.account.balance),
        "fees_total": str(fees.total(run_id=RUN_ID)),
        "duplicate_execution_replay_idempotent": True,
        "conflicting_position_replay_rejected_without_mutation": True,
        "conflicting_fee_replay_rejected_without_mutation": True,
        "position_lot_history": [lot.execution_id for lot in lots.history()],
        "close_events": [
            (event.execution_id, event.source_lot_execution_id, event.quantity)
            for event in lots.close_events()
        ],
        "u19_status": recovery.status.value,
        "ledger_manifest_sha256": comparator.manifest_sha256,
    }
    return manifest, comparator


def test_candidate_multileg_partial_cancel_latefill_close_reopen_restart_replay(tmp_path):
    first, comparator = _run_integrated_lifecycle(tmp_path / "u19-first.sqlite3")
    replay, replay_comparator = _run_integrated_lifecycle(tmp_path / "u19-replay.sqlite3")
    assert comparator.status == replay_comparator.status
    assert comparator.manifest == replay_comparator.manifest
    assert comparator.manifest_sha256 == replay_comparator.manifest_sha256
    assert first == replay
    assert first["account_realized_pnl"] == "80.0"
    assert first["account_unrealized_pnl"] == "0"
    assert first["account_balance"] == "24999999.0"
    assert first["fees_total"] == "1.0"
    assert first["u19_status"] == U19RecoveryStatus.FLAT_CONFIRMED.value


def test_two_candidates_interleave_without_cross_scope_and_u19_pending_order_isolated(tmp_path):
    candidate_a_id = "S2-CANDIDATE-MULTILEG-A"
    candidate_b_id = "S2-CANDIDATE-MULTILEG-B"
    group_a = f"VALIDATION_ONLY:RUN:{RUN_ID}:CANDIDATE:{candidate_a_id}"
    group_b = f"VALIDATION_ONLY:RUN:{RUN_ID}:CANDIDATE:{candidate_b_id}"
    clock_a = VirtualClock(STAMP)
    clock_b = VirtualClock(STAMP)
    runtime_a = VirtualSecuritiesFirmRuntime(
        initial_capital=25_000_000, clock=clock_a,
        validation_run_id=RUN_ID, validation_candidate_id=candidate_a_id,
    )
    runtime_b = VirtualSecuritiesFirmRuntime(
        initial_capital=25_000_000, clock=clock_b,
        validation_run_id=RUN_ID, validation_candidate_id=candidate_b_id,
    )
    lots_a, lots_b = VirtualPositionLotStore(), VirtualPositionLotStore()
    fees_a, fees_b = VirtualTrack9FeeLedger(), VirtualTrack9FeeLedger()

    def apply(runtime, lots, fees, report, candidate_id):
        instrument_id, option_type, strike = LEGS[report.leg_id]
        executed_at = datetime.fromisoformat(report.timestamp)
        identity = OptionInstrumentIdentity(
            instrument_id, instrument_id, "20261210", option_type, strike,
            MULTIPLIER, "SYNTHETIC:DERIVED_SCENARIO",
        )
        group_id = f"VALIDATION_ONLY:RUN:{RUN_ID}:CANDIDATE:{candidate_id}"
        lots.apply_execution(PositionLotProvenance(
            run_id=RUN_ID, instrument_id=instrument_id,
            strategy_id=report.strategy_id, group_id=group_id,
            leg_id=report.leg_id, client_order_id=report.client_order_id,
            execution_id=report.exec_id, side=str(report.side),
            opened_quantity=report.executed_qty,
            remaining_quantity=report.executed_qty,
            execution_timestamp=executed_at, instrument_identity=identity,
            contract_multiplier=MULTIPLIER,
            identity_source="SYNTHETIC:DERIVED_SCENARIO",
            position_role=PositionRole.NONE,
        ))
        fees.record(Track9FeeRecord(
            run_id=RUN_ID, strategy_id=report.strategy_id,
            group_id=group_id, leg_id=report.leg_id,
            client_order_id=report.client_order_id,
            execution_id=report.exec_id, instrument_id=instrument_id,
            fee_amount=FEE, executed_quantity=report.executed_qty,
            executed_price=Decimal(str(report.executed_price)),
            executed_at=executed_at, source="SYNTHETIC:FEE_FIXTURE",
        ))

    def submit_fill(runtime, clock, lots, fees, command, price, qty, candidate_id):
        assert runtime.process_order(command).status == "NEW"
        clock.sleep_policy(60)
        report = runtime._execute(command, float(price), clock.now(), quantity=qty)
        apply(runtime, lots, fees, report, candidate_id)
        return report

    # Interleave A's partial entry with B's complete open/close lifecycle.
    a_order = _command("ORDER-A-PENDING", "put", "BUY", 2, candidate_id=candidate_a_id)
    a_fill = submit_fill(runtime_a, clock_a, lots_a, fees_a, a_order, "10", 1, candidate_a_id)
    assert runtime_a.query_order(a_order.client_order_id).status == "PARTIALLY_FILLED"

    b_entry = _command("ORDER-B-ENTRY", "call", "BUY", 1, candidate_id=candidate_b_id)
    b_entry_fill = submit_fill(runtime_b, clock_b, lots_b, fees_b, b_entry, "20", 1, candidate_b_id)
    b_close = _command("ORDER-B-CLOSE", "call", "SELL", 1, candidate_id=candidate_b_id)
    b_close_fill = submit_fill(runtime_b, clock_b, lots_b, fees_b, b_close, "22", 1, candidate_b_id)

    assert runtime_a.account.positions
    assert runtime_a.account.realized_pnl == Decimal("0")
    assert runtime_b.account.positions == {}
    assert runtime_b.account.realized_pnl == Decimal("20.0")
    assert len(lots_a.history()) == 1 and len(lots_b.history()) == 1
    assert len(lots_a.close_events()) == 0 and len(lots_b.close_events()) == 1
    assert len(fees_a.snapshot(run_id=RUN_ID)) == 1
    assert len(fees_b.snapshot(run_id=RUN_ID)) == 2
    assert lots_a.history()[0].group_id == group_a
    assert all(lot.group_id == group_b for lot in lots_b.history())

    # Candidate A has a partial/unknown order; candidate B is independently flat.
    as_of = max(
        datetime.fromisoformat(a_fill.timestamp),
        datetime.fromisoformat(b_entry_fill.timestamp),
        datetime.fromisoformat(b_close_fill.timestamp),
    )
    a_position = (U19Position(LEGS["put"][0], Decimal("1")),)
    a_broker = U19BrokerPositionSnapshot(
        group_id=group_a, snapshot_id="SYNTHETIC:A-BROKER-PENDING",
        as_of=as_of, source="VALIDATION_ONLY:BROKER_EXCHANGE",
        positions=a_position, complete=True, capability_verified=True,
        payload_sha256=_digest({"group_id": group_a, "positions": [(LEGS["put"][0], "1")]}),
    )
    a_ledger = U19ExecutionLedgerSnapshot(
        group_id=group_a, snapshot_id="SYNTHETIC:A-LEDGER-PENDING",
        as_of=as_of, source="VALIDATION_ONLY:EXECUTION_LEDGER",
        positions=a_position, complete=True,
        payload_sha256=_digest({"group_id": group_a, "positions": [(LEGS["put"][0], "1")]}),
        execution_events=(U19ExecutionEvent(a_fill.exec_id, _digest({"execution_id": a_fill.exec_id})),),
        pending_order_ids=(a_order.client_order_id,),
    )
    b_broker = U19BrokerPositionSnapshot(
        group_id=group_b, snapshot_id="SYNTHETIC:B-BROKER-FLAT",
        as_of=as_of, source="VALIDATION_ONLY:BROKER_EXCHANGE",
        positions=(), complete=True, capability_verified=True,
        payload_sha256=_digest({"group_id": group_b, "positions": []}),
    )
    b_ledger = U19ExecutionLedgerSnapshot(
        group_id=group_b, snapshot_id="SYNTHETIC:B-LEDGER-FLAT",
        as_of=as_of, source="VALIDATION_ONLY:EXECUTION_LEDGER",
        positions=(), complete=True,
        payload_sha256=_digest({"group_id": group_b, "positions": []}),
        execution_events=tuple(
            U19ExecutionEvent(report.exec_id, _digest({"execution_id": report.exec_id}))
            for report in (b_entry_fill, b_close_fill)
        ),
        pending_order_ids=(),
    )
    decision_a = ValidationOnlyTrack2U19RecoveryCoordinator(
        SqliteTrack2U19RecoveryStore(tmp_path / "candidate-a-u19.sqlite3")
    ).recover(group_id=group_a, broker_snapshot=a_broker, ledger_snapshot=a_ledger)
    decision_b = ValidationOnlyTrack2U19RecoveryCoordinator(
        SqliteTrack2U19RecoveryStore(tmp_path / "candidate-b-u19.sqlite3")
    ).recover(group_id=group_b, broker_snapshot=b_broker, ledger_snapshot=b_ledger)

    assert decision_a.status is U19RecoveryStatus.PENDING_ORDER_RECONCILIATION_REQUIRED
    assert decision_a.pending_order_ids == (a_order.client_order_id,)
    assert decision_a.restore_allowed is False
    assert decision_a.new_entry_enabled is False
    assert decision_a.order_submission_enabled is False
    assert decision_b.status is U19RecoveryStatus.FLAT_CONFIRMED
    assert decision_b.pending_order_ids == ()
    assert decision_b.restore_allowed is True
    assert decision_b.strategy_resume_allowed is True
    assert decision_b.new_entry_enabled is False
    assert decision_b.order_submission_enabled is False
    assert SqliteTrack2U19RecoveryStore(tmp_path / "candidate-a-u19.sqlite3").load_latest(group_a)["pending_order_ids"] == [a_order.client_order_id]
    assert SqliteTrack2U19RecoveryStore(tmp_path / "candidate-b-u19.sqlite3").load_latest(group_b)["pending_order_ids"] == []
