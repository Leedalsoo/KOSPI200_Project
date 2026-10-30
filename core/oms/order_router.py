"""Standard production OrderRouter boundary."""
from __future__ import annotations

from typing import Any

from contracts.order_ack import to_order_ack_event
from contracts.types import BrokerOrderCommand, BrokerOrderResponse
from contracts.market_data_freshness import FreshnessVerdict, admits_freshness_verdict_for_identity
from core.oms.oms_fsm import OrderStateMachine


class OrderRouterError(RuntimeError):
    pass


class StandardOrderRouter:
    def __init__(self, *, order_state_machine: OrderStateMachine, broker_adapter: Any = None, reconciliation_guard: Any = None) -> None:
        if order_state_machine is None: raise ValueError("ORDER_STATE_MACHINE_REQUIRED")
        self._order_state_machine = order_state_machine
        self._broker_adapter = broker_adapter
        self._reconciliation_guard = reconciliation_guard

    def register_and_route(self, command: BrokerOrderCommand, token: Any, *, broker_adapter: Any = None, **kwargs: Any) -> BrokerOrderResponse:
        if command is None: raise OrderRouterError("BROKER_ORDER_COMMAND_REQUIRED")
        if token is None: raise OrderRouterError("RISK_APPROVAL_TOKEN_REQUIRED")
        if self._reconciliation_guard is not None:
            try:
                unresolved = self._reconciliation_guard.has_unresolved_reconciliation()
            except Exception as exc:
                raise OrderRouterError("RECONCILIATION_STATUS_UNAVAILABLE") from exc
            if unresolved:
                raise OrderRouterError("UNRESOLVED_EXECUTION_RECONCILIATION")
        freshness_verdict = kwargs.pop("freshness_verdict", None)
        if not isinstance(freshness_verdict, FreshnessVerdict) or freshness_verdict.status.value != "FRESH":
            raise OrderRouterError("MARKET_DATA_FRESHNESS_VERDICT_REQUIRED")
        expected_symbol = str(command.broker_symbol or command.instrument_id or "").strip()
        if (
            not command.instrument_id or not expected_symbol
            or freshness_verdict.instrument_id != command.instrument_id
            or freshness_verdict.symbol != expected_symbol
        ):
            raise OrderRouterError("MARKET_DATA_FRESHNESS_COMMAND_IDENTITY_MISMATCH")
        if not admits_freshness_verdict_for_identity(
            freshness_verdict, expected_instrument_id=command.instrument_id,
            expected_symbol=expected_symbol,
        ):
            raise OrderRouterError("MARKET_DATA_FRESHNESS_EVIDENCE_REQUIRED")
        broker = broker_adapter if broker_adapter is not None else self._broker_adapter
        if broker is None: raise OrderRouterError("BROKER_ADAPTER_REQUIRED")
        submit = getattr(broker, "submit", None)
        if not callable(submit): raise OrderRouterError("BROKER_SUBMIT_REQUIRED")

        if self._order_state_machine.get(command.client_order_id) is None:
            self._order_state_machine.apply_intent(command)
        self._order_state_machine.register_broker_order_command(command)

        response = submit(command, **kwargs)
        if not isinstance(response, BrokerOrderResponse):
            raise OrderRouterError("BROKER_ORDER_RESPONSE_REQUIRED")
        if response.client_order_id != command.client_order_id:
            raise OrderRouterError("BROKER_RESPONSE_CLIENT_ORDER_ID_MISMATCH")

        self._order_state_machine.apply_ack(to_order_ack_event(response))
        return response


__all__ = ("OrderRouterError", "StandardOrderRouter")
