from datetime import datetime, timezone
from decimal import Decimal

from application.historical_market_data_provider import HistoricalMarketDataProvider
from application.market_data_hub import MarketDataHub
from contracts.kis_index_futures_market_ws_adapter import KisIndexFuturesMarketObservation
from contracts.types import CanonicalMarketTick, DataQuality, MarketState, ProviderHealth
from environments.live.market.kis_futures_market_data import KISFuturesMarketDataProvider
from environments.virtual.market.canonical import ReferenceCanonicalMarketTick
from environments.virtual.market.replay_engine import HistoricalReplayEngine


class OtherProvider:
    def __init__(self) -> None:
        self.tick = CanonicalMarketTick(
            instrument_id="OTHER-A",
            observed_at=datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc),
            price=Decimal("1.25"),
        )
        self.callbacks = []

    def snapshot(self) -> MarketState:
        return MarketState(
            as_of=self.tick.observed_at,
            ticks={self.tick.instrument_id: self.tick},
            quality={self.tick.instrument_id: DataQuality(True, True, True)},
        )

    def subscribe(self, callback) -> None:
        self.callbacks.append(callback)

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            available=True,
            as_of=self.tick.observed_at,
            source="OTHER:TEST",
            observed_at=self.tick.observed_at,
            freshness_seconds=1.0,
        )


def _historical_tick() -> ReferenceCanonicalMarketTick:
    return ReferenceCanonicalMarketTick(
        timestamp="2026-09-17T10:00:00+00:00",
        underlying_price=510.25,
        underlying_symbol="KOSPI200",
        last_price=510.25,
        volume=120,
        seq_id=7,
        symbol="201S11305",
        option_source="KRX:HISTORICAL",
        expiry="202610",
        strike_price=510.0,
        option_type="CALL",
    )


def test_real_provider_classes_compose_through_market_data_hub():
    kis = KISFuturesMarketDataProvider(
        instrument_id_resolver=lambda symbol: symbol,
        observed_at_resolver=lambda obs: datetime(2026, 9, 17, 10, 1, tzinfo=timezone.utc),
    )
    historical = HistoricalMarketDataProvider(HistoricalReplayEngine([_historical_tick()]))
    other = OtherProvider()
    hub = MarketDataHub(
        {"kis": kis, "historical": historical, "other": other},
        active="kis",
    )

    received = []
    hub.subscribe(received.append)
    observation = KisIndexFuturesMarketObservation(
        shrn_iscd="FUT-TEST",
        observed_hour="100100",
        price=Decimal("512.5"),
        volume=Decimal("12"),
        ask_price=Decimal("512.6"),
        bid_price=Decimal("512.4"),
        source="KIS:H0IFCNT0",
    )
    kis.publish(observation)
    assert hub.snapshot().ticks["FUT-TEST"].price == Decimal("512.5")
    assert received
    assert hub.health().source == "KIS:H0IFCNT0"
    assert hub.health().observed_at == datetime(2026, 9, 17, 10, 1, tzinfo=timezone.utc)
    assert hub.health().freshness_seconds is not None

    hub.select("historical")
    historical.replay_next()
    assert hub.snapshot().ticks["201S11305"].price == Decimal("510.25")
    assert hub.health().source == "KRX:HISTORICAL"
    assert hub.health().observed_at == datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc)
    assert hub.health().freshness_seconds is not None

    hub.select("other")
    assert hub.snapshot().ticks["OTHER-A"].price == Decimal("1.25")
    assert hub.health().source == "OTHER:TEST"


def test_market_data_hub_composition_fails_closed_on_missing_or_invalid_provider():
    historical = HistoricalMarketDataProvider(HistoricalReplayEngine([_historical_tick()]))
    kis = KISFuturesMarketDataProvider(
        instrument_id_resolver=lambda symbol: symbol,
        observed_at_resolver=lambda obs: datetime(2026, 9, 17, 10, 1, tzinfo=timezone.utc),
    )
    hub = MarketDataHub({"kis": kis, "historical": historical}, active="historical")
    assert hub.active_provider == "historical"
    assert hub.health().available is False

    try:
        hub.select("missing")
    except KeyError:
        pass
    else:
        raise AssertionError("invalid provider selection must fail closed")
