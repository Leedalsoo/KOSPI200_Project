from datetime import date, datetime
from decimal import Decimal

import pytest

from contracts.kis_index_option_market_ws_adapter import KISIndexOptionMarketWebSocketAdapter
from core.option.option_master import InMemoryOptionContractMaster, KisOptionContractIdentity
from infrastructure.kis.track2_option_iv_observation_sink import KISTrack2OptionIVObservationSink
from infrastructure.kis.track2_option_iv_source import KISTrack2OptionIVSource
from infrastructure.kis.track9_iv_observation_history_store import KISTrack9IVObservationHistoryStore


def _master() -> InMemoryOptionContractMaster:
    master = InMemoryOptionContractMaster()
    master.register_contract_identity(KisOptionContractIdentity("201C51000", "", "2026-10-15", "CALL", Decimal("510")))
    return master


def _frame(iv: str, hour: str) -> str:
    values = [""] * 43
    values[0], values[1], values[2], values[10] = "201C51000", hour, "3.20", "100"
    values[41], values[42], values[33] = "3.30", "3.10", iv
    return f"0|H0IOCNT0|43|{'^'.join(values)}"


def test_h0iocnt0_sink_appends_source_owned_history(tmp_path) -> None:
    adapter = KISIndexOptionMarketWebSocketAdapter()
    master = _master()
    source = KISTrack2OptionIVSource(master)
    store = KISTrack9IVObservationHistoryStore(tmp_path / "iv.jsonl")
    sink = KISTrack2OptionIVObservationSink(
        option_master=master, iv_source=source, session_date=date(2026, 9, 18), history_source=store
    )
    sink.on_observation(adapter.adapt(_frame("0.241", "101530")))
    sink.on_observation(adapter.adapt(_frame("0.247", "101531")))
    records = store.query(
        symbol="201C51000", expiry="2026-10-15", option_type="CALL", strike=Decimal("510"),
        start=datetime(2026, 9, 18, 10, 15), end=datetime(2026, 9, 18, 10, 16)
    )
    assert [x.implied_volatility for x in records] == [Decimal("0.241"), Decimal("0.247")]
    assert all(x.source == "KIS:H0IOCNT0" for x in records)


def test_history_duplicate_is_idempotent_and_conflict_fails(tmp_path) -> None:
    store = KISTrack9IVObservationHistoryStore(tmp_path / "iv.jsonl")
    from contracts.track9_iv_timeseries import Track9IVObservation
    item = Track9IVObservation("S", "E", "CALL", Decimal("510"), Decimal("0.2"), datetime(2026, 9, 18, 1), "KIS:H0IOCNT0")
    store.append(item)
    store.append(item)
    assert len(store.query(symbol="S", expiry="E", option_type="CALL", strike=Decimal("510"), start=datetime(2026, 9, 18), end=datetime(2026, 9, 19))) == 1
    conflict = Track9IVObservation("S", "E", "CALL", Decimal("510"), Decimal("0.3"), item.observed_at, item.source)
    with pytest.raises(ValueError, match="DUPLICATE_CONFLICT"):
        store.append(conflict)
