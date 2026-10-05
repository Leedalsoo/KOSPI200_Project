from decimal import Decimal
from core.strategy.track7_volatility_skew_weekly_insurance import Track7VolatilitySkewWeeklyInsurance, Track7State
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal

def proposal(s,side):
    return StrategyExecutionProposal(proposed_quantity=1,asset_type="OPTION",side=side,track_id=s.strategy_id,tag_id="CURRENT",option_type="PUT",strike=Decimal("350"))

def test_strategy7_put_entry_builds_two_leg_insurance_plan():
    s=Track7VolatilitySkewWeeklyInsurance()
    s.state=Track7State(insurance_active=True,put_strike=Decimal("350"),call_strike=Decimal("360"))
    plan=s.build_execution_plan("T7-G",proposal=proposal(s,"BUY"))
    assert [(x.option_type,x.side,x.quantity) for x in plan.legs]==[("PUT","BUY",1),("CALL","BUY",1)]

def test_strategy7_put_close_resets_lifecycle():
    s=Track7VolatilitySkewWeeklyInsurance()
    s.state=Track7State(insurance_active=True,put_strike=Decimal("350"),call_strike=Decimal("360"))
    plan=s.build_execution_plan("T7-G",proposal=proposal(s,"SELL"))
    assert plan.purpose=="WEEKLY_INSURANCE_CLOSE"
    assert s.state.insurance_active is False
