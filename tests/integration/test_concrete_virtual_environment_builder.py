"""Test Concrete Virtual Environment Builder — test specification.

from application.composition.concrete_virtual_environment_builder import (
ConcreteVirtualEnvironmentBuilder,
)
class Dependencies:
initial_capital = 12_345_678
vssf_command_context = object()
class Scope:
def __init__(self):
self.vssf_runtime = object()
self.broker = object()
self.account = object()
self.position = object()
self.execution = object()
class ScopeFactory:
def __init__(self):
self.calls = []
self.scope = Scope()
def create(self, config, policy):
self.calls.append((config, policy))
return self.scope
class VMS:
def __init__(self):
self.clock = object()
class Bundle:
calls = []
@classmethod
def create(cls, config, policy, *, market, clock, broker, account, position, execution):
cls.calls.append({
"config": config,
"policy": policy,
"market": market,
"clock": clock,
"broker": broker,
"account": account,
"position": position,
"execution": execution,
})
return cls.calls[-1]
def test_builder_reuses_one_scope_and_passes_all_components(monkeypatch):
scope_factory = ScopeFactory()
vms = VMS()
builder = ConcreteVirtualEnvironmentBuilder(
dependencies=Dependencies(),
scope_factory=scope_factory,
vms_factory=lambda: vms,
)
Replace only concrete runtime constructors at the composition boundary;
this test does not create a real VMS/VSSF.
class ClockProvider:
def __init__(self, source):
self.source = source
monkeypatch.setattr(
"application.composition.concrete_virtual_environment_builder.VirtualEnvironmentBundle",
Bundle,
)
monkeypatch.setattr(
"application.composition.concrete_virtual_environment_builder.VMSClockProvider",
ClockProvider,
)
result = builder.build("config", "policy")
assert scope_factory.calls == [("config", "policy")]
assert result["market"] is vms
assert result["broker"] is scope_factory.scope.broker
assert result["account"] is scope_factory.scope.account
assert result["position"] is scope_factory.scope.position
assert result["execution"] is scope_factory.scope.execution
assert result["clock"].source is vms.clock
def test_dependency_validation_remains_owned_by_dependencies():
from application.composition.virtual_composition_dependencies import (
VirtualCompositionDependencies,
)
try:
pass
VirtualCompositionDependencies(
contract_registry=object(),
contract_mappings={},
initial_capital=0,
vssf_command_context=object(),
)
except (ValueError, TypeError) as exc:
pass
assert str(exc) in {
"VIRTUAL_INITIAL_CAPITAL_REQUIRED",
"VSSF_COMMAND_CONTEXT_REQUIRED",
}
else:
pass
raise AssertionError("invalid composition dependencies must fail closed")
"""
