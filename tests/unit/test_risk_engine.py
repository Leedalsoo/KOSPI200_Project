from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID
from contracts.risk import RiskApprovalToken
from core.risk.risk_config import RiskConfig
from core.risk.risk_engine import RiskEngine, RiskGate
from core.risk.risk_input import RiskAccountInput, RiskPosition, RiskPositionInput
from core.risk.risk_sensor import RiskSensorSnapshot

@dataclass(frozen=True)
class Command:
    client_order_id: str = "order-1"; track_id: str = "track1"; qty: int = 2; price: float = 1.0; side: str = "BUY"; tag_id: str = ""
    def get_instrument_key(self) -> str: return "OPTION_X"
class Margin:
    def calculate_order_margin(self, command): return command.price * command.qty * 250000.0
def account(*, cash=10_000_000, realized=0, used=0, free=10_000_000): return RiskAccountInput(Decimal(str(cash)), Decimal(str(realized)), Decimal(str(used)), Decimal(str(free)))
def test_kill_switch_denies_before_other_rules():
    e=RiskEngine(margin_engine=Margin()); e.trigger_kill_switch(); assert e.evaluate_order(Command(qty=0),account()).rejection_reason=="REJECTED_BY_KILL_SWITCH"
def test_qty_validation_and_max_are_preserved():
    e=RiskEngine(RiskConfig(max_order_qty=3),Margin()); assert "INVALID_ORDER_QTY" in e.evaluate_order(Command(qty=0),account()).rejection_reason; assert "EXCEEDED_MAX_ORDER_QTY" in e.evaluate_order(Command(qty=4),account()).rejection_reason
def test_daily_loss_uses_recorded_loss_plus_negative_account_pnl():
    e=RiskEngine(RiskConfig(max_daily_loss_krw=100),Margin()); e.record_realized_loss(-40); assert e.evaluate_order(Command(),account(realized=-60)).rejection_reason.startswith("EXCEEDED_MAX_DAILY_LOSS")
def test_position_limit_can_reduce():
    e=RiskEngine(RiskConfig(max_position_per_instrument=5),Margin()); r=e.evaluate_order(Command(qty=3),account(),RiskPositionInput({"OPTION_X":RiskPosition("BUY",4)}),allow_reduction=True); assert (r.decision,r.approved_qty,r.reduced_command.qty)==("REDUCE",1,1)
def test_position_limit_denies_without_reduction():
    e=RiskEngine(RiskConfig(max_position_per_instrument=5),Margin()); assert e.evaluate_order(Command(qty=3),account(),RiskPositionInput({"OPTION_X":RiskPosition("BUY",4)})).rejection_reason.startswith("EXCEEDED_INSTRUMENT_LIMIT")
def test_free_margin_can_reduce_and_recalculates_margin():
    e=RiskEngine(margin_engine=Margin()); r=e.evaluate_order(Command(qty=4),account(free=500_000),allow_reduction=True); assert (r.decision,r.approved_qty,r.required_margin)==("REDUCE",2,500_000)
def test_free_margin_denies_when_reduction_disabled():
    e=RiskEngine(margin_engine=Margin()); assert e.evaluate_order(Command(qty=4),account(free=500_000)).rejection_reason.startswith("INSUFFICIENT_FREE_MARGIN")
def test_margin_ratio_denies_after_margin_calculation():
    e=RiskEngine(RiskConfig(max_margin_utilization_ratio=.5),Margin()); assert e.evaluate_order(Command(qty=3),account(cash=1_000_000,used=300_000,free=1_000_000)).rejection_reason.startswith("EXCEEDED_MAX_MARGIN_RATIO")
def test_margin_diet_blocks_non_hedge_but_allows_risk_hedge():
    e=RiskEngine(margin_engine=Margin()); s=RiskSensorSnapshot(is_margin_diet_required=True,reason="MARGIN_DIET_TRIGGERED"); assert e.evaluate_order(Command(),account(),sensor_snapshot=s).rejection_reason.startswith("MARGIN_DIET_ACTIVE"); assert e.evaluate_order(Command(tag_id="RISK_HEDGE"),account(),sensor_snapshot=s).is_approved
def test_allow_issues_standard_token_without_legacy_dependency():
    r=RiskEngine(margin_engine=Margin()).evaluate_order(Command(),account()); assert r.is_approved and r.decision=="ALLOW" and isinstance(r.token,RiskApprovalToken) and isinstance(r.token.order_id,UUID) and r.reduced_command is None
def test_risk_gate_preserves_last_result_and_returns_token():
    g=RiskGate(RiskEngine(margin_engine=Margin())); a,t,reason=g.admit_order(Command(),account()); assert a and t is not None and reason is None and g.last_evaluation_result is not None
def test_expected_position_preserves_reference_side_qty_rules():
    e=RiskEngine(margin_engine=Margin()); p=RiskPositionInput({"OPTION_X":RiskPosition("BUY",3)}); assert e.calculate_expected_position(Command(qty=2,side="BUY"),p)["qty"]==5; assert e.calculate_expected_position(Command(qty=2,side="SELL"),p)["qty"]==1; assert e.calculate_expected_position(Command(qty=3,side="SELL"),p)=={"instrument_key":"OPTION_X","side":"FLAT","qty":0}; assert e.calculate_expected_position(Command(qty=5,side="SELL"),p)=={"instrument_key":"OPTION_X","side":"SELL","qty":2}

def test_invalid_risk_config_cannot_construct_risk_engine():
    import pytest
    with pytest.raises(ValueError, match="MAX_DAILY_LOSS_KRW_POSITIVE_REQUIRED"):
        pass
        RiskEngine(RiskConfig(max_daily_loss_krw=0), Margin())


def test_valid_decimal_risk_config_constructs_engine_and_preserves_threshold():
    config = RiskConfig(max_margin_utilization_ratio=Decimal("0.850000000000000001"))
    engine = RiskEngine(config, Margin())
    assert engine.config.max_margin_utilization_ratio == Decimal("0.850000000000000001")
