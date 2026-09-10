import pytest
from environments.live.position.live_position_aggregate import LivePositionAggregate
from environments.live.position.live_position_aggregate_risk_source import LivePositionAggregateRiskSource
from core.position.position_aggregate_risk_adapter import position_aggregate_to_risk_input

def test_live_aggregate_projects_authoritative_state_to_risk_input():
    a = LivePositionAggregate("OPT-1")
    a.apply_fill(side="BUY", quantity=3, price=1.25)
    risk = position_aggregate_to_risk_input(LivePositionAggregateRiskSource({"OPT-1": a}))
    assert risk.positions["OPT-1"].side == "BUY"
    assert risk.positions["OPT-1"].qty == 3

def test_flat_position_is_excluded():
    assert LivePositionAggregateRiskSource({"OPT-1": LivePositionAggregate("OPT-1")}).snapshot() == {}

def test_identity_mismatch_fails_closed():
    with pytest.raises(ValueError, match="LIVE_POSITION_INSTRUMENT_ID_MISMATCH"):
        pass
        LivePositionAggregateRiskSource({"OTHER": LivePositionAggregate("OPT-1")}).snapshot()
