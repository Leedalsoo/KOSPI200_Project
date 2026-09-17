"""Explicit application assembly for the Live execution -> OMS -> Position seam."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from contracts.types import BrokerOrderCommand, ExecutionReport
from core.oms.oms_fsm import OrderStateMachine
from environments.live.position.live_execution_position_bridge import LiveExecutionPositionBridge, LivePositionFillAdapter


@dataclass(frozen=True)
class LiveExecutionPositionComposition:
    """Concrete dependency bundle for one Live settlement scope."""
    execution_source: Any
    broker_command_source: OrderStateMachine
    order_state_machine: OrderStateMachine
    position_fill_adapter: Any
    execution_event_deduplicator: Any
    position_aggregate: Any
    settlement_bridge: LiveExecutionPositionBridge

    def settle(self, report: ExecutionReport) -> object:
        """Resolve the originating BrokerOrderCommand from OMS and settle the report."""
        return self.settlement_bridge.settle(report)


def create_live_execution_position_composition(
# *,
    execution_source: Any,
    order_state_machine: OrderStateMachine,
    position_fill_adapter: Any,
    execution_event_deduplicator: Any,
    position_aggregate: Any,
) -> LiveExecutionPositionComposition:
    """Assemble existing Live execution/OMS/Position components without hidden defaults."""
    required = {
        "execution_source": execution_source,
        "order_state_machine": order_state_machine,
        "position_fill_adapter": position_fill_adapter,
        "execution_event_deduplicator": execution_event_deduplicator,
        "position_aggregate": position_aggregate,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        raise ValueError("LIVE_COMPOSITION_DEPENDENCY_REQUIRED:" + ",".join(missing))

    bridge = LiveExecutionPositionBridge(
        order_state_machine=order_state_machine,
        position_fill_adapter=position_fill_adapter,
        execution_event_deduplicator=execution_event_deduplicator,
        position_aggregate=position_aggregate,
    )
    return LiveExecutionPositionComposition(
        execution_source=execution_source,
        broker_command_source=order_state_machine,
        order_state_machine=order_state_machine,
        position_fill_adapter=position_fill_adapter,
        execution_event_deduplicator=execution_event_deduplicator,
        position_aggregate=position_aggregate,
        settlement_bridge=bridge,
    )
