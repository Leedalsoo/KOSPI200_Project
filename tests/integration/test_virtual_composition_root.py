"""Test Virtual Composition Root — 테스트 사양 문서.

from application.composition.virtual_composition_root import (
create_virtual_composition_dependencies,
create_virtual_environment_factory,
)
from application.environment_hub.contracts import (
EnvironmentConfig, EnvironmentType, RuntimePolicy,
)
from environments.virtual.execution.vssf_command_context_provider import CanonicalVSSFCommandContextProvider
class Registry:
def get_contract_identity(self, shrn_iscd):
return object() if shrn_iscd == "201ABC" else None
class Builder:
def __init__(self, bundle): self.bundle = bundle; self.calls = []
def build(self, config, policy):
self.calls.append((config, policy)); return self.bundle
def test_composition_dependencies_accept_concrete_vssf_provider():
registry = Registry()
scenario_source = {"contract_mappings": [{"scenario_contract_key": "scenario-call", "shrn_iscd": "201ABC"}]}
provider = CanonicalVSSFCommandContextProvider()
dependencies = create_virtual_composition_dependencies(
contract_registry=registry, scenario_configuration=scenario_source,
initial_capital=12_345_678.0, vssf_command_context=provider,
scenario_source=scenario_source,
)
assert dependencies.contract_registry is registry
assert dependencies.scenario_source is scenario_source
assert dependencies.contract_mappings["scenario-call"].shrn_iscd == "201ABC"
assert dependencies.initial_capital == 12_345_678.0
assert dependencies.vssf_command_context is provider
def test_factory_uses_existing_virtual_builder_seam():
bundle = object(); builder = Builder(bundle)
factory = create_virtual_environment_factory(builder=builder)
config = EnvironmentConfig(environment=EnvironmentType.VIRTUAL, name="virtual-test")
policy = RuntimePolicy()
result = factory.create(config, policy)
assert result is bundle
assert builder.calls == [(config, policy)]
"""
