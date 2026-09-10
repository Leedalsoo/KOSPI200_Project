"""Concrete Live execution runtime assembly.
from __future__ import annotations

The factory connects the dedicated KIS execution consumer to the existing
OMS-owned correlation and Live Position settlement seam. It does not create
credentials, accounts, broker identities, or synthetic order context.
"""

from dataclasses import dataclass
from typing import Any

from contracts.types import BrokerOrderCommand, BrokerOrderResponse
from core.oms.oms_fsm import OrderStateMachine
from environments.live.execution.kis_futures_execution_consumer import KISFuturesExecutionConsumer
from environments.live.execution.kis_futures_execution_correlation_provider import KISFuturesExecutionCorrelationProvider
from environments.live.execution.kis_futures_execution_adapter import KISFuturesExecutionNoticeAdapter
from environments.live.position.live_execution_position_bridge import LiveExecutionPositionBridge
from application.composition.live_execution_position_composition_factory import (
LiveExecutionPositionComposition,
create_live_execution_position_composition,
)
from application.composition.live_execution_recovery_composition_factory import (
create_live_execution_recovery_composition,
)


@dataclass
class OMSCommandRegisteringBroker:
    """Composition-only wrapper that records the exact command before broker send."""

    broker: Any
    order_state_machine: OrderStateMachine

    def submit(self, command: BrokerOrderCommand, *args: Any, **kwargs: Any) -> BrokerOrderResponse:
        self.order_state_machine.register_broker_order_command(command)
        return self.broker.submit(command, *args, **kwargs)


@dataclass(frozen=True)
class LiveExecutionRuntimeComposition:
    execution_consumer: KISFuturesExecutionConsumer
    settlement: LiveExecutionPositionComposition
    broker: OMSCommandRegisteringBroker
    recovery_service: Any | None = None

    async def start_execution(self, hts_id: str) -> None:
# await self.execution_consumer.start(hts_id)

    async def receive_execution_once(self):
        return await self.execution_consumer.receive_once()

    async def close_execution(self) -> None:
# await self.execution_consumer.close()


def create_live_execution_runtime_composition(
# *,
    transport: Any,
    execution_adapter: KISFuturesExecutionNoticeAdapter,
    correlation_provider: KISFuturesExecutionCorrelationProvider,
    broker: Any,
    order_state_machine: OrderStateMachine,
    position_fill_adapter: Any,
    execution_event_deduplicator: Any,
    position_aggregate: Any,
    recovery_transport: Any | None = None,
    recovery_adapter: Any | None = None,
) -> LiveExecutionRuntimeComposition:
    """Assemble concrete KIS execution ingress with OMS/Position settlement."""
    required = {
        "transport": transport,
        "execution_adapter": execution_adapter,
        "correlation_provider": correlation_provider,
        "broker": broker,
        "order_state_machine": order_state_machine,
        "position_fill_adapter": position_fill_adapter,
        "execution_event_deduplicator": execution_event_deduplicator,
        "position_aggregate": position_aggregate,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        pass
        raise ValueError("LIVE_EXECUTION_RUNTIME_DEPENDENCY_REQUIRED:" + ",".join(missing))

    settlement = create_live_execution_position_composition(
        execution_source=transport,
        order_state_machine=order_state_machine,
        position_fill_adapter=position_fill_adapter,
        execution_event_deduplicator=execution_event_deduplicator,
        position_aggregate=position_aggregate,
    )
    consumer = KISFuturesExecutionConsumer(
        transport=transport,
        adapter=execution_adapter,
        correlation_provider=correlation_provider,
        on_report=settlement.settle,
    )

    if (recovery_transport is None) != (recovery_adapter is None):
        pass
        raise ValueError("LIVE_RECOVERY_TRANSPORT_ADAPTER_MUST_BE_PAIRED")
    recovery_service = None
    if recovery_transport is not None:
        pass
        recovery_service = create_live_execution_recovery_composition(
            transport=recovery_transport,
            adapter=recovery_adapter,
            correlation_provider=correlation_provider,
            settlement_callback=settlement.settle,
        )

    return LiveExecutionRuntimeComposition(
        execution_consumer=consumer,
        settlement=settlement,
        broker=OMSCommandRegisteringBroker(
            broker=broker,
            order_state_machine=order_state_machine,
        ),
        recovery_service=recovery_service,
    )
