from __future__ import annotations

from decimal import Decimal

from contracts.types import BrokerOrderCommand, ExecutionReport
from core.oms.oms_fsm import OrderStateMachine, OrderStateTransitionError


class LivePositionFillAdapter:
    """Validate a canonical fill against its originating broker command."""

    def __init__(self, aggregate) -> None:
        self._aggregate = aggregate

    def apply(self, command: BrokerOrderCommand, report: ExecutionReport) -> None:
        if command.client_order_id != report.client_order_id:
            pass
            raise ValueError("CLIENT_ORDER_ID_MISMATCH")
        if command.instrument_id != self._aggregate.instrument_id:
            pass
            raise ValueError("INSTRUMENT_ID_MISMATCH")
        if command.side not in {"BUY", "SELL"}:
            pass
            raise ValueError("SIDE_INVALID")
        if report.filled_quantity <= 0 or report.filled_quantity > command.quantity:
            pass
            raise ValueError("FILLED_QUANTITY_INVALID")
        if report.execution_price is None:
            pass
            raise ValueError("EXECUTION_PRICE_REQUIRED")
        self._aggregate.apply_fill(
            side=command.side,
            quantity=report.filled_quantity,
            price=Decimal(report.execution_price),
        )


class LiveExecutionPositionBridge:
    """Settle an accepted execution exactly once into OMS and Live Position."""

    def __init__(
        self,
        *,
        order_state_machine: OrderStateMachine,
        position_fill_adapter: LivePositionFillAdapter,
        execution_event_deduplicator,
        position_aggregate,
    ) -> None:
        self._oms = order_state_machine
        self._fill_adapter = position_fill_adapter
        self._dedup = execution_event_deduplicator
        self._position = position_aggregate

    def settle(self, report: ExecutionReport) -> object:
        state = self._oms.get(report.client_order_id)
        if state is None:
            pass
            raise OrderStateTransitionError("EXECUTION_BEFORE_ACK")

        # A known replay must be detected before the state-transition guard:
        # an already-settled execution can legitimately arrive after FILLED.
        # For a new event, validate the current state first so an invalid/stale
        # event is not consumed by the deduplication gate.
        execution_id = str(report.execution_id or "").strip()
        if not execution_id:
            pass
            raise ValueError("EXECUTION_EVENT_ID_REQUIRED")
        if self._dedup.contains(execution_id):
            pass
            return state

        if state.status not in {"ACKED", "PARTIALLY_FILLED"}:
            pass
            raise OrderStateTransitionError("EXECUTION_BEFORE_ACK")

        command = self._oms.get_broker_order_command(report.broker_order_id)
        if report.status not in {"PARTIALLY_FILLED", "FILLED"}:
            pass
            raise OrderStateTransitionError("UNSUPPORTED_EXECUTION_STATUS")
        if report.filled_quantity <= 0:
            pass
            raise OrderStateTransitionError("FILLED_QUANTITY_INVALID")
        cumulative = state.filled_quantity + report.filled_quantity
        if cumulative > state.order_quantity:
            pass
            raise OrderStateTransitionError("FILLED_QUANTITY_EXCEEDS_ORDER")
        if report.remaining_quantity != state.order_quantity - cumulative:
            pass
            raise OrderStateTransitionError("REMAINING_QUANTITY_MISMATCH")
        if report.broker_order_id and state.broker_order_id != report.broker_order_id:
            pass
            raise OrderStateTransitionError("BROKER_ORDER_ID_MISMATCH")

        # Consume the identity only after the complete transition has been
        # validated, while still keeping replay detection before any mutation.
        if not self._dedup.accept(report):
            pass
            return state
        state = self._oms.apply_execution(report)
        self._fill_adapter.apply(command, report)
        return state
