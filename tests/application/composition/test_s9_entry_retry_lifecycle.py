from datetime import datetime, timedelta, timezone
from dataclasses import replace
from decimal import Decimal
from types import MethodType, SimpleNamespace

import pytest

from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
from contracts.types import ExecutionFill, ExecutionLeg, ExecutionReport, MultiLegExecutionPlan, OptionInstrumentIdentity
from environments.virtual.authoritative_vssf.track9_fee_ledger import VirtualTrack9FeeLedger
from environments.virtual.position.virtual_position_lot_store import VirtualPositionLotStore

KST = timezone(timedelta(hours=9))


def _bridge_with_pending_order(submitted_at, *, expiry="20261112", cancel_filled=0):
    bridge = object.__new__(VirtualMultiLegExecutionBridge)
    put_id = OptionInstrumentIdentity("S9-PUT", "S9-PUT", expiry, "PUT",
                                      Decimal("500"), Decimal("100000"), "SYNTHETIC")
    call_id = OptionInstrumentIdentity("S9-CALL", "S9-CALL", expiry, "CALL",
                                       Decimal("500"), Decimal("100000"), "SYNTHETIC")
    put = ExecutionLeg("put", "BUY", 2, "PUT", Decimal("500"),
                       position_role="OVERNIGHT_INSURANCE", instrument_identity=put_id)
    call = ExecutionLeg("call", "BUY", 2, "CALL", Decimal("500"),
                        position_role="OVERNIGHT_INSURANCE", instrument_identity=call_id)
    plan = MultiLegExecutionPlan("S9-GROUP", "track9_event_overnight_insurance",
                                 (put, call), purpose="OVERNIGHT_INSURANCE")
    client_id = "S9-CALL-ORDER"
    report = ExecutionReport(client_id, "BROKER-1", None, "NEW", 0, 2, None, None,
                             submitted_at=submitted_at, group_id=plan.group_id, leg_id="call")
    bridge.pending_legs = {client_id: (plan, call, SimpleNamespace(client_order_id=client_id))}
    bridge.groups = {plan.group_id: [report]}
    bridge._s9_retry_schedule = {}
    bridge._s9_retry_attempts = {}
    bridge._group_plans = {plan.group_id: plan}
    calls = {"cancel": 0, "execute": []}

    def cancel(self, order_id):
        calls["cancel"] += 1
        self.pending_legs.pop(order_id, None)
        confirmed = ExecutionReport(order_id, "BROKER-1", None, "CANCELLED", cancel_filled,
                                    2 - cancel_filled, None, None,
                                    submitted_at=submitted_at, group_id=plan.group_id, leg_id="call")
        self.groups[plan.group_id] = [confirmed]
        return SimpleNamespace(reports=(confirmed,))

    def execute(self, retry_plan, *, group_plan):
        calls["execute"].append((retry_plan, group_plan))
        return SimpleNamespace(group_id=retry_plan.group_id)

    bridge.cancel_pending_order = MethodType(cancel, bridge)
    bridge.execute = MethodType(execute, bridge)
    return bridge, plan, calls


def test_s9_five_minute_timeout_cancels_confirms_then_waits_five_minutes():
    submitted = datetime(2026, 11, 9, 15, 0, tzinfo=KST)
    bridge, plan, calls = _bridge_with_pending_order(submitted, cancel_filled=1)

    assert bridge.process_s9_entry_retries(datetime(2026, 11, 9, 15, 4, 59, tzinfo=KST)) == ()
    assert calls["cancel"] == 0
    assert calls["execute"] == []

    bridge.process_s9_entry_retries(datetime(2026, 11, 9, 15, 5, tzinfo=KST))
    assert calls["cancel"] == 1
    assert calls["execute"] == []

    bridge.process_s9_entry_retries(datetime(2026, 11, 9, 15, 9, 59, tzinfo=KST))
    assert calls["execute"] == []

    bridge.process_s9_entry_retries(datetime(2026, 11, 9, 15, 10, tzinfo=KST))
    assert len(calls["execute"]) == 1
    retry_plan, group_plan = calls["execute"][0]
    assert retry_plan.legs[0].leg_id == "call"
    assert retry_plan.legs[0].side == "BUY"
    assert retry_plan.legs[0].quantity == 1
    assert retry_plan.attempt_id == "S9-RETRY-0001"
    assert group_plan is plan


def test_s9_does_not_retry_before_market_close_without_confirmed_cancel():
    submitted = datetime(2026, 11, 9, 15, 44, tzinfo=KST)
    bridge, _plan, calls = _bridge_with_pending_order(submitted)

    bridge.process_s9_entry_retries(datetime(2026, 11, 9, 15, 45, tzinfo=KST))
    assert calls["cancel"] == 1
    assert calls["execute"] == []
    assert bridge._s9_retry_schedule == {}


def test_s9_cancel_race_filled_order_is_reconciled_without_retry():
    submitted = datetime(2026, 11, 9, 15, 0, tzinfo=KST)
    bridge, plan, calls = _bridge_with_pending_order(submitted)

    def filled_during_cancel(self, order_id):
        calls["cancel"] += 1
        self.pending_legs.pop(order_id, None)
        filled = ExecutionReport(order_id, "BROKER-1", "FILL-1", "FILLED", 2, 0,
                                 Decimal("10"), datetime(2026, 11, 9, 15, 5, tzinfo=KST),
                                 submitted_at=submitted, group_id=plan.group_id, leg_id="call")
        self.groups[plan.group_id] = [filled]
        return SimpleNamespace(reports=(filled,))

    bridge.cancel_pending_order = MethodType(filled_during_cancel, bridge)
    bridge.process_s9_entry_retries(datetime(2026, 11, 9, 15, 5, tzinfo=KST))
    assert calls["cancel"] == 1
    assert calls["execute"] == []
    assert bridge._s9_retry_schedule == {}


def test_s9_terminal_rejection_waits_five_minutes_then_retries_only_missing_leg():
    submitted = datetime(2026, 11, 9, 15, 0, tzinfo=KST)
    bridge, plan, calls = _bridge_with_pending_order(submitted)
    bridge.pending_legs.clear()
    rejected = ExecutionReport("S9-CALL-REJECTED", None, None, "REJECTED", 0, 2,
                               None, None, submitted_at=submitted,
                               group_id=plan.group_id, leg_id="call")
    bridge.groups[plan.group_id] = [rejected]

    bridge.process_s9_entry_retries(datetime(2026, 11, 9, 15, 0, tzinfo=KST))
    assert calls["execute"] == []
    bridge.process_s9_entry_retries(datetime(2026, 11, 9, 15, 4, 59, tzinfo=KST))
    assert calls["execute"] == []
    bridge.process_s9_entry_retries(datetime(2026, 11, 9, 15, 5, tzinfo=KST))
    assert len(calls["execute"]) == 1
    retry_plan, _ = calls["execute"][0]
    assert retry_plan.legs[0].leg_id == "call"
    assert retry_plan.legs[0].side == "BUY"
    assert retry_plan.legs[0].quantity == 2


def test_cancel_reconciliation_preserves_retry_attempt_identity():
    submitted = datetime(2026, 11, 9, 15, 0, tzinfo=KST)
    bridge, plan, _calls = _bridge_with_pending_order(submitted)
    order_id = next(iter(bridge.pending_legs))
    bridge._pending_attempt_ids = {order_id: "S9-RETRY-0003"}
    confirmed = ExecutionReport(order_id, "BROKER-1", None, "CANCELLED", 0, 2,
                                None, None, submitted_at=submitted,
                                group_id=plan.group_id, leg_id="call")
    broker = SimpleNamespace(
        cancel=lambda _order_id: None,
        query=lambda _order_id: confirmed,
    )
    bridge.ack = SimpleNamespace(broker=broker)
    bridge.cancel_pending_order = VirtualMultiLegExecutionBridge.cancel_pending_order.__get__(
        bridge, VirtualMultiLegExecutionBridge,
    )
    captured = []

    def execute(self, single_plan, *, group_plan, reconciled_reports, reconciled_commands):
        captured.append((single_plan, group_plan, reconciled_reports, reconciled_commands))
        return SimpleNamespace(reports=(confirmed,))

    bridge.execute = MethodType(execute, bridge)
    bridge.cancel_pending_order(order_id)
    assert captured[0][0].attempt_id == "S9-RETRY-0003"
    assert captured[0][2][order_id] is confirmed


def test_s9_last_trading_day_cancels_at_1520_regular_session_boundary():
    submitted = datetime(2026, 11, 9, 15, 15, tzinfo=KST)
    bridge, _plan, calls = _bridge_with_pending_order(
        submitted, expiry="20261109",
    )
    bridge.process_s9_entry_retries(datetime(2026, 11, 9, 15, 19, 59, tzinfo=KST))
    assert calls["cancel"] == 0
    bridge.process_s9_entry_retries(datetime(2026, 11, 9, 15, 20, tzinfo=KST))
    assert calls["cancel"] == 1
    assert calls["execute"] == []


def test_s9_cancel_confirmation_failure_fails_closed_without_retry():
    from core.strategy.track9_event_overnight_insurance import Track9State

    submitted = datetime(2026, 11, 9, 15, 0, tzinfo=KST)
    bridge, _plan, calls = _bridge_with_pending_order(submitted)
    bridge.cancel_pending_order = MethodType(
        lambda self, _order_id: (_ for _ in ()).throw(RuntimeError("QUERY_UNAVAILABLE")),
        bridge,
    )
    strategy = SimpleNamespace(state=Track9State(state="OVERNIGHT_INSURANCE_PARTIAL"))
    bridge.process_s9_entry_retries(
        datetime(2026, 11, 9, 15, 5, tzinfo=KST), strategy=strategy,
    )
    assert strategy.state.state == "RECONCILIATION_REQUIRED"
    assert len(bridge.pending_legs) == 1
    assert bridge._s9_retry_schedule == {}
    assert calls["execute"] == []

def _s9_execution_replay_inputs():
    bridge = object.__new__(VirtualMultiLegExecutionBridge)
    bridge.run_id = "S9-IDEMPOTENCY-RUN"
    bridge.execution_legs = {}
    bridge.provenance = {}
    bridge.leg_positions = {}
    bridge._applied_execution_fingerprints = {}
    bridge.position_lot_store = VirtualPositionLotStore()
    bridge.fee_ledger = VirtualTrack9FeeLedger()
    identity = OptionInstrumentIdentity(
        "SYNTHETIC-S9-CALL-20261112-500", "SYNTHETIC-S9-CALL-20261112-500",
        "20261112", "CALL", Decimal("500"), Decimal("250000"),
        "SYNTHETIC_VALIDATION_ONLY",
    )
    leg = SimpleNamespace(leg_id="call", side="BUY", position_role="NONE")
    plan = MultiLegExecutionPlan(
        group_id="S9-IDEMPOTENCY-GROUP",
        strategy_id="track9_event_overnight_insurance",
        purpose="OVERNIGHT_INSURANCE",
        legs=(ExecutionLeg(
            "call", "BUY", 1, option_type="CALL", strike=Decimal("500"),
            instrument_identity=identity,
        ),),
    )
    command = SimpleNamespace(
        client_order_id="S9-ATTEMPT-1-CALL", instrument_id=identity.instrument_id,
        side="BUY", instrument_identity=identity,
    )
    report = ExecutionReport(
        client_order_id=command.client_order_id, broker_order_id="SYNTHETIC-BROKER-1",
        execution_id="S9-SYNTHETIC-EXEC-001", status="FILLED",
        filled_quantity=1, remaining_quantity=0, execution_price=Decimal("10"),
        execution_timestamp=datetime(2026, 11, 9, 10, 0, tzinfo=KST),
        fee=Decimal("0.10"), group_id=plan.group_id, leg_id="call",
    )
    return bridge, plan, leg, identity, command, report


def test_s9_duplicate_execution_callback_is_idempotent_across_position_and_fee_projections():
    bridge, plan, leg, identity, command, report = _s9_execution_replay_inputs()

    for _ in range(2):
        bridge._apply_reconciled_execution(
            plan=plan, leg=leg, identity=identity,
            broker_command=command, report=report,
        )

    assert len(bridge.position_lot_store.history()) == 1
    assert len(bridge.fee_ledger.query(run_id=bridge.run_id)) == 1
    assert bridge.fee_ledger.total(run_id=bridge.run_id) == Decimal("0.10")
    assert bridge.leg_positions[identity.instrument_id].qty == 1
    assert set(bridge._applied_execution_fingerprints) == {"S9-SYNTHETIC-EXEC-001"}


def test_s9_conflicting_duplicate_execution_callback_fails_closed_without_projection_mutation():
    bridge, plan, leg, identity, command, report = _s9_execution_replay_inputs()
    bridge._apply_reconciled_execution(
        plan=plan, leg=leg, identity=identity,
        broker_command=command, report=report,
    )
    before_fingerprints = dict(bridge._applied_execution_fingerprints)
    before_provenance = dict(bridge.provenance)

    conflicting = replace(report, execution_price=Decimal("10.25"))
    with pytest.raises(
        RuntimeError,
        match="MULTI_LEG_EXECUTION_ID_CONFLICT_RECONCILIATION_REQUIRED",
    ):
        bridge._apply_reconciled_execution(
            plan=plan, leg=leg, identity=identity,
            broker_command=command, report=conflicting,
        )

    assert len(bridge.position_lot_store.history()) == 1
    assert len(bridge.fee_ledger.query(run_id=bridge.run_id)) == 1
    assert bridge.fee_ledger.total(run_id=bridge.run_id) == Decimal("0.10")
    assert bridge.leg_positions[identity.instrument_id].qty == 1
    assert bridge._applied_execution_fingerprints == before_fingerprints
    assert bridge.provenance == before_provenance

def test_s9_retry_attempts_receive_distinct_client_order_identity():
    bridge, plan, _leg, identity, _command, _report = _s9_execution_replay_inputs()
    first = replace(plan, attempt_id="S9-RETRY-0001")
    second = replace(plan, attempt_id="S9-RETRY-0002")
    first_order = bridge._client_order_id(first, first.legs[0], identity)
    second_order = bridge._client_order_id(second, second.legs[0], identity)

    assert first_order != second_order
    assert first_order.startswith(plan.group_id + "-call-")
    assert second_order.startswith(plan.group_id + "-call-")

def test_s9_late_fill_from_prior_attempt_cannot_overfill_after_retry_fill():
    bridge, plan, leg, identity, command, first_report = _s9_execution_replay_inputs()
    bridge.groups = {plan.group_id: [first_report]}
    bridge._group_plans = {plan.group_id: plan}
    retry_plan = replace(plan, attempt_id="S9-RETRY-0001")
    retry_leg = retry_plan.legs[0]
    retry_command = SimpleNamespace(**{**vars(command), "client_order_id": "S9-ATTEMPT-2-CALL"})
    retry_fill = replace(
        first_report,
        client_order_id=retry_command.client_order_id,
        broker_order_id="SYNTHETIC-BROKER-2",
        execution_id="S9-SYNTHETIC-EXEC-002",
    )
    bridge.groups[plan.group_id] = [retry_fill]
    late_prior_attempt_fill = replace(
        first_report,
        broker_order_id="SYNTHETIC-BROKER-1",
        execution_id="S9-SYNTHETIC-EXEC-003",
    )

    with pytest.raises(
        RuntimeError,
        match="MULTI_LEG_EXECUTION_LEG_OVERFILL_RECONCILIATION_REQUIRED",
    ):
        bridge._apply_reconciled_execution(
            plan=retry_plan, leg=retry_leg, identity=identity,
            broker_command=command, report=late_prior_attempt_fill,
        )

    assert len(bridge.position_lot_store.history()) == 0
    assert bridge.fee_ledger.query(run_id=bridge.run_id) == ()
    assert bridge.leg_positions == {}
    assert bridge._applied_execution_fingerprints == {}

def test_s9_execution_fill_ids_reconcile_position_lots_fees_and_strategy_average():
    from core.strategy.track9_event_overnight_insurance import Track9EventOvernightInsurance

    bridge, plan, leg, identity, command, report = _s9_execution_replay_inputs()
    plan_leg = replace(plan.legs[0], quantity=2)
    plan = replace(plan, legs=(plan_leg,))
    bridge._group_plans = {plan.group_id: plan}
    fills = (
        ExecutionFill(
            "S9-CROSS-FILL-001", 1, Decimal("10"),
            datetime(2026, 11, 9, 10, 0, tzinfo=KST), Decimal("0.10"),
        ),
        ExecutionFill(
            "S9-CROSS-FILL-002", 1, Decimal("11"),
            datetime(2026, 11, 9, 10, 1, tzinfo=KST), Decimal("0.10"),
        ),
    )
    report = replace(
        report, filled_quantity=2, remaining_quantity=0,
        execution_price=Decimal("10.5"), fee=Decimal("0.20"),
        execution_fills=fills,
    )
    bridge._apply_reconciled_execution(
        plan=plan, leg=leg, identity=identity,
        broker_command=command, report=report,
    )

    strategy = Track9EventOvernightInsurance()
    strategy.on_execution_result(
        "OVERNIGHT_INSURANCE",
        SimpleNamespace(
            group_id=plan.group_id, group_complete=True, reports=(report,),
        ),
    )

    lots = bridge.position_lot_store.history()
    fees = bridge.fee_ledger.snapshot(run_id=bridge.run_id)
    expected_ids = {fill.execution_id for fill in fills}
    assert {lot.execution_id for lot in lots} == expected_ids
    assert {fee.execution_id for fee in fees} == expected_ids
    assert sum(lot.opened_quantity for lot in lots) == 2
    assert sum(fee.executed_quantity for fee in fees) == 2
    assert bridge.fee_ledger.total(run_id=bridge.run_id) == Decimal("0.20")
    assert bridge.leg_positions[identity.instrument_id].avg_price == Decimal("10.5")
    assert strategy.state.call_entry_fill_price == Decimal("10.5")
