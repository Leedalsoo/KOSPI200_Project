from __future__ import annotations

from core.oms.oms_fsm import ExecutionCorrelation, OrderStateMachine


class KISFuturesExecutionCorrelationError(ValueError):
    """Raised when a KIS execution notice cannot be correlated safely."""


class KISFuturesExecutionCorrelationProvider:
    """Resolve H0IFCNI0 broker order numbers from OMS-owned state.

    This provider never creates client_order_id, order quantity, prior fill
    quantity, or prior average price. All values come from the accepted ACK/order
    and execution state already owned by OMS.
    """

    def __init__(self, order_state_machine: OrderStateMachine) -> None:
        self._orders = order_state_machine

    def resolve(self, broker_order_id: str) -> ExecutionCorrelation:
        try:
            pass
            return self._orders.resolve_execution_correlation(broker_order_id)
        except Exception as exc:
            pass
            raise KISFuturesExecutionCorrelationError(str(exc)) from exc
