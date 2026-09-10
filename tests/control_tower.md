[Child Page] control_tower_test_spec.md
# Control Tower 통합 검증 Spec
## No.074 Core/Strategy 동일성
    - 4개 Environment 선택에 따라 core/와 core/strategy/ 코드가 달라지지 않는다.
    - 동일 Strategy Registry/호출 계약을 사용한다.
    - Environment 차이는 Adapter/Execution 영역에서만 발생한다. fileciteturn111file0L1-L10
## No.075 High-Speed ↔ Virtual
    - 동일 Scenario를 Virtual 1x와 High-Speed 가속 정책에서 비교한다.
    - 시간 경계 및 floating-point 차이를 별도 기록한다. fileciteturn111file3L32-L39
## No.076 Contract compatibility
    - Virtual/Paper/Live가 동일 MarketDataProvider Contract를 만족한다.
    - Core 변경 없이 Adapter 교체가 가능한지 확인한다. fileciteturn112file0L1-L10
## No.077 Environment isolation
    - 다른 Environment의 Broker/VMS/VSSF 객체가 생성·공유되지 않는지 정적 import 및 객체 생성 경계를 검사한다.
    - 특히 Live에서 VSSF 객체 생성이 없어야 한다. fileciteturn111file1L11-L19
## No.078 Lifecycle/Recovery
    - 4개 Environment 각각 Start/Stop/Restart 경계를 확인한다.
    - 실행 중 환경 전환은 거부하거나 안전하게 중지 후 전환한다.
    - 정상 Stop/강제 종료/Restart 후 상태 복구를 별도 검증한다. fileciteturn111file4L41-L50
## 현재 검증 한계
실제 브로커·브라우저·외부 API 실행은 현재 환경에서 수행할 수 없으므로 정적 구조/계약/테스트 설계까지만 PASS로 기록하고 실제 실행 증거는 BLOCKED로 분리한다.
## No.528 Technical lifecycle status
    - RuntimeStatus.technical_state는 Control Tower의 기술적 lifecycle 상태 전용 필드다.
    - shutdown cancellation drain timeout은 technical_state="STOP_TIMEOUT"으로 표현한다.
    - STOP_TIMEOUT을 주문 상태, 체결 상태, 포지션 상태, Risk Domain 상태와 합치지 않는다.
    - timeout 상태에서는 shared execution ownership을 release/reuse하지 않는 fail-closed 계약을 유지한다.
    - 검증: RuntimePolicy custom timeout → cancellation capability/fallback → unresolved drain → LIVE_RUNTIME_SHUTDOWN_DRAIN_TIMEOUT + STOP_TIMEOUT 분리.

[Child Page] test_control_tower_runtime_status_projection.py
```python
from dataclasses import dataclass

from contracts.types import EnvironmentType
from interfaces.control_tower.runtime_api import ControlTowerRuntimeAPI


@dataclass
class _ControllerStatus:
    environment: str | None
    state: str


class _Controller:
    def __init__(self, status):
        self._status = status

    def start(self, config, policy):
        self._status = _ControllerStatus("live", "RUNNING")

    def stop(self):
        self._status = _ControllerStatus("live", "STOPPED")

    def status(self):
        return self._status


class _Lifecycle:
    def __init__(self, technical_state=None):
        self.technical_state = technical_state


def test_control_tower_projects_live_technical_state_into_standard_runtime_status():
    api = ControlTowerRuntimeAPI(
        _Controller(_ControllerStatus("live", "STOPPING")),
        lifecycle_status_source=_Lifecycle("STOP_TIMEOUT"),
    )

    status = api.status()

    assert status.environment is EnvironmentType.LIVE
    assert status.running is False
    assert status.technical_state == "STOP_TIMEOUT"
    assert status.execution_allowed is False
    assert status.reason == "STOP_TIMEOUT"


def test_control_tower_without_lifecycle_failure_keeps_standard_status():
    api = ControlTowerRuntimeAPI(
        _Controller(_ControllerStatus("virtual", "RUNNING")),
        lifecycle_status_source=_Lifecycle(None),
    )

    status = api.status()

    assert status.environment is EnvironmentType.VIRTUAL
    assert status.running is True
    assert status.connected is True
    assert status.execution_allowed is True
    assert status.technical_state is None
```
## No.529 검증
    - coordinator lifecycle source의 STOP_TIMEOUT이 표준 RuntimeStatus.technical_state로 projection되는지 검증한다.
    - technical failure 시 execution_allowed=False가 유지되는지 검증한다.
    - lifecycle failure가 없을 때 기존 RUNNING 상태가 표준 status로 정규화되는지 검증한다.

[Child Page] test_control_tower_live_status_assembly.py
```python
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
        create_live_control_tower_runtime_api(lifecycle_coordinator=None)
    except ValueError as exc:
        assert str(exc) == "LIVE_RUNTIME_LIFECYCLE_COORDINATOR_REQUIRED"
    else:
        raise AssertionError("missing coordinator must fail closed")
```
## No.534 검증
    - production assembly가 동일 coordinator의 controller와 technical lifecycle source를 함께 주입한다.
    - STOP_TIMEOUT이 RuntimeStatus까지 fail-closed로 도달한다.
    - lifecycle coordinator 누락은 fallback 없이 거부한다.
## No.535 command-path fail-closed 검증
```python
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
        api.start("CONFIG", "POLICY")
    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
        api.restart("CONFIG", "POLICY")

    assert controller.started == 0
    assert controller.stopped == 0
```
    - STOP_TIMEOUT coordinator가 Control Tower command path를 통해 controller start/restart로 우회되지 않는지 검증한다.
    - status projection뿐 아니라 control command도 technical terminal state를 fail-closed로 존중한다.
## No.536 stop ownership + identity mismatch 검증
```python

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
        api.status()
    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_CONTROLLER_IDENTITY_CHANGED"):
        api.start("CONFIG", "POLICY")
```
    - STOP_TIMEOUT에서 Control Tower stop()이 underlying controller를 직접 호출하지 않는지 검증한다.
    - lifecycle coordinator의 identity guard가 실패하면 status/control path가 synthetic fallback 없이 동일 오류로 fail-closed되는지 검증한다.
## No.539 status polling + command 동시성 검증
```python
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
            api.status()

    asyncio.run(scenario())
```
    - async command 완료 후 status polling이 lifecycle source identity failure를 synthetic 정상 상태로 숨기지 않고 fail-closed한다.
    - command serialization과 status projection은 별도 책임이지만 동일 authoritative lifecycle source를 사용한다.
## No.568 technical_state 전체 non-None fail-closed command 경계 회귀 검증
```python
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

    # Live adapter의 sync command는 별도 정책으로 항상 차단된다.
    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_SYNC_COMMAND_NOT_AVAILABLE"):
        api.start("CONFIG", "POLICY")
    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_SYNC_COMMAND_NOT_AVAILABLE"):
        api.stop()
    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_SYNC_COMMAND_NOT_AVAILABLE"):
        api.restart("CONFIG", "POLICY")

    async def run_async_commands():
        command = SimpleNamespace(
            config="CONFIG",
            policy=_Policy(),
            hts_id="HTS",
            recovery_query="Q",
        )
        with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
            await api.start_live(command)
        with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
            await api.stop_live()
        with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
            await api.restart_live(command)

    asyncio.run(run_async_commands())
    assert controller.started == 0
    assert controller.stopped == 0
```
    - STOP_TIMEOUT뿐 아니라 STOP_CONTROLLER_FAILED, STOP_EXECUTION_CLOSE_FAILED, TRANSPORT_OWNERSHIP_RELEASE_FAILED도 동일한 terminal technical state 계약으로 검증한다.
    - status projection은 각 technical state를 그대로 노출하고 execution_allowed=False, reason=technical_state를 유지한다.
    - Live adapter의 sync API 차단과 별개로 실제 async start_live/stop_live/restart_live가 coordinator의 restart/stop admission을 우회하지 못하는지 executable하게 검증한다.
## No.575 terminal state status polling·command serialization·concurrent ownership claim 교차 회귀 검증
```python
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
        await coordinator.start("C", "P", hts_id="H", recovery_query="Q")
    api = create_live_control_tower_runtime_api(lifecycle_coordinator=coordinator)

    command = type("Command", (), {"config":"C", "policy":"P", "hts_id":"H2", "recovery_query":"Q2"})()
    blocked = asyncio.create_task(api.start_live(command))
    await asyncio.sleep(0)
    for _ in range(3):
        status = api.status()
        status_reads.append((status.technical_state, status.execution_allowed, status.reason))
        await asyncio.sleep(0)
    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
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
        asyncio.run(coordinator.start("C", "P", hts_id="H", recovery_query="Q"))

    failures = []
    for _ in range(3):
        with pytest.raises(RuntimeError, match="LIVE_EXECUTION_TRANSPORT_ALREADY_OWNED") as exc:
            registry.claim(transport)
        failures.append(str(exc.value))
    assert failures == ["LIVE_EXECUTION_TRANSPORT_ALREADY_OWNED"] * 3
    assert coordinator.technical_state == "STARTUP_CLEANUP_CANCELLED"
```
    - terminal coordinator 상태에서는 command adapter의 serialization lock이 존재해도 status polling이 technical state를 정상 상태로 변환하거나 숨기지 않는다.
    - 반복된 status polling과 blocked command 이후에도 STARTUP_CLEANUP_CANCELLED identity가 불변임을 확인한다.
    - unresolved owner가 존재하는 동일 transport에 대한 반복 claim도 모두 단일 ownership registry 경계에서 차단된다.
    - 실제 multi-loop/thread caller contract는 현재 source에 없으므로 concurrency architecture를 확장하지 않고 기존 single-loop/registry 계약 범위에서 검증한다.
## No.576 terminal technical_state 공통 invariant 중복·누락 정리 회귀 검증
```python
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
```
    - production source의 generic technical_state is not None 계약에 실제로 존재하는 terminal state 목록을 테스트 fixture로만 집약했다.
    - 각 state별 개별 status/command 테스트를 삭제하지 않고, 공통 invariant 누락 방지를 위한 parametrized regression을 추가했다.
    - clean state가 terminal invariant에 오인되어 execution이 차단되지 않는 정상 경계도 함께 확인한다.
    - production enum·새 abstraction은 도입하지 않는다.

[Child Page] test_live_control_tower_async_command_adapter.py
```python
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
        with pytest.raises(RuntimeError, match="LIVE_RUNTIME_SYNC_COMMAND_NOT_AVAILABLE"):
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
```
## No.539 검증
    - UI/application boundary가 concrete Live dependency 대신 LiveLifecycleCommand DTO를 전달한다.
    - 동일 Live Control Tower entry의 concurrent start/stop은 command lock으로 직렬화된다.
    - restart stop → start 사이에 다른 command가 interleave되지 않는다.
## No.540 typed command + single adapter assembly 검증
```python
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
```
    - Live command DTO가 canonical EnvironmentConfig/RuntimePolicy를 사용하고 LIVE 이외 환경 command를 fail-closed한다.
    - 동일 coordinator를 두 번 assembly해도 adapter와 command lock이 하나만 존재한다.
## No.541 assembly mutation fail-closed + lifecycle exception lock-release 검증
```python

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
        await api.stop_live()
    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
        await api.start_live(command)
    receive.cancel()
```
    - assembly cache 외부 mutation은 새 adapter 생성으로 복구하지 않고 fail-closed한다.
    - start failure와 STOP_TIMEOUT 예외가 adapter lock을 영구 점유하지 않아 이후 command 호출 자체는 가능하다.
    - 단 STOP_TIMEOUT의 coordinator restart admission은 그대로 차단되어 lock release가 lifecycle 정상화를 의미하지 않음을 분리 검증한다.