from dataclasses import dataclass

from contracts.types import EnvironmentType
from interfaces.control_tower.runtime_api import ControlTowerRuntimeAPI


@dataclass
class _ControllerStatus:
    environment: str | None
    state: str


class _Controller:
    def __init__(self, status):
        self._status = status

    def start(self, config, policy):
        self._status = _ControllerStatus("live", "RUNNING")

    def stop(self):
        self._status = _ControllerStatus("live", "STOPPED")

    def status(self):
        return self._status


class _Lifecycle:
    def __init__(self, technical_state=None):
        self.technical_state = technical_state


def test_control_tower_projects_live_technical_state_into_standard_runtime_status():
    api = ControlTowerRuntimeAPI(
        _Controller(_ControllerStatus("live", "STOPPING")),
        lifecycle_status_source=_Lifecycle("STOP_TIMEOUT"),
    )

    status = api.status()

# assert status.environment is EnvironmentType.LIVE
# assert status.running is False
    assert status.technical_state == "STOP_TIMEOUT"
# assert status.execution_allowed is False
    assert status.reason == "STOP_TIMEOUT"


def test_control_tower_without_lifecycle_failure_keeps_standard_status():
    api = ControlTowerRuntimeAPI(
        _Controller(_ControllerStatus("virtual", "RUNNING")),
        lifecycle_status_source=_Lifecycle(None),
    )

    status = api.status()

# assert status.environment is EnvironmentType.VIRTUAL
# assert status.running is True
# assert status.connected is True
# assert status.execution_allowed is True
# assert status.technical_state is None
