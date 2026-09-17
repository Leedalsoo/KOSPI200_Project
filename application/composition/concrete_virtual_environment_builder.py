"""Concrete authoritative VMS/VSSF builder for one Virtual environment scope."""
from __future__ import annotations
from typing import Any
from application.composition.virtual_builder_contract import VirtualAuthoritativeScope, VirtualAuthoritativeScopeFactory
from application.composition.virtual_composition_dependencies import VirtualCompositionDependencies
from environments.virtual.bundle import VirtualEnvironmentBundle
from environments.virtual.broker.virtual_broker import VirtualBroker
from environments.virtual.broker.virtual_broker_api import VirtualBrokerApi
from environments.virtual.account.vssf_account_snapshot_adapter import VSSFAccountSnapshotAdapter
from environments.virtual.position.vssf_position_aggregate_adapter import VSSFPositionAggregateAdapter
from environments.virtual.execution.virtual_execution import VirtualExecutionEngine
from environments.virtual.execution.vssf_execution_adapter import VSSFExecutionAdapter
from environments.virtual.clock import VMSClockProvider
from environments.virtual.market.simulator_runtime import VirtualMarketSimulatorRuntime
from environments.virtual.authoritative_vssf.firm_runtime import VirtualSecuritiesFirmRuntime

class ReferenceVirtualAuthoritativeScopeFactory(VirtualAuthoritativeScopeFactory):
    def __init__(self, *, dependencies: VirtualCompositionDependencies) -> None:
        self._dependencies = dependencies
    def create(self, config: Any, policy: Any) -> VirtualAuthoritativeScope:
        dependencies = self._dependencies
        vssf = VirtualSecuritiesFirmRuntime(initial_capital=float(dependencies.initial_capital))
        account = VSSFAccountSnapshotAdapter(vssf.account)
        position = VSSFPositionAggregateAdapter(vssf.account)
        execution_adapter = VSSFExecutionAdapter(command_context=dependencies.vssf_command_context, vssf_runtime=vssf)
        execution = VirtualExecutionEngine(position=position, account=account, authoritative_execute=execution_adapter.execute)
        return VirtualAuthoritativeScope(vssf_runtime=vssf, broker=VirtualBroker(execution, market_data_handler=vssf.process_market_data), account=account, position=position, execution=execution)

class ConcreteVirtualEnvironmentBuilder:
    def __init__(self, *, dependencies: VirtualCompositionDependencies, scope_factory: VirtualAuthoritativeScopeFactory | None = None, vms_factory=VirtualMarketSimulatorRuntime) -> None:
        self._dependencies = dependencies
        self._scope_factory = scope_factory or ReferenceVirtualAuthoritativeScopeFactory(dependencies=dependencies)
        self._vms_factory = vms_factory
    def build(self, config: Any, policy: Any) -> VirtualEnvironmentBundle:
        scope = self._scope_factory.create(config, policy)
        vms = self._vms_factory(option_master=self._dependencies.option_master)
        vms.subscribe(lambda tick: scope.broker.process_market_data(tick, option_quotes=vms.option_quotes))
        broker_api = VirtualBrokerApi(scope.broker, scope.account)
        return VirtualEnvironmentBundle.create(config=config, policy=policy, market=vms, clock=VMSClockProvider(vms.clock), broker=scope.broker, broker_api=broker_api, account=scope.account, position=scope.position, execution=scope.execution, option_master=self._dependencies.option_master)
