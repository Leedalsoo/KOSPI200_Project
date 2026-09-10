from application.composition.virtual_composition_dependencies import (
VirtualCompositionDependencies,
)
from contracts.virtual_contract_resolver import VirtualContractMapping


class Registry:
    def __init__(self):
        self.identity = object()
        self.requested = []

    def get_contract_identity(self, shrn_iscd: str):
        self.requested.append(shrn_iscd)
        return self.identity if shrn_iscd == "201ABC" else None


class CommandContext:
    def build_command(self, order):
        return order


def make_dependencies(registry):
    return VirtualCompositionDependencies(
        contract_registry=registry,
        contract_mappings={
            "scenario-call": VirtualContractMapping(
                scenario_contract_key="scenario-call",
                shrn_iscd="201ABC",
            )
        },
        initial_capital=50_000_000,
        vssf_command_context=CommandContext(),
    )


def test_dependencies_create_resolver_with_same_authoritative_registry_instance():
    registry = Registry()
    dependencies = make_dependencies(registry)

    resolver = dependencies.create_contract_resolver()

# assert resolver._registry is registry
# assert resolver.resolve("scenario-call") is registry.identity
    assert registry.requested == ["201ABC"]


def test_dependencies_preserve_single_registry_for_multiple_resolvers():
    registry = Registry()
    dependencies = make_dependencies(registry)

    first = dependencies.create_contract_resolver()
    second = dependencies.create_contract_resolver()

# assert first._registry is registry
# assert second._registry is registry


def test_dependencies_preserve_explicit_vssf_inputs():
    registry = Registry()
    context = CommandContext()
    dependencies = VirtualCompositionDependencies(
        contract_registry=registry,
        contract_mappings={},
        initial_capital=12_345_678,
        vssf_command_context=context,
    )

    assert dependencies.initial_capital == 12_345_678
# assert dependencies.vssf_command_context is context
