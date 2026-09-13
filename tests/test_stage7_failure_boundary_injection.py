from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from application.composition.live_runtime_lifecycle_coordinator import LiveRuntimeLifecycleCoordinator
from core.risk.risk_engine import RiskEngine
from core.strategy.contracts import StrategyContext
from core.strategy.orchestrator import StrategyOrchestrator
from core.strategy.registry import StrategyRegistry
from infrastructure.kis.futures_execution_transport import (
    FuturesExecutionTransportError,
    KISFuturesExecutionTransport,
)
from environments.virtual.execution.virtual_execution import VirtualExecutionEngine


class Margin:
    def calculate_order_margin(self, command):
        return 100.0


@dataclass(frozen=True)
class Command:
    qty: int = 1
    price: float = 1.0
    side: str = "BUY"
    client_order_id: str = "o1"
    track_id: str = "t1"
    tag_id: str = ""
    def get_instrument_key(self): return "OPTION_X"


class Controller:
    def __init__(self, events): self.events = events
    def start(self, config, policy): self.events.append("controller.start")
    def stop(self): self.events.append("controller.stop")


class Bootstrap:
    def __init__(self, events, *, start_error=None):
        self.events = events
        self.start_error = start_error
    def startup_reconcile(self, query):
        self.events.append("reconcile")
        return "OK"
    async def start_execution(self, hts_id):
        self.events.append("execution.start")
        if self.start_error is not None: raise self.start_error
    async def close_execution(self): self.events.append("execution.close")


class FailingStrategy:
    strategy_id = "T1"
    version = "1"
    def initialize(self, context): pass
    def on_market_state(self, context): pass
    def evaluate(self, context): raise RuntimeError("INJECTED_STRATEGY_FAILURE")
    def reset(self): pass


def test_risk_kill_switch_failure_boundary_denies_order():
    engine = RiskEngine(margin_engine=Margin())
    engine.trigger_kill_switch("INJECTED_PANIC")
    result = engine.evaluate_order(Command(), SimpleNamespace(
        realized_pnl=0, used_margin=0, total_balance=10000, free_margin=10000,
    ))
    assert result.rejection_reason == "REJECTED_BY_KILL_SWITCH"


def test_virtual_execution_failure_boundary_fails_closed():
    engine = VirtualExecutionEngine(position=object(), account=object())
    with pytest.raises(RuntimeError, match="AUTHORITATIVE_VSSF_EXECUTION_ADAPTER_REQUIRED"):
        engine.execute(object())


def test_kis_transport_connection_failure_is_normalized():
    async def failing_factory(url): raise OSError("INJECTED_CONNECTION_FAILURE")
    from infrastructure.kis.auth import KISAuthManager
    auth = KISAuthManager(app_key="k", app_secret="s", is_vts=True)
    transport = KISFuturesExecutionTransport(auth, socket_factory=failing_factory)
    with pytest.raises(FuturesExecutionTransportError, match="connection failed"):
        asyncio.run(transport.connect())


def test_lifecycle_start_failure_cleans_up_and_releases_ownership():
    events = []
    released = []
    coordinator = LiveRuntimeLifecycleCoordinator(
        controller=Controller(events),
        bootstrap=Bootstrap(events, start_error=RuntimeError("INJECTED_START_FAILURE")),
        release_execution_transport_ownership=lambda: released.append(True),
    )
    with pytest.raises(RuntimeError, match="INJECTED_START_FAILURE"):
        asyncio.run(coordinator.start("config", "policy", hts_id="HTS", recovery_query="Q"))
    assert events == ["controller.start", "reconcile", "execution.start", "execution.close", "controller.stop"]
    assert released == [True]
    assert coordinator.technical_state is None


def test_strategy_evaluation_failure_is_captured_without_crashing_orchestrator():
    registry = StrategyRegistry()
    registry.register(FailingStrategy())
    orchestrator = StrategyOrchestrator(registry, [("T1", "1")])
    result = orchestrator.run({"T1": StrategyContext(strategy_id="T1")})
    assert result.signals == ()
    assert len(result.failures) == 1
    assert result.failures[0].stage == "evaluate"
    assert result.failures[0].error_type == "RuntimeError"
    assert result.failures[0].message == "INJECTED_STRATEGY_FAILURE"
