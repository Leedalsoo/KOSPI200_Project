from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
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


class ShutdownPolicy:
    graceful_shutdown_timeout_seconds = 0.01
    cancellation_drain_timeout_seconds = 0.01


class HangingBootstrap(Bootstrap):
    def __init__(self, events, *, cancel_is_noop=False):
        super().__init__(events)
        self.cancel_is_noop = cancel_is_noop
        self.receive_started = asyncio.Event()

    async def receive_execution_once(self):
        self.receive_started.set()
        await asyncio.Event().wait()

    async def cancel_execution_receives(self):
        self.events.append("receive.cancel")
        if not self.cancel_is_noop:
            return
        await asyncio.sleep(0)


def _started_coordinator(bootstrap, *, policy=None):
    events = bootstrap.events
    coordinator = LiveRuntimeLifecycleCoordinator(
        controller=Controller(events),
        bootstrap=bootstrap,
    )
    coordinator._started = True
    coordinator._stopping = False
    coordinator._policy = policy or ShutdownPolicy()
    return coordinator


def test_lifecycle_shutdown_cancellation_sets_technical_state():
    async def _test():
        events = []
        bootstrap = HangingBootstrap(events)
        coordinator = _started_coordinator(bootstrap)
        receive_task = asyncio.create_task(coordinator.receive_execution_once())
        await bootstrap.receive_started.wait()
        stop_task = asyncio.create_task(coordinator.stop())
        await asyncio.sleep(0)
        stop_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stop_task
        assert coordinator.technical_state == "STOP_SHUTDOWN_CANCELLED"
        assert coordinator._started is False
        assert "controller.stop" not in events
        receive_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await receive_task

    asyncio.run(_test())


def test_lifecycle_shutdown_drain_timeout_is_fail_closed():
    async def _test():
        events = []
        bootstrap = HangingBootstrap(events, cancel_is_noop=True)
        coordinator = _started_coordinator(bootstrap)
        receive_task = asyncio.create_task(coordinator.receive_execution_once())
        await bootstrap.receive_started.wait()
        with pytest.raises(RuntimeError, match="LIVE_RUNTIME_SHUTDOWN_DRAIN_TIMEOUT"):
            await coordinator.stop()
        assert coordinator.technical_state == "STOP_TIMEOUT"
        assert coordinator._started is False
        assert coordinator._stopping is True
        assert "controller.stop" not in events
        receive_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await receive_task

    asyncio.run(_test())


def test_kis_transport_malformed_control_message_is_normalized():
    from infrastructure.kis.auth import KISAuthManager
    auth = KISAuthManager(app_key="k", app_secret="s", is_vts=True)
    transport = KISFuturesExecutionTransport(auth)
    with pytest.raises(FuturesExecutionTransportError, match="invalid KIS websocket control message"):
        transport._normalize("{not-json")


def test_kis_transport_payload_without_crypto_context_is_rejected():
    from infrastructure.kis.auth import KISAuthManager
    auth = KISAuthManager(app_key="k", app_secret="s", is_vts=True)
    transport = KISFuturesExecutionTransport(auth)
    with pytest.raises(FuturesExecutionTransportError, match="crypto context is not established"):
        transport._normalize("1|H0IFCNI0|22|ENCODED_PAYLOAD")


def test_kis_transport_decryption_failure_is_normalized():
    from infrastructure.kis.auth import KISAuthManager
    auth = KISAuthManager(app_key="k", app_secret="s", is_vts=True)
    transport = KISFuturesExecutionTransport(auth)
    transport._crypto["H0IFCNI0"] = ("0" * 16, "1" * 16)
    with pytest.raises(FuturesExecutionTransportError, match="invalid KIS H0IFCNI0 encrypted payload"):
        transport._normalize("1|H0IFCNI0|22|bm90LXZhbGlk")


class FailingStopController(Controller):
    def stop(self):
        self.events.append("controller.stop")
        raise RuntimeError("INJECTED_CONTROLLER_STOP_FAILURE")


def test_lifecycle_controller_stop_failure_sets_technical_state():
    async def _test():
        events = []
        bootstrap = Bootstrap(events)
        coordinator = LiveRuntimeLifecycleCoordinator(
            controller=FailingStopController(events),
            bootstrap=bootstrap,
        )
        coordinator._started = True
        coordinator._policy = ShutdownPolicy()
        with pytest.raises(RuntimeError, match="INJECTED_CONTROLLER_STOP_FAILURE"):
            await coordinator.stop()
        assert events == ["execution.close", "controller.stop"]
        assert coordinator.technical_state == "STOP_CONTROLLER_FAILED"
        assert coordinator._started is False
        assert coordinator._stopping is True

    asyncio.run(_test())


def test_lifecycle_transport_ownership_release_failure_sets_technical_state():
    async def _test():
        events = []
        released = []
        def fail_release():
            released.append(True)
            raise RuntimeError("INJECTED_OWNERSHIP_RELEASE_FAILURE")
        coordinator = LiveRuntimeLifecycleCoordinator(
            controller=Controller(events),
            bootstrap=Bootstrap(events),
            release_execution_transport_ownership=fail_release,
        )
        coordinator._started = True
        coordinator._policy = ShutdownPolicy()
        with pytest.raises(RuntimeError, match="INJECTED_OWNERSHIP_RELEASE_FAILURE"):
            await coordinator.stop()
        assert events == ["execution.close", "controller.stop"]
        assert released == [True]
        assert coordinator.technical_state == "TRANSPORT_OWNERSHIP_RELEASE_FAILED"
        assert coordinator._started is False
        assert coordinator._stopping is True

    asyncio.run(_test())


class DelegatingBootstrap(Bootstrap):
    def __init__(self, events):
        super().__init__(events)
        self.release_receive = asyncio.Event()
        self.cancel_called = False

    async def receive_execution_once(self):
        await self.release_receive.wait()
        return "RECEIVE_DONE"

    async def cancel_execution_receives(self):
        self.events.append("receive.cancel")
        self.cancel_called = True
        self.release_receive.set()


def test_lifecycle_stop_delegates_receive_cancellation_and_drains():
    async def _test():
        events = []
        bootstrap = DelegatingBootstrap(events)
        coordinator = _started_coordinator(bootstrap)
        receive_task = asyncio.create_task(coordinator.receive_execution_once())
        await asyncio.sleep(0)
        await coordinator.stop()
        assert await receive_task == "RECEIVE_DONE"
        assert bootstrap.cancel_called is True
        assert events == ["execution.close", "receive.cancel", "controller.stop"]
        assert coordinator.technical_state is None
        assert coordinator._started is False
        assert coordinator._stopping is False

    asyncio.run(_test())
