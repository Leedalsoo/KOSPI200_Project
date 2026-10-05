from datetime import datetime
from decimal import Decimal
from application.composition.track4_analytics_provider import build_track4_analytics_snapshot
from core.strategy.contracts import StrategyContext, StrategyInput
from core.strategy.track4_gamma_scalping import Track4GammaScalping, Track4MarketInput

def data(delta):
    return Track4MarketInput(observed_at=datetime(2026,9,8,10),current_price=Decimal("350"),active_vol=Decimal("1"),base_vol=Decimal("1"),time_str="10:00:00",current_delta=Decimal(delta),current_gamma=Decimal("0"),current_pnl=Decimal("0"),current_equity=Decimal("1000000"),price_history=(Decimal("350"),Decimal("351")),current_theta=Decimal("-0.1"))

def ctx(payload):
    return StrategyContext(strategy_id="track4_gamma_scalping",input=StrategyInput(payload=payload),analytics=build_track4_analytics_snapshot(payload,run_id="t4",as_of=payload.observed_at))

def test_strategy4_positive_delta_sells_futures_hedge():
    signal=Track4GammaScalping().evaluate(ctx(data("0.41")))[0]
    assert signal.execution_proposal.asset_type=="FUTURES"
    assert signal.execution_proposal.side=="SELL"
    assert signal.execution_proposal.proposed_quantity==3

def test_strategy4_deadband_does_not_hedge():
    assert Track4GammaScalping().evaluate(ctx(data("0.2")))==()
