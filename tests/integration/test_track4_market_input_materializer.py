from datetime import datetime
from decimal import Decimal
import pytest
from application.composition.track4_market_input_materializer import Track4RuntimeInputMaterializer
from contracts.track4_composite_runtime_input_provider import Track4CompositeRuntimeInputProvider
from contracts.track4_kis_greeks_provider import KISIndexOptionGreeksProvider
from contracts.track4_market_projection_provider import Track4MarketProjectionProvider
from contracts.track4_runtime_input_provider import Track4InputSourceUnavailable
from contracts.track4_vssf_account_projection_provider import Track4VSSFAccountProjectionProvider
from core.sensor.market_condition_sensor import MarketConditionSnapshot
from contracts.types import AccountSnapshot, DataQuality

AS_OF = datetime(2026,1,2,10,0)

def snapshot(as_of=AS_OF):
    return MarketConditionSnapshot(as_of=as_of,instrument_id="KOSPI200_VIRTUAL",current_price=350.0,price_change=0.2,volatility=0.012,baseline_volatility=0.010,volatility_ratio=1.2,drawdown=0.0,stress_level=0.0,stress_flags=())

class StubAccountProvider:
    def __init__(self, as_of=AS_OF):
        self._snapshot=AccountSnapshot(as_of=as_of,balances={"cash":Decimal("1000000"),"realized_pnl":Decimal("1000"),"unrealized_pnl":Decimal("2000")},freshness=DataQuality(is_fresh=True,is_complete=True,source_available=True,reason="test"))
    def snapshot(self): return self._snapshot

def make_provider(account_as_of=AS_OF):
    market=Track4MarketProjectionProvider(lambda:snapshot(),price_history_supplier=lambda _:(349.0,350.0)); account=Track4VSSFAccountProjectionProvider(StubAccountProvider(account_as_of)); return Track4CompositeRuntimeInputProvider(market,account)

def make_greeks(observed_at="2026-01-02T10:00:00"):
    return KISIndexOptionGreeksProvider.from_payload({"delta":"0.52","gama":"0.18","theta":"-0.07","hts_ints_vltl":"0.21"},instrument_id="KOSPI200-OPT-1",observed_at=observed_at)

def test_materializer_preserves_same_tick_authoritative_values():
    result=Track4RuntimeInputMaterializer(make_provider(),make_greeks()).materialize(AS_OF)
    assert result.observed_at == AS_OF
    assert result.current_price == Decimal("350.0")
    assert result.active_vol == Decimal("0.21")
    assert result.current_delta == Decimal("0.52")
    assert result.current_gamma == Decimal("0.18")
    assert result.current_pnl == Decimal("3000")
    assert result.current_equity == Decimal("1000000")
    assert result.price_history == (Decimal("349.0"),Decimal("350.0"))
    assert result.premium_spent is None and result.accumulated_gamma_profit is None and result.theta_decay_cost is None

def test_tick_and_account_market_timestamp_mismatch_fails_closed():
    with pytest.raises(Track4InputSourceUnavailable, match="TRACK4_SOURCE_TIMESTAMP_MISMATCH"):
        Track4RuntimeInputMaterializer(make_provider(datetime(2026,1,2,10,0,1)),make_greeks()).materialize(AS_OF)

def test_tick_and_greeks_timestamp_mismatch_fails_closed():
    with pytest.raises(Track4InputSourceUnavailable, match="TRACK4_GREEKS_TIMESTAMP_MISMATCH"):
        Track4RuntimeInputMaterializer(make_provider(),make_greeks("2026-01-02T10:00:01")).materialize(AS_OF)

def test_missing_history_fails_closed():
    market=Track4MarketProjectionProvider(lambda:snapshot(),price_history_supplier=lambda _:()); account=Track4VSSFAccountProjectionProvider(StubAccountProvider()); provider=Track4CompositeRuntimeInputProvider(market,account)
    with pytest.raises(Track4InputSourceUnavailable, match="TRACK4_CORE_INPUT_INCOMPLETE"):
        Track4RuntimeInputMaterializer(provider,make_greeks()).materialize(AS_OF)
