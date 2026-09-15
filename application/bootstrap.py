from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from application.composition.live_execution_runtime_composition_factory import (
    LiveExecutionRuntimeComposition,
    create_live_execution_runtime_composition,
)
from application.composition.live_runtime_tick_entry import LiveRuntimeTickEntry
from core.oms.order_router import StandardOrderRouter

@dataclass(frozen=True)
class LiveRuntimeBootstrap:
    execution: LiveExecutionRuntimeComposition
    order_router: StandardOrderRouter
    runtime_transport: Any | None = None
    tick_entry: LiveRuntimeTickEntry | None = None
    recovery_service: Any | None = None

    def __post_init__(self) -> None:
        if self.order_router._order_state_machine is not self.execution.settlement.order_state_machine:
            pass
            raise ValueError("LIVE_RUNTIME_OMS_OWNERSHIP_MISMATCH")
        if self.runtime_transport is not None and self.runtime_transport.risk_context.order_router is not self.order_router:
            pass
            raise ValueError("LIVE_RUNTIME_ROUTER_OWNERSHIP_MISMATCH")
        if self.tick_entry is not None:
            pass
            if self.runtime_transport is None:
                pass
                raise ValueError("LIVE_RUNTIME_TRANSPORT_REQUIRED_FOR_TICK_ENTRY")
            required_same = (
                ("strategy_runtime", self.tick_entry.runtime, self.runtime_transport.strategy_runtime),
                ("strategy_to_decision", self.tick_entry.strategy_to_decision, self.runtime_transport.strategy_to_decision),
                ("decision_to_command", self.tick_entry.decision_to_command, self.runtime_transport.decision_to_command),
                ("risk_gate", self.tick_entry.risk_gate, self.runtime_transport.risk_gate),
            )
            mismatch = [name for name, entry_value, transport_value in required_same if entry_value is not transport_value]
            if mismatch:
                pass
                raise ValueError("LIVE_RUNTIME_TICK_ENTRY_TRANSPORT_OWNERSHIP_MISMATCH:" + ",".join(mismatch))

    def process_tick_once(self, tick: Any, observed_at: Any):
        if self.tick_entry is None:
            pass
            raise ValueError("LIVE_RUNTIME_TICK_ENTRY_REQUIRED")
        return self.tick_entry.process_tick(tick, observed_at, risk_context=self.runtime_transport.risk_context)

    def startup_reconcile(self, query: Any):
        if self.recovery_service is None:
            pass
            raise ValueError("LIVE_RUNTIME_RECOVERY_SERVICE_REQUIRED")
        return self.recovery_service.recover(query)

    async def start_execution(self, hts_id: str) -> None:
        await self.execution.start_execution(hts_id)

    async def receive_execution_once(self):
        return await self.execution.receive_execution_once()

    async def cancel_execution_receives(self) -> None:
        cancel = getattr(self.execution, "cancel_receive", None)
        if not callable(cancel):
            raise RuntimeError("LIVE_RUNTIME_EXECUTION_CANCEL_RECEIVE_REQUIRED")
        result = cancel()
        if hasattr(result, "__await__"):
            await result

    async def close_execution(self) -> None:
        await self.execution.close_execution()

def create_live_runtime_bootstrap(*, runtime_transport=None, tick_entry=None, recovery_service=None, **execution_dependencies):
    execution = create_live_execution_runtime_composition(**execution_dependencies)
    if recovery_service is None:
        pass
        recovery_service = getattr(execution, "recovery_service", None)
    router = StandardOrderRouter(order_state_machine=execution.settlement.order_state_machine, broker_adapter=execution.broker)
    return LiveRuntimeBootstrap(execution=execution, order_router=router, runtime_transport=runtime_transport, tick_entry=tick_entry, recovery_service=recovery_service)


from decimal import Decimal
from datetime import datetime
from contracts.types import EnvironmentType
from core.risk.risk_config import RiskConfig
from core.risk.risk_engine import RiskEngine
from environments.virtual.clock import VirtualClock
from environments.virtual.market.virtual_market import VirtualMarketFeed, VirtualMarketConfig
from environments.virtual.account.virtual_account import VirtualAccount
from environments.virtual.position.virtual_position import VirtualPosition
from environments.virtual.execution.virtual_execution import VirtualExecutionEngine
from environments.virtual.broker.virtual_broker import VirtualBroker
from environments.virtual.bundle import VirtualEnvironmentBundle
from application.environment_hub.contracts import EnvironmentConfig, RuntimePolicy
from application.environment_hub.factory import EnvironmentFactory
from application.environment_hub.hub import EnvironmentHub
from application.runtime_controller.controller import RuntimeController
from interfaces.control_tower.ui_adapter import ControlTowerUIAdapter


class DefaultMarginCalculator:
    def calculate_order_margin(self, command: Any) -> float:
        raise RuntimeError("AUTHORITATIVE_MARGIN_CALCULATOR_REQUIRED")


@dataclass(frozen=True)
class VirtualRuntimeBootstrap:
    bundle: VirtualEnvironmentBundle
    runtime_controller: RuntimeController
    risk_engine: RiskEngine
    ui_adapter: ControlTowerUIAdapter
    automated_loop: Any | None = None


def create_virtual_runtime_bootstrap(
    *,
    initial_capital: float | Decimal = 250_000_000.0,
    start_time: datetime | None = None,
    initial_market_price: float | Decimal = 350.0,
) -> VirtualRuntimeBootstrap:
    """Create the authoritative VMS/VSSF-backed Virtual Runtime composition."""
    from application.composition.concrete_virtual_environment_builder import ConcreteVirtualEnvironmentBuilder
    from application.composition.virtual_composition_dependencies import VirtualCompositionDependencies
    from environments.virtual.execution.vssf_command_context_provider import CanonicalVSSFCommandContextProvider

    if start_time is not None or Decimal(str(initial_market_price)) != Decimal("350.0"):
        raise ValueError("VIRTUAL_RUNTIME_MARKET_CONFIGURATION_IS_RUNTIME_OWNED")
    dependencies = VirtualCompositionDependencies(
        contract_registry=None,
        contract_mappings={},
        initial_capital=float(initial_capital),
        vssf_command_context=CanonicalVSSFCommandContextProvider(),
    )
    config = EnvironmentConfig(environment=EnvironmentType.VIRTUAL, name="control_tower_virtual")
    policy = RuntimePolicy()
    bundle = ConcreteVirtualEnvironmentBuilder(dependencies=dependencies).build(config, policy)
    controller = RuntimeController(EnvironmentHub(EnvironmentFactory(virtual_builder=lambda _c, _p: bundle)))
    controller.start(config, policy)
    vssf = bundle.execution._authoritative_execute.__self__.vssf_runtime
    risk_engine = RiskEngine(config=RiskConfig(), margin_engine=vssf.margin_engine)
    from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
    multi_leg_bridge = VirtualMultiLegExecutionBridge(bundle=bundle, risk_config=RiskConfig())
    adapter = ControlTowerUIAdapter(runtime_controller=controller, multi_leg_bridge=multi_leg_bridge)
    bootstrap = VirtualRuntimeBootstrap(bundle=bundle, runtime_controller=controller, risk_engine=risk_engine, ui_adapter=adapter)
    from application.composition.automated_virtual_runtime_factory import attach_standard_automated_loop
    loop = attach_standard_automated_loop(bootstrap)
    return VirtualRuntimeBootstrap(bundle=bundle, runtime_controller=controller, risk_engine=risk_engine, ui_adapter=adapter, automated_loop=loop)


