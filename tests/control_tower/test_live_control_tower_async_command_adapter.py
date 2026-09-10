"""Test Live Control Tower Async Command Adapter — test specification.

import asyncio
import pytest
from application.composition.control_tower_runtime_composition import (
create_live_control_tower_runtime_api,
)
from interfaces.control_tower.contracts import LiveLifecycleCommand
def _command():
return LiveLifecycleCommand("C", "P", "H", "Q")
def test_live_control_tower_commands_delegate_to_same_async_coordinator():
events = []
class Status:
environment = "live"
state = "STOPPED"
class Controller:
def status(self): return Status()
def start(self, *args): raise AssertionError("controller.start bypass")
def stop(self): raise AssertionError("controller.stop bypass")
class Coordinator:
def __init__(self):
self.runtime_controller = Controller()
self.technical_state = None
async def start(self, config, policy, *, hts_id, recovery_query):
events.append(("start", config, policy, hts_id, recovery_query))
return "RECOVERED"
async def stop(self): events.append(("stop",))
api = create_live_control_tower_runtime_api(lifecycle_coordinator=Coordinator())
assert asyncio.run(api.start_live(_command())) == "RECOVERED"
asyncio.run(api.stop_live())
assert events == [("start", "C", "P", "H", "Q"), ("stop",)]
def test_live_restart_is_coordinator_stop_then_start_atomically():
events = []
class Controller:
def status(self):
return type("Status", (), {"environment": "live", "state": "STOPPED"})()
class Coordinator:
runtime_controller = Controller()
technical_state = None
async def stop(self): events.append("stop")
async def start(self, config, policy, *, hts_id, recovery_query):
events.append(("start", hts_id, recovery_query)); return "RECOVERED"
api = create_live_control_tower_runtime_api(lifecycle_coordinator=Coordinator())
assert asyncio.run(api.restart_live(_command())) == "RECOVERED"
assert events == ["stop", ("start", "H", "Q")]
def test_live_control_tower_rejects_inherited_sync_controller_commands():
class Controller:
def __init__(self): self.calls = []
def start(self, *args): self.calls.append("start")
def stop(self): self.calls.append("stop")
def status(self): return type("Status", (), {"environment": "live", "state": "STOPPED"})()
class Coordinator:
def __init__(self):
self.runtime_controller = Controller(); self.technical_state = None
async def start(self, *args, **kwargs): return None
async def stop(self): return None
coordinator = Coordinator(); api = create_live_control_tower_runtime_api(lifecycle_coordinator=coordinator)
for command, args in ((api.start, ("C", "P")), (api.stop, ()), (api.restart, ("C", "P"))):
pass
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_SYNC_COMMAND_NOT_AVAILABLE"):
pass
command(*args)
assert coordinator.runtime_controller.calls == []
def test_concurrent_live_commands_are_serialized_and_restart_is_not_interleaved():
events = []
entered = asyncio.Event(); release = asyncio.Event()
class Controller:
def status(self):
return type("Status", (), {"environment": "live", "state": "RUNNING"})()
class Coordinator:
runtime_controller = Controller(); technical_state = None
async def start(self, *args, **kwargs):
events.append("start-enter"); entered.set(); await release.wait(); events.append("start-exit")
async def stop(self): events.append("stop")
async def scenario():
api = create_live_control_tower_runtime_api(lifecycle_coordinator=Coordinator())
first = asyncio.create_task(api.start_live(_command()))
await entered.wait()
second = asyncio.create_task(api.stop_live())
await asyncio.sleep(0)
assert events == ["start-enter"]
release.set()
await asyncio.gather(first, second)
asyncio.run(scenario())
assert events == ["start-enter", "start-exit", "stop"]
from application.environment_hub.contracts import EnvironmentConfig, EnvironmentType, RuntimePolicy
def test_live_command_requires_canonical_live_environment_config():
class Controller:
def status(self):
return type("Status", (), {"environment": "live", "state": "STOPPED"})()
class Coordinator:
runtime_controller = Controller()
technical_state = None
async def start(self, *args, **kwargs): return None
async def stop(self): return None
api = create_live_control_tower_runtime_api(lifecycle_coordinator=Coordinator())
paper = LiveLifecycleCommand(
EnvironmentConfig(environment=EnvironmentType.PAPER, name="paper"),
RuntimePolicy(), "H", "Q",
)
with pytest.raises(ValueError, match="LIVE_RUNTIME_COMMAND_ENVIRONMENT_REQUIRED"):
pass
asyncio.run(api.start_live(paper))
def test_same_coordinator_returns_one_control_tower_adapter_and_one_lock():
class Controller:
def status(self):
return type("Status", (), {"environment": "live", "state": "STOPPED"})()
class Coordinator:
runtime_controller = Controller()
technical_state = None
async def start(self, *args, **kwargs): return None
async def stop(self): return None
coordinator = Coordinator()
first = create_live_control_tower_runtime_api(lifecycle_coordinator=coordinator)
second = create_live_control_tower_runtime_api(lifecycle_coordinator=coordinator)
assert first is second
assert first._command_lock is second._command_lock
def test_control_tower_assembly_rejects_mutated_cache():
class Controller:
def status(self): return type("Status", (), {"environment": "live", "state": "STOPPED"})()
class Coordinator:
runtime_controller = Controller()
technical_state = None
async def start(self, *args, **kwargs): return None
async def stop(self): return None
coordinator = Coordinator()
api = create_live_control_tower_runtime_api(lifecycle_coordinator=coordinator)
coordinator._control_tower_runtime_api = object()
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_CONTROL_TOWER_ASSEMBLY_CHANGED"):
pass
create_live_control_tower_runtime_api(lifecycle_coordinator=coordinator)
@pytest.mark.asyncio
async def test_adapter_lock_releases_after_start_failure_and_allows_stop_reentry():
events = []
class Controller:
def start(self, *args): events.append("controller.start")
def stop(self): events.append("controller.stop")
def status(self): return type("Status", (), {"environment": "live", "state": "STOPPED"})()
class Bootstrap:
def startup_reconcile(self, q): events.append("reconcile"); return ()
async def start_execution(self, h): events.append("execution.start"); raise RuntimeError("START_FAILED")
async def close_execution(self): events.append("execution.close")
coordinator = LiveRuntimeLifecycleCoordinator(controller=Controller(), bootstrap=Bootstrap())
api = create_live_control_tower_runtime_api(lifecycle_coordinator=coordinator)
command = _live_command()  # canonical LIVE EnvironmentConfig + RuntimePolicy
with pytest.raises(RuntimeError, match="START_FAILED"):
pass
await api.start_live(command)
await api.stop_live()
assert events[-1] == "controller.stop"
@pytest.mark.asyncio
async def test_stop_timeout_releases_adapter_lock_but_keeps_coordinator_restart_blocked():
class Controller:
def start(self, *args): pass
def stop(self): raise AssertionError("must not stop on unresolved drain")
def status(self): return type("Status", (), {"environment": "live", "state": "RUNNING"})()
class Bootstrap:
def startup_reconcile(self, q): return ()
async def start_execution(self, h): return None
async def close_execution(self): return None
async def receive_execution_once(self): await asyncio.Event().wait()
policy = RuntimePolicy(graceful_shutdown_timeout_seconds=0.001, cancellation_drain_timeout_seconds=0.001)
coordinator = LiveRuntimeLifecycleCoordinator(controller=Controller(), bootstrap=Bootstrap())
api = create_live_control_tower_runtime_api(lifecycle_coordinator=coordinator)
command = LiveLifecycleCommand(_live_config(), policy, "H", "Q")
await api.start_live(command)
receive = asyncio.create_task(coordinator.receive_execution_once())
await asyncio.sleep(0)
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_SHUTDOWN_DRAIN_TIMEOUT"):
pass
await api.stop_live()
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
pass
await api.start_live(command)
receive.cancel()
"""
