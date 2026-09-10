"""Test Track9 Event Overnight Insurance — 테스트 사양 문서.

from decimal import Decimal
import inspect
from core.strategy.contracts import StrategyContext, StrategyInput
from core.strategy.track9_event_overnight_insurance import (
Track9EventOvernightInsurance,
Track9MarketInput,
)
STRATEGY_ID = "track9_event_overnight_insurance"
def base(**kwargs):
values = dict(
strategy_id=STRATEGY_ID,
current_price=Decimal("350"),
active_sell_qty=4,
current_insurance_qty=1,
date_str="2026-09-04",
)
values.update(kwargs)
return Track9MarketInput(**values)
def context(data):
return StrategyContext(
strategy_id=STRATEGY_ID,
input=StrategyInput(payload=data),
)
def test_overnight_target_is_half_of_active_sell_qty():
s = Track9EventOvernightInsurance()
signals = s.evaluate(context(base()))
assert any(x.direction == "ADD_INSURANCE" for x in signals)
assert "TARGET_QTY:2" in next(x.reason for x in signals if x.direction == "ADD_INSURANCE")
def test_insurance_reduce_when_excess():
s = Track9EventOvernightInsurance()
signals = s.evaluate_overnight_insurance(base(current_insurance_qty=4))
assert signals[0].direction == "REDUCE_INSURANCE"
def test_early_profit_take_90_percent_once():
s = Track9EventOvernightInsurance()
signals = s.evaluate_early_profit_take(
base(time_str="09:03:00", current_insurance_qty=10)
)
assert signals[0].direction == "EARLY_PROFIT_TAKE"
assert s.evaluate_early_profit_take(
base(time_str="09:04:00", current_insurance_qty=10)
) == ()
def test_reentry_after_0930_when_stable():
s = Track9EventOvernightInsurance()
signals = s.evaluate_reentry(
base(time_str="09:30:01", target_qty=5, existing_qty=3, market_stable=True)
)
assert signals[0].direction == "REHEDGE_ENTRY"
def test_event_iv_spike_enters_and_budget_blocked():
s = Track9EventOvernightInsurance()
signals = s.evaluate_event_volatility(base(iv_spike=Decimal("4")))
assert signals[0].direction == "ENTER_EVENT_STRANGLE"
blocked = Track9EventOvernightInsurance().evaluate_event_volatility(
base(
iv_spike=Decimal("4"),
event_budget=Decimal("100"),
estimated_event_cost=Decimal("101"),
)
)
assert blocked[0].direction == "EVENT_BUDGET_BLOCKED"
def test_event_vol_crush_and_trailing_close():
s = Track9EventOvernightInsurance()
s.evaluate_event_volatility(base(iv_spike=Decimal("4")))
signals = s.evaluate_event_volatility(base(iv_crush=Decimal("-3")))
assert signals[0].direction == "CLOSE_EVENT_STRANGLE"
s = Track9EventOvernightInsurance()
s.evaluate_event_volatility(base(iv_spike=Decimal("4")))
s.evaluate_event_volatility(
base(current_pnl=Decimal("60000"), premium_spent=Decimal("250000"))
)
signals = s.evaluate_event_volatility(
base(current_pnl=Decimal("50000"), premium_spent=Decimal("250000"))
)
assert signals[0].direction == "CLOSE_EVENT_STRANGLE"
def test_dynamic_rebuild_net_pnl_and_guards():
s = Track9EventOvernightInsurance()
assert s.evaluate_dynamic_profit_rebuild(
base(current_pnl=Decimal("400100"), total_fees=Decimal("101"))
) == ()
assert s.evaluate_dynamic_profit_rebuild(
base(current_pnl=Decimal("500000"), risk_guard_active=True)
) == ()
assert s.evaluate_dynamic_profit_rebuild(
base(current_pnl=Decimal("500000"), margin_ratio=Decimal("0.86"))
) == ()
signals = s.evaluate_dynamic_profit_rebuild(
base(current_pnl=Decimal("400500"), total_fees=Decimal("500"))
)
assert [x.direction for x in signals] == [
"DYNAMIC_PROFIT_TAKE",
"DYNAMIC_REBUILD_FENCE",
]
def test_strategy_id_mismatch_is_noop():
s = Track9EventOvernightInsurance()
bad_context = StrategyContext(
strategy_id="other_strategy",
input=StrategyInput(payload=base()),
)
assert s.evaluate(bad_context) == ()
def test_strategy_has_no_legacy_execution_dependency():
from core.strategy import track9_event_overnight_insurance
source = inspect.getsource(track9_event_overnight_insurance)
assert 'getattr(context, "track9_input"' not in source
assert "OrderRequest" not in source
assert "Broker" not in source
assert "AtomicBudgetManager" not in source
"""
