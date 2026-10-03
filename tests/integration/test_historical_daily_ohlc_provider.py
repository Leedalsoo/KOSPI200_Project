from datetime import date, datetime, timezone
from decimal import Decimal

from application.historical_daily_ohlc_provider import HistoricalMarketDailyOHLCProvider
from contracts.historical_daily_store import HistoricalDailyStore
from contracts.historical_market_ohlc import HistoricalDailyOHLC


class Calendar:
    def prev_trading_day(self, value):
        return date(2026, 9, 23)


def test_completed_daily_bar_can_be_retrieved_after_later_collection_time(tmp_path):
    path = tmp_path / "daily.jsonl"
    store = HistoricalDailyStore(path)
    record = HistoricalDailyOHLC(
        symbol="KOSPI200",
        trading_date=date(2026, 9, 23),
        open=Decimal("1137.29"),
        high=Decimal("1137.56"),
        low=Decimal("1114.46"),
        close=Decimal("1126.12"),
        observed_at=datetime(2026, 9, 28, 9, 0, tzinfo=timezone.utc),
        source="KIS.VTS:FHPUP02120000:2001",
    )
    store.append_unique(record, provenance={"provider": "KIS", "index_code": "2001"})

    provider = HistoricalMarketDailyOHLCProvider(store, Calendar())
    result = provider.get_previous_completed_day(
        symbol="KOSPI200",
        observed_at=datetime(2026, 9, 28, 7, 1, tzinfo=timezone.utc),
    )

    assert result is not None
    assert result.trading_date == date(2026, 9, 23)
    assert result.close == Decimal("1126.12")
