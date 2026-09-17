from datetime import datetime
from decimal import Decimal

import pytest

from application.market_data_hub import MarketDataHub
from contracts.types import CanonicalMarketTick, DataQuality, MarketState, ProviderHealth


class StubProvider:
    def __init__(self, instrument_id: str) -> None:
        self.tick = CanonicalMarketTick(
            instrument_id=instrument_id,
            observed_at=datetime(2026, 9, 17, 10, 0),
            price=Decimal("510.0"),
            volume=Decimal("10"),
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
        return ProviderHealth(True, self.tick.observed_at)


def test_market_data_hub_delegates_without_changing_provider_contract():
    first = StubProvider("FUT-A")
    second = StubProvider("FUT-B")
    hub = MarketDataHub({"kis": first, "other": second}, active="kis")

    assert hub.active_provider == "kis"
    assert hub.provider_names() == ("kis", "other")
    assert hub.snapshot().ticks["FUT-A"] == first.tick
    assert hub.health().available is True

    received = []
    hub.subscribe(received.append)
    assert first.callbacks == [received.append]


def test_market_data_hub_switches_provider_explicitly():
    first = StubProvider("FUT-A")
    second = StubProvider("FUT-B")
    hub = MarketDataHub({"kis": first, "other": second}, active="kis")

    hub.select("other")
    assert hub.active_provider == "other"
    assert hub.snapshot().ticks["FUT-B"] == second.tick

    with pytest.raises(KeyError):
        hub.select("missing")


def test_market_data_hub_fails_closed_for_invalid_configuration():
    with pytest.raises(ValueError, match="MARKET_DATA_HUB_PROVIDER_REQUIRED"):
        MarketDataHub({}, active="kis")
    with pytest.raises(ValueError, match="MARKET_DATA_HUB_ACTIVE_PROVIDER_REQUIRED"):
        MarketDataHub({"kis": StubProvider("FUT-A")}, active="missing")
