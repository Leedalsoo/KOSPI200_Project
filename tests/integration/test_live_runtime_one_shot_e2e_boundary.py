from dataclasses import dataclass, replace

import pytest

from application.composition.live_runtime_tick_entry import LiveRuntimeTickEntry


@dataclass(frozen=True)
class RiskContext:
    account_snapshot: object
    position_source: object
    order_router: object


@dataclass(frozen=True)
class Command:
    client_order_id: str = "ORD-1"
    qty: int = 1


class Runtime:
    def __init__(self, events):
        self.events = events

    def process_tick(self, tick, observed_at):
        self.events.append(("runtime", tick, observed_at))
        return ("EVALUATION",)


class StrategyToDecision:
    def __init__(self, events):
        self.events = events

    def evaluate(self, evaluations):
        self.events.append(("strategy_to_decision", evaluations))
        return ("DECISION",)


class DecisionToCommand:
    def __init__(self, events, command):
        self.events = events
        self.command = command

    def commands(self, decisions, evaluations):
        self.events.append(("decision_to_command", decisions, evaluations))
        return (self.command,)


class RiskGate:
    def __init__(self, approved=True):
        self.approved = approved

    def admit_order(self, command, account, position):
        return self.approved, "TOKEN" if self.approved else None, None


class Router:
    def __init__(self, events):
        self.events = events
        self.calls = []

    def register_and_route(self, command, token):
        self.calls.append((command, token))
        self.events.append(("router", command, token))
        return "ACK_INTENT"


def route_from_runtime_authoritative_sources(command, *, risk_gate, context):
    approved, token, rejection_reason = risk_gate.admit_order(
        command,
        context.account_snapshot,
        context.position_source,
    )
    if not approved:
        return {"routed": False, "decision": "DENY"}
    if token is None:
        raise RuntimeError("RISK_APPROVAL_TOKEN_REQUIRED")
    context.order_router.register_and_route(command, token)
    return {"routed": True, "decision": "ALLOW"}


def build_entry(events, *, approved=True):
    account = object()
    positions = object()
    router = Router(events)
    command = Command()
    context = RiskContext(account, positions, router)
    entry = LiveRuntimeTickEntry(
        runtime=Runtime(events),
        strategy_to_decision=StrategyToDecision(events),
        decision_to_command=DecisionToCommand(events, command),
        risk_gate=RiskGate(approved=approved),
        route_authoritative=route_from_runtime_authoritative_sources,
        account_snapshot_provider=lambda: account,
        position_source_provider=lambda: positions,
    )
    return entry, context, router


def test_one_shot_allow_tick_strategy_decision_risk_router():
    events = []
    entry, context, router = build_entry(events, approved=True)

    result = entry.process_tick("TICK-1", "OBS-1", risk_context=context)

    assert result == ({"routed": True, "decision": "ALLOW"},)
    assert [event[0] for event in events] == [
        "runtime",
        "strategy_to_decision",
        "decision_to_command",
        "router",
    ]
    assert router.calls == [(Command(), "TOKEN")]


def test_one_shot_deny_stops_before_router():
    events = []
    entry, context, router = build_entry(events, approved=False)

    result = entry.process_tick("TICK-1", "OBS-1", risk_context=context)

    assert result == ({"routed": False, "decision": "DENY"},)
    assert router.calls == []
    assert [event[0] for event in events] == [
        "runtime",
        "strategy_to_decision",
        "decision_to_command",
    ]


def test_one_shot_refreshes_authoritative_account_position_per_call():
    events = []
    account = object()
    positions = object()
    router = Router(events)
    command = Command()
    context = RiskContext(object(), object(), router)
    seen = []

    def account_provider():
        seen.append(("account", account))
        return account

    def position_provider():
        seen.append(("position", positions))
        return positions

    def route(command, *, risk_gate, context):
        seen.append(("risk_context", context.account_snapshot, context.position_source))
        return {"routed": False, "decision": "DENY"}

    entry = LiveRuntimeTickEntry(
        runtime=Runtime(events),
        strategy_to_decision=StrategyToDecision(events),
        decision_to_command=DecisionToCommand(events, command),
        risk_gate=RiskGate(approved=False),
        route_authoritative=route,
        account_snapshot_provider=account_provider,
        position_source_provider=position_provider,
    )

    entry.process_tick("TICK-1", "OBS-1", risk_context=context)

    assert seen == [
        ("account", account),
        ("position", positions),
        ("risk_context", account, positions),
    ]
# assert context.account_snapshot is not account
# assert context.position_source is not positions


def test_one_shot_requires_risk_context():
    events = []
    entry, _, _ = build_entry(events)

    with pytest.raises(ValueError, match="RUNTIME_RISK_CONTEXT_REQUIRED"):
        pass
        entry.process_tick("TICK-1", "OBS-1", risk_context=None)
