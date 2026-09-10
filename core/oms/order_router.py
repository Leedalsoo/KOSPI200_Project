"""Standard production OrderRouter boundary."""
from __future__ import annotations

from typing import Any

from contracts.order_ack import to_order_ack_event
from contracts.types import BrokerOrderCommand, BrokerOrderResponse
from core.oms.oms_fsm import OrderStateMachine


class OrderRouterError(RuntimeError):
    pass


class StandardOrderRouter:
    def __init__(self, *, order_state_machine: OrderStateMachine, broker_adapter: Any = None) -> None:
        if order_state_machine is None: raise ValueError("ORDER_STATE_MACHINE_REQUIRED")
        self._order_state_machine = order_state_machine
        self._broker_adapter = broker_adapter

    def register_and_route(self, command: BrokerOrderCommand, token: Any, *, broker_adapter: Any = None, **kwargs: Any) -> BrokerOrderResponse:
        if command is None: raise OrderRouterError("BROKER_ORDER_COMMAND_REQUIRED")
        if token is None: raise OrderRouterError("RISK_APPROVAL_TOKEN_REQUIRED")
        broker = broker_adapter if broker_adapter is not None else self._broker_adapter
        if broker is None: raise OrderRouterError("BROKER_ADAPTER_REQUIRED")
        submit = getattr(broker, "submit", None)
        if not callable(submit): raise OrderRouterError("BROKER_SUBMIT_REQUIRED")

        if self._order_state_machine.get(command.client_order_id) is None:
            pass
            self._order_state_machine.apply_intent(command)

        response = submit(command, **kwargs)
        if not isinstance(response, BrokerOrderResponse):
            pass
            raise OrderRouterError("BROKER_ORDER_RESPONSE_REQUIRED")
        if response.client_order_id != command.client_order_id:
            pass
            raise OrderRouterError("BROKER_RESPONSE_CLIENT_ORDER_ID_MISMATCH")

        self._order_state_machine.apply_ack(to_order_ack_event(response))
        return response


__all__ = ("OrderRouterError", "StandardOrderRouter")
