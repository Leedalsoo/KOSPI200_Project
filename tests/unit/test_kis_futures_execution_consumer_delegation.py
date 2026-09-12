"""Unit tests for KISFuturesExecutionConsumer and Live Execution delegation path.

NOTE: All test fixtures herein are synthetic logic-verification fixtures.
Passing these tests proves adapter/delegation correctness against synthetic data contracts,
NOT successful external connection to the live KIS system.
"""
from __future__ import annotations

import asyncio
from typing import Any
import pytest

from application.bootstrap import LiveRuntimeBootstrap
from application.composition.live_execution_runtime_composition_factory import (
    LiveExecutionRuntimeComposition,
)
from application.composition.live_runtime_lifecycle_coordinator import (
    LiveRuntimeLifecycleCoordinator,
)
from core.oms.oms_fsm import ExecutionCorrelation
from environments.live.execution.kis_futures_execution_adapter import (
    KISFuturesExecutionNoticeAdapter,
)
from environments.live.execution.kis_futures_execution_consumer import (
    KISFuturesExecutionConsumer,
)
from environments.live.execution.kis_futures_execution_correlation_provider import (
    KISFuturesExecutionCorrelationProvider,
)


class MockTransport:
    def __init__(self) -> None:
        self.events: list[tuple[str, ...]] = []
        self.closed = False
        self.cancelled = False

    async def connect(self) -> None:
        self.events.append(("connect",))

    async def subscribe(self, tr_id: str, tr_key: str) -> None:
        self.events.append(("subscribe", tr_id, tr_key))

    async def recv(self) -> str:
        self.events.append(("recv",))
        # Valid format: parts >= 4, parts[1] == "H0IFCNI0"
        # plain format with ^ separator: broker_order_id is parts[2] in notice ("B123")
        values = ["C", "A", "B123", "O", "02", "00", "00", "K200", "2", "350.0", "101010", "N", "Y", "Y", "01", "5", "N", "KOSPI", "00", "1", "1", "350.0"]
        plain = "^".join(values)
        return f"1|H0IFCNI0|22|{plain}"

    async def cancel_recv(self) -> None:
        self.cancelled = True
        self.events.append(("cancel_recv",))

    async def close(self) -> None:
        self.closed = True
        self.events.append(("close",))


class MockTransportNoCancel:
    def __init__(self) -> None:
        self.events: list[tuple[str, ...]] = []
        self.closed = False

    async def connect(self) -> None:
        self.events.append(("connect",))

    async def subscribe(self, tr_id: str, tr_key: str) -> None:
        self.events.append(("subscribe", tr_id, tr_key))

    async def recv(self) -> str:
        self.events.append(("recv",))
        return "1|H0IFCNI0|22|C^A^B123^O^02^00^00^K200^2^350.0^101010^N^Y^Y^01^5^N^KOSPI^00^1^1^350.0"

    async def close(self) -> None:
        self.closed = True
        self.events.append(("close",))


class MockAsyncReportHandler:
    def __init__(self) -> None:
        self.reports: list[Any] = []

    async def __call__(self, report: Any) -> None:
        await asyncio.sleep(0.001)
        self.reports.append(report)


class FakeOrderStateMachine:
    def resolve_execution_correlation(self, broker_order_id: str) -> ExecutionCorrelation:
        if broker_order_id == "B123":
            return ExecutionCorrelation(
                client_order_id="C1",
                broker_order_id="B123",
                order_quantity=5,
                prior_filled_quantity=0,
            )
        raise ValueError(f"Unknown broker order id: {broker_order_id}")


class FakeSettlement:
    def __init__(self, osm: Any) -> None:
        self.order_state_machine = osm


class FakeOrderRouter:
    def __init__(self, osm: Any) -> None:
        self._order_state_machine = osm


def _build_consumer(transport: Any, on_report: Any) -> KISFuturesExecutionConsumer:
    osm = FakeOrderStateMachine()
    provider = KISFuturesExecutionCorrelationProvider(osm)  # type: ignore[arg-type]
    return KISFuturesExecutionConsumer(
        transport=transport,
        adapter=KISFuturesExecutionNoticeAdapter(),
        correlation_provider=provider,
        on_report=on_report,
    )


def test_consumer_start_connects_and_subscribes():
    async def _test():
        transport = MockTransport()
        consumer = _build_consumer(transport, lambda r: None)

        await consumer.start("HTS_USER_01")
        assert transport.events == [
            ("connect",),
            ("subscribe", "H0IFCNI0", "HTS_USER_01"),
        ]

    asyncio.run(_test())


def test_consumer_start_fails_on_empty_hts_id():
    async def _test():
        transport = MockTransport()
        consumer = _build_consumer(transport, lambda r: None)

        with pytest.raises(ValueError, match="HTS ID is required"):
            await consumer.start("   ")

    asyncio.run(_test())


def test_consumer_receive_once_awaits_report_handler_and_returns_report():
    async def _test():
        transport = MockTransport()
        handler = MockAsyncReportHandler()
        consumer = _build_consumer(transport, handler)

        report = await consumer.receive_once()
        assert report.client_order_id == "C1"
        assert report.broker_order_id == "B123"
        assert report.filled_quantity == 2
        assert len(handler.reports) == 1
        assert handler.reports[0] == report

    asyncio.run(_test())


def test_consumer_cancel_receive_uses_cancel_recv_if_available():
    async def _test():
        transport = MockTransport()
        consumer = _build_consumer(transport, lambda r: None)

        await consumer.cancel_receive()
        assert transport.cancelled is True
        assert ("cancel_recv",) in transport.events

    asyncio.run(_test())


def test_consumer_cancel_receive_falls_back_to_close_if_no_cancel_recv():
    async def _test():
        transport = MockTransportNoCancel()
        consumer = _build_consumer(transport, lambda r: None)

        await consumer.cancel_receive()
        assert transport.closed is True
        assert ("close",) in transport.events

    asyncio.run(_test())


def test_consumer_close_awaits_transport_close():
    async def _test():
        transport = MockTransport()
        consumer = _build_consumer(transport, lambda r: None)

        await consumer.close()
        assert transport.closed is True
        assert ("close",) in transport.events

    asyncio.run(_test())


def test_live_execution_runtime_composition_delegation():
    async def _test():
        transport = MockTransport()
        consumer = _build_consumer(transport, lambda r: None)

        composition = LiveExecutionRuntimeComposition(
            execution_consumer=consumer,
            settlement=None,  # type: ignore[arg-type]
            broker=None,  # type: ignore[arg-type]
        )

        # 1. start_execution
        await composition.start_execution("HTS_99")
        assert ("connect",) in transport.events
        assert ("subscribe", "H0IFCNI0", "HTS_99") in transport.events

        # 2. cancel_receive
        await composition.cancel_receive()
        assert transport.cancelled is True

        # 3. close_execution
        await composition.close_execution()
        assert transport.closed is True

    asyncio.run(_test())


def test_live_runtime_bootstrap_delegation():
    async def _test():
        transport = MockTransport()
        consumer = _build_consumer(transport, lambda r: None)
        osm = FakeOrderStateMachine()

        composition = LiveExecutionRuntimeComposition(
            execution_consumer=consumer,
            settlement=FakeSettlement(osm),  # type: ignore[arg-type]
            broker=None,  # type: ignore[arg-type]
        )

        bootstrap = LiveRuntimeBootstrap(
            execution=composition,
            order_router=FakeOrderRouter(osm),  # type: ignore[arg-type]
            runtime_transport=None,
        )

        # 1. start_execution
        await bootstrap.start_execution("HTS_BOOT")
        assert ("connect",) in transport.events
        assert ("subscribe", "H0IFCNI0", "HTS_BOOT") in transport.events

        # 2. receive_execution_once
        report = await bootstrap.receive_execution_once()
        assert report.client_order_id == "C1"

        # 3. cancel_execution_receives
        await bootstrap.cancel_execution_receives()
        assert transport.cancelled is True

        # 4. close_execution
        await bootstrap.close_execution()
        assert transport.closed is True

    asyncio.run(_test())


def test_live_runtime_bootstrap_cancel_receive_required_error():
    async def _test():
        # If execution composition has no cancel_receive
        osm = FakeOrderStateMachine()
        dummy_execution = type("DummyExecution", (), {"settlement": FakeSettlement(osm)})()
        bootstrap = LiveRuntimeBootstrap(
            execution=dummy_execution,  # type: ignore[arg-type]
            order_router=FakeOrderRouter(osm),  # type: ignore[arg-type]
            runtime_transport=None,
        )

        with pytest.raises(RuntimeError, match="LIVE_RUNTIME_EXECUTION_CANCEL_RECEIVE_REQUIRED"):
            await bootstrap.cancel_execution_receives()

    asyncio.run(_test())


def test_lifecycle_coordinator_to_transport_full_delegation_chain():
    async def _test():
        transport = MockTransport()
        handler = MockAsyncReportHandler()
        consumer = _build_consumer(transport, handler)
        osm = FakeOrderStateMachine()

        composition = LiveExecutionRuntimeComposition(
            execution_consumer=consumer,
            settlement=FakeSettlement(osm),  # type: ignore[arg-type]
            broker=None,  # type: ignore[arg-type]
        )

        class FakeRecoveryService:
            def recover(self, query: Any) -> tuple[str]:
                return ("RECOVERED",)

        bootstrap = LiveRuntimeBootstrap(
            execution=composition,
            order_router=FakeOrderRouter(osm),  # type: ignore[arg-type]
            runtime_transport=None,
            recovery_service=FakeRecoveryService(),
        )

        class FakeController:
            def __init__(self) -> None:
                self.started = False
                self.stopped = False

            def start(self, config: Any, policy: Any) -> None:
                self.started = True

            def stop(self) -> None:
                self.stopped = True

        controller = FakeController()
        coordinator = LiveRuntimeLifecycleCoordinator(
            controller=controller,
            bootstrap=bootstrap,
        )

        # 1. start: controller.start -> startup_reconcile -> bootstrap.start_execution -> consumer.start -> transport.connect & subscribe
        result = await coordinator.start("CONFIG", "POLICY", hts_id="HTS_FULL", recovery_query="QUERY")
        assert result == ("RECOVERED",)
        assert controller.started is True
        assert transport.events[:2] == [
            ("connect",),
            ("subscribe", "H0IFCNI0", "HTS_FULL"),
        ]

        # 2. receive_execution_once: coordinator -> bootstrap -> composition -> consumer -> transport.recv -> parse -> report
        report = await coordinator.receive_execution_once()
        assert report.client_order_id == "C1"
        assert ("recv",) in transport.events

        # 3. stop: coordinator -> bootstrap.close_execution -> composition.close_execution -> consumer.close -> transport.close -> controller.stop
        await coordinator.stop()
        assert transport.closed is True
        assert controller.stopped is True

    asyncio.run(_test())
