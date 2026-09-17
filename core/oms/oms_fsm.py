from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from contracts.types import BrokerOrderCommand, ExecutionReport, OrderAckEvent


class OrderStateTransitionError(ValueError):
    """Raised when an order state transition is unsafe or invalid."""


@dataclass(frozen=True)
class OrderState:
    client_order_id: str
    status: str
    broker_order_id: str | None = None
    order_quantity: int = 0
    filled_quantity: int = 0
    broker_order_command: BrokerOrderCommand | None = None
    average_execution_price: Decimal | None = None


@dataclass(frozen=True)
class ExecutionCorrelation:
    """OMS-owned state required to correlate a broker execution notice."""

    client_order_id: str
    broker_order_id: str
    order_quantity: int
    prior_filled_quantity: int
    prior_average_price: Decimal | None = None


class OrderStateMachine:
    """OMS-owned order state and broker/client correlation boundary."""

    def __init__(self) -> None:
        self._states: dict[str, OrderState] = {}
        self._broker_to_client: dict[str, str] = {}

    def apply_intent(self, intent) -> OrderState:
        client_order_id = str(intent.client_order_id).strip()
        if not client_order_id:
            raise OrderStateTransitionError("CLIENT_ORDER_ID_REQUIRED")
        quantity = int(intent.quantity)
        if quantity <= 0:
            raise OrderStateTransitionError("ORDER_QUANTITY_INVALID")
        if client_order_id in self._states:
            raise OrderStateTransitionError("ORDER_INTENT_ALREADY_REGISTERED")
        state = OrderState(client_order_id, "SUBMITTED", order_quantity=quantity)
        self._states[client_order_id] = state
        return state

    def register_broker_order_command(self, command: BrokerOrderCommand) -> OrderState:
        client_order_id = str(command.client_order_id).strip()
        if not client_order_id:
            raise OrderStateTransitionError("CLIENT_ORDER_ID_REQUIRED")
        current = self._states.get(client_order_id)
        if current is None:
            raise OrderStateTransitionError("ORDER_NOT_REGISTERED")
        if current.status not in {"SUBMITTED", "ACKED"}:
            raise OrderStateTransitionError("BROKER_COMMAND_AFTER_INVALID_STATE")
        if command.quantity != current.order_quantity:
            raise OrderStateTransitionError("BROKER_COMMAND_QUANTITY_MISMATCH")
        if command.instrument_identity is not None and command.instrument_id != command.instrument_identity.instrument_id:
            raise OrderStateTransitionError("BROKER_COMMAND_INSTRUMENT_ID_MISMATCH")
        state = OrderState(
            client_order_id=current.client_order_id,
            status=current.status,
            broker_order_id=current.broker_order_id,
            order_quantity=current.order_quantity,
            filled_quantity=current.filled_quantity,
            broker_order_command=command,
            average_execution_price=current.average_execution_price,
        )
        self._states[client_order_id] = state
        return state

    def apply_ack(self, event: OrderAckEvent) -> OrderState:
        client_order_id = str(event.client_order_id).strip()
        if not client_order_id:
            raise OrderStateTransitionError("CLIENT_ORDER_ID_REQUIRED")
        current = self._states.get(client_order_id)
        if current is None:
            raise OrderStateTransitionError("ORDER_NOT_REGISTERED")
        if current.status not in {"SUBMITTED", "ACKED"}:
            raise OrderStateTransitionError("ACK_AFTER_TERMINAL_STATE")
        if event.accepted and not event.broker_order_id:
            raise OrderStateTransitionError("BROKER_ORDER_ID_REQUIRED_FOR_ACCEPTED_ACK")
        if event.accepted:
            broker_order_id = str(event.broker_order_id).strip()
            previous_client = self._broker_to_client.get(broker_order_id)
            if previous_client is not None and previous_client != client_order_id:
                raise OrderStateTransitionError("BROKER_ORDER_ID_ALREADY_CORRELATED")
            self._broker_to_client[broker_order_id] = client_order_id
        state = OrderState(
            client_order_id=client_order_id,
            status="ACKED" if event.accepted else "REJECTED",
            broker_order_id=event.broker_order_id,
            order_quantity=current.order_quantity,
            filled_quantity=current.filled_quantity,
            broker_order_command=current.broker_order_command,
            average_execution_price=current.average_execution_price,
        )
        self._states[client_order_id] = state
        return state

    def resolve_execution_correlation(self, broker_order_id: str) -> ExecutionCorrelation:
        broker_id = str(broker_order_id).strip()
        if not broker_id:
            raise OrderStateTransitionError("BROKER_ORDER_ID_REQUIRED")
        client_order_id = self._broker_to_client.get(broker_id)
        if client_order_id is None:
            raise OrderStateTransitionError("BROKER_ORDER_ID_NOT_CORRELATED")
        state = self._states.get(client_order_id)
        if state is None:
            raise OrderStateTransitionError("CORRELATED_ORDER_STATE_MISSING")
        if state.status not in {"ACKED", "PARTIALLY_FILLED"}:
            raise OrderStateTransitionError("EXECUTION_CORRELATION_STATE_INVALID")
        return ExecutionCorrelation(
            client_order_id=state.client_order_id,
            broker_order_id=broker_id,
            order_quantity=state.order_quantity,
            prior_filled_quantity=state.filled_quantity,
            prior_average_price=state.average_execution_price,
        )

    def get_broker_order_command(self, broker_order_id: str | None) -> BrokerOrderCommand:
        broker_id = str(broker_order_id or "").strip()
        if not broker_id:
            raise OrderStateTransitionError("BROKER_ORDER_ID_REQUIRED")
        client_order_id = self._broker_to_client.get(broker_id)
        if client_order_id is None:
            raise OrderStateTransitionError("BROKER_ORDER_ID_NOT_CORRELATED")
        state = self._states.get(client_order_id)
        if state is None or state.broker_order_command is None:
            raise OrderStateTransitionError("BROKER_ORDER_COMMAND_NOT_REGISTERED")
        if state.broker_order_id != broker_id:
            raise OrderStateTransitionError("BROKER_ORDER_ID_MISMATCH")
        return state.broker_order_command

    def apply_execution(self, report: ExecutionReport) -> OrderState:
        client_order_id = str(report.client_order_id).strip()
        current = self._states.get(client_order_id)
        if current is None:
            raise OrderStateTransitionError("ORDER_NOT_REGISTERED")
        if current.status not in {"ACKED", "PARTIALLY_FILLED"}:
            raise OrderStateTransitionError("EXECUTION_BEFORE_ACK")
        if report.status not in {"PARTIALLY_FILLED", "FILLED"}:
            raise OrderStateTransitionError("UNSUPPORTED_EXECUTION_STATUS")
        if report.filled_quantity <= 0:
            raise OrderStateTransitionError("FILLED_QUANTITY_INVALID")
        cumulative = current.filled_quantity + report.filled_quantity
        if cumulative > current.order_quantity:
            raise OrderStateTransitionError("FILLED_QUANTITY_EXCEEDS_ORDER")
        if report.remaining_quantity != current.order_quantity - cumulative:
            raise OrderStateTransitionError("REMAINING_QUANTITY_MISMATCH")
        if report.broker_order_id and current.broker_order_id != report.broker_order_id:
            raise OrderStateTransitionError("BROKER_ORDER_ID_MISMATCH")
        average_execution_price = current.average_execution_price
        if report.execution_price is not None and report.execution_price > 0:
            if current.filled_quantity == 0 or average_execution_price is None:
                average_execution_price = report.execution_price
            else:
                average_execution_price = (average_execution_price * Decimal(current.filled_quantity) + report.execution_price * Decimal(report.filled_quantity)) / Decimal(cumulative)
        state = OrderState(
            client_order_id=client_order_id,
            status=report.status,
            broker_order_id=report.broker_order_id or current.broker_order_id,
            order_quantity=current.order_quantity,
            filled_quantity=cumulative,
            broker_order_command=current.broker_order_command,
            average_execution_price=average_execution_price,
        )
        self._states[client_order_id] = state
        return state

    def command_for(self, client_order_id: str) -> BrokerOrderCommand:
        state = self._states.get(str(client_order_id).strip())
        if state is None or state.broker_order_command is None:
            raise OrderStateTransitionError("BROKER_ORDER_COMMAND_NOT_REGISTERED")
        return state.broker_order_command

    def get(self, client_order_id: str) -> OrderState | None:
        return self._states.get(client_order_id)


__all__ = (
    "ExecutionCorrelation",
    "OrderState",
    "OrderStateMachine",
    "OrderStateTransitionError",
)
