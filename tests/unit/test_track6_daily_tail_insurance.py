"""Test Track6 Daily Tail Insurance — 테스트 사양 문서.

from decimal import Decimal
from core.strategy.track6_daily_tail_insurance import (
Track6DailyTailInsurance,
Track6MarketInput,
)
def base(**overrides):
values = {
"strategy_id": "track6_daily_tail_insurance",
"current_price": Decimal("350"),
"active_vol": Decimal("1.5"),
"base_vol": Decimal("1.0"),
"budget": Decimal("250000"),
"date_str": "2026-09-04",
"time_str": "09:00:00",
}
values.update(overrides)
return Track6MarketInput(**values)
def test_volatility_spike_buys_daily_insurance():
s = Track6DailyTailInsurance()
signals = s.evaluate_buy(base(active_vol=Decimal("1.3")))
assert signals and signals[0].direction == "BUY_INSURANCE"
assert s.state.long_put_strike == Decimal("337.5")
assert s.state.long_call_strike == Decimal("362.5")
def test_no_trigger_below_volatility_threshold():
s = Track6DailyTailInsurance()
signals = s.evaluate_buy(base(active_vol=Decimal("1.29")))
assert signals == ()
assert not s.state.is_active
def test_insufficient_budget_blocks_entry():
s = Track6DailyTailInsurance()
signals = s.evaluate_buy(base(budget=Decimal("249999")))
assert signals == ()
def test_1515_pending_queue_cancel():
s = Track6DailyTailInsurance()
signals = s.evaluate_buy(base(time_str="15:15:01"))
assert signals and signals[0].direction == "CANCEL"
def test_trailing_lockdown_after_1512():
s = Track6DailyTailInsurance()
s.evaluate_buy(base())
assert s.evaluate_take_profit(Decimal("320"), Decimal("1.5"), "15:12:01") == ()
def test_1515_expiry_fallback_closes():
s = Track6DailyTailInsurance()
s.evaluate_buy(base())
signals = s.evaluate_expiry_cutoff("15:15:00")
assert signals and signals[0].direction == "CLOSE_FALLBACK"
assert not s.state.is_active
def test_strategy_has_no_legacy_order_dependency():
import inspect
from core.strategy import track6_daily_tail_insurance
source = inspect.getsource(track6_daily_tail_insurance)
assert "OrderRequest" not in source
assert "Broker" not in source
assert "TimeService" not in source
def test_typed_payload_requires_matching_strategy_id():
s = Track6DailyTailInsurance()
assert base().strategy_id == s.strategy_id
assert base(strategy_id="track5_gap_divergence").strategy_id != s.strategy_id
"""
