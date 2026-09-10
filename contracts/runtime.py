from dataclasses import dataclass
from typing import Protocol

from contracts.types import EnvironmentType


@dataclass(frozen=True)
class RuntimeCommand:
    action: str
    environment: EnvironmentType | None = None


@dataclass(frozen=True)
class RuntimeStatus:
    running: bool
    environment: EnvironmentType | None
    connected: bool
    execution_allowed: bool
    reason: str | None = None
    # Control-plane lifecycle state. Never reuse Domain order/position status values.
    technical_state: str | None = None


class RuntimeControl(Protocol):
    """UI-facing runtime control boundary."""

    def execute(self, command: RuntimeCommand) -> RuntimeStatus: ...

    def status(self) -> RuntimeStatus: ...
