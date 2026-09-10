from decimal import Decimal
import pytest
from contracts.types import ExecutionLeg, MultiLegExecutionPlan, OptionInstrumentIdentity
from core.oms.multi_leg_materializer import MultiLegExecutionSemantics, MultiLegMaterializationError, materialize_multi_leg_plan

def resolver(leg):
    return OptionInstrumentIdentity(f"OPT-{leg.option_type}-{leg.strike}", "KOSPI200", "2026-12", leg.option_type, leg.strike)

def test_track2_four_leg_lossless():
    plan = MultiLegExecutionPlan("G-2", "track2", (ExecutionLeg("short_put","SELL",1,"PUT",Decimal("300")), ExecutionLeg("short_call","SELL",1,"CALL",Decimal("400")), ExecutionLeg("long_put","BUY",1,"PUT",Decimal("250")), ExecutionLeg("long_call","BUY",1,"CALL",Decimal("450"))))
    intents = materialize_multi_leg_plan(plan, resolve_identity=resolver, semantics=MultiLegExecutionSemantics("LIMIT","ENTRY"))
    assert len(intents) == 4
    assert [(i.group_id,i.leg_id,i.side,i.quantity) for i in intents] == [("G-2","short_put","SELL",1),("G-2","short_call","SELL",1),("G-2","long_put","BUY",1),("G-2","long_call","BUY",1)]

def test_track8_asymmetric_qty_lossless():
    plan = MultiLegExecutionPlan("G-8", "track8", (ExecutionLeg("put","BUY",3,"PUT",Decimal("350")), ExecutionLeg("call","BUY",1,"CALL",Decimal("450"))))
    intents = materialize_multi_leg_plan(plan, resolve_identity=resolver, semantics=MultiLegExecutionSemantics("LIMIT","ENTRY"))
    assert [i.quantity for i in intents] == [3,1]

def test_identity_mismatch_fails_closed():
    plan = MultiLegExecutionPlan("G", "track9", (ExecutionLeg("put","BUY",1,"PUT",Decimal("350")),))
    wrong = lambda _: OptionInstrumentIdentity("X","KOSPI200","2026-12","CALL",Decimal("350"))
    with pytest.raises(MultiLegMaterializationError, match="OPTION_TYPE_IDENTITY_MISMATCH"):
        pass
        materialize_multi_leg_plan(plan, resolve_identity=wrong, semantics=MultiLegExecutionSemantics("LIMIT","HEDGE"))
