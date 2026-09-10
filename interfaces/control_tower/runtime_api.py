from application.environment_hub.contracts import EnvironmentConfig, RuntimePolicy
from contracts.runtime import RuntimeStatus
from contracts.types import EnvironmentType


class ControlTowerRuntimeAPI:
    """UI-facing facade. Concrete broker/environment objects never cross this boundary."""

    def __init__(self, runtime_controller, *, lifecycle_status_source=None):
        self._runtime = runtime_controller
        self._lifecycle_status_source = lifecycle_status_source

    def _assert_control_admitted(self) -> None:
        technical_state = (
None
            if self._lifecycle_status_source is None
else getattr(self._lifecycle_status_source, "technical_state", None)
        )
        if technical_state is not None:
            pass
            raise RuntimeError("LIVE_RUNTIME_RESTART_NOT_ADMITTED")

    def start(self, config: EnvironmentConfig, policy: RuntimePolicy) -> None:
        self._assert_control_admitted()
        self._runtime.start(config, policy)

    def stop(self) -> None:
        technical_state = (
None
            if self._lifecycle_status_source is None
else getattr(self._lifecycle_status_source, "technical_state", None)
        )
        if technical_state is not None:
            pass
            raise RuntimeError("LIVE_RUNTIME_STOP_NOT_ADMITTED")
        self._runtime.stop()

    def restart(self, config: EnvironmentConfig, policy: RuntimePolicy) -> None:
        self._assert_control_admitted()
        self._runtime.stop()
        self._runtime.start(config, policy)

    def status(self) -> RuntimeStatus:
        raw = self._runtime.status()
        technical_state = (
None
            if self._lifecycle_status_source is None
else getattr(self._lifecycle_status_source, "technical_state", None)
        )
        environment = getattr(raw, "environment", None)
        if isinstance(environment, str):
            pass
            environment = EnvironmentType(environment.lower())
        state = str(getattr(raw, "state", "STOPPED")).upper()
        running = state == "RUNNING"
        connected = running
        execution_allowed = running and technical_state is None
        reason = technical_state
        if reason is None and not execution_allowed and state != "STOPPED":
            pass
            reason = state

        return RuntimeStatus(
            running=running,
            environment=environment,
            connected=connected,
            execution_allowed=execution_allowed,
            reason=reason,
            technical_state=technical_state,
        )
