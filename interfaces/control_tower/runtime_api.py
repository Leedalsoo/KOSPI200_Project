"""Environment-neutral Control Tower runtime facade."""

from application.environment_hub.contracts import EnvironmentConfig, RuntimePolicy
from contracts.runtime import RuntimeStatus
from contracts.types import EnvironmentType


class ControlTowerRuntimeAPI:
    """Expose runtime control/status without leaking concrete environment objects."""

    def __init__(self, runtime_controller, *, lifecycle_status_source=None):
        self._runtime = runtime_controller
        self._lifecycle_status_source = lifecycle_status_source

    def _technical_state(self):
        if self._lifecycle_status_source is None:
            return None
        return getattr(self._lifecycle_status_source, "technical_state", None)

    def _assert_control_admitted(self) -> None:
        technical_state = self._technical_state()
        if technical_state is not None:
            raise RuntimeError("LIVE_RUNTIME_RESTART_NOT_ADMITTED")

    def start(self, config: EnvironmentConfig, policy: RuntimePolicy) -> None:
        self._assert_control_admitted()
        self._runtime.start(config, policy)

    def stop(self) -> None:
        technical_state = self._technical_state()
        if technical_state is not None:
            raise RuntimeError("LIVE_RUNTIME_STOP_NOT_ADMITTED")
        self._runtime.stop()

    def restart(self, config: EnvironmentConfig, policy: RuntimePolicy) -> None:
        self._assert_control_admitted()
        self._runtime.stop()
        self._runtime.start(config, policy)

    def status(self) -> RuntimeStatus:
        raw = self._runtime.status()
        technical_state = self._technical_state()
        environment = getattr(raw, "environment", None)
        if isinstance(environment, str):
            environment = EnvironmentType(environment.lower())

        state = str(getattr(raw, "state", "STOPPED")).upper()
        running = state == "RUNNING"
        connected = bool(getattr(raw, "connected", running))
        execution_allowed = running and connected and technical_state is None
        reason = technical_state
        if reason is None and not execution_allowed and state != "STOPPED":
            reason = state

        return RuntimeStatus(
            running=running,
            environment=environment,
            connected=connected,
            execution_allowed=execution_allowed,
            reason=reason,
            technical_state=technical_state,
        )
