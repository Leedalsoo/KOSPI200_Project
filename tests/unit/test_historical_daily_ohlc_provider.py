from datetime import date, datetime
from decimal import Decimal

from contracts.historical_daily_store import HistoricalDailyStore
from contracts.historical_market_ohlc import HistoricalDailyOHLC
from application.historical_daily_ohlc_provider import HistoricalMarketDailyOHLCProvider


class Calendar:
    def prev_trading_day(self, value):
        return date(2026, 9, 18)


def test_daily_store_backed_provider_reads_completed_ohlc_and_source(tmp_path):
    store = HistoricalDailyStore(tmp_path / "daily.jsonl")
    record = HistoricalDailyOHLC(
        symbol="B056A960",
        trading_date=date(2026, 9, 18),
        open=Decimal("12.0"),
        high=Decimal("15.0"),
        low=Decimal("11.0"),
        close=Decimal("14.0"),
        observed_at=datetime(2026, 9, 18),
        source="KRX_OPEN_API:opt_bydd_trd;KRX_ISU_CD=B056A960",
    )
    store.append(record, provenance={"raw_sha256": "abc", "master_sha256": "def"})
    provider = HistoricalMarketDailyOHLCProvider(store, Calendar())
    result = provider.get_previous_completed_day(
        symbol="B056A960", observed_at=datetime(2026, 9, 19, 9, 0)
    )
    assert result == record
