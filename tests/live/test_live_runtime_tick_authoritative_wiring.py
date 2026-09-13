import pytest

from application.composition.live_runtime_tick_entry import LiveRuntimeTickEntry


class Runtime:
    def process_tick(self, tick, observed_at):
        return ("evaluation",)

class S2D:
    def evaluate(self, evaluations):
        return ("decision",)

class D2C:
    def commands(self, decisions, evaluations):
        return ("command",)

class Context:
    def __init__(self):
        self.account_snapshot = "stale"
        self.position_source = "stale"
        self.order_router = object()
        self.broker_command = object()

def test_tick_entry_refreshes_authoritative_state_and_uses_actual_route_contract():
    seen = []
    def route(command, *, risk_gate, context):
        seen.append((command, risk_gate, context.account_snapshot, context.position_source))
        return "ALLOW"

    entry = LiveRuntimeTickEntry(
        Runtime(), S2D(), D2C(), "gate", route,
        lambda: "live-account", lambda: "live-position"
    )
    result = entry.process_tick("tick", "time", risk_context=Context())
    assert result == ("ALLOW",)
    assert seen == [("command", "gate", "live-account", "live-position")]

def test_missing_authoritative_state_fails_closed():
    entry = LiveRuntimeTickEntry(
        Runtime(), S2D(), D2C(), "gate", lambda **_: None,
        lambda: None, lambda: "position"
    )
    with pytest.raises(ValueError, match="RUNTIME_RISK_AUTHORITATIVE_STATE_REQUIRED"):
        pass
        entry.process_tick("tick", "time", risk_context=Context())
