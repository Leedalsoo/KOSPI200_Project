from datetime import date, datetime
from decimal import Decimal

from contracts.historical_daily_store import HistoricalDailyStore
from contracts.historical_market_ohlc import HistoricalDailyOHLC
from application.composition.track7_classic_pivot_provider import Track7ClassicPivotProvider
from application.historical_daily_ohlc_provider import HistoricalMarketDailyOHLCProvider


class Calendar:
    def prev_trading_day(self, value):
        return date(2026, 9, 17)


def _store(tmp_path):
    store = HistoricalDailyStore(tmp_path / "daily.jsonl")
    record = HistoricalDailyOHLC(
        symbol="B056A960",
        trading_date=date(2026, 9, 17),
        open=Decimal("340"), high=Decimal("360"), low=Decimal("340"), close=Decimal("345"),
        observed_at=datetime(2026, 9, 17), source="TEST.HISTORICAL.KRX",
    )
    store.append(record, provenance={"raw_sha256": "abc", "master_sha256": "def"})
    return store


def test_previous_completed_day_ohlc_reads_daily_store(tmp_path):
    provider = HistoricalMarketDailyOHLCProvider(_store(tmp_path), Calendar())
    result = provider.get_previous_completed_day(symbol="B056A960", observed_at=datetime(2026, 9, 18, 9, 0))
    assert result is not None
    assert (result.open, result.high, result.low, result.close) == (Decimal("340"), Decimal("360"), Decimal("340"), Decimal("345"))
    assert result.source == "TEST.HISTORICAL.KRX"


def test_classic_pivot_selects_nearest_support_and_resistance(tmp_path):
    provider = Track7ClassicPivotProvider(HistoricalMarketDailyOHLCProvider(_store(tmp_path), Calendar()))
    result = provider.get_support_resistance(symbol="B056A960", observed_at=datetime(2026, 9, 18, 9, 0), current_price=Decimal("350"))
    assert result is not None
    assert result.support == Decimal("348.35")
    assert result.resistance == Decimal("356.65")
    assert result.definition == "CLASSIC_FLOOR_PIVOT_PREVIOUS_COMPLETED_DAILY_OHLC"
    assert result.window == "PREVIOUS_COMPLETED_TRADING_DAY_1_DAILY_BAR"
    assert result.calculation_version == "TRACK7-CLASSIC-PIVOT-v1"


def test_classic_pivot_fails_closed_without_previous_day_data(tmp_path):
    provider = Track7ClassicPivotProvider(HistoricalMarketDailyOHLCProvider(HistoricalDailyStore(tmp_path / "empty.jsonl"), Calendar()))
    assert provider.get_support_resistance(symbol="B056A960", observed_at=datetime(2026, 9, 18, 9, 0), current_price=Decimal("350")) is None
