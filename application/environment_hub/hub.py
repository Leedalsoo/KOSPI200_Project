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
