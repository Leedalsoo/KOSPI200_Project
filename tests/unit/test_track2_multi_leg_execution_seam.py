"""Test Track2 Multi Leg Execution Seam — 테스트 사양 문서.

from decimal import Decimal
from contracts.types import OptionInstrumentIdentity
from core.oms.multi_leg_materializer import (
MultiLegExecutionSemantics,
materialize_multi_leg_plan,
)
from core.oms.multi_leg_submission import submit_multi_leg_intents
from core.strategy.track2_asymmetric_trap import Track2AsymmetricTrap
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
"2026-12",
leg.option_type,
leg.strike,
)
def test_track2_actual_plan_to_common_materializer_and_submission_seam():
plan = Track2AsymmetricTrap().build_execution_plan(
"T2-G", Decimal("350"), 0.80, 1.0
)
assert [
(leg.leg_id, leg.side, leg.option_type, leg.strike, leg.quantity)
for leg in plan.legs
] == [
("short_put", "SELL", "PUT", Decimal("340.0"), 1),
("short_call", "SELL", "CALL", Decimal("360.0"), 1),
("long_put", "BUY", "PUT", Decimal("345.0"), 1),
("long_call", "BUY", "CALL", Decimal("355.0"), 1),
]
intents = materialize_multi_leg_plan(
plan,
resolve_identity=resolver,
semantics=MultiLegExecutionSemantics("LIMIT", "ENTRY"),
)
assert [
(i.leg_id, i.side, i.instrument_identity.option_type,
i.instrument_identity.strike, i.quantity)
for i in intents
] == [
(leg.leg_id, leg.side, leg.option_type, leg.strike, leg.quantity)
for leg in plan.legs
]
router = Router()
out = submit_multi_leg_intents(
intents,
to_broker_command=Command,
approval_token_for=lambda intent, command: f"T:{intent.leg_id}",
order_router=router,
)
assert out == ("short_put", "short_call", "long_put", "long_call")
assert [leg_id for leg_id, _ in router.calls] == list(out)
"""
