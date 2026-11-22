from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace

import pytest

from environments.live.execution.kis_futures_execution_adapter import (
    KISFuturesExecutionContext,
    KISFuturesExecutionNoticeAdapter,
    _FIELDS,
)
from environments.live.execution.kis_futures_execution_consumer import KISFuturesExecutionConsumer


def _frame() -> str:
    values = [""] * len(_FIELDS)
    values[_FIELDS.index("oder_no")] = "broker-1"
    values[_FIELDS.index("cntg_qty")] = "1"
    values[_FIELDS.index("cntg_unpr")] = "14.75"
    values[_FIELDS.index("stck_cntg_hour")] = "085412"
    values[_FIELDS.index("cntg_yn")] = "Y"
    values[_FIELDS.index("oder_qty")] = "2"
    return f"0|H0IFCNI0|{len(values)}|{'^'.join(values)}"


class _Transport:
    def __init__(self, frame: str) -> None:
        self.frame = frame
        self.recv_count = 0

    async def recv(self) -> str:
        self.recv_count += 1
        return self.frame


class _Correlation:
    def resolve(self, broker_order_id: str):
        assert broker_order_id == "broker-1"
        return SimpleNamespace(
            client_order_id="client-1",
            order_quantity=2,
            prior_filled_quantity=0,
        )


def test_kis_execution_consumer_propagates_settlement_busy_error_without_retry():
    transport = _Transport(_frame())

    def fail_settlement(_report):
        raise sqlite3.OperationalError("database is locked")

    consumer = KISFuturesExecutionConsumer(
        transport=transport,
        adapter=KISFuturesExecutionNoticeAdapter(),
        correlation_provider=_Correlation(),
        on_report=fail_settlement,
    )

    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        asyncio.run(consumer.receive_once())

    assert transport.recv_count == 1


def test_kis_h0ifcni0_report_does_not_invent_fee_or_calendar_date():
    adapter = KISFuturesExecutionNoticeAdapter()
    notice = adapter.parse(_frame())
    report = adapter.to_execution_report(
        notice,
        KISFuturesExecutionContext(
            client_order_id="client-1",
            order_quantity=2,
            prior_filled_quantity=0,
        ),
    )

    assert report.execution_id.startswith("KIS-H0IFCNI0-")
    assert report.filled_quantity == 1
    assert report.execution_price.as_tuple() == (0, (1, 4, 7, 5), -2)
    assert report.execution_timestamp is None
    assert report.fee is None
    assert report.source_freshness is not None
    assert report.source_freshness.is_complete is False



class _DisconnectingTransport:
    def __init__(self) -> None:
        self.connect_count = 0
        self.subscribe_count = 0
        self.recv_count = 0
        self.close_count = 0

    async def connect(self) -> None:
        self.connect_count += 1

    async def subscribe(self, _tr_id: str, _hts_id: str) -> None:
        self.subscribe_count += 1

    async def recv(self) -> str:
        self.recv_count += 1
        raise ConnectionError("SYNTHETIC_WS_DISCONNECTED")

    async def close(self) -> None:
        self.close_count += 1


def test_kis_execution_consumer_does_not_reconnect_after_receive_disconnect():
    transport = _DisconnectingTransport()
    consumer = KISFuturesExecutionConsumer(
        transport=transport,
        adapter=KISFuturesExecutionNoticeAdapter(),
        correlation_provider=_Correlation(),
        on_report=lambda _report: None,
    )

    async def exercise():
        await consumer.start("TEST-HTS")
        for _ in range(2):
            with pytest.raises(ConnectionError, match="SYNTHETIC_WS_DISCONNECTED"):
                await consumer.receive_once()

    asyncio.run(exercise())

    # Characterization only: receive_once propagates transport failure and does
    # not own reconnect/resubscribe/close policy. No broker or network is used.
    assert transport.connect_count == 1
    assert transport.subscribe_count == 1
    assert transport.recv_count == 2
    assert transport.close_count == 0


def test_runtime_lifecycle_propagates_settlement_error_and_drains_receive_tracking():
    from application.composition.live_runtime_lifecycle_coordinator import LiveRuntimeLifecycleCoordinator

    class Controller:
        def start(self, _config, _policy):
            return None

    class Bootstrap:
        def __init__(self):
            self.receive_calls = 0

        def startup_reconcile(self, _query):
            return object()

        async def start_execution(self, _hts_id):
            return None

        async def receive_execution_once(self):
            self.receive_calls += 1
            raise sqlite3.OperationalError("database is locked")

    coordinator = LiveRuntimeLifecycleCoordinator(controller=Controller(), bootstrap=Bootstrap())

    async def exercise():
        await coordinator.start(object(), object(), hts_id="TEST-HTS", recovery_query=object())
        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            await coordinator.receive_execution_once()
        assert coordinator._active_receives == 0
        assert coordinator._receives_drained.is_set()
        assert coordinator._bootstrap.receive_calls == 1

    asyncio.run(exercise())
