폴더: Control Tower UI 및 외부 진입점.

[Child Page] control_tower
폴더 페이지
[Child Page] README.md
# Control Tower UI
## 목적
4개 Environment를 하나의 Control Tower에서 선택·조작하되 UI가 Broker/VMS/VSSF/KIS를 직접 호출하지 않는다.
## 단일 제어 경로
```plain text
UI → ControlTowerRuntimeAPI → RuntimeController → EnvironmentHub → EnvironmentBundle → Standard Contracts/Core

Live production assembly: `LiveRuntimeLifecycleCoordinator` is the authoritative technical lifecycle owner. Live Control Tower status uses the same controller through `LiveControlTowerRuntimeAPI`; UI/application lifecycle input is carried by `LiveLifecycleCommand`, and adapter-level async serialization keeps concurrent start/stop/restart requests on one coordinator command sequence.
```
## 표시 범위
        - Active Environment / Runtime lifecycle
        - Market status 및 stale/freshness
        - Account / Position / PnL / Orders
        - Risk / Kill Switch
        - Permission / Live approval / Credential readiness
        - High-Speed speed multiplier / Scenario
        - 오류 및 실행 중단 상태
## 기능
        - Environment 선택
        - Start / Stop / Restart
        - 상태 조회
        - Safety 상태 조회
        - 실행 중인 Environment가 있을 때 이중 실행 방지
## Legacy 보존 원칙
기존 option_program/control 및 web_interface의 기능은 신규 View Model로 이전 가능한 항목을 먼저 매핑한다. 기존 UI는 Phase 14 reference tracing 전까지 삭제하지 않는다.
[Child Page] contracts.py
```python
from dataclasses import dataclass
from enum import Enum
from typing import Any

from application.environment_hub.contracts import (
    EnvironmentConfig,
    EnvironmentType,
    RuntimePolicy,
)


class RuntimeCommand(str, Enum):
    START = "start"
    STOP = "stop"
    RESTART = "restart"
    STATUS = "status"


@dataclass(frozen=True)
class ControlTowerCommand:
    command: RuntimeCommand
    environment: EnvironmentType | None = None


@dataclass(frozen=True)
class LiveLifecycleCommand:
    """Typed UI/application input for the Live async lifecycle boundary."""
    config: EnvironmentConfig
    policy: RuntimePolicy
    hts_id: str
    recovery_query: Any


@dataclass(frozen=True)
class SafetyView:
    kill_switch: bool
    live_approval: bool
    credential_ready: bool
    execution_allowed: bool
    reason: str
```
## 책임
        - Live command의 config는 canonical EnvironmentConfig, policy는 canonical RuntimePolicy만 사용한다.
        - UI/application boundary는 coordinator/transport concrete object를 직접 다루지 않는다.
        - hts_id, recovery_query는 Live bootstrap lifecycle에 필요한 boundary 입력으로 유지한다.
[Child Page] runtime_api.py
```python
from application.environment_hub.contracts import EnvironmentConfig, RuntimePolicy
from contracts.runtime import RuntimeStatus
from contracts.types import EnvironmentType


class ControlTowerRuntimeAPI:
    """UI-facing facade. Concrete broker/environment objects never cross this boundary."""

    def __init__(self, runtime_controller, *, lifecycle_status_source=None):
        self._runtime = runtime_controller
        self._lifecycle_status_source = lifecycle_status_source

    def _assert_control_admitted(self) -> None:
        technical_state = (
            None
            if self._lifecycle_status_source is None
            else getattr(self._lifecycle_status_source, "technical_state", None)
        )
        if technical_state is not None:
            raise RuntimeError("LIVE_RUNTIME_RESTART_NOT_ADMITTED")

    def start(self, config: EnvironmentConfig, policy: RuntimePolicy) -> None:
        self._assert_control_admitted()
        self._runtime.start(config, policy)

    def stop(self) -> None:
        technical_state = (
            None
            if self._lifecycle_status_source is None
            else getattr(self._lifecycle_status_source, "technical_state", None)
        )
        if technical_state is not None:
            raise RuntimeError("LIVE_RUNTIME_STOP_NOT_ADMITTED")
        self._runtime.stop()

    def restart(self, config: EnvironmentConfig, policy: RuntimePolicy) -> None:
        self._assert_control_admitted()
        self._runtime.stop()
        self._runtime.start(config, policy)

    def status(self) -> RuntimeStatus:
        raw = self._runtime.status()
        technical_state = (
            None
            if self._lifecycle_status_source is None
            else getattr(self._lifecycle_status_source, "technical_state", None)
        )
        environment = getattr(raw, "environment", None)
        if isinstance(environment, str):
            environment = EnvironmentType(environment.lower())
        state = str(getattr(raw, "state", "STOPPED")).upper()
        running = state == "RUNNING"
        connected = running
        execution_allowed = running and technical_state is None
        reason = technical_state
        if reason is None and not execution_allowed and state != "STOPPED":
            reason = state

        return RuntimeStatus(
            running=running,
            environment=environment,
            connected=connected,
            execution_allowed=execution_allowed,
            reason=reason,
            technical_state=technical_state,
        )
```
## Status projection boundary
        - lifecycle_status_source는 production composition이 보유한 coordinator만 주입한다.
        - STOP_TIMEOUT을 포함한 모든 non-None technical failure는 Domain 상태가 아니라 RuntimeStatus.technical_state로 투영한다.
        - technical failure가 존재하면 execution_allowed=False로 fail-closed한다.
        - lifecycle source가 없거나 technical failure가 없으면 기존 controller 상태를 표준 RuntimeStatus로 정규화한다.
        - technical_state가 non-None인 모든 terminal 상태에서는 start/restart뿐 아니라 direct controller stop()도 terminal coordinator ownership/release 경계를 우회하지 못하도록 차단한다.
[Child Page] view_models.py
from dataclasses import dataclass
@dataclass(frozen=True)
class EnvironmentStatusView:
environment: str | None
runtime_state: str
market_state: str = "UNKNOWN"
account_state: str = "UNKNOWN"
position_state: str = "UNKNOWN"
pnl: float | None = None
orders_state: str = "UNKNOWN"
risk_state: str = "UNKNOWN"
kill_switch: bool = True
live_approval: bool = False
credential_ready: bool = False
execution_allowed: bool = False
speed_multiplier: float | None = None
scenario: str | None = None
error: str | None = None
def from_runtime_status(status) -> EnvironmentStatusView:
"""Map only the Runtime status contract; never expose concrete environment objects."""
return EnvironmentStatusView(
environment=status.environment,
runtime_state=status.state,
)
[Child Page] permissions.py
class ControlTowerPermissions:
"""UI permission hints; final Live order authorization remains in Live Safety Gate."""
@staticmethod
def can_start(environment, safety) -> bool:
if environment == "live":
return bool(safety.live_approval and safety.credential_ready and not safety.kill_switch)
return not safety.kill_switch
@staticmethod
def can_control_runtime(runtime_state: str, command: str) -> bool:
if command == "start":
return runtime_state != "RUNNING"
if command == "stop":
return runtime_state == "RUNNING"
if command == "restart":
return runtime_state == "RUNNING"
return command == "status"
@staticmethod
def can_submit_live_order(safety) -> bool:
"""UI must never authorize a Live order; it only reflects readiness."""
return False
[Child Page] live_runtime_api.py
```python
from __future__ import annotations

import asyncio

from application.environment_hub.contracts import EnvironmentType
from interfaces.control_tower.contracts import LiveLifecycleCommand
from interfaces.control_tower.runtime_api import ControlTowerRuntimeAPI


class LiveControlTowerRuntimeAPI(ControlTowerRuntimeAPI):
    """Async command boundary for the authoritative Live lifecycle coordinator."""

    def __init__(self, lifecycle_coordinator):
        if lifecycle_coordinator is None:
            raise ValueError("LIVE_RUNTIME_LIFECYCLE_COORDINATOR_REQUIRED")
        controller = lifecycle_coordinator.runtime_controller
        super().__init__(controller, lifecycle_status_source=lifecycle_coordinator)
        self._lifecycle_coordinator = lifecycle_coordinator
        self._command_lock = asyncio.Lock()

    def start(self, *args, **kwargs):
        raise RuntimeError("LIVE_RUNTIME_SYNC_COMMAND_NOT_AVAILABLE")

    def stop(self):
        raise RuntimeError("LIVE_RUNTIME_SYNC_COMMAND_NOT_AVAILABLE")

    def restart(self, *args, **kwargs):
        raise RuntimeError("LIVE_RUNTIME_SYNC_COMMAND_NOT_AVAILABLE")

    def _validate_live_command(self, command: LiveLifecycleCommand) -> None:
        if not isinstance(command, LiveLifecycleCommand):
            raise TypeError("LIVE_RUNTIME_COMMAND_REQUIRED")
        if command.config.environment is not EnvironmentType.LIVE:
            raise ValueError("LIVE_RUNTIME_COMMAND_ENVIRONMENT_REQUIRED")

    async def start_live(self, command: LiveLifecycleCommand):
        self._validate_live_command(command)
        async with self._command_lock:
            return await self._lifecycle_coordinator.start(
                command.config,
                command.policy,
                hts_id=command.hts_id,
                recovery_query=command.recovery_query,
            )

    async def stop_live(self) -> None:
        async with self._command_lock:
            await self._lifecycle_coordinator.stop()

    async def restart_live(self, command: LiveLifecycleCommand):
        self._validate_live_command(command)
        async with self._command_lock:
            await self._lifecycle_coordinator.stop()
            return await self._lifecycle_coordinator.start(
                command.config,
                command.policy,
                hts_id=command.hts_id,
                recovery_query=command.recovery_query,
            )
```
## 책임
        - Live lifecycle command의 authoritative owner는 LiveRuntimeLifecycleCoordinator다.
        - UI/application boundary는 LiveLifecycleCommand DTO만 전달한다.
        - adapter-level async lock은 동일 Control Tower entry의 start/stop/restart를 하나의 lifecycle command sequence로 직렬화한다.
        - restart는 lock을 유지한 stop → start 원자적 sequence다.
        - status projection은 기존 ControlTowerRuntimeAPI.status() 계약을 유지한다.
        - base class의 sync start/stop/restart는 Live adapter에서 차단한다.

[Child Page] cli
폴더 페이지