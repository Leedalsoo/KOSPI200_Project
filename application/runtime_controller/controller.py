from dataclasses import dataclass

from application.environment_hub.contracts import EnvironmentConfig, RuntimePolicy
from application.environment_hub.hub import EnvironmentHub


@dataclass(frozen=True)
class RuntimeStatus:
    environment: str | None
    state: str


class RuntimeController:
    def __init__(self, hub: EnvironmentHub) -> None:
        self._hub = hub
        self._state = "STOPPED"

    def start(self, config: EnvironmentConfig, policy: RuntimePolicy) -> None:
        if self._state == "RUNNING":
            raise RuntimeError("runtime is already running")
        bundle = self._hub.create(config, policy)
        bundle.initialize()
        bundle.connect()
        bundle.start()
        self._hub.activate(bundle)
        self._state = "RUNNING"

    def stop(self) -> None:
        bundle = self._hub.active
        if bundle is None:
            self._state = "STOPPED"
            return
        self._state = "STOPPING"
        bundle.stop()
        bundle.shutdown()
        self._hub.deactivate()
        self._state = "STOPPED"

    @property
    def environment_hub(self) -> EnvironmentHub:
        """Public lifecycle boundary for application/UI adapters."""
        return self._hub

    def status(self) -> RuntimeStatus:
        bundle = self._hub.active
        return RuntimeStatus(
            environment=None if bundle is None else bundle.environment.value,
            state=self._state,
        )
