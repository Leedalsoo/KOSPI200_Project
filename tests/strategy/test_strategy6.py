from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from contracts.analytics import AnalyticsStatus
from core.strategy.contracts import StrategyContext, SignalKind
from core.strategy.track6_daily_tail_insurance import Track6DailyTailInsurance, Track6State

def snapshot(time_str, values):
    metrics={k:SimpleNamespace(status=AnalyticsStatus.AVAILABLE,value=v) for k,v in values.items()}
    return SimpleNamespace(as_of=datetime.fromisoformat("2026-10-01T"+time_str),get=lambda key:metrics.get(key))

def active():
    s=Track6DailyTailInsurance()
    s.state=Track6State(is_active=True,bought_date="2026-10-01",long_put_strike=Decimal("100"),long_call_strike=Decimal("100"),high_watermark_intrinsic=Decimal("20"),trailing_stop_active=True)
    return s

def test_strategy6_trailing_close_has_put_sell_proposal():
    s=active()
    a=snapshot("10:00:00",{"price.last":Decimal("99"),"volatility.active":Decimal("1"),"portfolio.premium_spent":Decimal("10")})
    signal=s.evaluate_take_profit(StrategyContext(strategy_id=s.strategy_id,analytics=a))[0]
    assert signal.direction=="CLOSE"
    assert signal.execution_proposal.side=="SELL"
    assert signal.execution_proposal.option_type=="PUT"

def test_strategy6_trailing_update_is_non_execution():
    s=active()
    s.state=Track6State(is_active=True,long_put_strike=Decimal("100"),long_call_strike=Decimal("100"))
    a=snapshot("10:00:00",{"price.last":Decimal("120"),"volatility.active":Decimal("1"),"portfolio.premium_spent":Decimal("10")})
    signal=s.evaluate_take_profit(StrategyContext(strategy_id=s.strategy_id,analytics=a))[0]
    assert signal.kind is SignalKind.NON_EXECUTION
    assert signal.execution_proposal is None
