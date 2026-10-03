from decimal import Decimal

from application.composition.runtime_strategy_result_collection_adapter import RuntimeStrategyEvaluation
from application.composition.runtime_strategy_to_decision_adapter import RuntimeStrategyToDecisionAdapter
from contracts.types import BrokerOrderCommand, ExecutionReport
from core.decision.decision_arbiter import DecisionArbiter
from core.oms.oms_fsm import OrderStateMachine
from core.runtime.runtime_execution_context import RuntimeExecutionContext
from core.strategy.contracts import Signal
from tests.integration.test_runtime_strategy_to_decision_adapter import Context


def cancel_evaluation(sequence=1):
    return RuntimeStrategyEvaluation(
        context=Context("track6_daily_tail_insurance"),
        result=Signal("track6_daily_tail_insurance", "CANCEL", 1.0, "CANCEL_PENDING_TRANCHES_15:15"),
        local_sequence=sequence,
        runtime_context=RuntimeExecutionContext(77, sequence),
    )


def test_cancel_signal_becomes_explicit_cancel_request_from_authoritative_ids():
    adapter = RuntimeStrategyToDecisionAdapter(DecisionArbiter())
    result = adapter.arbitrate(
        [cancel_evaluation()],
        price=351.10,
        timestamp="2026-09-30T15:15:00",
        account=None,
        pending_order_ids_provider=lambda strategy_id: ("ORD-1", "ORD-2"),
    )
    assert result.canonical_signals == ()
    assert len(result.cancel_requests) == 1
    assert result.cancel_requests[0].client_order_ids == ("ORD-1", "ORD-2")


def test_cancel_signal_fails_closed_without_authoritative_pending_source():
    adapter = RuntimeStrategyToDecisionAdapter(DecisionArbiter())
    try:
        adapter.arbitrate([cancel_evaluation()], price=351.10, timestamp="2026-09-30T15:15:00", account=None)
    except ValueError as exc:
        assert str(exc) == "CANCEL_PENDING_ORDER_SOURCE_REQUIRED"
    else:
        raise AssertionError("expected missing pending-order source to fail closed")


def test_oms_exposes_and_closes_only_pending_orders_for_strategy():
    fsm = OrderStateMachine()
    fsm.apply_intent(type("Intent", (), {"client_order_id":"ORD-1", "quantity":1})())
    fsm.register_broker_order_command(BrokerOrderCommand(
        client_order_id="ORD-1", instrument_id="OPT-1", side="BUY", quantity=1, order_type="LIMIT",
        strategy_id="track6_daily_tail_insurance",
    ))
    assert fsm.pending_client_order_ids("track6_daily_tail_insurance") == ("ORD-1",)
    report = ExecutionReport(
        client_order_id="ORD-1", broker_order_id="BROKER-1", execution_id=None, status="CANCELLED",
        filled_quantity=0, remaining_quantity=0, execution_price=None, execution_timestamp=None,
        fee=None,
    )
    fsm.apply_cancel(report)
    assert fsm.pending_client_order_ids("track6_daily_tail_insurance") == ()
    assert fsm.get("ORD-1").status == "CANCELLED"
