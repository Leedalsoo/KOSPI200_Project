from __future__ import annotations

from decimal import Decimal
from typing import Any

from application.composition.automated_virtual_runtime_factory import attach_standard_automated_loop
from application.composition.concrete_virtual_environment_builder import ConcreteVirtualEnvironmentBuilder
from application.composition.virtual_composition_dependencies import VirtualCompositionDependencies
from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
from application.control_tower_hub import ControlTowerHub
from application.environment_hub.contracts import EnvironmentConfig, RuntimePolicy
from application.environment_hub.factory import EnvironmentFactory
from application.environment_hub.hub import EnvironmentHub
from application.run_hub.contracts import RunContext
from application.run_hub.hub import RunSession
from application.runtime_hub.hub import RuntimeHub
from application.runtime_controller.controller import RuntimeController
from application.composition.option_expiry_source import KisOptionMasterExpirySource
from application.composition.standard_runtime_input_provider import StandardRuntimeInputProvider
from contracts.types import EnvironmentType
from core.risk.risk_config import RiskConfig
from core.risk.risk_engine import RiskEngine
from environments.virtual.execution.vssf_command_context_provider import CanonicalVSSFCommandContextProvider
from infrastructure.kis.track2_option_iv_source import KISTrack2OptionIVSource
from interfaces.control_tower.ui_adapter import ControlTowerUIAdapter


def create_virtual_run_session(context: RunContext, option_master: Any) -> RunSession:
    dependencies = VirtualCompositionDependencies(
        contract_registry=None,
        option_master=option_master,
        contract_mappings={},
        initial_capital=float(context.initial_capital or 250_000_000.0),
        vssf_command_context=CanonicalVSSFCommandContextProvider(),
    )
    config = EnvironmentConfig(environment=EnvironmentType.VIRTUAL, name=f"run_{context.run_id}")
    policy = RuntimePolicy()
    holder: dict[str, Any] = {}
    def build(_config: EnvironmentConfig, _policy: RuntimePolicy):
        bundle = ConcreteVirtualEnvironmentBuilder(dependencies=dependencies).build(_config, _policy)
        holder["bundle"] = bundle
        return bundle
    environment_hub = EnvironmentHub(EnvironmentFactory(virtual_builder=build))
    controller = RuntimeController(environment_hub)
    controller.start(config, policy)
    bundle = environment_hub.active
    if bundle is None:
        raise RuntimeError("VIRTUAL_RUN_ENVIRONMENT_NOT_ACTIVE")
    if context.scenario:
        scenario_engine = getattr(bundle.market, "scenario_engine", None)
        if scenario_engine is not None:
            scenario_engine.set_scenario(context.scenario)
    vssf = bundle.execution._authoritative_execute.__self__.vssf_runtime
    risk_engine = RiskEngine(config=RiskConfig(), margin_engine=vssf.margin_engine)
    bridge = VirtualMultiLegExecutionBridge(bundle=bundle, option_master=bundle.option_master, risk_config=RiskConfig())
    bundle.broker_api.attach_group_read_model(
        snapshot_reader=bridge.position_groups.snapshot,
        reports_reader=bridge.group_reports,
        group_ids_reader=lambda: tuple(bridge.position_groups.all().keys()),
    )
    adapter = ControlTowerUIAdapter(runtime_controller=controller, broker_api=bundle.broker_api)
    strategy_hub = None
    loop = attach_standard_automated_loop(type("Bootstrap", (), {"bundle": bundle})(), strategy_keys=context.strategy_keys)
    strategy_hub = loop.strategy_hub
    runtime_hub = RuntimeHub(loop)
    tower = ControlTowerHub(runtime_controller=controller, ui_adapter=adapter, strategy_hub=strategy_hub, run_context=context)
    return RunSession(
        context=context,
        runtime_controller=controller,
        bundle=bundle,
        strategy_hub=strategy_hub,
        runtime_hub=runtime_hub,
        ui_adapter=adapter,
        control_tower_hub=tower,
    )
