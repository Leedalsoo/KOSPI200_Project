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
    track7_order_timeout_seconds: float | None = None


class EnvironmentBundle(EnvironmentLifecycle, Protocol):
    environment: EnvironmentType


__all__ = ("EnvironmentBundle", "EnvironmentConfig", "EnvironmentType", "RuntimePolicy")
