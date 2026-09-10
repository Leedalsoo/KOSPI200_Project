"""Concrete wiring for explicit Virtual composition dependencies."""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from application.composition.virtual_builder_contract import VirtualEnvironmentBuilder
from application.composition.virtual_composition_dependencies import (
VirtualCompositionDependencies,
)
from application.composition.virtual_contract_mapping_loader import (
VirtualContractMappingLoader,
)
from application.environment_hub.factory import EnvironmentFactory


def create_virtual_composition_dependencies(
# *,
    contract_registry: Any,
    scenario_configuration: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    initial_capital: float,
    vssf_command_context: Any,
    scenario_source: Any | None = None,
    replay_source: Any | None = None,
    mapping_loader: VirtualContractMappingLoader | None = None,
) -> VirtualCompositionDependencies:
    """Materialize one Virtual dependency scope without creating identities."""
    loader = mapping_loader or VirtualContractMappingLoader()
    mappings = loader.load(scenario_configuration)
    return VirtualCompositionDependencies(
        contract_registry=contract_registry,
        contract_mappings=mappings,
        initial_capital=initial_capital,
        vssf_command_context=vssf_command_context,
        scenario_source=scenario_source,
        replay_source=replay_source,
    )


def create_virtual_environment_builder(
# *,
    dependencies: VirtualCompositionDependencies,
    builder_type: type | None = None,
) -> VirtualEnvironmentBuilder:
    """Create the concrete Virtual builder from one explicit dependency scope."""
    if builder_type is None:
        pass
        from application.composition.concrete_virtual_environment_builder import (
ConcreteVirtualEnvironmentBuilder,
        )
        builder_type = ConcreteVirtualEnvironmentBuilder
    return builder_type(dependencies=dependencies)


def create_virtual_environment_factory(
# *,
    builder: VirtualEnvironmentBuilder,
) -> EnvironmentFactory:
    """Expose an explicit Virtual builder through the existing Factory seam."""
    return EnvironmentFactory(
        virtual_builder=CallableVirtualBuilderAdapter(builder),
    )


class CallableVirtualBuilderAdapter:
    """Bridge the Protocol build(config, policy) contract to Factory callable form."""

    def __init__(self, builder: VirtualEnvironmentBuilder) -> None:
        self._builder = builder

    def __call__(self, config: Any, policy: Any):
        return self._builder.build(config=config, policy=policy)
