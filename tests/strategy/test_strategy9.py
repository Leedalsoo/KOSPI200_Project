from decimal import Decimal
from core.strategy.track9_event_overnight_insurance import Track9EventOvernightInsurance, Track9State
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal

def make(pair_qty):
    s=Track9EventOvernightInsurance(pair_quantity=pair_qty)
    s.state=Track9State(entry_date="2026-10-05",entry_qty=pair_qty,put_strike=Decimal("1090"),call_strike=Decimal("1110"),entered_today=True,state="OVERNIGHT_INSURANCE_AWAITING_FILLS")
    p=StrategyExecutionProposal(proposed_quantity=pair_qty,asset_type="OPTION",side="BUY",track_id=s.strategy_id,tag_id="OVERNIGHT_INSURANCE_PUT",option_type="PUT",strike=Decimal("1090"))
    return s,s.build_execution_plan("T9-G",proposal=p)

def test_strategy9_approved_put_builds_put_call_pair():
    s,plan=make(2)
    assert [(x.leg_id,x.option_type,x.quantity) for x in plan.legs]==[("put","PUT",2),("call","CALL",2)]

def test_strategy9_pair_plan_preserves_same_quantity():
    _,plan=make(3)
    assert {x.quantity for x in plan.legs}=={3}
