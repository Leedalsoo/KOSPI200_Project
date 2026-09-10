```python
from decimal import Decimal

import pytest

from contracts.track4_composite_runtime_input_provider import Track4CompositeRuntimeInputProvider
from contracts.track4_runtime_input_provider import Track4InputSourceUnavailable, Track4RuntimeInputReadiness


class StubProvider:
    def __init__(self, readiness, values=None):
        self._readiness = readiness
        self._values = values or {}

    def readiness(self):
        return self._readiness

    def __getattr__(self, name):
        if name in self._values:
            return lambda: self._values[name]
        return lambda: (_ for _ in ()).throw(Track4InputSourceUnavailable(f"{name} unavailable"))


def test_composition_merges_market_and_account_readiness():
    market = StubProvider(
        Track4RuntimeInputReadiness(True, False, False, False, False),
        {"current_price": Decimal("100"), "active_vol": Decimal("0.2"), "base_vol": Decimal("0.15")},
    )
    account = StubProvider(
        Track4RuntimeInputReadiness(False, False, True, False, False),
        {"current_pnl": Decimal("1234"), "current_equity": Decimal("50000000")},
    )
    provider = Track4CompositeRuntimeInputProvider(market, account)

    assert provider.current_price() == Decimal("100")
    assert provider.active_vol() == Decimal("0.2")
    assert provider.base_vol() == Decimal("0.15")
    assert provider.current_pnl() == Decimal("1234")
    assert provider.current_equity() == Decimal("50000000")
    readiness = provider.readiness()
    assert readiness.market is True
    assert readiness.account_pnl is True
    assert readiness.history is False
    assert readiness.greeks is False
    assert readiness.attribution is False
    assert readiness.is_complete is False


def test_unresolved_sources_remain_fail_closed():
    market = StubProvider(Track4RuntimeInputReadiness(True, False, False, False, False))
    account = StubProvider(Track4RuntimeInputReadiness(False, False, True, False, False))
    provider = Track4CompositeRuntimeInputProvider(market, account)

    with pytest.raises(Track4InputSourceUnavailable):
        provider.price_high()
    with pytest.raises(Track4InputSourceUnavailable):
        provider.current_delta()
    with pytest.raises(Track4InputSourceUnavailable):
        provider.premium_spent()
```

검증 목적: Market + Account/PnL partial source 조합이 readiness만 확장하고, 미확보 history/Greeks/attribution을 합성하지 않는지 확인한다.

def test_kis_greeks_are_consumed_through_runtime_composition():
from contracts.track4_kis_greeks_provider import KISIndexOptionGreeksProvider
from contracts.track4_market_projection_provider import Track4MarketProjectionProvider
from core.sensor.market_condition_sensor import MarketConditionSnapshot
snapshot = MarketConditionSnapshot(
as_of="2026-09-06T09:00:00",
instrument_id="KOSPI200-OPT",
current_price=425.0,
price_change=1.0,
volatility=0.18,
baseline_volatility=0.16,
volatility_ratio=1.125,
drawdown=0.0,
stress_level=0.0,
stress_flags=(),
)
kis = KISIndexOptionGreeksProvider.from_payload(
{
"delta": "0.42",
"gama": "0.013",
"theta": "-0.021",
"hts_ints_vltl": "0.247",
},
instrument_id="KOSPI200-OPT",
observed_at="2026-09-06T09:00:00",
)
market = Track4MarketProjectionProvider(lambda: snapshot, greeks_provider=kis)
account = StubProvider(
Track4RuntimeInputReadiness(False, False, True, False, False),
{"current_pnl": Decimal("0"), "current_equity": Decimal("50000000")},
)
provider = Track4CompositeRuntimeInputProvider(market, account)
assert provider.current_delta() == Decimal("0.42")
assert provider.current_gamma() == Decimal("0.013")
assert provider.active_vol() == Decimal("0.247")
assert provider.readiness().greeks is True
assert provider.readiness().market is True
assert provider.readiness().account_pnl is True
assert provider.readiness().is_complete is False