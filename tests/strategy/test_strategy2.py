from decimal import Decimal
from core.strategy.track2_asymmetric_trap import Track2AsymmetricTrap
from core.strategy.contracts import StrategyContext

def test_strategy2_builds_four_leg_trap():
    plan=Track2AsymmetricTrap().build_execution_plan("T2-G",Decimal("350"),0.8,1.0)
    assert len(plan.legs)==4
    assert {x.option_type for x in plan.legs}=={"PUT","CALL"}

def test_strategy2_missing_analytics_is_fail_closed():
    s=Track2AsymmetricTrap()
    assert s.evaluate(StrategyContext(strategy_id=s.strategy_id,input=None,analytics=None))==()
