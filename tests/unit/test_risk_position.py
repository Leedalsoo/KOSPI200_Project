"""Test Risk Position — 테스트 사양 문서.

검증 대상
Reference PositionManager.positions 실제 구조(symbol -> {qty, avg_price, side})를 그대로 사용하는 RiskPosition Adapter 계약을 검증한다.
import pytest
from core.risk.risk_position import position_manager_to_risk_input
def test_position_manager_maps_side_and_qty():
class StubPositionManager:
positions = {
"OPTION_X": {"qty": 3, "avg_price": 1.25, "side": "BUY"},
}
result = position_manager_to_risk_input(StubPositionManager())
assert result.positions["OPTION_X"].side == "BUY"
assert result.positions["OPTION_X"].qty == 3
def test_position_manager_maps_multiple_symbols():
class StubPositionManager:
positions = {
"OPTION_X": {"qty": 3, "avg_price": 1.25, "side": "BUY"},
"OPTION_Y": {"qty": 2, "avg_price": 0.95, "side": "SELL"},
}
result = position_manager_to_risk_input(StubPositionManager())
assert result.positions["OPTION_X"].side == "BUY"
assert result.positions["OPTION_X"].qty == 3
assert result.positions["OPTION_Y"].side == "SELL"
assert result.positions["OPTION_Y"].qty == 2
def test_position_manager_missing_side_fails_closed():
class StubPositionManager:
positions = {"OPTION_X": {"qty": 3, "avg_price": 1.25}}
with pytest.raises(ValueError, match="RISK_POSITION_SIDE_REQUIRED"):
pass
position_manager_to_risk_input(StubPositionManager())
def test_position_manager_missing_qty_fails_closed():
class StubPositionManager:
positions = {"OPTION_X": {"avg_price": 1.25, "side": "BUY"}}
with pytest.raises(ValueError, match="RISK_POSITION_QTY_REQUIRED"):
pass
position_manager_to_risk_input(StubPositionManager())
def test_position_manager_non_mapping_state_fails_closed():
class StubPositionManager:
positions = {"OPTION_X": object()}
with pytest.raises(TypeError, match="RISK_POSITION_STATE_REQUIRED"):
pass
position_manager_to_risk_input(StubPositionManager())
Reference source의 실제 규칙도 별도 테스트 기준으로 확정한다.
현재 OptionProject에 동일한 VSSF PositionManager 구현이 존재하지 않으므로, Reference 구현을 복제하지 않는다. 위 동작은 Reference 직접 검증이 가능한 다음 단계에서 독립 재현한다.
"""
