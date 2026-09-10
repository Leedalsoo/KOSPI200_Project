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
