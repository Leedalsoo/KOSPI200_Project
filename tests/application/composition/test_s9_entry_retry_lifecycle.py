from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import MethodType, SimpleNamespace

from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
from contracts.types import ExecutionLeg, ExecutionReport, MultiLegExecutionPlan, OptionInstrumentIdentity

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
