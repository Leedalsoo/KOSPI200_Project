from decimal import Decimal
import pytest
from contracts.types import ExecutionLeg, MultiLegExecutionPlan, OptionInstrumentIdentity
from core.oms.multi_leg_materializer import MultiLegExecutionSemantics, materialize_multi_leg_plan
from core.oms.multi_leg_submission import MultiLegSubmissionError, submit_multi_leg_intents


def resolver(leg):
    return OptionInstrumentIdentity(f"OPT-{leg.option_type}-{leg.strike}", "KOSPI200", "2026-12", leg.option_type, leg.strike)

class Command:
    def __init__(self, i):
        self.client_order_id=i.client_order_id; self.group_id=i.group_id; self.leg_id=i.leg_id

class Router:
    def __init__(self): self.calls=[]
    def register_and_route(self, command, token):
        self.calls.append((command.leg_id, token)); return command.leg_id


def test_multi_leg_submission_preserves_declared_order_and_provenance():
    plan = MultiLegExecutionPlan("G-2", "track2", (
        ExecutionLeg("a","SELL",1,"PUT",Decimal("300")),
        ExecutionLeg("b","SELL",1,"CALL",Decimal("400")),
        ExecutionLeg("c","BUY",1,"PUT",Decimal("250")),
        ExecutionLeg("d","BUY",1,"CALL",Decimal("450")),
    ))
    intents=materialize_multi_leg_plan(plan, resolve_identity=resolver, semantics=MultiLegExecutionSemantics("LIMIT","ENTRY"))
    router=Router()
    out=submit_multi_leg_intents(intents, to_broker_command=Command, approval_token_for=lambda i,c: f"T:{i.leg_id}", order_router=router)
    assert out == ("a","b","c","d")
    assert [x[0] for x in router.calls] == ["a","b","c","d"]


def test_missing_token_fails_before_that_leg_is_routed():
    plan=MultiLegExecutionPlan("G", "track8", (ExecutionLeg("a","BUY",3,"PUT",Decimal("350")), ExecutionLeg("b","BUY",1,"CALL",Decimal("450"))))
    intents=materialize_multi_leg_plan(plan, resolve_identity=resolver, semantics=MultiLegExecutionSemantics("LIMIT","ENTRY"))
    router=Router()
    with pytest.raises(MultiLegSubmissionError, match="RISK_APPROVAL_TOKEN_REQUIRED"):
        pass
        submit_multi_leg_intents(intents, to_broker_command=Command, approval_token_for=lambda i,c: None if i.leg_id=="b" else "T:a", order_router=router)
    assert [x[0] for x in router.calls] == ["a"]
