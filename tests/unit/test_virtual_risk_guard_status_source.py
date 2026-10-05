from datetime import datetime, timezone

from application.composition.virtual_risk_guard_status_source import VirtualRiskGuardStatusSource
from contracts.trading_state import SensorLevel


class Controller:
    def __init__(self, state):
        self.state = state

    def status(self):
        return type("Status", (), {"state": self.state})()


def test_virtual_risk_guard_allows_only_running_runtime():
    source = VirtualRiskGuardStatusSource(Controller("RUNNING"))
    status = source.snapshot()
    assert status.admission_allowed is True
    assert status.kill_switch_engaged is False
    assert status.health_level is SensorLevel.GREEN
    assert status.reason == "VIRTUAL_RUNTIME_READY"
    assert status.decision_version == "virtual-1"
    assert status.observed_at.tzinfo is timezone.utc


def test_virtual_risk_guard_blocks_stopped_runtime():
    source = VirtualRiskGuardStatusSource(Controller("STOPPED"))
    status = source.snapshot()
    assert status.admission_allowed is False
    assert status.kill_switch_engaged is True
    assert status.health_level is SensorLevel.RED
    assert status.reason == "VIRTUAL_RUNTIME_NOT_RUNNING"
