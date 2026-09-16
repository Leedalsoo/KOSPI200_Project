from decimal import Decimal

from environments.virtual.market.canonical import ReferenceCanonicalMarketTick
from environments.virtual.market.historical_market_store import HistoricalMarketStore
from environments.virtual.market.simulator_runtime import VirtualMarketSimulatorRuntime
from environments.virtual.broker.virtual_broker import VirtualBroker


class RecordingHandler:
    def __init__(self):
        self.ticks = []

    def __call__(self, tick):
        self.ticks.append(tick)


def test_historical_replay_publishes_through_virtual_exchange(tmp_path):
    store = HistoricalMarketStore(tmp_path / "events.jsonl")
    store.append(
        ReferenceCanonicalMarketTick(
            timestamp="2026-09-16T10:00:00.123",
            underlying_price=512.5,
            strike_price=510.0,
            option_type="CALL",
            contract_multiplier=250000.0,
            bid_price=3.20,
            ask_price=3.30,
            last_price=3.25,
            volume=120,
            seq_id=7,
            expiry="202610",
            symbol="201S11305",
        ),
        source="KIS:H0IOCNT0",
    )
    runtime = VirtualMarketSimulatorRuntime()
    handler = RecordingHandler()
    runtime.subscribe(handler)
    runtime.load_historical_store(store, source="KIS:H0IOCNT0")

    tick = runtime.replay_next()

    assert tick is not None
    assert tick.seq_id == 7
    assert runtime.last_tick == tick
    assert handler.ticks == [tick]
    assert runtime.futures_price == 512.5 + runtime.config.futures_basis_points


def test_replayed_market_data_reaches_virtual_broker_and_api_boundary(tmp_path):
    store = HistoricalMarketStore(tmp_path / "events.jsonl")
    tick = ReferenceCanonicalMarketTick(
        timestamp="2026-09-16T10:00:00.123",
        underlying_price=512.5,
        strike_price=510.0,
        option_type="CALL",
        contract_multiplier=250000.0,
        bid_price=3.20,
        ask_price=3.30,
        last_price=3.25,
        volume=120,
        seq_id=1,
        expiry="202610",
        symbol="201S11305",
    )
    store.append(tick, source="KIS:H0IOCNT0")

    runtime = VirtualMarketSimulatorRuntime()
    received = []
    broker = VirtualBroker(
        execution_engine=None,
        market_data_handler=lambda market_tick: received.append(market_tick),
    )
    runtime.subscribe(lambda market_tick: broker.process_market_data(
        market_tick, option_quotes=runtime.option_quotes
    ))
    runtime.load_historical_store(store, source="KIS:H0IOCNT0")

    replayed = runtime.replay_next()
    snapshot = broker.get_market_snapshot()
    quote = broker.get_option_quote(option_type="CALL", strike=510.0, expiry="202610")

    assert replayed == tick
    assert received == [tick]
    assert snapshot["tick"] == tick
    assert quote == {
        "bid": 3.20,
        "ask": 3.30,
        "last": 3.25,
        "timestamp": tick.timestamp,
        "contract_multiplier": 250000.0,
    }
