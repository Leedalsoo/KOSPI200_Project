from datetime import datetime

from environments.virtual.market.canonical import ReferenceCanonicalMarketTick
from environments.virtual.market.historical_market_store import HistoricalMarketStore
from environments.virtual.market.replay_engine import HistoricalReplayEngine


def tick(seq: int) -> ReferenceCanonicalMarketTick:
    return ReferenceCanonicalMarketTick(
        timestamp=datetime(2026, 1, 2, 9, 0, seq).isoformat(),
        underlying_price=350.0 + seq,
        strike_price=350.0,
        option_type="CALL",
        bid_price=1.0 + seq,
        ask_price=1.1 + seq,
        last_price=1.05 + seq,
        volume=100 + seq,
        seq_id=seq,
        expiry="202609",
        symbol="KOSPI200",
    )


def test_historical_market_store_round_trip(tmp_path):
    store = HistoricalMarketStore(tmp_path / "market.jsonl")
    source_ticks = [tick(1), tick(2)]
    assert store.append_many(source_ticks, source="KRX_CAPTURE") == 2
    assert store.load_ticks(source="KRX_CAPTURE") == source_ticks
    assert store.load_ticks(source="SYNTHETIC") == []


def test_historical_replay_can_load_persisted_source(tmp_path):
    store = HistoricalMarketStore(tmp_path / "market.jsonl")
    store.append_many([tick(1), tick(2)], source="KRX_CAPTURE")
    store.append(tick(9), source="SYNTHETIC")
    replay = HistoricalReplayEngine.from_store(store, source="KRX_CAPTURE")
    assert replay.next_tick().seq_id == 1
    assert replay.next_tick().seq_id == 2
    assert replay.next_tick() is None


def test_historical_market_store_requires_explicit_source(tmp_path):
    store = HistoricalMarketStore(tmp_path / "market.jsonl")
    try:
        store.append(tick(1), source="")
    except ValueError as exc:
        assert str(exc) == "MARKET_DATA_SOURCE_REQUIRED"
    else:
        raise AssertionError("missing source must fail closed")
