"""Test Runtime Controller Virtual Integration — test specification.

from application.composition import runtime_composition_factory as subject
from application.environment_hub.contracts import (
EnvironmentConfig,
EnvironmentType,
RuntimePolicy,
)
class LifecycleBundle:
def __init__(self):
self.environment = EnvironmentType.VIRTUAL
self.calls = []
self.connected = False
self.running = False
def initialize(self):
self.calls.append("initialize")
def connect(self):
self.calls.append("connect")
self.connected = True
def start(self):
self.calls.append("start")
if not self.connected:
pass
raise RuntimeError("not connected")
self.running = True
def stop(self):
self.calls.append("stop")
self.running = False
def shutdown(self):
self.calls.append("shutdown")
self.connected = False
class Builder:
def __init__(self, bundle):
self.bundle = bundle
self.calls = []
def build(self, config, policy):
self.calls.append((config, policy))
return self.bundle
def test_virtual_runtime_controller_start_stop_through_real_assembly(monkeypatch):
bundle = LifecycleBundle()
builder = Builder(bundle)
dependencies = object()
monkeypatch.setattr(
subject,
"create_virtual_composition_dependencies",
lambda **kwargs: dependencies,
)
monkeypatch.setattr(
subject,
"create_virtual_environment_builder",
lambda *, dependencies: builder,
)
controller = subject.create_virtual_runtime_controller(
contract_registry=object(),
scenario_configuration={"contract_mappings": []},
initial_capital=1000.0,
vssf_command_context=object(),
)
config = EnvironmentConfig(
environment=EnvironmentType.VIRTUAL,
name="virtual-integration",
)
policy = RuntimePolicy()
controller.start(config, policy)
assert builder.calls == [(config, policy)]
assert bundle.calls == ["initialize", "connect", "start"]
assert bundle.connected is True
assert bundle.running is True
assert controller.status().environment == "virtual"
assert controller.status().state == "RUNNING"
controller.stop()
assert bundle.calls == [
"initialize", "connect", "start", "stop", "shutdown"
]
assert bundle.connected is False
assert bundle.running is False
assert controller.status().environment is None
assert controller.status().state == "STOPPED"
"""
