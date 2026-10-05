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


def test_track9_strategy_builds_pair_plan_from_approved_proposal():
    from core.strategy.track9_event_overnight_insurance import Track9EventOvernightInsurance, Track9State
    from core.strategy.strategy_execution_proposal import StrategyExecutionProposal

    strategy = Track9EventOvernightInsurance(pair_quantity=2)
    strategy.state = Track9State(
        entry_date="2026-10-05",
        entry_qty=2,
        put_strike=Decimal("1090"),
        call_strike=Decimal("1110"),
        entered_today=True,
        state="OVERNIGHT_INSURANCE_AWAITING_FILLS",
    )
    proposal = StrategyExecutionProposal(
        proposed_quantity=2,
        asset_type="OPTION",
        side="BUY",
        track_id=strategy.strategy_id,
        tag_id="OVERNIGHT_INSURANCE_PUT",
        option_type="PUT",
        strike=Decimal("1090"),
    )
    plan = strategy.build_execution_plan("T9-G", proposal=proposal)
    assert [(x.leg_id, x.side, x.option_type, x.strike, x.quantity) for x in plan.legs] == [
        ("put", "BUY", "PUT", Decimal("1090"), 2),
        ("call", "BUY", "CALL", Decimal("1110"), 2),
    ]
