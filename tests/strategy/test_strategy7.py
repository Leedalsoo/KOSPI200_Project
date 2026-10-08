from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from contracts.analytics import AnalyticsStatus
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


def test_strategy7_trailing_uses_actual_put_call_mark_prices():
    s=Track7VolatilitySkewWeeklyInsurance()
    s.state=Track7State(insurance_active=True,put_strike=Decimal("350"),call_strike=Decimal("360"),contract_multiplier=Decimal("250000"),peak_profit=Decimal("0"))

    class Analytics:
        as_of=datetime(2026, 10, 6, 10, 0)
        values={
            "options.track7_put_mark_price": Decimal("2.0"),
            "options.track7_call_mark_price": Decimal("2.0"),
            "calendar.is_expiry_day": False,
        }
        def get(self, key):
            value=self.values.get(key)
            return SimpleNamespace(value=value, status=AnalyticsStatus.AVAILABLE) if value is not None else None

    ctx=SimpleNamespace(strategy_id=s.strategy_id, analytics=Analytics())
    assert s.evaluate(ctx) == ()
    s.state=Track7State(**{**s.state.__dict__, "peak_profit": Decimal("1000000")})
    Analytics.values["options.track7_put_mark_price"]=Decimal("1.0")
    Analytics.values["options.track7_call_mark_price"]=Decimal("1.0")
    signals=s.evaluate(ctx)
    assert signals and "TRAILING_20PCT" in signals[0].reason
