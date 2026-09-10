"""Test Control Tower Live Status Assembly — 테스트 사양 문서.

from application.composition.control_tower_runtime_composition import (
create_live_control_tower_runtime_api,
)
class _Status:
def __init__(self, environment="live", state="STOPPING"):
self.environment = environment
self.state = state
class _Controller:
def status(self):
return _Status()
class _Coordinator:
def __init__(self, technical_state=None):
self.runtime_controller = _Controller()
self.technical_state = technical_state
def test_live_control_tower_assembly_projects_stop_timeout_fail_closed():
coordinator = _Coordinator("STOP_TIMEOUT")
api = create_live_control_tower_runtime_api(
lifecycle_coordinator=coordinator,
)
status = api.status()
assert api._runtime is coordinator.runtime_controller
assert api._lifecycle_status_source is coordinator
assert status.technical_state == "STOP_TIMEOUT"
assert status.execution_allowed is False
assert status.reason == "STOP_TIMEOUT"
def test_live_control_tower_assembly_rejects_missing_coordinator():
try:
pass
create_live_control_tower_runtime_api(lifecycle_coordinator=None)
except ValueError as exc:
pass
assert str(exc) == "LIVE_RUNTIME_LIFECYCLE_COORDINATOR_REQUIRED"
else:
pass
raise AssertionError("missing coordinator must fail closed")
import pytest
def test_stop_timeout_control_tower_rejects_start_and_restart_without_controller_bypass():
class Status:
environment = "live"
state = "STOPPED"
class Controller:
def __init__(self):
self.started = 0
self.stopped = 0
def start(self, config, policy):
self.started += 1
def stop(self):
self.stopped += 1
def status(self):
return Status()
controller = Controller()
coordinator = type(
"Coordinator",
(), {"runtime_controller": controller, "technical_state": "STOP_TIMEOUT"},
)()
api = create_live_control_tower_runtime_api(
lifecycle_coordinator=coordinator,
)
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
pass
api.start("CONFIG", "POLICY")
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
pass
api.restart("CONFIG", "POLICY")
assert controller.started == 0
assert controller.stopped == 0
def test_stop_timeout_control_tower_rejects_direct_stop_bypass():
class Status:
environment = "live"
state = "STOPPED"
class Controller:
def __init__(self):
self.stopped = 0
def stop(self):
self.stopped += 1
def status(self):
return Status()
controller = Controller()
coordinator = type(
"Coordinator",
(), {"runtime_controller": controller, "technical_state": "STOP_TIMEOUT"},
)()
api = create_live_control_tower_runtime_api(lifecycle_coordinator=coordinator)
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_STOP_NOT_ADMITTED"):
pass
api.stop()
assert controller.stopped == 0
def test_control_tower_fails_closed_when_coordinator_identity_guard_rejects_status_source():
class Status:
environment = "live"
state = "RUNNING"
class Controller:
def status(self):
return Status()
class Coordinator:
runtime_controller = Controller()
@property
def technical_state(self):
raise RuntimeError("LIVE_RUNTIME_CONTROLLER_IDENTITY_CHANGED")
api = create_live_control_tower_runtime_api(lifecycle_coordinator=Coordinator())
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_CONTROLLER_IDENTITY_CHANGED"):
pass
api.status()
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_CONTROLLER_IDENTITY_CHANGED"):
pass
api.start("CONFIG", "POLICY")
import asyncio
import pytest
def test_status_polling_fails_closed_during_live_command_when_identity_changes():
class Controller:
def status(self):
return type("Status", (), {"environment": "live", "state": "RUNNING"})()
class Coordinator:
def __init__(self):
self.runtime_controller = Controller()
self._bad = False
@property
def technical_state(self):
if self._bad:
pass
raise RuntimeError("LIVE_RUNTIME_CONTROLLER_IDENTITY_CHANGED")
return None
async def start(self, *args, **kwargs):
self._bad = True
coordinator = Coordinator()
api = create_live_control_tower_runtime_api(lifecycle_coordinator=coordinator)
async def scenario():
command = LiveLifecycleCommand("C", "P", "H", "Q")
task = asyncio.create_task(api.start_live(command))
await task
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_CONTROLLER_IDENTITY_CHANGED"):
pass
api.status()
asyncio.run(scenario())
import asyncio
from types import SimpleNamespace
import pytest
from application.composition.control_tower_runtime_composition import (
create_live_control_tower_runtime_api,
)
from application.composition.live_runtime_lifecycle_coordinator import (
LiveRuntimeLifecycleCoordinator,
)
class _Controller:
def __init__(self):
self.started = 0
self.stopped = 0
def start(self, config, policy):
self.started += 1
def stop(self):
self.stopped += 1
def status(self):
return SimpleNamespace(environment="live", state="STOPPED")
class _Bootstrap:
def startup_reconcile(self, query):
return ()
async def start_execution(self, hts_id):
return None
async def close_execution(self):
return None
class _Policy:
graceful_shutdown_timeout_seconds = 0
cancellation_drain_timeout_seconds = 0
@pytest.mark.parametrize(
"technical_state",
[
"STOP_TIMEOUT",
"STOP_CONTROLLER_FAILED",
"STOP_EXECUTION_CLOSE_FAILED",
"TRANSPORT_OWNERSHIP_RELEASE_FAILED",
],
)
def test_any_terminal_technical_state_is_projected_and_async_commands_cannot_bypass(technical_state):
controller = _Controller()
coordinator = LiveRuntimeLifecycleCoordinator(
controller=controller,
bootstrap=_Bootstrap(),
)
coordinator._technical_state = technical_state
api = create_live_control_tower_runtime_api(
lifecycle_coordinator=coordinator,
)
status = api.status()
assert status.technical_state == technical_state
assert status.execution_allowed is False
assert status.reason == technical_state
Live adapter의 sync command는 별도 정책으로 항상 차단된다.
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_SYNC_COMMAND_NOT_AVAILABLE"):
pass
api.start("CONFIG", "POLICY")
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_SYNC_COMMAND_NOT_AVAILABLE"):
pass
api.stop()
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_SYNC_COMMAND_NOT_AVAILABLE"):
pass
api.restart("CONFIG", "POLICY")
async def run_async_commands():
command = SimpleNamespace(
config="CONFIG",
policy=_Policy(),
hts_id="HTS",
recovery_query="Q",
)
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
pass
await api.start_live(command)
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
pass
await api.stop_live()
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
pass
await api.restart_live(command)
asyncio.run(run_async_commands())
assert controller.started == 0
assert controller.stopped == 0
import asyncio
import pytest
from application.composition.control_tower_runtime_composition import (
create_live_control_tower_runtime_api,
)
from application.composition.live_runtime_lifecycle_coordinator import (
LiveRuntimeLifecycleCoordinator,
)
from application.composition.live_runtime_production_factory import (
_LiveExecutionTransportOwnershipRegistry,
)
@pytest.mark.asyncio
async def test_startup_cleanup_terminal_state_survives_status_polling_during_serialized_command():
status_reads = []
class Controller:
def __init__(self): self.starts = 0
def start(self, *args): self.starts += 1
def status(self):
return type("Status", (), {"environment": "live", "state": "STOPPED"})()
class Bootstrap:
def startup_reconcile(self, query): return ()
async def start_execution(self, hts_id): raise asyncio.CancelledError()
async def close_execution(self): raise asyncio.CancelledError()
controller = Controller()
coordinator = LiveRuntimeLifecycleCoordinator(controller=controller, bootstrap=Bootstrap())
with pytest.raises(asyncio.CancelledError):
pass
await coordinator.start("C", "P", hts_id="H", recovery_query="Q")
api = create_live_control_tower_runtime_api(lifecycle_coordinator=coordinator)
command = type("Command", (), {"config":"C", "policy":"P", "hts_id":"H2", "recovery_query":"Q2"})()
blocked = asyncio.create_task(api.start_live(command))
await asyncio.sleep(0)
for _ in range(3):
pass
status = api.status()
status_reads.append((status.technical_state, status.execution_allowed, status.reason))
await asyncio.sleep(0)
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
pass
await blocked
assert status_reads == [
("STARTUP_CLEANUP_CANCELLED", False, "STARTUP_CLEANUP_CANCELLED"),
] * 3
assert controller.starts == 1
def test_startup_cleanup_terminal_state_concurrent_transport_claim_has_single_owner():
registry = _LiveExecutionTransportOwnershipRegistry()
transport = object()
release = registry.claim(transport)
class Controller:
def start(self, *args): pass
def stop(self): raise AssertionError("unresolved cleanup must retain ownership")
class Bootstrap:
def startup_reconcile(self, query): return ()
async def start_execution(self, hts_id): raise asyncio.CancelledError()
async def close_execution(self): raise asyncio.CancelledError()
coordinator = LiveRuntimeLifecycleCoordinator(
controller=Controller(), bootstrap=Bootstrap(),
release_execution_transport_ownership=release,
)
with pytest.raises(asyncio.CancelledError):
pass
asyncio.run(coordinator.start("C", "P", hts_id="H", recovery_query="Q"))
failures = []
for _ in range(3):
pass
with pytest.raises(RuntimeError, match="LIVE_EXECUTION_TRANSPORT_ALREADY_OWNED") as exc:
pass
registry.claim(transport)
failures.append(str(exc.value))
assert failures == ["LIVE_EXECUTION_TRANSPORT_ALREADY_OWNED"] * 3
assert coordinator.technical_state == "STARTUP_CLEANUP_CANCELLED"
import asyncio
from types import SimpleNamespace
import pytest
from application.composition.control_tower_runtime_composition import (
create_live_control_tower_runtime_api,
)
from application.composition.live_runtime_lifecycle_coordinator import (
LiveRuntimeLifecycleCoordinator,
)
_TERMINAL_STATES = (
"STOP_TIMEOUT",
"STOP_CONTROLLER_FAILED",
"STOP_EXECUTION_CLOSE_FAILED",
"TRANSPORT_OWNERSHIP_RELEASE_FAILED",
"STOP_SHUTDOWN_CANCELLED",
"STARTUP_CLEANUP_CANCELLED",
)
class _Controller:
def __init__(self):
self.started = 0
self.stopped = 0
def start(self, config, policy): self.started += 1
def stop(self): self.stopped += 1
def status(self):
return SimpleNamespace(environment="live", state="STOPPED")
class _Bootstrap:
def startup_reconcile(self, query): return ()
async def start_execution(self, hts_id): return None
async def close_execution(self): return None
NaNdef test_terminal_technical_state_common_invariant_projects_and_blocks_all_lifecycle_commands(technical_state):
controller = _Controller()
coordinator = LiveRuntimeLifecycleCoordinator(
controller=controller, bootstrap=_Bootstrap()
)
coordinator._technical_state = technical_state
api = create_live_control_tower_runtime_api(
lifecycle_coordinator=coordinator
)
status = api.status()
assert (status.technical_state, status.execution_allowed, status.reason) == (
technical_state, False, technical_state
)
command = SimpleNamespace(
config="CONFIG", policy="POLICY", hts_id="HTS", recovery_query="Q"
)
async def scenario():
for operation in (
lambda: api.start_live(command),
api.stop_live,
lambda: api.restart_live(command),
):
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
pass
await operation()
asyncio.run(scenario())
assert controller.started == 0
assert controller.stopped == 0
def test_clean_state_remains_admitted_and_is_not_captured_by_terminal_invariant():
controller = _Controller()
coordinator = LiveRuntimeLifecycleCoordinator(
controller=controller, bootstrap=_Bootstrap()
)
api = create_live_control_tower_runtime_api(lifecycle_coordinator=coordinator)
status = api.status()
assert status.technical_state is None
assert status.execution_allowed is True
"""
