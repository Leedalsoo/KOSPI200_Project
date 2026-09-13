from decimal import Decimal
from datetime import datetime
import pytest
from contracts.track4_kis_greeks_provider import KISIndexOptionGreeksProvider
from contracts.track4_runtime_input_provider import Track4InputSourceUnavailable
from application.composition.track4_runtime_input_provider_factory import Track4RuntimeInputProviderFactory
from contracts.types import AccountSnapshot, DataQuality

class StubAccountProvider:
    def snapshot(self):
        return AccountSnapshot(as_of=datetime(2026,9,6,12,0,0),balances={"cash":Decimal("1000000"),"realized_pnl":Decimal("12000"),"unrealized_pnl":Decimal("3000")},freshness=DataQuality(is_fresh=True,is_complete=True,source_available=True,reason="test"))

def make_snapshot():
    from core.sensor.market_condition_sensor import MarketConditionSnapshot
    return MarketConditionSnapshot(as_of=datetime(2026,9,6,12,0,0),instrument_id="KOSPI200",current_price=350.0,price_change=1.0,volatility=0.02,baseline_volatility=0.015,volatility_ratio=1.333333,drawdown=0.0,stress_level=0.1,stress_flags=())

def test_factory_wires_authoritative_market_and_account_sources():
    greeks=KISIndexOptionGreeksProvider.from_payload({"delta":"0.2","gama":"0.01","theta":"-0.03","hts_ints_vltl":"0.25"},instrument_id="KOSPI200-C",observed_at="2026-09-06T12:00:00+09:00")
    provider=Track4RuntimeInputProviderFactory.create(snapshot_supplier=make_snapshot,price_history_supplier=lambda instrument_id:(349.0,350.0),account_provider=StubAccountProvider(),greeks_provider=greeks)
    assert provider.current_price()==Decimal("350.0")
    assert provider.active_vol()==Decimal("0.25")
    assert provider.base_vol()==Decimal("0.015")
    assert provider.price_history()==(Decimal("349.0"),Decimal("350.0"))
    assert provider.current_delta()==Decimal("0.2")
    assert provider.current_gamma()==Decimal("0.01")
    assert provider.current_pnl()==Decimal("15000")
    assert provider.current_equity()==Decimal("1000000")

def test_factory_remains_fail_closed_for_unresolved_attribution():
    provider=Track4RuntimeInputProviderFactory.create(snapshot_supplier=make_snapshot,price_history_supplier=lambda instrument_id:(349.0,350.0),account_provider=StubAccountProvider())
    with pytest.raises(Track4InputSourceUnavailable): provider.current_delta()
    with pytest.raises(Track4InputSourceUnavailable): provider.accumulated_gamma_profit()
    with pytest.raises(Track4InputSourceUnavailable): provider.theta_decay_cost()
