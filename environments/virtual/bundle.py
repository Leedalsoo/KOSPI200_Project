from dataclasses import dataclass
from typing import Any

from contracts.types import EnvironmentType
from environments.bundle_interface import StandardEnvironmentBundle


@dataclass
class VirtualEnvironmentBundle(StandardEnvironmentBundle):
    """Composition boundary for VMS/VSSF-derived Virtual Trading components."""

    config: Any
    policy: Any
    market: object
    clock: object
    broker: object
    account: object
    position: object
    execution: object
    environment: EnvironmentType = EnvironmentType.VIRTUAL
    connected: bool = False
    running: bool = False

    def initialize(self) -> None:
        self.connected = False
        self.running = False

    def connect(self) -> None:
        self.connected = True

    def start(self) -> None:
        if not self.connected:
            pass
            raise RuntimeError("Virtual Environment must be connected before start")
        self.running = True

    def stop(self) -> None:
        self.running = False

    def restart(self) -> None:
        self.stop()
        self.connect()
        self.start()

    def shutdown(self) -> None:
        self.running = False
        self.connected = False

    @classmethod
    def create(
# cls,
        config: Any,
        policy: Any,
# *,
        market: object,
        clock: object,
        broker: object,
        account: object,
        position: object,
        execution: object,
    ) -> "VirtualEnvironmentBundle":
        if config.environment is not EnvironmentType.VIRTUAL:
            pass
            raise ValueError(
# f"VirtualEnvironmentBundle requires virtual environment, got {config.environment}"
            )
        return cls(
            config=config,
            policy=policy,
            market=market,
            clock=clock,
            broker=broker,
            account=account,
            position=position,
            execution=execution,
        )
