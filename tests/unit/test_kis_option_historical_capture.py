from decimal import Decimal

import pytest

from contracts.kis_index_option_market_ws_adapter import KisIndexOptionMarketObservation
from core.option.option_master import KisOptionContractIdentity
from infrastructure.kis.option_historical_capture import KISOptionHistoricalCapture
from infrastructure.kis.option_historical_recorder import KISOptionHistoricalRecorder
from infrastructure.kis.underlying_market_state import KISUnderlyingMarketState
from environments.virtual.market.historical_market_store import HistoricalMarketStore
from contracts.kis_index_futures_market_ws_adapter import KisIndexFuturesMarketObservation


class FakeTransport:
    def __init__(self) -> None:
        self.connected = False
        self.subscriptions: list[tuple[str, str]] = []
        self.frames: list[str] = []
        self.closed = False

    async def connect(self) -> None:
        self.connected = True

    async def subscribe(self, tr_id: str, symbol: str) -> None:
        self.subscriptions.append((tr_id, symbol))

    async def recv(self) -> str:
        return self.frames.pop(0)

    async def close(self) -> None:
        self.closed = True


class FakeMaster:
    def get_contract_identity(self, shrn_iscd: str):
        if shrn_iscd != "201S11305":
            return None
        return KisOptionContractIdentity("201S11305", "K", "2026-10-01", "CALL", Decimal("510"), "5")


def _trade_frame() -> str:
    values = [""] * 43
    values[0] = "201S11305"
    values[1] = "101530123"
    values[2] = "3.25"
    values[10] = "120"
    values[41] = "3.30"
    values[42] = "3.20"
    return f"0|H0IOCNT0|{len(values)}|{'^'.join(values)}"


def test_capture_connects_trade_and_quote_subscriptions(tmp_path) -> None:
    store = HistoricalMarketStore(tmp_path / "events.jsonl")
    recorder = KISOptionHistoricalRecorder(store, FakeMaster())
    transport = FakeTransport()
    capture = KISOptionHistoricalCapture(transport, recorder)

    capture.start_session("2026-09-16")
    import asyncio
    asyncio.run(capture.connect_and_subscribe("201S11305"))

    assert transport.connected is True
    assert transport.subscriptions == [
        ("H0IOCNT0", "201S11305"),
        ("H0IOASP0", "201S11305"),
    ]


def test_capture_assigns_monotonic_session_sequence_and_records(tmp_path) -> None:
    store = HistoricalMarketStore(tmp_path / "events.jsonl")
    recorder = KISOptionHistoricalRecorder(store, FakeMaster())
    transport = FakeTransport()
    capture = KISOptionHistoricalCapture(transport, recorder)
    capture.start_session("2026-09-16")
    transport.frames = [_trade_frame(), _trade_frame()]

    import asyncio
    asyncio.run(capture.capture_one())
    asyncio.run(capture.capture_one())

    assert capture.sequence == 2
    ticks = store.load_ticks(source="KIS:H0IOCNT0")
    assert [tick.seq_id for tick in ticks] == [1, 2]


def test_capture_requires_session_before_observing() -> None:
    store = HistoricalMarketStore("unused.jsonl")
    recorder = KISOptionHistoricalRecorder(store, FakeMaster())
    capture = KISOptionHistoricalCapture(FakeTransport(), recorder)

    with pytest.raises(ValueError, match="SESSION_DATE_REQUIRED"):
        capture.observe(_trade_frame())


def test_capture_attaches_latest_authoritative_underlying_price(tmp_path) -> None:
    store = HistoricalMarketStore(tmp_path / "events.jsonl")
    recorder = KISOptionHistoricalRecorder(store, FakeMaster())
    underlying = KISUnderlyingMarketState()
    underlying.update(KisIndexFuturesMarketObservation(
        shrn_iscd="101V6000", observed_hour="101529",
        price=Decimal("512.50"), volume=Decimal("10"),
        ask_price=Decimal("512.55"), bid_price=Decimal("512.45"),
        source="KIS:H0IFCNT0",
    ))
    capture = KISOptionHistoricalCapture(
        FakeTransport(), recorder, underlying_state=underlying
    )
    capture.start_session("2026-09-16")
    capture.observe(_trade_frame())

    tick = store.load_ticks(source="KIS:H0IOCNT0")[0]
    assert tick.underlying_price == 512.50
