from datetime import date
from decimal import Decimal

import pytest

from contracts.kis_index_option_market_ws_adapter import KISIndexOptionMarketWebSocketAdapter
from contracts.track4_kis_greeks_provider import KISIndexOptionGreeksProvider
from core.option.option_master import InMemoryOptionContractMaster, KisOptionContractIdentity
from infrastructure.kis.track2_option_iv_source import KISTrack2OptionIVSource


def _master() -> InMemoryOptionContractMaster:
    master = InMemoryOptionContractMaster()
    master.register_contract_identity(KisOptionContractIdentity("201C51000", "", "2026-10-15", "CALL", Decimal("510")))
    master.register_contract_identity(KisOptionContractIdentity("201P51000", "", "2026-10-15", "PUT", Decimal("510")))
    return master


def _frame(symbol: str, iv: str, hour: str = "101530") -> str:
    values = [""] * 43
    values[0], values[1] = symbol, hour
    values[2], values[10], values[41], values[42] = "3.20", "100", "3.30", "3.10"
    values[33] = iv
    return f"0|H0IOCNT0|43|{'^'.join(values)}"


def test_h0iocnt0_iv_is_mapped_through_option_master_for_call_and_put() -> None:
    adapter = KISIndexOptionMarketWebSocketAdapter()
    source = KISTrack2OptionIVSource(_master())
    for symbol, iv in (("201C51000", "0.241"), ("201P51000", "0.257")):
        observation = adapter.adapt(_frame(symbol, iv))
        source.update_observation(observation, session_date=date(2026, 9, 17))
    assert source.get_iv(expiry="2026-10-15", option_type="CALL", strike=Decimal("510")) == Decimal("0.241")
    assert source.get_iv(expiry="2026-10-15", option_type="PUT", strike=Decimal("510")) == Decimal("0.257")


def test_unknown_identity_fails_closed() -> None:
    adapter = KISIndexOptionMarketWebSocketAdapter()
    source = KISTrack2OptionIVSource(_master())
    observation = adapter.adapt(_frame("UNKNOWN", "0.24"))
    with pytest.raises(ValueError, match="IDENTITY_UNAVAILABLE"):
        source.update_observation(observation, session_date=date(2026, 9, 17))


from infrastructure.kis.track2_option_iv_observation_sink import KISTrack2OptionIVObservationSink


def test_h0iocnt0_observation_sink_connects_adapter_to_iv_chain() -> None:
    adapter = KISIndexOptionMarketWebSocketAdapter()
    master = _master()
    source = KISTrack2OptionIVSource(master)
    sink = KISTrack2OptionIVObservationSink(option_master=master, iv_source=source, session_date=date(2026, 9, 17))
    observation = adapter.adapt(_frame("201C51000", "0.241"))
    sink.on_observation(observation)
    assert source.get_iv(expiry="202610", option_type="CALL", strike=Decimal("510")) == Decimal("0.241")
