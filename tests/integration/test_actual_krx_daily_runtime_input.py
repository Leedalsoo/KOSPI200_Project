from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from application.composition.track7_support_resistance_source import Track7AuthoritativeSupportResistanceSource
from application.composition.track7_classic_pivot_provider import Track7ClassicPivotProvider
from application.composition.virtual_runtime_data_provider import VirtualRuntimeDataProvider
from application.historical_daily_ohlc_provider import HistoricalMarketDailyOHLCProvider
from contracts.historical_daily_store import HistoricalDailyStore
from environments.virtual.market.canonical import ReferenceCanonicalMarketTick


class Calendar:
    def prev_trading_day(self, value):
        return date(2026, 9, 18)


def test_actual_krx_daily_store_reaches_track7_runtime_input():
    path = Path("data/historical/canonical/20260918_daily_ohlc.jsonl")
    store = HistoricalDailyStore(path)
    records = store.load_records()
    assert len(records) == 624
    actual, provenance = next((record, prov) for record, prov in records if record.symbol == "B056A960")
    assert actual.trading_date == date(2026, 9, 18)
    assert provenance["source_endpoint"].endswith("/opt_bydd_trd")
    provider = HistoricalMarketDailyOHLCProvider(store, Calendar())
    source = Track7AuthoritativeSupportResistanceSource(Track7ClassicPivotProvider(provider))
    tick = ReferenceCanonicalMarketTick(
        timestamp="2026-09-19T09:00:00",
        symbol=actual.symbol,
        underlying_symbol=actual.symbol,
        underlying_price=float(actual.close),
        last_price=float(actual.close),
        seq_id=1,
    )
    data = VirtualRuntimeDataProvider(
        market=type("Market", (), {"recent_ticks": (tick,), "scenario": type("Scenario", (), {"active_config": lambda self: {}})()})(),
        track7_support_resistance_source=source,
    ).snapshot(tick)
    assert data.support is not None
    assert data.resistance is not None
    assert data.status["track7_support_resistance"].available is True
    assert data.status["track7_support_resistance"].source.startswith("HistoricalMarketData/CanonicalDailyOHLC:")
