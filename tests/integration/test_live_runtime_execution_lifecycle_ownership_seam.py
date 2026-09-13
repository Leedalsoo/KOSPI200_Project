from __future__ import annotations

import asyncio

from application.bootstrap import LiveRuntimeBootstrap
from application.environment_hub.hub import EnvironmentHub
from application.runtime_controller.controller import RuntimeController


class Bundle:
    environment = type("Environment", (), {"value": "live"})()

    def __init__(self, events): self.events = events
    def initialize(self): self.events.append("bundle.initialize")
    def connect(self): self.events.append("bundle.connect"); return True
    def start(self): self.events.append("bundle.start")
    def stop(self): self.events.append("bundle.stop")
    def shutdown(self): self.events.append("bundle.shutdown")


class Hub:
    def __init__(self, bundle): self._bundle = bundle; self.active = None
    def create(self, config, policy): return self._bundle
    def activate(self, bundle): self.active = bundle
    def deactivate(self): self.active = None


class Execution:
    def __init__(self, events, shared_state):
        self.events = events
        self.shared_state = shared_state
        self.settlement = type("Settlement", (), {"order_state_machine": shared_state["oms"]})()
    async def start_execution(self, hts): self.events.append("execution.start")
    async def receive_execution_once(self): self.events.append("execution.receive"); return self.shared_state
    async def close_execution(self): self.events.append("execution.close")


class Recovery:
    def __init__(self, events): self.events = events
    def recover(self, query): self.events.append("recovery.startup_reconcile"); return "SETTLED"


class Router:
    def __init__(self, fsm): self._order_state_machine = fsm


def test_explicit_lifecycle_order_and_shared_settlement_state():
    events = []
    shared_state = {"oms": object(), "position": "POSITION-1"}
    hub = Hub(Bundle(events))
    controller = RuntimeController(hub)
    execution = Execution(events, shared_state)
    recovery = Recovery(events)
    bootstrap = LiveRuntimeBootstrap(
        execution=execution,
        order_router=Router(shared_state["oms"]),
        recovery_service=recovery,
    )

    controller.start("live-config", "live-policy")
    assert controller._state == "RUNNING"
    assert bootstrap.startup_reconcile("Q1") == "SETTLED"
    asyncio.run(bootstrap.start_execution("HTS"))
    assert asyncio.run(bootstrap.receive_execution_once()) is shared_state
    asyncio.run(bootstrap.close_execution())
    controller.stop()

    assert events == [
        "bundle.initialize", "bundle.connect", "bundle.start",
        "recovery.startup_reconcile", "execution.start",
        "execution.receive", "execution.close",
        "bundle.stop", "bundle.shutdown",
    ]
    assert controller._state == "STOPPED"
    assert controller._hub.active is None


def test_no_implicit_bootstrap_or_execution_lifecycle_inside_controller():
    events = []
    controller = RuntimeController(Hub(Bundle(events)))
    controller.start("live-config", "live-policy")
    assert events == ["bundle.initialize", "bundle.connect", "bundle.start"]
    controller.stop()
    assert events == [
        "bundle.initialize", "bundle.connect", "bundle.start",
        "bundle.stop", "bundle.shutdown",
    ]
