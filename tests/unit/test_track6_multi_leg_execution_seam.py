"""Test Track6 Multi Leg Execution Seam — 테스트 사양 문서.

from decimal import Decimal
from contracts.types import OptionInstrumentIdentity
from core.oms.multi_leg_materializer import (
MultiLegExecutionSemantics,
materialize_multi_leg_plan,
)
from core.oms.multi_leg_submission import submit_multi_leg_intents
from core.strategy.track6_daily_tail_insurance import (
Track6DailyTailInsurance,
Track6MarketInput,
)
class Command:
def __init__(self, intent):
self.group_id = intent.group_id
self.leg_id = intent.leg_id
class Router:
def __init__(self):
self.calls = []
def register_and_route(self, command, token):
self.calls.append((command.leg_id, token))
return command.leg_id
def resolver(leg):
return OptionInstrumentIdentity(
f"OPT-{leg.option_type}-{leg.strike}",
"KOSPI200",
"2026-09",
leg.option_type,
leg.strike,
)
def market_input():
return Track6MarketInput(
strategy_id="track6_daily_tail_insurance",
current_price=Decimal("350"),
active_vol=Decimal("1.3"),
base_vol=Decimal("1.0"),
budget=Decimal("250000"),
date_str="2026-09-08",
time_str="09:00:00",
)
def test_track6_actual_active_state_plan_to_common_materializer_and_submission_seam():
strategy = Track6DailyTailInsurance()
signals = strategy.evaluate_buy(market_input())
assert signals and signals[0].direction == "BUY_INSURANCE"
plan = strategy.build_execution_plan("T6-G")
assert plan is not None
assert [
(leg.leg_id, leg.side, leg.option_type, leg.strike, leg.quantity)
for leg in plan.legs
] == [
("put", "BUY", "PUT", Decimal("337.5"), 1),
("call", "BUY", "CALL", Decimal("362.5"), 1),
]
intents = materialize_multi_leg_plan(
plan,
resolve_identity=resolver,
semantics=MultiLegExecutionSemantics("LIMIT", "ENTRY"),
)
assert [
(i.group_id, i.leg_id, i.side, i.instrument_identity.option_type,
i.instrument_identity.strike, i.quantity)
for i in intents
] == [
(plan.group_id, leg.leg_id, leg.side, leg.option_type, leg.strike, leg.quantity)
for leg in plan.legs
]
router = Router()
out = submit_multi_leg_intents(
intents,
to_broker_command=Command,
approval_token_for=lambda intent, command: f"T:{intent.leg_id}",
order_router=router,
)
assert out == ("put", "call")
assert [leg_id for leg_id, _ in router.calls] == list(out)
"""
