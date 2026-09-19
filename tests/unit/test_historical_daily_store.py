from decimal import Decimal

from contracts.historical_daily_store import HistoricalDailyStore
from contracts.historical_market_ohlc import HistoricalDailyOHLC
from datetime import date, datetime


def _record(symbol="A016C000"):
    return HistoricalDailyOHLC(
        symbol=symbol,
        trading_date=date(2026, 9, 18),
        open=Decimal("500"),
        high=Decimal("510"),
        low=Decimal("495"),
        close=Decimal("505"),
        observed_at=datetime(2026, 9, 18),
        source="KRX_OPEN_API:fut_bydd_trd;KRX_ISU_CD=A016C000",
    )


def test_daily_store_round_trip_preserves_decimal_and_provenance(tmp_path):
    store = HistoricalDailyStore(tmp_path / "daily.jsonl")
    record = _record()
    provenance = {
        "raw_file": "20260918_futures_daily.json",
        "raw_sha256": "abc",
        "source_endpoint": "KRX_OPEN_API:fut_bydd_trd",
        "trading_date": "2026-09-18",
        "krx_isu_cd": "A016C000",
        "master_files": "data_0900_20260919.xlsx",
        "master_sha256": "def",
        "observation_semantics": "EOD_DAILY_OHLC;observed_at_is_date_anchor_not_trade_timestamp",
    }
    store.append(record, provenance=provenance)
    loaded = store.load_records(symbol="A016C000", trading_date="2026-09-18")
    assert loaded == [(record, provenance)]


def test_daily_store_requires_provenance(tmp_path):
    store = HistoricalDailyStore(tmp_path / "daily.jsonl")
    try:
        store.append(_record(), provenance={})
    except ValueError as exc:
        assert str(exc) == "HISTORICAL_DAILY_PROVENANCE_REQUIRED"
    else:
        raise AssertionError("missing provenance must fail closed")

def test_daily_store_is_idempotent(tmp_path):
    store = HistoricalDailyStore(tmp_path / "daily.jsonl")
    record = _record()
    provenance = {"raw_file": "x", "raw_sha256": "y"}
    assert store.append_unique(record, provenance=provenance) is True
    assert store.append_unique(record, provenance=provenance) is False
    assert len(store.load_records()) == 1
