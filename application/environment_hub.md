폴더: Environment Hub 계층.

[Child Page] registry.py
구현 예정: Architecture와 Standard Contract 확정 후 실제 코드 작성.

[Child Page] contracts.py
```python
from dataclasses import dataclass
from typing import Protocol

from contracts.environment import EnvironmentLifecycle
from contracts.types import EnvironmentType


@dataclass(frozen=True)
class EnvironmentConfig:
    environment: EnvironmentType
    name: str


@dataclass(frozen=True)
class RuntimePolicy:
    allow_live_orders: bool = False
    speed_multiplier: float = 1.0
    # Standard shutdown policy. Live defaults are bounded and may be
    # explicitly overridden by environment-specific composition.
    graceful_shutdown_timeout_seconds: float = 10.0
    cancellation_drain_timeout_seconds: float = 5.0


class EnvironmentBundle(EnvironmentLifecycle, Protocol):
    environment: EnvironmentType


__all__ = ("EnvironmentBundle", "EnvironmentConfig", "EnvironmentType", "RuntimePolicy")
```
## Ownership
    - EnvironmentType is canonical in contracts.types.
    - EnvironmentLifecycle is canonical in contracts.environment.
    - This application module retains the existing import surface for EnvironmentConfig, RuntimePolicy, and EnvironmentBundle while delegating shared contract ownership downward.
## Shutdown policy ownership
    - graceful_shutdown_timeout_seconds: ingress 차단·close 이후 정상 종료를 기다리는 기술적 최대 시간.
    - cancellation_drain_timeout_seconds: cancellation 요청 후 task 종료를 확인하는 기술적 최대 시간.
    - timeout 값은 RuntimePolicy에서 환경별 composition이 명시적으로 override할 수 있다.
    - timeout 자체는 업무 주문 취소나 포지션 청산을 의미하지 않는다. 미완료 업무 상태의 의미는 Domain/운영 정책에서 별도로 정의한다.
    - cancellation 후에도 receive ownership이 남으면 coordinator는 ownership release를 수행하지 않고 fail-closed한다.

[Child Page] factory.py
```python
from typing import Callable

from application.environment_hub.contracts import (
    EnvironmentBundle,
    EnvironmentConfig,
    EnvironmentType,
    RuntimePolicy,
)


class EnvironmentFactory:
    def __init__(
        self,
        *,
        virtual_builder: Callable[[EnvironmentConfig, RuntimePolicy], EnvironmentBundle]
        | None = None,
        live_builder: Callable[[EnvironmentConfig, RuntimePolicy], EnvironmentBundle]
        | None = None,
    ) -> None:
        self._virtual_builder = virtual_builder
        self._live_builder = live_builder

    def create(
        self, config: EnvironmentConfig, policy: RuntimePolicy
    ) -> EnvironmentBundle:
        if config.environment is EnvironmentType.VIRTUAL:
            if self._virtual_builder is None:
                raise RuntimeError(
                    "Virtual Environment composition is not configured: "
                    "inject a builder that supplies the actual VMS/VSSF components"
                )
            return self._virtual_builder(config, policy)
        if config.environment is EnvironmentType.HIGH_SPEED:
            from environments.high_speed.bundle import HighSpeedEnvironmentBundle
            return HighSpeedEnvironmentBundle(config, policy)
        if config.environment is EnvironmentType.PAPER:
            from environments.paper.bundle import PaperEnvironmentBundle
            return PaperEnvironmentBundle(config, policy)
        if config.environment is EnvironmentType.LIVE:
            if self._live_builder is None:
                raise RuntimeError(
                    "Live Environment composition is not configured: "
                    "inject a builder that supplies the actual broker/market/account/position components"
                )
            return self._live_builder(config, policy)
        raise ValueError(f"unsupported environment: {config.environment}")
```
## Virtual composition 경계
    - Factory는 Core/Strategy를 생성하지 않는다.
    - Virtual Bundle에 임의의 초기 가격, 계좌 잔고, 시장 시나리오, Broker 정책을 생성하지 않는다.
    - 현재 EnvironmentConfig에는 실제 VMS/VSSF 구성 파라미터가 없으므로 Factory가 VirtualEnvironmentBundle(config, policy)를 직접 호출하지 않는다.
    - Virtual 환경은 실제 VMS/VSSF 구성요소를 조립하는 virtual_builder를 명시적으로 주입해야 한다.
    - 실제 VMS/VSSF builder가 제공되기 전에는 Virtual 생성 요청을 조용히 부분 구성 상태로 통과시키지 않고 명확하게 실패시킨다.
    - High-Speed/Paper/Live의 기존 Factory 분기와 import 경계는 유지한다.
## 후속 조건
실제 VMS Market + Virtual Clock + VSSF-derived Broker/Account/Position/Execution의 생성 파라미터와 builder source가 확정되면 virtual_builder를 실제 composition으로 연결한다. 이 단계에서는 기능을 추측하여 구현하지 않는다.

[Child Page] hub.py
```python
from application.environment_hub.contracts import EnvironmentBundle, EnvironmentConfig, RuntimePolicy
from application.environment_hub.factory import EnvironmentFactory


class EnvironmentHub:
    def __init__(self, factory: EnvironmentFactory) -> None:
        self._factory = factory
        self._active: EnvironmentBundle | None = None

    @property
    def active(self) -> EnvironmentBundle | None:
        return self._active

    def create(self, config: EnvironmentConfig, policy: RuntimePolicy) -> EnvironmentBundle:
        if self._active is not None:
            raise RuntimeError("an environment is already active")
        return self._factory.create(config, policy)

    def activate(self, bundle: EnvironmentBundle) -> None:
        if self._active is not None:
            raise RuntimeError("cannot activate a second environment")
        self._active = bundle

    def deactivate(self) -> None:
        self._active = None
```
Hub는 하나의 Runtime에서 하나의 활성 Environment만 소유한다.