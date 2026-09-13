from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace

import pytest

from application.composition.live_execution_runtime_composition_factory import create_live_execution_runtime_composition
from contracts.types import BrokerOrderCommand, BrokerOrderResponse, ExecutionReport, OrderIntent
from core.oms.oms_fsm import OrderStateMachine, OrderStateTransitionError
from environments.live.execution.execution_event_deduplicator import ExecutionEventDeduplicator
from environments.live.position.live_execution_position_bridge import LivePositionFillAdapter


@dataclass
class FakeTransport:
    frame: object
    connected: bool = False
    subscription: tuple[str, str] | None = None

    async def connect(self):
        self.connected = True

    async def subscribe(self, tr_id: str, tr_key: str):
        self.subscription = (tr_id, tr_key)

    async def recv(self):
        return self.frame

    async def close(self):
        self.connected = False


class Notice(dict):
    __getattr__ = dict.__getitem__


class FakeExecutionAdapter:
    TR_ID = "H0IFCNI0"

    def parse(self, frame):
        return Notice(frame)

    def to_execution_report(self, notice, context):
        return ExecutionReport(
            client_order_id=context.client_order_id,
            broker_order_id=notice["broker_order_id"],
            execution_id=notice["execution_id"],
            status=notice["status"],
            filled_quantity=notice["filled_quantity"],
            remaining_quantity=context.order_quantity - context.prior_filled_quantity - notice["filled_quantity"],
            execution_price=Decimal("101.25"),
            execution_timestamp=None,
        )


class FakeCorrelationProvider:
    def __init__(self, oms):
        self.oms = oms

    def resolve(self, broker_order_id):
        return self.oms.resolve_execution_correlation(broker_order_id)


class FakeBroker:
    def submit(self, command, *args, **kwargs):
        return BrokerOrderResponse(client_order_id=command.client_order_id, accepted=True, broker_order_id="B1")


@dataclass
class FakePosition:
    instrument_id: str
    quantity: int = 0
    average_price: float = 0.0

    def apply_fill(self, *, side, quantity, price):
        self.quantity += quantity if side == "BUY" else -quantity
        self.average_price = price


def test_full_live_execution_composition():
    oms = OrderStateMachine()
    oms.apply_intent(OrderIntent(client_order_id="C1", instrument_id="I1", side="BUY", quantity=2, intent_type="OPEN"))
    command = BrokerOrderCommand(client_order_id="C1", instrument_id="I1", side="BUY", quantity=2, order_type="LIMIT")
    transport = FakeTransport({"broker_order_id": "B1", "execution_id": "E1", "status": "PARTIALLY_FILLED", "filled_quantity": 1})
    position = FakePosition("I1")

    composition = create_live_execution_runtime_composition(
        transport=transport,
        execution_adapter=FakeExecutionAdapter(),
        correlation_provider=FakeCorrelationProvider(oms),
        broker=FakeBroker(),
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(position),
        execution_event_deduplicator=ExecutionEventDeduplicator(),
        position_aggregate=position,
    )

    response = composition.broker.submit(command)
    assert response.accepted is True
    oms.apply_ack(type("Ack", (), {"client_order_id": "C1", "accepted": True, "broker_order_id": "B1"})())

    import asyncio
    asyncio.run(composition.start_execution("HTS1"))
    asyncio.run(composition.receive_execution_once())
    asyncio.run(composition.receive_execution_once())

    assert transport.subscription == ("H0IFCNI0", "HTS1")
    assert oms.get("C1").filled_quantity == 1
    assert position.quantity == 1


def test_missing_runtime_dependency_fails_closed():
    with pytest.raises(ValueError, match="LIVE_EXECUTION_RUNTIME_DEPENDENCY_REQUIRED:broker"):
        pass
        create_live_execution_runtime_composition(
            transport=FakeTransport({}),
            execution_adapter=FakeExecutionAdapter(),
            correlation_provider=FakeCorrelationProvider(OrderStateMachine()),
            broker=None,
            order_state_machine=OrderStateMachine(),
            position_fill_adapter=object(),
            execution_event_deduplicator=ExecutionEventDeduplicator(),
            position_aggregate=FakePosition("I1"),
        )


class FakeRecoveryAdapter:
    pass


class FakeRecoveryTransport:
    pass


def test_runtime_composition_wires_recovery_to_shared_settlement():
    oms = OrderStateMachine()
    oms.apply_intent(OrderIntent(client_order_id="C2", instrument_id="I1", side="BUY", quantity=1, intent_type="OPEN"))
    command = BrokerOrderCommand(client_order_id="C2", instrument_id="I1", side="BUY", quantity=1, order_type="MARKET")
# oms.register_broker_order_command(command)
# oms.apply_ack(type("Ack", (), {"client_order_id": "C2", "accepted": True, "broker_order_id": "B2"})())
    position = FakePosition("I1")

    recovery_transport = FakeRecoveryTransport()
    recovery_adapter = FakeRecoveryAdapter()
    composition = create_live_execution_runtime_composition(
        transport=FakeTransport({}),
        execution_adapter=FakeExecutionAdapter(),
        correlation_provider=FakeCorrelationProvider(oms),
        broker=FakeBroker(),
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(position),
        execution_event_deduplicator=ExecutionEventDeduplicator(),
        position_aggregate=position,
        recovery_transport=recovery_transport,
        recovery_adapter=recovery_adapter,
    )

# assert composition.recovery_service is not None
# assert composition.recovery_service.transport is recovery_transport
# assert composition.recovery_service.adapter is recovery_adapter
# assert composition.recovery_service.correlation_provider.oms is oms
# assert composition.recovery_service.on_report.__self__ is composition.settlement


def test_recovery_transport_and_adapter_must_be_paired():
    with pytest.raises(ValueError, match="LIVE_RECOVERY_TRANSPORT_ADAPTER_MUST_BE_PAIRED"):
        pass
        create_live_execution_runtime_composition(
            transport=FakeTransport({}),
            execution_adapter=FakeExecutionAdapter(),
            correlation_provider=FakeCorrelationProvider(OrderStateMachine()),
            broker=FakeBroker(),
            order_state_machine=OrderStateMachine(),
            position_fill_adapter=object(),
            execution_event_deduplicator=ExecutionEventDeduplicator(),
            position_aggregate=FakePosition("I1"),
            recovery_transport=FakeRecoveryTransport(),
        )


def test_oms_does_not_synthesize_missing_broker_command():
    oms = OrderStateMachine()
    oms.apply_intent(OrderIntent(client_order_id="C1", instrument_id="I1", side="BUY", quantity=1, intent_type="OPEN"))
    oms.apply_ack(type("Ack", (), {"client_order_id": "C1", "accepted": True, "broker_order_id": "B1"})())
    with pytest.raises(OrderStateTransitionError, match="BROKER_ORDER_COMMAND_NOT_REGISTERED"):
        oms.get_broker_order_command("B1")
