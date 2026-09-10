"""Explicit application assembly for one Virtual runtime scope."""
from __future__ import annotations
from collections.abc import Mapping, Sequence
from typing import Any
from application.composition.virtual_composition_root import create_virtual_composition_dependencies, create_virtual_environment_builder, create_virtual_environment_factory
from application.environment_hub.hub import EnvironmentHub
from application.runtime_controller.controller import RuntimeController


def create_virtual_runtime_controller(*, contract_registry: Any, scenario_configuration: Mapping[str, Any] | Sequence[Mapping[str, Any]], initial_capital: float, vssf_command_context: Any, scenario_source: Any | None = None, replay_source: Any | None = None) -> RuntimeController:
    dependencies = create_virtual_composition_dependencies(
        contract_registry=contract_registry,
        scenario_configuration=scenario_configuration,
        initial_capital=initial_capital,
        vssf_command_context=vssf_command_context,
        scenario_source=scenario_source,
        replay_source=replay_source,
    )
    builder = create_virtual_environment_builder(dependencies=dependencies)
    factory = create_virtual_environment_factory(builder=builder)
    return RuntimeController(hub=EnvironmentHub(factory=factory))
