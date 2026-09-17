from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

from application.composition.track7_classic_pivot_provider import Track7ClassicPivotProvider
from application.historical_daily_ohlc_provider import HistoricalMarketDailyOHLCProvider
from environments.virtual.market.historical_market_store import HistoricalMarketStore
from environments.virtual.market.canonical import ReferenceCanonicalMarketTick


class Calendar:
    def prev_trading_day(self, value):
        return date(2026, 9, 17)


def _store(tmp_path):
    store = HistoricalMarketStore(tmp_path / "market.jsonl")
    for seq, hour, price in ((1, 9, 340), (2, 10, 350), (3, 11, 360), (4, 15, 345)):
        store.append(
            ReferenceCanonicalMarketTick(
                timestamp=f"2026-09-17T{hour:02d}:00:00",
                underlying_price=price, underlying_symbol="KOSPI200",
                symbol="KOSPI200", seq_id=seq,
            ),
            source="TEST.HISTORICAL.KRX",
        )
    return store


def test_previous_completed_day_ohlc_is_aggregated_from_historical_events(tmp_path):
    provider = HistoricalMarketDailyOHLCProvider(_store(tmp_path), Calendar())
    result = provider.get_previous_completed_day(
        symbol="KOSPI200", observed_at=datetime(2026, 9, 18, 9, 0)
    )
    assert result is not None
    assert (result.open, result.high, result.low, result.close) == (
        Decimal("340"), Decimal("360"), Decimal("340"), Decimal("345")
    )
    assert result.source == "TEST.HISTORICAL.KRX"


def test_classic_pivot_selects_nearest_support_and_resistance(tmp_path):
    provider = Track7ClassicPivotProvider(
        HistoricalMarketDailyOHLCProvider(_store(tmp_path), Calendar())
    )
    result = provider.get_support_resistance(
        symbol="KOSPI200", observed_at=datetime(2026, 9, 18, 9, 0),
        current_price=Decimal("350"),
    )
    assert result is not None
    assert result.support == Decimal("348.35")
    assert result.resistance == Decimal("356.65")
    assert result.definition == "CLASSIC_FLOOR_PIVOT_PREVIOUS_COMPLETED_DAILY_OHLC"
    assert result.window == "PREVIOUS_COMPLETED_TRADING_DAY_1_DAILY_BAR"
    assert result.calculation_version == "TRACK7-CLASSIC-PIVOT-v1"


def test_classic_pivot_fails_closed_without_previous_day_data(tmp_path):
    provider = Track7ClassicPivotProvider(
        HistoricalMarketDailyOHLCProvider(HistoricalMarketStore(tmp_path / "empty.jsonl"), Calendar())
    )
    assert provider.get_support_resistance(
        symbol="KOSPI200", observed_at=datetime(2026, 9, 18, 9, 0),
        current_price=Decimal("350"),
    ) is None
