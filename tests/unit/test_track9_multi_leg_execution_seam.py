from decimal import Decimal
from contracts.types import OptionInstrumentIdentity
from core.oms.multi_leg_materializer import MultiLegExecutionSemantics, materialize_multi_leg_plan
from core.oms.multi_leg_submission import submit_multi_leg_intents
from core.strategy.multi_leg_plan import build_pair_plan

class Command:
    def __init__(self, intent):
        self.group_id, self.leg_id = intent.group_id, intent.leg_id

class Router:
    def __init__(self): self.calls = []
    def register_and_route(self, command, token):
        self.calls.append((command.leg_id, token)); return command.leg_id

def resolver(leg):
    return OptionInstrumentIdentity(f"OPT-{leg.option_type}-{leg.strike}", "KOSPI200", "2026-09", leg.option_type, leg.strike)

def test_track9_actual_pair_plan_to_common_materializer_and_submission_seam():
    plan = build_pair_plan(group_id="T9-G", strategy_id="track9_event_overnight_insurance", purpose="OVERNIGHT_INSURANCE", put_strike=Decimal("335"), call_strike=Decimal("365"), put_quantity=2, call_quantity=2, side="BUY")
    assert [(x.leg_id, x.side, x.option_type, x.strike, x.quantity) for x in plan.legs] == [
        ("put", "BUY", "PUT", Decimal("335"), 2),
        ("call", "BUY", "CALL", Decimal("365"), 2)]
    intents = materialize_multi_leg_plan(plan, resolve_identity=resolver, semantics=MultiLegExecutionSemantics("LIMIT", "ENTRY"))
    assert [(i.group_id, i.leg_id, i.side, i.instrument_identity.option_type, i.instrument_identity.strike, i.quantity) for i in intents] == [
        (plan.group_id, x.leg_id, x.side, x.option_type, x.strike, x.quantity) for x in plan.legs]
    router = Router()
    out = submit_multi_leg_intents(intents, to_broker_command=Command, approval_token_for=lambda intent, command: f"T:{intent.leg_id}", order_router=router)
    assert out == ("put", "call")
    assert [leg_id for leg_id, _ in router.calls] == list(out)
