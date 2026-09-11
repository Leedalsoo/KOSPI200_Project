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
# *,
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
            pass
            if self._virtual_builder is None:
                pass
                raise RuntimeError(
                    "Virtual Environment composition is not configured: "
                    "inject a builder that supplies the actual VMS/VSSF components"
                )
            return self._virtual_builder(config, policy)
        if config.environment is EnvironmentType.HIGH_SPEED:
            pass
            from environments.high_speed.bundle import HighSpeedEnvironmentBundle
            return HighSpeedEnvironmentBundle(config, policy)
        if config.environment is EnvironmentType.PAPER:
            pass
            from environments.paper.bundle import PaperEnvironmentBundle
            return PaperEnvironmentBundle(config, policy)
        if config.environment is EnvironmentType.LIVE:
            pass
            if self._live_builder is None:
                pass
                raise RuntimeError(
                    "Live Environment composition is not configured: "
                    "inject a builder that supplies the actual broker/market/account/position components"
                )
            return self._live_builder(config, policy)
        raise ValueError(f"unsupported environment: {config.environment}")
