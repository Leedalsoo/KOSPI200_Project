from decimal import Decimal

from application.bootstrap import create_virtual_runtime_bootstrap
from application.composition.virtual_runtime_data_provider import VirtualRuntimeDataProvider


def test_virtual_runtime_data_provider_uses_vms_observations_and_explicit_unavailable_sources():
    bootstrap = create_virtual_runtime_bootstrap()
    market = bootstrap.bundle.market
    provider = VirtualRuntimeDataProvider(market)
    ticks = list(market.generate_tick_stream(total_days=1, ticks_per_day=4))
    data = provider.snapshot(ticks[-1])

    assert data.price == Decimal(str(ticks[-1].last_price))
    assert data.as_of.isoformat() == ticks[-1].timestamp
    assert data.prices
    assert data.high_price >= data.low_price
    assert data.status["tick"].available is True
    assert data.status["ohlc_history"].source == "VMS.recent_ticks"
    assert data.status["macro"].available is True
    assert data.status["macro"].source == "VMS.scenario.active_config"
    assert data.status["event"].available is True
    assert data.status["event"].source == "VMS.scenario.shock_schedule"



