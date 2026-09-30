from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from contracts.kis_index_futures_market_ws_adapter import KisIndexFuturesMarketObservation
from contracts.kis_index_price_source import KISIndexPriceObservation
from infrastructure.kis.track3_runtime_input_source import KISTrack3RuntimeInputSource


def _option(ts):
    identity = SimpleNamespace(
        instrument_id="CALL-350",
        symbol="CALL350",
        expiry="20261008",
        option_type="CALL",
        strike=Decimal("350"),
        contract_multiplier=Decimal("250000"),
    )
    return SimpleNamespace(
        observed_at=ts,
        collected_at=ts,
        contract=identity,
        quote=SimpleNamespace(last=Decimal("2.0")),
        source="KIS:OPTION",
    )


def test_kis_track3_source_builds_futures_index_basis_input():
    source = KISTrack3RuntimeInputSource()
    start = datetime(2026, 9, 30, 9, 0)
    for i in range(12):
        ts = start + timedelta(seconds=i)
        source.update_index(KISIndexPriceObservation("KOSPI200", "2001", Decimal("350") + Decimal(i) / 10, ts, "KIS:FHPUP02100000:2001"))
        source.update_futures(KisIndexFuturesMarketObservation("A01609", ts.strftime("%H%M%S"), Decimal("352" ) + Decimal(i) / 10 + Decimal(i) / 100, Decimal(100 + i), Decimal("352.1") + Decimal(i) / 10, Decimal("351.9") + Decimal(i) / 10, "KIS:H0IFCNT0"), session_date=start.date())
        source.update_option(_option(ts))
    source.set_common_analytics(observed_at=start + timedelta(seconds=11), active_vol=0.2, base_vol=0.1, current_regime="NORMAL")
    payload = source.get_input("KOSPI200", start + timedelta(seconds=11))
    assert payload is not None
    assert payload.source == "KIS:Track3:FuturesIndexBasis+OptionObservation"
    assert len(payload.spread_history) == 12
    assert payload.active_vol > 0
    assert payload.base_vol > 0
    assert payload.contract_multiplier == 250000.0
    assert payload.options_legs


def test_kis_track3_source_fails_closed_without_authoritative_futures():
    source = KISTrack3RuntimeInputSource()
    ts = datetime(2026, 9, 30, 9, 0)
    source.update_index(KISIndexPriceObservation("KOSPI200", "2001", Decimal("350"), ts, "KIS:FHPUP02100000:2001"))
    assert source.get_input("KOSPI200", ts) is None


def test_kis_track3_source_rejects_stale_futures_index_match():
    source = KISTrack3RuntimeInputSource()
    start = datetime(2026, 9, 30, 9, 0)
    for i in range(12):
        ts = start + timedelta(seconds=i)
        source.update_index(KISIndexPriceObservation("KOSPI200", "2001", Decimal("350") + Decimal(i) / 10, ts + timedelta(seconds=10), "KIS:FHPUP02100000:2001"))
        source.update_futures(KisIndexFuturesMarketObservation("A01609", ts.strftime("%H%M%S"), Decimal("352" ) + Decimal(i) / 10 + Decimal(i) / 100, Decimal(100 + i), Decimal("352.1") + Decimal(i) / 10, Decimal("351.9") + Decimal(i) / 10, "KIS:H0IFCNT0"), session_date=start.date())
        source.update_option(_option(ts))
    assert source.get_input("KOSPI200", start + timedelta(seconds=11)) is None