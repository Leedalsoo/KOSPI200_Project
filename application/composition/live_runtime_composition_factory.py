"""Explicit application assembly for one Live runtime scope."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from application.environment_hub.contracts import EnvironmentConfig, RuntimePolicy
from application.environment_hub.factory import EnvironmentFactory
from application.environment_hub.hub import EnvironmentHub
from application.runtime_controller.controller import RuntimeController
from environments.live.bundle import LiveEnvironmentBundle
from environments.live.contracts import LiveSafetyPolicy


def create_live_runtime_controller(
# *,
    live_builder: Callable[[EnvironmentConfig, RuntimePolicy], LiveEnvironmentBundle],
) -> RuntimeController:
    """Create a Live RuntimeController using only caller-supplied dependencies."""
    if live_builder is None:
        raise ValueError("LIVE_RUNTIME_BUILDER_REQUIRED")
    factory = EnvironmentFactory(live_builder=live_builder)
    return RuntimeController(hub=EnvironmentHub(factory=factory))


def build_live_bundle_from_components(
# *,
    market: Any,
    broker: Any,
    account: Any,
    position: Any,
    reconciler: Any,
    recovery: Any,
    safety_policy: LiveSafetyPolicy,
) -> Callable[[EnvironmentConfig, RuntimePolicy], LiveEnvironmentBundle]:
    """Bind concrete Live components without creating synthetic defaults."""
    required = {
        "market": market,
        "broker": broker,
        "account": account,
        "position": position,
        "reconciler": reconciler,
        "recovery": recovery,
        "safety_policy": safety_policy,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        raise ValueError("LIVE_RUNTIME_DEPENDENCY_REQUIRED:" + ",".join(missing))

    def builder(config: EnvironmentConfig, policy: RuntimePolicy) -> LiveEnvironmentBundle:
        if config.environment.value != "live":
            raise ValueError("LIVE_RUNTIME_BUILDER_ENVIRONMENT_MISMATCH")
        return LiveEnvironmentBundle(
            market=market,
            broker=broker,
            account=account,
            position=position,
            reconciler=reconciler,
            recovery=recovery,
            policy=safety_policy,
        )

    return builder
