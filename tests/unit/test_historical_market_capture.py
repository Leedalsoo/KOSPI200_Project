from decimal import Decimal
import asyncio

from contracts.kis_index_futures_market_ws_adapter import KisIndexFuturesMarketObservation
from infrastructure.kis.historical_market_capture import KISHistoricalMarketCapture
from infrastructure.kis.option_historical_capture import KISOptionHistoricalCapture
from infrastructure.kis.option_historical_recorder import KISOptionHistoricalRecorder
from infrastructure.kis.underlying_market_state import KISUnderlyingMarketState
from environments.virtual.market.historical_market_store import HistoricalMarketStore
from core.option.option_master import KisOptionContractIdentity


class FakeTransport:
    def __init__(self, frames=None):
        self.frames = list(frames or [])
        self.connected = False
        self.subscriptions = []
        self.closed = False

    async def connect(self):
        self.connected = True

    async def subscribe(self, tr_id, symbol):
        self.subscriptions.append((tr_id, symbol))

    async def recv(self):
        return self.frames.pop(0)

    async def close(self):
        self.closed = True


class FakeMaster:
    def get_contract_identity(self, shrn_iscd):
        if shrn_iscd != "201S11305":
            return None
        return KisOptionContractIdentity("201S11305", "K", "2026-10-01", "CALL", Decimal("510"), "5")


def option_trade_frame():
    values = [""] * 43
    values[0], values[1], values[2], values[10] = "201S11305", "101530123", "3.25", "120"
    values[41], values[42] = "3.30", "3.20"
    return f"0|H0IOCNT0|{len(values)}|{'^'.join(values)}"


def futures_trade_frame():
    values = [""] * 37
    values[0], values[1], values[5], values[10] = "101V6000", "101529", "512.50", "10"
    values[35], values[36] = "512.55", "512.45"
    return f"0|H0IFCNT0|{len(values)}|{'^'.join(values)}"


def test_composition_connects_both_streams_and_preserves_symbol_boundary(tmp_path):
    option_transport = FakeTransport()
    underlying_transport = FakeTransport()
    store = HistoricalMarketStore(tmp_path / "events.jsonl")
    state = KISUnderlyingMarketState()
    recorder = KISOptionHistoricalRecorder(store, FakeMaster())
    option_capture = KISOptionHistoricalCapture(option_transport, recorder, underlying_state=state)
    composition = KISHistoricalMarketCapture(option_capture, underlying_transport, underlying_state=state)

    composition.start_session("2026-09-16", option_symbol="201S11305", underlying_symbol="101V6000")
    asyncio.run(composition.connect())

    assert option_transport.subscriptions == [("H0IOCNT0", "201S11305"), ("H0IOASP0", "201S11305")]
    assert underlying_transport.subscriptions == [("H0IFCNT0", "101V6000"), ("H0IFASP0", "101V6000")]


def test_underlying_event_updates_state_before_option_event(tmp_path):
    option_transport = FakeTransport([option_trade_frame()])
    underlying_transport = FakeTransport([futures_trade_frame()])
    store = HistoricalMarketStore(tmp_path / "events.jsonl")
    state = KISUnderlyingMarketState()
    recorder = KISOptionHistoricalRecorder(store, FakeMaster())
    option_capture = KISOptionHistoricalCapture(option_transport, recorder, underlying_state=state)
    composition = KISHistoricalMarketCapture(option_capture, underlying_transport, underlying_state=state)
    composition.start_session("2026-09-16", option_symbol="201S11305", underlying_symbol="101V6000")

    underlying = asyncio.run(composition.capture_underlying_once())
    option = asyncio.run(composition.capture_option_once())

    assert underlying.shrn_iscd == "101V6000"
    assert composition.underlying_sequence == 1
    assert state.state is not None
    assert state.state.price == Decimal("512.50")
    tick = store.load_ticks(source="KIS:H0IOCNT0")[0]
    assert tick.underlying_price == 512.50
    assert tick.underlying_symbol == "101V6000"
    assert tick.underlying_observed_hour == "101529"
    assert tick.underlying_source == "KIS:H0IFCNT0"
    assert tick.option_observed_hour == "101530123"
    assert tick.option_source == "KIS:H0IOCNT0"
    assert tick.underlying_sequence == 1
    assert option.shrn_iscd == "201S11305"


def test_composition_fails_closed_without_session():
    state = KISUnderlyingMarketState()
    option_capture = KISOptionHistoricalCapture(FakeTransport(), KISOptionHistoricalRecorder(HistoricalMarketStore("unused.jsonl"), FakeMaster()))
    composition = KISHistoricalMarketCapture(option_capture, FakeTransport(), underlying_state=state)
    try:
        composition.start_session("2026-09-16", option_symbol="", underlying_symbol="101V6000")
    except ValueError as exc:
        assert "OPTION_SYMBOL_REQUIRED" in str(exc)
    else:
        raise AssertionError("expected fail-closed validation")


def test_option_linkage_rejects_stale_underlying(tmp_path):
    option = option_trade_frame().replace("101530123", "101535123")
    option_transport = FakeTransport([option])
    underlying_transport = FakeTransport([futures_trade_frame()])
    state = KISUnderlyingMarketState()
    store = HistoricalMarketStore(tmp_path / "events.jsonl")
    recorder = KISOptionHistoricalRecorder(store, FakeMaster())
    capture = KISOptionHistoricalCapture(option_transport, recorder, underlying_state=state)
    composition = KISHistoricalMarketCapture(
        capture, underlying_transport, underlying_state=state,
        max_underlying_age_seconds=2.0,
    )
    composition.start_session("2026-09-16", option_symbol="201S11305", underlying_symbol="101V6000")
    asyncio.run(composition.capture_underlying_once())
    try:
        asyncio.run(composition.capture_option_once())
    except ValueError as exc:
        assert "AUTHORITATIVE_UNDERLYING_STALE" in str(exc)
    else:
        raise AssertionError("expected stale underlying rejection")


def test_option_linkage_accepts_underlying_within_age_window(tmp_path):
    option = option_trade_frame().replace("101530123", "101530900")
    option_transport = FakeTransport([option])
    underlying_transport = FakeTransport([futures_trade_frame()])
    state = KISUnderlyingMarketState()
    store = HistoricalMarketStore(tmp_path / "events.jsonl")
    recorder = KISOptionHistoricalRecorder(store, FakeMaster())
    capture = KISOptionHistoricalCapture(option_transport, recorder, underlying_state=state)
    composition = KISHistoricalMarketCapture(
        capture, underlying_transport, underlying_state=state,
        max_underlying_age_seconds=2.0,
    )
    composition.start_session("2026-09-16", option_symbol="201S11305", underlying_symbol="101V6000")
    asyncio.run(composition.capture_underlying_once())
    result = asyncio.run(composition.capture_option_once())
    assert result.shrn_iscd == "201S11305"
