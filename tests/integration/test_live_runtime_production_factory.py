"""Test Live Runtime Production Factory — test specification.

import asyncio
import pytest
from application.composition import live_runtime_production_factory as factory
def _deps():
pass
deps = {
name: object()
for name in (
"market", "broker", "account", "position", "reconciler", "transport",
"execution_adapter", "correlation_provider", "order_state_machine",
"execution_event_deduplicator", "safety_policy",
)
}
aggregate = object()
deps["position_aggregate"] = aggregate
deps["position_fill_adapter"] = type("FillAdapter", (), {"_aggregate": aggregate})()
return deps
def test_factory_uses_single_bootstrap_recovery_and_controller(monkeypatch):
pass
events = []
class Bootstrap:
pass
recovery_service = object()
def fake_bootstrap(**kwargs):
pass
events.append(("bootstrap", kwargs))
return Bootstrap()
def fake_builder(**kwargs):
pass
events.append(("bundle_builder", kwargs))
return object()
def fake_controller(*, live_builder):
pass
events.append(("controller", live_builder))
return object()
class Coordinator:
pass
def __init__(self, *, controller, bootstrap, **kwargs):
pass
self.controller = controller
self.bootstrap = bootstrap
monkeypatch.setattr(factory, "create_live_runtime_bootstrap", fake_bootstrap)
monkeypatch.setattr(factory, "build_live_bundle_from_components", fake_builder)
monkeypatch.setattr(factory, "create_live_runtime_controller", fake_controller)
monkeypatch.setattr(factory, "LiveRuntimeLifecycleCoordinator", Coordinator)
deps = _deps()
coordinator = factory.create_live_runtime_lifecycle_coordinator(**deps)
assert isinstance(coordinator, Coordinator)
assert [name for name, *_ in events] == ["bootstrap", "bundle_builder", "controller"]
assert events[1][1]["recovery"] is coordinator.bootstrap.recovery_service
bootstrap_kwargs = events[0][1]
builder_kwargs = events[1][1]
assert bootstrap_kwargs["broker"] is deps["broker"]
assert bootstrap_kwargs["order_state_machine"] is deps["order_state_machine"]
assert bootstrap_kwargs["correlation_provider"] is deps["correlation_provider"]
assert bootstrap_kwargs["position_aggregate"] is deps["position_aggregate"]
assert builder_kwargs["broker"] is deps["broker"]
assert builder_kwargs["position"] is deps["position"]
def test_factory_rejects_position_fill_adapter_bound_to_different_aggregate(monkeypatch):
pass
deps = _deps()
deps["position_fill_adapter"] = type("FillAdapter", (), {"_aggregate": object()})()
with pytest.raises(ValueError, match="LIVE_RUNTIME_POSITION_AGGREGATE_OWNERSHIP_MISMATCH"):
pass
factory.create_live_runtime_lifecycle_coordinator(**deps)
def test_concrete_assembly_exposes_required_lifecycle_graph(monkeypatch):
pass
events = []
class Bootstrap:
pass
recovery_service = object()
def startup_reconcile(self, query):
pass
events.append("reconcile")
return "recovered"
async def start_execution(self, hts_id):
events.append("execution.start")
async def receive_execution_once(self):
events.append("execution.receive")
return "event"
async def close_execution(self):
events.append("execution.close")
class Controller:
pass
def start(self, config, policy):
pass
events.extend(["bundle.initialize", "bundle.connect", "bundle.start"])
def stop(self):
pass
events.extend(["bundle.stop", "bundle.shutdown"])
holder = {}
def fake_bootstrap(**kwargs):
pass
bootstrap = Bootstrap()
holder["bootstrap"] = bootstrap
return bootstrap
def fake_builder(**kwargs):
pass
holder["builder_kwargs"] = kwargs
return object()
def fake_controller(*, live_builder):
pass
holder["controller"] = Controller()
return holder["controller"]
monkeypatch.setattr(factory, "create_live_runtime_bootstrap", fake_bootstrap)
monkeypatch.setattr(factory, "build_live_bundle_from_components", fake_builder)
monkeypatch.setattr(factory, "create_live_runtime_controller", fake_controller)
coordinator = factory.create_live_runtime_lifecycle_coordinator(**_deps())
asyncio.run(coordinator.start(object(), object(), hts_id="H", recovery_query=object()))
asyncio.run(coordinator.receive_execution_once())
asyncio.run(coordinator.stop())
assert events == [
"bundle.initialize", "bundle.connect", "bundle.start",
"reconcile", "execution.start", "execution.receive",
"execution.close", "bundle.stop", "bundle.shutdown",
]
assert holder["builder_kwargs"]["recovery"] is holder["bootstrap"].recovery_service
def test_factory_requires_and_validates_risk_state_providers_for_injected_tick_entry(monkeypatch):
pass
class Bootstrap:
pass
recovery_service = object()
def fake_bootstrap(**kwargs):
pass
return Bootstrap()
monkeypatch.setattr(factory, "create_live_runtime_bootstrap", fake_bootstrap)
monkeypatch.setattr(factory, "build_live_bundle_from_components", lambda **kwargs: object())
monkeypatch.setattr(factory, "create_live_runtime_controller", lambda *, live_builder: object())
account_provider = lambda: "account"
position_provider = lambda: "position"
providers = type(
"Providers",
(),
{
"account_snapshot_provider": account_provider,
"position_source_provider": position_provider,
},
)()
tick_entry = type(
"TickEntry",
(),
{
"account_snapshot_provider": account_provider,
"position_source_provider": position_provider,
},
)()
deps = _deps()
deps["tick_entry"] = tick_entry
with pytest.raises(ValueError, match="LIVE_RUNTIME_RISK_STATE_PROVIDERS_REQUIRED"):
pass
factory.create_live_runtime_lifecycle_coordinator(**deps)
deps["risk_state_providers"] = providers
coordinator = factory.create_live_runtime_lifecycle_coordinator(**deps)
assert coordinator.bootstrap is not None
deps["risk_state_providers"] = type(
"Providers",
(),
{
"account_snapshot_provider": lambda: "other-account",
"position_source_provider": position_provider,
},
)()
with pytest.raises(ValueError, match="LIVE_RUNTIME_RISK_STATE_PROVIDER_OWNERSHIP_MISMATCH:account_snapshot_provider"):
pass
factory.create_live_runtime_lifecycle_coordinator(**deps)
def test_stop_restart_preserves_nested_execution_graph_identity(monkeypatch):
class Settlement:
def __init__(self):
self.position_aggregate = object()
self.order_state_machine = object()
self.execution_event_deduplicator = object()
class Execution:
def __init__(self):
self.settlement = Settlement()
self.broker = object()
self.recovery_service = object()
class Bootstrap:
def __init__(self):
self.execution = Execution()
self.recovery_service = self.execution.recovery_service
def startup_reconcile(self, query): return "ok"
async def start_execution(self, hts_id): pass
async def close_execution(self): pass
class Controller:
def start(self, config, policy): pass
def stop(self): pass
bootstrap = Bootstrap()
coordinator = factory.LiveRuntimeLifecycleCoordinator(controller=Controller(), bootstrap=bootstrap)
settlement = bootstrap.execution.settlement
graph_before = tuple(map(id, (bootstrap, bootstrap.execution, settlement, settlement.position_aggregate, settlement.order_state_machine, settlement.execution_event_deduplicator, bootstrap.execution.broker, bootstrap.recovery_service)))
asyncio.run(coordinator.start("CONFIG", "POLICY", hts_id="H", recovery_query="Q1"))
asyncio.run(coordinator.stop())
asyncio.run(coordinator.start("CONFIG", "POLICY", hts_id="H", recovery_query="Q2"))
assert tuple(map(id, (coordinator._bootstrap, coordinator._bootstrap.execution, coordinator._bootstrap.execution.settlement, coordinator._bootstrap.execution.settlement.position_aggregate, coordinator._bootstrap.execution.settlement.order_state_machine, coordinator._bootstrap.execution.settlement.execution_event_deduplicator, coordinator._bootstrap.execution.broker, coordinator._bootstrap.recovery_service))) == graph_before
def test_explicit_new_runtime_graph_is_disjoint_from_old_runtime_graph():
old = new_runtime_graph()
new = new_runtime_graph()
old_ids = {
id(old), id(old._controller), id(old._bootstrap),
id(old._bootstrap.execution),
id(old._bootstrap.execution.settlement),
}
new_ids = {
id(new), id(new._controller), id(new._bootstrap),
id(new._bootstrap.execution),
id(new._bootstrap.execution.settlement),
}
assert old_ids.isdisjoint(new_ids)
@pytest.mark.asyncio
async def test_shared_execution_transport_cannot_be_reowned_until_old_runtime_drains(monkeypatch):
events = []
entered = asyncio.Event()
release = asyncio.Event()
class Bootstrap:
recovery_service = object()
def startup_reconcile(self, query): return "ok"
async def start_execution(self, hts_id): pass
async def receive_execution_once(self):
entered.set()
await release.wait()
return "old-report"
async def close_execution(self):
events.append("close")
class Controller:
def start(self, config, policy): pass
def stop(self): events.append("stop")
monkeypatch.setattr(factory, "create_live_runtime_bootstrap", lambda **kwargs: Bootstrap())
monkeypatch.setattr(factory, "build_live_bundle_from_components", lambda **kwargs: object())
monkeypatch.setattr(factory, "create_live_runtime_controller", lambda *, live_builder: Controller())
deps = _deps()
old = factory.create_live_runtime_lifecycle_coordinator(**deps)
await old.start("CONFIG", "POLICY", hts_id="OLD", recovery_query="Q")
receive_task = asyncio.create_task(old.receive_execution_once())
await entered.wait()
stop_task = asyncio.create_task(old.stop())
with pytest.raises(RuntimeError, match="LIVE_EXECUTION_TRANSPORT_ALREADY_OWNED"):
pass
factory.create_live_runtime_lifecycle_coordinator(**deps)
assert not stop_task.done()
release.set()
assert await receive_task == "old-report"
await stop_task
new = factory.create_live_runtime_lifecycle_coordinator(**deps)
assert new is not old
@pytest.mark.asyncio
async def test_stop_blocks_old_ingress_before_close_finishes():
old = new_runtime_graph()
await old.start("CONFIG", "POLICY", hts_id="OLD", recovery_query="Q")
closing = asyncio.create_task(old.stop())
await old._bootstrap.close_entered.wait()
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_NOT_STARTED"):
pass
await old.receive_execution_once()
old._bootstrap.release_close.set()
await closing
@pytest.mark.asyncio
async def test_new_runtime_can_receive_while_old_is_draining_without_graph_handoff():
old = new_runtime_graph()
await old.start("CONFIG", "POLICY", hts_id="OLD", recovery_query="Q")
closing = asyncio.create_task(old.stop())
await old._bootstrap.close_entered.wait()
new = new_runtime_graph()
await new.start("CONFIG", "POLICY", hts_id="NEW", recovery_query="Q")
assert await new.receive_execution_once() == "event"
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_NOT_STARTED"):
pass
await old.receive_execution_once()
assert old._bootstrap is not new._bootstrap
assert old._controller is not new._controller
old._bootstrap.release_close.set()
await closing
def test_production_factory_exposes_control_tower_api_for_same_coordinator(monkeypatch):
from application.composition import live_runtime_production_factory as factory
controller = object()
coordinator = type(
"Coordinator",
(), {"runtime_controller": controller, "technical_state": None},
)()
api = factory.create_live_control_tower_runtime(
lifecycle_coordinator=coordinator,
)
assert api._runtime is controller
assert api._lifecycle_status_source is coordinator
def test_stop_timeout_coordinator_cannot_be_hidden_by_production_control_tower_entry():
from application.composition import live_runtime_production_factory as factory
class Status:
environment = "live"
state = "STOPPING"
class Controller:
def status(self):
return Status()
coordinator = type(
"Coordinator",
(), {"runtime_controller": Controller(), "technical_state": "STOP_TIMEOUT"},
)()
api = factory.create_live_control_tower_runtime(
lifecycle_coordinator=coordinator,
)
status = api.status()
assert api._lifecycle_status_source is coordinator
assert status.technical_state == "STOP_TIMEOUT"
assert status.execution_allowed is False
assert status.reason == "STOP_TIMEOUT"
def test_production_factory_builds_real_controller_with_concrete_live_builder(monkeypatch):
from application.environment_hub.contracts import EnvironmentConfig, EnvironmentType, RuntimePolicy
from application.runtime_controller.controller import RuntimeController
class Bootstrap:
recovery_service = object()
def startup_reconcile(self, query):
return ("RECOVERED", query)
async def start_execution(self, hts_id):
return hts_id
async def receive_execution_once(self):
return "REPORT"
async def close_execution(self):
return None
monkeypatch.setattr(factory, "create_live_runtime_bootstrap", lambda **kwargs: Bootstrap())
deps = _deps()
coordinator = factory.create_live_runtime_lifecycle_coordinator(**deps)
assert isinstance(coordinator.runtime_controller, RuntimeController)
assert coordinator.bootstrap.recovery_service is not None
config = EnvironmentConfig(environment=EnvironmentType.LIVE)
policy = RuntimePolicy()
builder = factory.build_live_bundle_from_components(
market=deps["market"],
broker=deps["broker"],
account=deps["account"],
position=deps["position"],
reconciler=deps["reconciler"],
recovery=coordinator.bootstrap.recovery_service,
safety_policy=deps["safety_policy"],
)
bundle = builder(config, policy)
assert bundle.market is deps["market"]
assert bundle.broker is deps["broker"]
assert bundle.account is deps["account"]
assert bundle.position is deps["position"]
assert bundle.reconciler is deps["reconciler"]
assert bundle.recovery is coordinator.bootstrap.recovery_service
@pytest.mark.asyncio
async def test_invalid_shutdown_timeout_does_not_poison_started_lifecycle():
class Policy:
graceful_shutdown_timeout_seconds = -1
cancellation_drain_timeout_seconds = 1
class Bootstrap:
recovery_service = object()
def startup_reconcile(self, query):
return "ok"
async def start_execution(self, hts_id):
pass
async def close_execution(self):
raise AssertionError("close_execution must not run with invalid policy")
class Controller:
def __init__(self):
self.started = 0
self.stopped = 0
def start(self, config, policy):
self.started += 1
def stop(self):
self.stopped += 1
controller = Controller()
coordinator = factory.LiveRuntimeLifecycleCoordinator(
controller=controller,
bootstrap=Bootstrap(),
)
await coordinator.start("CONFIG", Policy(), hts_id="H", recovery_query="Q")
with pytest.raises(ValueError, match="LIVE_RUNTIME_INVALID_SHUTDOWN_TIMEOUT"):
pass
await coordinator.stop()
assert coordinator._started is True
assert coordinator._stopping is False
assert coordinator.technical_state is None
assert controller.stopped == 0
def test_factory_releases_transport_ownership_when_coordinator_construction_fails(monkeypatch):
deps = _deps()
transport = deps["transport"]
class BrokenCoordinator:
def __init__(self, **kwargs):
raise RuntimeError("LIVE_RUNTIME_COORDINATOR_CONSTRUCTION_FAILED")
monkeypatch.setattr(factory, "LiveRuntimeLifecycleCoordinator", BrokenCoordinator)
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_COORDINATOR_CONSTRUCTION_FAILED"):
pass
factory.create_live_runtime_lifecycle_coordinator(**deps)
Failed assembly must not permanently reserve the caller-supplied transport.
monkeypatch.setattr(factory, "LiveRuntimeLifecycleCoordinator", factory.LiveRuntimeLifecycleCoordinator)
coordinator = factory.create_live_runtime_lifecycle_coordinator(**deps)
assert coordinator is not None
"""
