"""FRESH-09 cold-start correlation and offline recovery boundary tests."""
from types import SimpleNamespace

import pytest

from contracts.types import BrokerOrderCommand, ExecutionReport, OrderAckEvent
from core.oms.oms_fsm import OrderStateMachine, OrderStateTransitionError
from environments.live.execution.execution_event_deduplicator import ExecutionEventDeduplicator
from environments.live.execution.live_execution_recovery_service import LiveExecutionRecoveryService
from environments.live.execution.kis_futures_execution_recovery_adapter import KISExecutionRecoveryQuery


def _command(client_id="client-1", quantity=3):
    return BrokerOrderCommand(client_order_id=client_id, instrument_id="FUT-1", side="BUY",
        quantity=quantity, order_type="LIMIT", broker_symbol="FUTSYM", strategy_id="S1")


def _report(client_id="client-1", broker_id="broker-1", execution_id="exec-1"):
    return ExecutionReport(client_order_id=client_id, broker_order_id=broker_id,
        execution_id=execution_id, status="PARTIALLY_FILLED", filled_quantity=1,
        remaining_quantity=2, execution_price=None, execution_timestamp=None)


def _acknowledged_fsm():
    fsm = OrderStateMachine()
    command = _command()
    fsm.apply_intent(command)
    fsm.register_broker_order_command(command)
    fsm.apply_ack(OrderAckEvent(client_order_id="client-1", accepted=True, broker_order_id="broker-1"))
    return fsm


def test_fresh09_cold_start_does_not_invent_broker_to_client_correlation():
    before_restart = _acknowledged_fsm()
    assert before_restart.resolve_execution_correlation("broker-1").client_order_id == "client-1"

    after_restart = OrderStateMachine()
    with pytest.raises(OrderStateTransitionError, match="BROKER_ORDER_ID_NOT_CORRELATED"):
        after_restart.resolve_execution_correlation("broker-1")
    with pytest.raises(OrderStateTransitionError, match="ORDER_NOT_REGISTERED"):
        after_restart.apply_execution(_report())
    assert after_restart.get("client-1") is None


def test_fresh09_offline_recovery_fixture_stops_before_normalization_when_correlation_missing():
    class Transport:
        def __init__(self):
            self.calls = 0
        def inquire(self, query):
            self.calls += 1
            return {"output": [{"odno": "broker-1", "tot_ccld_qty": "1"}]}

    class Adapter:
        def __init__(self):
            self.calls = 0
        def normalize(self, response, context_for_order):
            self.calls += 1
            context_for_order("broker-1")
            raise AssertionError("unreachable if cold-start correlation is fail-closed")

    transport, adapter = Transport(), Adapter()
    fresh_fsm = OrderStateMachine()
    correlation_provider = SimpleNamespace(resolve=fresh_fsm.resolve_execution_correlation)
    service = LiveExecutionRecoveryService(transport, adapter, correlation_provider, lambda report: report)
    query = KISExecutionRecoveryQuery(cano="00000000", account_product_code="01",
        start_order_date="20261014", end_order_date="20261014", virtual=True)

    with pytest.raises(OrderStateTransitionError, match="BROKER_ORDER_ID_NOT_CORRELATED"):
        service.recover(query)
    assert transport.calls == 1
    assert adapter.calls == 1


def test_fresh09_in_memory_execution_deduplication_resets_after_cold_start():
    report = _report()
    first_session = ExecutionEventDeduplicator()
    assert first_session.accept(report) is True
    assert first_session.accept(report) is False

    restarted_session = ExecutionEventDeduplicator()
    # This exposes the persistence boundary; it does not claim that a durable
    # production dedup store exists elsewhere in the system.
    assert restarted_session.contains("exec-1") is False
    assert restarted_session.accept(report) is True
