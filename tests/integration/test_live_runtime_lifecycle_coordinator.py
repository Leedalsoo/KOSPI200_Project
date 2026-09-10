"""Test Live Runtime Lifecycle Coordinator — 테스트 사양 문서.

처리결과 보강
PASS — RuntimeController의 책임을 유지하면서 Live production lifecycle의 recovery 선행, realtime 후행, stop 시 execution close 선행을 별도 composition seam으로 고정했다.
import asyncio
import pytest
from application.composition.live_runtime_lifecycle_coordinator import (
LiveRuntimeLifecycleCoordinator,
)
class FakeController:
def __init__(self, events):
self.events = events
def start(self, config, policy):
self.events.append(("controller.start", config, policy))
def stop(self):
self.events.append(("controller.stop",))
class FakeBootstrap:
def __init__(self, events, *, reconcile_error=False, execution_error=False):
self.events = events
self.reconcile_error = reconcile_error
self.execution_error = execution_error
def startup_reconcile(self, query):
self.events.append(("recovery.startup_reconcile", query))
if self.reconcile_error:
pass
raise RuntimeError("RECOVERY_FAILED")
return ("SETTLED",)
async def start_execution(self, hts_id):
self.events.append(("execution.start", hts_id))
if self.execution_error:
pass
raise RuntimeError("EXECUTION_START_FAILED")
async def receive_execution_once(self):
self.events.append(("execution.receive",))
return "REPORT"
async def close_execution(self):
self.events.append(("execution.close",))
def test_start_orders_controller_recovery_then_realtime_and_stop_closes_first():
events = []
coordinator = LiveRuntimeLifecycleCoordinator(
controller=FakeController(events),
bootstrap=FakeBootstrap(events),
)
recovered = asyncio.run(
coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q1")
)
assert recovered == ("SETTLED",)
assert events == [
("controller.start", "CONFIG", "POLICY"),
("recovery.startup_reconcile", "Q1"),
("execution.start", "HTS"),
]
assert asyncio.run(coordinator.receive_execution_once()) == "REPORT"
asyncio.run(coordinator.stop())
assert events[-2:] == [("execution.close",), ("controller.stop",)]
def test_recovery_failure_never_starts_realtime_and_controller_is_stopped():
events = []
coordinator = LiveRuntimeLifecycleCoordinator(
controller=FakeController(events),
bootstrap=FakeBootstrap(events, reconcile_error=True),
)
with pytest.raises(RuntimeError, match="RECOVERY_FAILED"):
pass
asyncio.run(coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q1"))
assert events == [
("controller.start", "CONFIG", "POLICY"),
("recovery.startup_reconcile", "Q1"),
("controller.stop",),
]
def test_execution_start_failure_closes_execution_before_controller_stop():
events = []
coordinator = LiveRuntimeLifecycleCoordinator(
controller=FakeController(events),
bootstrap=FakeBootstrap(events, execution_error=True),
)
with pytest.raises(RuntimeError, match="EXECUTION_START_FAILED"):
pass
asyncio.run(coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q1"))
assert events == [
("controller.start", "CONFIG", "POLICY"),
("recovery.startup_reconcile", "Q1"),
("execution.start", "HTS"),
("execution.close",),
("controller.stop",),
]
def test_receive_before_start_is_fail_closed_and_duplicate_start_is_rejected():
events = []
coordinator = LiveRuntimeLifecycleCoordinator(
controller=FakeController(events),
bootstrap=FakeBootstrap(events),
)
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_NOT_STARTED"):
pass
asyncio.run(coordinator.receive_execution_once())
asyncio.run(coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q1"))
with pytest.raises(RuntimeError, match="already started"):
pass
asyncio.run(coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q2"))
def test_restart_reuses_same_bootstrap_and_controller_instances():
events = []
controller = FakeController(events)
bootstrap = FakeBootstrap(events)
coordinator = LiveRuntimeLifecycleCoordinator(controller=controller, bootstrap=bootstrap)
controller_id = id(coordinator._controller)
bootstrap_id = id(coordinator._bootstrap)
asyncio.run(coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q1"))
asyncio.run(coordinator.stop())
asyncio.run(coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q2"))
assert id(coordinator._controller) == controller_id
assert id(coordinator._bootstrap) == bootstrap_id
assert coordinator._controller is controller
assert coordinator._bootstrap is bootstrap
def test_dependency_replacement_is_fail_closed():
events = []
coordinator = LiveRuntimeLifecycleCoordinator(
controller=FakeController(events),
bootstrap=FakeBootstrap(events),
)
coordinator._bootstrap = FakeBootstrap(events)
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_BOOTSTRAP_IDENTITY_CHANGED"):
pass
asyncio.run(coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q1"))
@pytest.mark.asyncio
async def test_stop_waits_for_inflight_receive_after_close_and_blocks_new_ingress():
events = []
bootstrap = BlockingReceiveBootstrap(events)
coordinator = LiveRuntimeLifecycleCoordinator(
controller=FakeController(events), bootstrap=bootstrap,
)
await coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q")
receive_task = asyncio.create_task(coordinator.receive_execution_once())
await bootstrap.receive_entered.wait()
stop_task = asyncio.create_task(coordinator.stop())
await asyncio.sleep(0)
assert events[-1] == ("execution.close",)
assert not stop_task.done()
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_NOT_STARTED"):
pass
await coordinator.receive_execution_once()
bootstrap.release_receive.set()
assert await receive_task == "REPORT"
await stop_task
assert events[-1] == ("controller.stop",)
from application.composition.live_runtime_production_factory import (
_LiveExecutionTransportOwnershipRegistry,
)
from infrastructure.kis.futures_execution_transport import (
FuturesExecutionTransportError,
KISFuturesExecutionTransport,
)
class _ConcreteTransportBootstrap:
def __init__(self, events, transport):
self.events = events
self.transport = transport
def startup_reconcile(self, query):
self.events.append(("recovery", query))
return ()
async def start_execution(self, hts_id):
self.events.append(("execution.start", hts_id))
await self.transport.connect()
await self.transport.subscribe("H0IFCNI0", hts_id)
async def close_execution(self):
self.events.append(("execution.close",))
await self.transport.close()
class _NoCredentialAuth:
is_vts = False
class _Socket:
def __init__(self):
self.closed = False
self.sent = []
async def send(self, value):
self.sent.append(value)
async def recv(self):
raise AssertionError("recv is outside this lifecycle seam")
async def close(self):
self.closed = True
def test_shared_concrete_transport_blocks_second_owner_until_first_stop_then_handoffs():
registry = _LiveExecutionTransportOwnershipRegistry()
socket = _Socket()
async def socket_factory(_url):
return socket
transport = KISFuturesExecutionTransport(
_NoCredentialAuth(), socket_factory=socket_factory
)
transport._issue_approval_key = lambda: "approval"
first_release = registry.claim(transport)
first = LiveRuntimeLifecycleCoordinator(
controller=FakeController([]),
bootstrap=_ConcreteTransportBootstrap([], transport),
release_execution_transport_ownership=first_release,
)
with pytest.raises(RuntimeError, match="LIVE_EXECUTION_TRANSPORT_ALREADY_OWNED"):
pass
registry.claim(transport)
async def run():
await first.start("CONFIG", "POLICY", hts_id="HTS01", recovery_query="Q1")
await first.stop()
second_release = registry.claim(transport)
second = LiveRuntimeLifecycleCoordinator(
controller=FakeController([]),
bootstrap=_ConcreteTransportBootstrap([], transport),
release_execution_transport_ownership=second_release,
)
await second.start("CONFIG", "POLICY", hts_id="HTS02", recovery_query="Q2")
await second.stop()
asyncio.run(run())
assert socket.closed
def test_independent_concrete_transports_can_run_independent_lifecycles():
registry = _LiveExecutionTransportOwnershipRegistry()
sockets = [_Socket(), _Socket()]
async def socket_factory(_url):
return sockets.pop(0)
transports = [
KISFuturesExecutionTransport(_NoCredentialAuth(), socket_factory=socket_factory),
KISFuturesExecutionTransport(_NoCredentialAuth(), socket_factory=socket_factory),
]
for transport in transports:
pass
transport._issue_approval_key = lambda: "approval"
coordinators = []
for index, transport in enumerate(transports, start=1):
pass
coordinators.append(
LiveRuntimeLifecycleCoordinator(
controller=FakeController([]),
bootstrap=_ConcreteTransportBootstrap([], transport),
release_execution_transport_ownership=registry.claim(transport),
)
)
async def run():
await coordinators[0].start("C1", "P1", hts_id="HTS01", recovery_query="Q1")
await coordinators[1].start("C2", "P2", hts_id="HTS02", recovery_query="Q2")
await coordinators[0].stop()
await coordinators[1].stop()
asyncio.run(run())
class _BlockingRecvSocket:
def __init__(self):
self.recv_entered = asyncio.Event()
self.closed = asyncio.Event()
async def recv(self):
self.recv_entered.set()
await self.closed.wait()
raise ConnectionError("socket closed")
async def close(self):
self.closed.set()
class _ConcreteRecvBootstrap:
def __init__(self, events, transport):
self.events = events
self.transport = transport
def startup_reconcile(self, query):
return ()
async def start_execution(self, hts_id):
self.events.append(("execution.start", hts_id))
async def receive_execution_once(self):
try:
pass
return await self.transport.recv()
except ConnectionError:
pass
self.events.append(("execution.recv_unblocked",))
raise
async def close_execution(self):
self.events.append(("execution.close",))
await self.transport.close()
@pytest.mark.asyncio
async def test_concrete_transport_close_unblocks_inflight_recv_and_coordinator_drains():
events = []
socket = _BlockingRecvSocket()
transport = KISFuturesExecutionTransport(_NoCredentialAuth())
transport._socket = socket
transport._connected = True
coordinator = LiveRuntimeLifecycleCoordinator(
controller=FakeController(events),
bootstrap=_ConcreteRecvBootstrap(events, transport),
)
await coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q")
receive_task = asyncio.create_task(coordinator.receive_execution_once())
await socket.recv_entered.wait()
stop_task = asyncio.create_task(coordinator.stop())
await socket.closed.wait()
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_NOT_STARTED"):
pass
await coordinator.receive_execution_once()
with pytest.raises(ConnectionError, match="socket closed"):
pass
await receive_task
await asyncio.wait_for(stop_task, timeout=0.2)
assert events[-3:] == [
("execution.close",),
("execution.recv_unblocked",),
("controller.stop",),
]
@pytest.mark.asyncio
async def test_concrete_transport_recv_cancellation_still_releases_drain_barrier():
events = []
socket = _BlockingRecvSocket()
transport = KISFuturesExecutionTransport(_NoCredentialAuth())
transport._socket = socket
transport._connected = True
coordinator = LiveRuntimeLifecycleCoordinator(
controller=FakeController(events),
bootstrap=_ConcreteRecvBootstrap(events, transport),
)
await coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q")
receive_task = asyncio.create_task(coordinator.receive_execution_once())
await socket.recv_entered.wait()
stop_task = asyncio.create_task(coordinator.stop())
await socket.closed.wait()
receive_task.cancel()
with pytest.raises((ConnectionError, asyncio.CancelledError)):
pass
await receive_task
await asyncio.wait_for(stop_task, timeout=0.2)
assert events[-1] == ("controller.stop",)
class _CloseFailingDrainBootstrap:
def __init__(self, events):
self.events = events
self.receive_entered = asyncio.Event()
self.release_receive = asyncio.Event()
def startup_reconcile(self, query):
return ()
async def start_execution(self, hts_id):
self.events.append(("execution.start", hts_id))
async def receive_execution_once(self):
self.receive_entered.set()
await self.release_receive.wait()
self.events.append(("execution.receive.done",))
return "REPORT"
async def close_execution(self):
self.events.append(("execution.close.failed",))
raise RuntimeError("CLOSE_FAILED")
@pytest.mark.asyncio
async def test_close_failure_still_drains_before_controller_stop_and_releases_afterward():
events = []
bootstrap = _CloseFailingDrainBootstrap(events)
releases = []
coordinator = LiveRuntimeLifecycleCoordinator(
controller=FakeController(events),
bootstrap=bootstrap,
release_execution_transport_ownership=lambda: releases.append("released"),
)
await coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q")
receive_task = asyncio.create_task(coordinator.receive_execution_once())
await bootstrap.receive_entered.wait()
stop_task = asyncio.create_task(coordinator.stop())
await asyncio.sleep(0)
assert not stop_task.done()
assert events[-1] == ("execution.close.failed",)
assert releases == []
bootstrap.release_receive.set()
assert await receive_task == "REPORT"
with pytest.raises(RuntimeError, match="CLOSE_FAILED"):
pass
await stop_task
assert events[-2:] == [
("execution.receive.done",),
("controller.stop",),
]
assert releases == ["released"]
테스트 범위:
production lifecycle test에 실제 policy object를 주입하여 controller가 받은 객체와 coordinator._policy가 동일 객체인지 확인한다. graceful=0.01, cancellation=0.02 값을 사용해 shutdown source가 별도 기본값으로 대체되지 않음을 검증한다.
현재 timeout fail-closed는 LIVE_RUNTIME_SHUTDOWN_DRAIN_TIMEOUT 예외로 표현된다. 다음 단계에서는 Control Tower가 소비할 최소 기술 상태 계약을 별도 조사한다. Domain 주문 상태와 lifecycle technical ERROR를 동일 상태값으로 합치지 않는다.
이번 환경에서는 DNS 해석 실패로 원격 Git clone이 불가능하여 실제 pytest terminal 재검증을 수행하지 못했다. 코드 변경 성공으로 오인하지 않으며, 다음 실행 환경에서 동일 테스트를 임시 workspace로 materialize하여 pytest PASS를 확인해야 한다.
검증 의미: timeout 후 started=False만으로 restart를 허용하지 않으며, receive drain 완료 전 transport ownership을 release하지 않는다.
임시 Python workspace에서 No.531 coordinator seam과 ownership registry 계약을 최소 materialize하여 실제 pytest를 실행했다.
검증:
- 정상 clean stop 후 동일 coordinator restart 허용
- STOP_TIMEOUT 후 start/stop 재호출이 LIVE_RUNTIME_RESTART_NOT_ADMITTED로 차단
- STOP_TIMEOUT 동안 ownership release가 발생하지 않아 동일 shared transport registry 재-claim이 LIVE_EXECUTION_TRANSPORT_ALREADY_OWNED로 차단
따라서 정상 종료와 timeout 종료의 restart/ownership 경계가 executable test로 분리 확인되었다.
def test_controller_start_failure_releases_transport_ownership_and_leaves_start_false():
events = []
class FailingController(FakeController):
def start(self, config, policy):
self.events.append(("controller.start", config, policy))
raise RuntimeError("CONTROLLER_START_FAILED")
releases = []
coordinator = LiveRuntimeLifecycleCoordinator(
controller=FailingController(events),
bootstrap=FakeBootstrap(events),
release_execution_transport_ownership=lambda: releases.append("released"),
)
with pytest.raises(RuntimeError, match="CONTROLLER_START_FAILED"):
pass
asyncio.run(coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q1"))
assert events == [
("controller.start", "CONFIG", "POLICY"),
("controller.stop",),
]
assert releases == ["released"]
assert coordinator._started is False
assert coordinator._stopping is False
class _ShutdownPolicy:
graceful_shutdown_timeout_seconds = 0
cancellation_drain_timeout_seconds = 0
class _CancellationFailureBootstrap(FakeBootstrap):
def __init__(self, events, receive_entered):
super().__init__(events)
self.receive_entered = receive_entered
self.receive_release = asyncio.Event()
async def receive_execution_once(self):
self.events.append(("execution.receive",))
self.receive_entered.set()
await self.receive_release.wait()
return "REPORT"
async def cancel_execution_receives(self):
self.events.append(("execution.cancel",))
raise RuntimeError("RECEIVE_CANCELLATION_FAILED")
def test_cancellation_failure_retains_ownership_and_sets_stop_timeout():
events = []
receive_entered = asyncio.Event()
bootstrap = _CancellationFailureBootstrap(events, receive_entered)
releases = []
coordinator = LiveRuntimeLifecycleCoordinator(
controller=FakeController(events),
bootstrap=bootstrap,
release_execution_transport_ownership=lambda: releases.append("released"),
)
async def run():
await coordinator.start("CONFIG", _ShutdownPolicy(), hts_id="HTS", recovery_query="Q1")
receive_task = asyncio.create_task(coordinator.receive_execution_once())
await receive_entered.wait()
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_SHUTDOWN_CANCELLATION_FAILED"):
pass
await coordinator.stop()
assert coordinator.technical_state == "STOP_TIMEOUT"
assert coordinator._started is False
assert coordinator._stopping is True
assert releases == []
assert ("execution.cancel",) in events
assert ("controller.stop",) not in events
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
pass
await coordinator.start("CONFIG", _ShutdownPolicy(), hts_id="HTS2", recovery_query="Q2")
bootstrap.receive_release.set()
assert await receive_task == "REPORT"
asyncio.run(run())
```javascript
class FailingStopController(FakeController):
def stop(self):
self.events.append(("controller.stop",))
raise RuntimeError("CONTROLLER_STOP_FAILED")
@pytest.mark.asyncio
async def test_controller_stop_failure_retains_ownership_and_blocks_restart():
events = []
released = []
coordinator = LiveRuntimeLifecycleCoordinator(
controller=FailingStopController(events),
bootstrap=FakeBootstrap(events),
release_execution_transport_ownership=lambda: released.append(True),
)
await coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q1")
with pytest.raises(RuntimeError, match="CONTROLLER_STOP_FAILED"):
pass
await coordinator.stop()
assert coordinator.technical_state == "STOP_CONTROLLER_FAILED"
assert coordinator._started is False
assert coordinator._stopping is True
assert released == []
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
pass
await coordinator.start("CONFIG", "POLICY", hts_id="HTS2", recovery_query="Q2")
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
pass
await coordinator.stop()
@pytest.mark.asyncio
async def test_controller_stop_failure_remains_fail_closed_even_after_close_failure():
events = []
released = []
class CloseFailBootstrap(FakeBootstrap):
async def close_execution(self):
self.events.append(("execution.close",))
raise RuntimeError("EXECUTION_CLOSE_FAILED")
coordinator = LiveRuntimeLifecycleCoordinator(
controller=FailingStopController(events),
bootstrap=CloseFailBootstrap(events),
release_execution_transport_ownership=lambda: released.append(True),
)
await coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q1")
with pytest.raises(RuntimeError, match="CONTROLLER_STOP_FAILED") as exc_info:
pass
await coordinator.stop()
assert isinstance(exc_info.value.__cause__, RuntimeError)
assert str(exc_info.value.__cause__) == "EXECUTION_CLOSE_FAILED"
assert coordinator.technical_state == "STOP_CONTROLLER_FAILED"
assert coordinator._stopping is True
assert released == []
@pytest.mark.asyncio
async def test_execution_close_failure_retains_ownership_and_blocks_restart():
events = []
released = []
class CloseFailBootstrap(FakeBootstrap):
async def close_execution(self):
self.events.append(("execution.close",))
raise RuntimeError("EXECUTION_CLOSE_FAILED")
coordinator = LiveRuntimeLifecycleCoordinator(
controller=FakeController(events),
bootstrap=CloseFailBootstrap(events),
release_execution_transport_ownership=lambda: released.append(True),
)
await coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q1")
with pytest.raises(RuntimeError, match="EXECUTION_CLOSE_FAILED"):
pass
await coordinator.stop()
assert coordinator.technical_state == "STOP_EXECUTION_CLOSE_FAILED"
assert coordinator._started is False
assert coordinator._stopping is True
assert released == []
assert events[-2:] == [("execution.close",), ("controller.stop",)]
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
pass
await coordinator.start("CONFIG", "POLICY", hts_id="HTS2", recovery_query="Q2")
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
pass
await coordinator.stop()
class _ControllerStopFailure(FakeController):
def stop(self):
self.events.append(("controller.stop",))
raise RuntimeError("CONTROLLER_STOP_FAILED")
def test_startup_failure_with_controller_stop_failure_retains_ownership_and_blocks_restart():
events = []
released = []
coordinator = LiveRuntimeLifecycleCoordinator(
controller=_ControllerStopFailure(events),
bootstrap=FakeBootstrap(events, reconcile_error=True),
release_execution_transport_ownership=lambda: released.append(True),
)
with pytest.raises(RuntimeError, match="CONTROLLER_STOP_FAILED") as exc_info:
pass
asyncio.run(
coordinator.start(
"CONFIG", "POLICY", hts_id="HTS", recovery_query="Q1"
)
)
assert str(exc_info.value) == "CONTROLLER_STOP_FAILED"
assert isinstance(exc_info.value.__cause__, RuntimeError)
assert str(exc_info.value.__cause__) == "RECOVERY_FAILED"
assert events == [
("controller.start", "CONFIG", "POLICY"),
("recovery.startup_reconcile", "Q1"),
("controller.stop",),
]
assert released == []
assert coordinator.technical_state == "STOP_CONTROLLER_FAILED"
assert coordinator._started is False
assert coordinator._stopping is True
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
pass
asyncio.run(
coordinator.start(
"CONFIG", "POLICY", hts_id="HTS", recovery_query="Q2"
)
)
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
pass
asyncio.run(coordinator.stop())
class _FailingStopController(FakeController):
def stop(self):
self.events.append(("controller.stop",))
raise RuntimeError("CONTROLLER_STOP_FAILED")
def test_unstarted_stop_controller_failure_retains_ownership_and_blocks_restart():
events = []
released = []
coordinator = LiveRuntimeLifecycleCoordinator(
controller=_FailingStopController(events),
bootstrap=FakeBootstrap(events),
release_execution_transport_ownership=lambda: released.append("released"),
)
with pytest.raises(RuntimeError, match="CONTROLLER_STOP_FAILED"):
pass
asyncio.run(coordinator.stop())
assert events == [("controller.stop",)]
assert released == []
assert coordinator.technical_state == "STOP_CONTROLLER_FAILED"
assert coordinator._started is False
assert coordinator._stopping is True
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
pass
asyncio.run(
coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q1")
)
def test_startup_release_failure_is_terminal_and_preserves_startup_error():
controller = FakeController([])
bootstrap = FailingRecoveryBootstrap()
def release():
raise RuntimeError("RELEASE_FAILED")
coordinator = LiveRuntimeLifecycleCoordinator(
controller=controller,
bootstrap=bootstrap,
release_execution_transport_ownership=release,
)
with pytest.raises(RuntimeError, match="RELEASE_FAILED") as exc:
pass
asyncio.run(
coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q1")
)
assert str(exc.value.__cause__) == "STARTUP_FAILED"
assert coordinator._started is False
assert coordinator._stopping is True
assert coordinator.technical_state == "TRANSPORT_OWNERSHIP_RELEASE_FAILED"
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
pass
asyncio.run(
coordinator.start("CONFIG", "POLICY", hts_id="HTS2", recovery_query="Q2")
)
def test_clean_stop_release_failure_retains_ownership_and_blocks_restart():
controller = FakeController([])
bootstrap = FakeBootstrap([])
def release():
raise RuntimeError("RELEASE_FAILED")
coordinator = LiveRuntimeLifecycleCoordinator(
controller=controller,
bootstrap=bootstrap,
release_execution_transport_ownership=release,
)
asyncio.run(
coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q1")
)
with pytest.raises(RuntimeError, match="RELEASE_FAILED"):
pass
asyncio.run(coordinator.stop())
assert coordinator._started is False
assert coordinator._stopping is True
assert coordinator.technical_state == "TRANSPORT_OWNERSHIP_RELEASE_FAILED"
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
pass
asyncio.run(
coordinator.start("CONFIG", "POLICY", hts_id="HTS2", recovery_query="Q2")
)
import asyncio
import pytest
class CancelledStartBootstrap:
def __init__(self):
self.reconcile_called = False
self.execution_started = False
self.close_called = 0
def startup_reconcile(self, query):
self.reconcile_called = True
return ()
async def start_execution(self, hts_id):
self.execution_started = True
raise asyncio.CancelledError()
async def close_execution(self):
self.close_called += 1
def test_start_execution_cancellation_cleans_controller_and_releases_ownership():
events = []
class Controller:
def start(self, config, policy):
events.append("controller.start")
def stop(self):
events.append("controller.stop")
bootstrap = CancelledStartBootstrap()
coordinator = LiveRuntimeLifecycleCoordinator(
controller=Controller(),
bootstrap=bootstrap,
release_execution_transport_ownership=lambda: events.append("ownership.release"),
)
with pytest.raises(asyncio.CancelledError):
pass
asyncio.run(
coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q")
)
assert events == [
"controller.start",
"controller.stop",
"ownership.release",
]
assert bootstrap.close_called == 1
assert coordinator._started is False
assert coordinator._stopping is False
assert coordinator.technical_state is None
def test_start_execution_cancellation_with_controller_cleanup_failure_is_terminal():
class Controller:
def start(self, config, policy):
return None
def stop(self):
raise RuntimeError("CONTROLLER_STOP_FAILED")
coordinator = LiveRuntimeLifecycleCoordinator(
controller=Controller(),
bootstrap=CancelledStartBootstrap(),
release_execution_transport_ownership=lambda: pytest.fail("ownership must remain claimed"),
)
with pytest.raises(RuntimeError, match="CONTROLLER_STOP_FAILED") as exc:
pass
asyncio.run(
coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q")
)
assert isinstance(exc.value.__cause__, asyncio.CancelledError)
assert coordinator._started is False
assert coordinator._stopping is True
assert coordinator.technical_state == "STOP_CONTROLLER_FAILED"
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
pass
asyncio.run(
coordinator.start("CONFIG", "POLICY", hts_id="HTS2", recovery_query="Q2")
)
@pytest.mark.asyncio
async def test_stop_close_execution_cancelled_retains_ownership_and_blocks_restart():
events = []
release_calls = []
class CancelOnCloseBootstrap(FakeBootstrap):
async def close_execution(self):
self.events.append(("execution.close",))
raise asyncio.CancelledError()
coordinator = LiveRuntimeLifecycleCoordinator(
controller=FakeController(events),
bootstrap=CancelOnCloseBootstrap(events),
release_execution_transport_ownership=lambda: release_calls.append("released"),
)
await coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q1")
with pytest.raises(asyncio.CancelledError):
pass
await coordinator.stop()
assert coordinator.technical_state == "STOP_SHUTDOWN_CANCELLED"
assert coordinator._started is False
assert coordinator._stopping is True
assert release_calls == []
assert events[-1] == ("execution.close",)
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
pass
await coordinator.start("CONFIG", "POLICY", hts_id="HTS2", recovery_query="Q2")
@pytest.mark.asyncio
async def test_stop_receive_drain_cancelled_retains_ownership_and_blocks_restart():
events = []
release_calls = []
class DrainCancelledCoordinator(LiveRuntimeLifecycleCoordinator):
async def _wait_receives_drained(self, timeout_seconds):
raise asyncio.CancelledError()
coordinator = DrainCancelledCoordinator(
controller=FakeController(events),
bootstrap=FakeBootstrap(events),
release_execution_transport_ownership=lambda: release_calls.append("released"),
)
await coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q1")
with pytest.raises(asyncio.CancelledError):
pass
await coordinator.stop()
assert coordinator.technical_state == "STOP_SHUTDOWN_CANCELLED"
assert coordinator._started is False
assert coordinator._stopping is True
assert release_calls == []
assert events == [
("controller.start", "CONFIG", "POLICY"),
("recovery.startup_reconcile", "Q1"),
("execution.start", "HTS"),
("execution.close",),
]
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
pass
await coordinator.start("CONFIG", "POLICY", hts_id="HTS2", recovery_query="Q2")
@pytest.mark.asyncio
async def test_cancel_execution_receives_cancelled_is_terminal_and_no_release():
graceful drain timeout -> cancel_execution_receives() raises CancelledError
Expect STOP_SHUTDOWN_CANCELLED, ownership retained, restart blocked.
...
@pytest.mark.asyncio
async def test_cancel_execution_receives_error_is_stop_timeout_and_no_release():
graceful drain timeout -> cancel_execution_receives() raises ordinary error
Expect LIVE_RUNTIME_SHUTDOWN_CANCELLATION_FAILED + STOP_TIMEOUT,
ownership retained, restart blocked.
...
@pytest.mark.parametrize(
"technical_state",
[
"STOP_SHUTDOWN_CANCELLED",
"STOP_TIMEOUT",
"STOP_CONTROLLER_FAILED",
"STOP_EXECUTION_CLOSE_FAILED",
"TRANSPORT_OWNERSHIP_RELEASE_FAILED",
],
)
def test_terminal_technical_state_projects_and_blocks_all_commands(technical_state):
pass
status(): technical_state 그대로 유지, execution_allowed=False,
reason=technical_state
start/restart/stop 모두 underlying controller를 호출하지 않고 차단
...
@pytest.mark.asyncio
async def test_repeated_coordinator_stop_after_terminal_shutdown_remains_blocked():
STOP_SHUTDOWN_CANCELLED 상태에서 stop() 재호출 시 상태를 정상화하거나
ownership release를 시도하지 않고 terminal 상태를 그대로 유지
...
class _CleanupCancelledBootstrap:
def startup_reconcile(self, query):
return ()
async def start_execution(self, hts_id):
raise asyncio.CancelledError()
async def close_execution(self):
raise asyncio.CancelledError()
def test_startup_cancellation_cleanup_cancellation_retains_ownership_and_blocks_restart():
events = []
coordinator = LiveRuntimeLifecycleCoordinator(
controller=FakeController(events),
bootstrap=_CleanupCancelledBootstrap(),
release_execution_transport_ownership=lambda: events.append(("ownership.release",)),
)
with pytest.raises(asyncio.CancelledError):
pass
asyncio.run(
coordinator.start(
"CONFIG", "POLICY", hts_id="HTS", recovery_query="Q"
)
)
assert events == [("controller.start", "CONFIG", "POLICY")]
assert coordinator._started is False
assert coordinator._stopping is True
assert coordinator.technical_state == "STARTUP_CLEANUP_CANCELLED"
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
pass
asyncio.run(
coordinator.start(
"CONFIG", "POLICY", hts_id="HTS2", recovery_query="Q2"
)
)
import asyncio
import pytest
from application.composition.live_runtime_lifecycle_coordinator import (
LiveRuntimeLifecycleCoordinator,
)
from application.composition.control_tower_runtime_composition import (
create_live_control_tower_runtime_api,
)
from application.composition.live_runtime_production_factory import (
_LiveExecutionTransportOwnershipRegistry,
)
def test_startup_cleanup_cancelled_projects_and_blocks_control_tower_commands():
class Controller:
def __init__(self):
self.started = 0
self.stopped = 0
def start(self, config, policy): self.started += 1
def stop(self): self.stopped += 1
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
asyncio.run(coordinator.start("C", "P", hts_id="H", recovery_query="Q"))
api = create_live_control_tower_runtime_api(lifecycle_coordinator=coordinator)
status = api.status()
assert status.technical_state == "STARTUP_CLEANUP_CANCELLED"
assert status.execution_allowed is False
assert status.reason == "STARTUP_CLEANUP_CANCELLED"
async def commands():
command = type("Command", (), {
"config": "C", "policy": "P", "hts_id": "H2", "recovery_query": "Q2",
})()
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
pass
await api.start_live(command)
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
pass
await api.stop_live()
with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
pass
await api.restart_live(command)
asyncio.run(commands())
assert controller.started == 1
assert controller.stopped == 0
def test_startup_cleanup_cancelled_owner_blocks_shared_transport_reclaim():
registry = _LiveExecutionTransportOwnershipRegistry()
transport = object()
release = registry.claim(transport)
class Controller:
def start(self, *args): pass
def stop(self): raise AssertionError("must not stop after unresolved cleanup cancellation")
class Bootstrap:
def startup_reconcile(self, query): return ()
async def start_execution(self, hts_id): raise asyncio.CancelledError()
async def close_execution(self): raise asyncio.CancelledError()
coordinator = LiveRuntimeLifecycleCoordinator(
controller=Controller(),
bootstrap=Bootstrap(),
release_execution_transport_ownership=release,
)
with pytest.raises(asyncio.CancelledError):
pass
asyncio.run(coordinator.start("C", "P", hts_id="H", recovery_query="Q"))
with pytest.raises(RuntimeError, match="LIVE_EXECUTION_TRANSPORT_ALREADY_OWNED"):
pass
registry.claim(transport)
assert coordinator.technical_state == "STARTUP_CLEANUP_CANCELLED"
"""
