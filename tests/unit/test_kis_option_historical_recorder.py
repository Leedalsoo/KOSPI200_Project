from decimal import Decimal

import pytest

from contracts.kis_index_option_market_ws_adapter import KisIndexOptionMarketObservation
from core.option.option_master import KisOptionContractIdentity
from environments.virtual.market.historical_market_store import HistoricalMarketStore
from infrastructure.kis.option_historical_recorder import KISOptionHistoricalRecorder


class _Master:
    def __init__(self, identity):
        self.identity = identity

    def get_contract_identity(self, shrn_iscd):
        if self.identity is None:
            return None
        return self.identity if shrn_iscd == self.identity.shrn_iscd else None


def _observation():
    return KisIndexOptionMarketObservation(
        shrn_iscd="201S11305",
        observed_hour="101530123",
        last_price=Decimal("3.25"),
        ask_price=Decimal("3.30"),
        bid_price=Decimal("3.20"),
        volume=Decimal("120"),
        source="KIS:H0IOCNT0",
    )


def test_records_kis_observation_with_authoritative_identity(tmp_path):
    identity = KisOptionContractIdentity(
        shrn_iscd="201S11305",
        stnd_iscd="STD11305",
        expiry="202610",
        option_type="CALL",
        strike=Decimal("510"),
        info_type="5",
    )
    store = HistoricalMarketStore(tmp_path / "market.jsonl")
    recorder = KISOptionHistoricalRecorder(store, _Master(identity))

    tick = recorder.record(_observation(), session_date="2026-09-16", seq_id=7)

    assert tick.timestamp == "2026-09-16T10:15:30.123"
    assert tick.expiry == "202610"
    assert tick.strike_price == 510.0
    assert tick.option_type == "CALL"
    assert store.load_ticks(source="KIS_INDEX_OPTION_WS")[0] == tick


def test_requires_authoritative_identity(tmp_path):
    store = HistoricalMarketStore(tmp_path / "market.jsonl")
    recorder = KISOptionHistoricalRecorder(store, _Master(None))
    with pytest.raises(ValueError, match="AUTHORITATIVE_OPTION_IDENTITY_REQUIRED"):
        recorder.record(_observation(), session_date="2026-09-16", seq_id=1)
