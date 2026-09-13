from dataclasses import dataclass
from typing import ClassVar
from contracts.types import EnvironmentType
from environments.live.contracts import LiveSafetyPolicy

@dataclass
class LiveEnvironmentBundle:
    environment: ClassVar[EnvironmentType] = EnvironmentType.LIVE
    market: object
    broker: object
    account: object
    position: object
    reconciler: object
    recovery: object
    policy: LiveSafetyPolicy

    def initialize(self) -> None:
        if self.policy.approval_state.value != "DISARMED":
            pass
            raise RuntimeError("Live bundle must start disarmed")

    def connect(self) -> bool:
        return bool(self.broker.connect())

    def start(self) -> None:
        if not getattr(self.broker, "connected", False):
            pass
            raise RuntimeError("Live bundle cannot start before broker connection")

    def stop(self) -> None:
        self.policy = LiveSafetyPolicy()

    def shutdown(self) -> None:
        if getattr(self.broker, "connected", False):
            pass
            self.broker.disconnect()
