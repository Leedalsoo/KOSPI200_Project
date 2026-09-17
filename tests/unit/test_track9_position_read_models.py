from datetime import datetime
from decimal import Decimal
from contracts.position_provenance import PositionLotProvenance, PositionRole
from contracts.track9_position_read_models import Track9InsurancePositionReadModel, Track9OptionPositionAttributionReadModel
from contracts.types import OptionInstrumentIdentity
from environments.virtual.position.virtual_position_lot_store import VirtualPositionLotStore
ID = OptionInstrumentIdentity("OPT", "OPT", "202601", "CALL", Decimal("100"), Decimal("250000"), "OPTION_MASTER")
def make(e, side, qty, role=PositionRole.NONE, strategy="S1", group="G1", leg="L1", ts=None):
    ts = ts or datetime(2026,1,1,9,0)
    return PositionLotProvenance("R1", "OPT", strategy, group, leg, "C"+e, e, side, qty, qty, ts, ID, Decimal("250000"), "OPTION_MASTER", role)
def test_attribution_projects_all_open_lots_without_merging():
    s=VirtualPositionLotStore(); s.apply_execution(make("E1","BUY",2)); s.apply_execution(make("E2","BUY",3,strategy="S2",group="G2",leg="L2"))
    rows=Track9OptionPositionAttributionReadModel(s).snapshot()
    assert [(x.strategy_id,x.group_id,x.remaining_quantity) for x in rows] == [("S1","G1",2),("S2","G2",3)]
def test_insurance_projects_only_explicit_roles():
    s=VirtualPositionLotStore(); s.apply_execution(make("E1","BUY",1)); s.apply_execution(make("E2","BUY",2,PositionRole.EVENT_INSURANCE,group="G2",leg="L2"))
    rows=Track9InsurancePositionReadModel(s).snapshot()
    assert len(rows)==1; assert rows[0].position_role == PositionRole.EVENT_INSURANCE
    assert rows[0].execution_id == "E2"
def test_read_models_follow_partial_close_projection():
    s=VirtualPositionLotStore(); s.apply_execution(make("E1","BUY",5,PositionRole.OVERNIGHT_INSURANCE)); s.apply_execution(make("E2","SELL",2))
    row=Track9InsurancePositionReadModel(s).snapshot()[0]
    assert row.remaining_quantity == 3; assert row.execution_id == "E1"

def test_empty_store_is_authoritatively_empty():
    s=VirtualPositionLotStore()
    assert Track9OptionPositionAttributionReadModel(s).snapshot() == ()
    assert Track9InsurancePositionReadModel(s).snapshot() == ()

def test_all_insurance_roles_are_projected():
    s=VirtualPositionLotStore()
    for i,r in enumerate((PositionRole.OVERNIGHT_INSURANCE,PositionRole.EVENT_INSURANCE,PositionRole.REHEDGE_INSURANCE),1):
        s.apply_execution(make("E"+str(i),"BUY",1,r,group="G"+str(i),leg="L"+str(i)))
    assert {x.position_role for x in Track9InsurancePositionReadModel(s).snapshot()} == {PositionRole.OVERNIGHT_INSURANCE,PositionRole.EVENT_INSURANCE,PositionRole.REHEDGE_INSURANCE}
