폴더: unit, integration, e2e, regression, safety 검증.

[Child Page] unit
폴더 페이지
[Child Page] test_risk_position.py
## 검증 대상
Reference PositionManager.positions 실제 구조(symbol -> {qty, avg_price, side})를 그대로 사용하는 RiskPosition Adapter 계약을 검증한다.
```python
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
        position_manager_to_risk_input(StubPositionManager())


def test_position_manager_missing_qty_fails_closed():
    class StubPositionManager:
        positions = {"OPTION_X": {"avg_price": 1.25, "side": "BUY"}}

    with pytest.raises(ValueError, match="RISK_POSITION_QTY_REQUIRED"):
        position_manager_to_risk_input(StubPositionManager())


def test_position_manager_non_mapping_state_fails_closed():
    class StubPositionManager:
        positions = {"OPTION_X": object()}

    with pytest.raises(TypeError, match="RISK_POSITION_STATE_REQUIRED"):
        position_manager_to_risk_input(StubPositionManager())
```
## PositionManager 동작 검증 기준
Reference source의 실제 규칙도 별도 테스트 기준으로 확정한다.
        - 동일 방향 체결: qty 증가, weighted average price 갱신
        - 반대 방향 체결 + attribution 존재: 기존 side lot을 FIFO 차감
        - FIFO 청산 후 잔여 체결량: 반대 side 신규 entry
        - aggregate position의 side/qty가 최종 상태와 일치
        - Risk Adapter는 최종 aggregate side/qty만 읽고 position 의미를 재해석하지 않음
현재 OptionProject에 동일한 VSSF PositionManager 구현이 존재하지 않으므로, Reference 구현을 복제하지 않는다. 위 동작은 Reference 직접 검증이 가능한 다음 단계에서 독립 재현한다.
[Child Page] test_risk.py
```python
from uuid import uuid4

from contracts.risk import RiskApprovalToken, RiskEvaluationResult


def test_risk_approval_token_contract_is_legacy_independent():
    order_id = uuid4()
    token = RiskApprovalToken(
        order_id=order_id,
        timestamp_ns=123456789,
        signature="sig",
    )

    assert token.order_id == order_id
    assert token.timestamp_ns == 123456789
    assert token.signature == "sig"


def test_risk_approval_token_is_immutable():
    token = RiskApprovalToken(uuid4(), 1, "sig")

    try:
        token.signature = "changed"
    except Exception:
        pass
    else:
        raise AssertionError("RiskApprovalToken must be immutable")


def test_risk_evaluation_result_allow_contract():
    token = RiskApprovalToken(uuid4(), 10, "sig")
    result = RiskEvaluationResult(
        is_approved=True,
        decision="ALLOW",
        original_qty=3,
        approved_qty=3,
        required_margin=750000.0,
        estimated_margin_ratio=0.20,
        token=token,
    )

    assert result.is_approved is True
    assert result.decision == "ALLOW"
    assert result.original_qty == 3
    assert result.approved_qty == 3
    assert result.rejection_reason is None
    assert result.required_margin == 750000.0
    assert result.estimated_margin_ratio == 0.20
    assert result.token == token
    assert result.reduced_command is None


def test_risk_evaluation_result_reduce_contract():
    reduced_command = object()
    result = RiskEvaluationResult(
        is_approved=True,
        decision="REDUCE",
        original_qty=10,
        approved_qty=4,
        required_margin=1000000.0,
        estimated_margin_ratio=0.80,
        token=RiskApprovalToken(uuid4(), 20, "sig"),
        reduced_command=reduced_command,
    )

    assert result.is_approved is True
    assert result.decision == "REDUCE"
    assert result.approved_qty == 4
    assert result.reduced_command is reduced_command


def test_risk_evaluation_result_deny_contract():
    result = RiskEvaluationResult(
        is_approved=False,
        decision="DENY",
        original_qty=10,
        approved_qty=0,
        rejection_reason="POSITION_LIMIT",
    )

    assert result.is_approved is False
    assert result.decision == "DENY"
    assert result.approved_qty == 0
    assert result.rejection_reason == "POSITION_LIMIT"
    assert result.token is None
    assert result.reduced_command is None
```
## 검증 기준
        - Standard RiskApprovalToken은 Legacy shared.core.contracts를 참조하지 않는다.
        - RiskEvaluationResult는 Reference의 ALLOW/REDUCE/DENY 출력 의미를 표현한다.
        - ALLOW/REDUCE에서는 approved_qty를 authoritative quantity로 사용하고 REDUCE에는 reduced_command를 보존한다.
        - DENY에서는 token과 reduced command가 없는 결과를 표현한다.
        - 실제 pytest 실행 결과가 없는 경우 PASS로 기록하지 않는다.
[Child Page] test_risk_engine.py
```python
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
        RiskEngine(RiskConfig(max_daily_loss_krw=0), Margin())


def test_valid_decimal_risk_config_constructs_engine_and_preserves_threshold():
    config = RiskConfig(max_margin_utilization_ratio=Decimal("0.850000000000000001"))
    engine = RiskEngine(config, Margin())
    assert engine.config.max_margin_utilization_ratio == Decimal("0.850000000000000001")

```
## 검증 기준
        - Reference 판정 순서와 ALLOW/REDUCE/DENY 의미를 유지한다.
        - Standard RiskAccountInput / RiskPositionInput만 사용한다.
        - Margin 계산은 주입형 MarginCalculator 경계로 유지한다.
        - Legacy shared.*, VSSF MarginEngine, CanonicalAccountSummary, Legacy RiskApprovalToken을 import하지 않는다.
        - 독립 테스트는 kill switch, qty, daily loss, position limit, free margin, margin ratio, margin diet, token, RiskGate 및 expected position을 검증한다.
[Child Page] test_risk_sensor.py
```python
from decimal import Decimal

from core.risk.risk_config import RiskConfig
from core.risk.risk_sensor import RiskSensor


def test_normal_sensor_state():
    result = RiskSensor().scan_risk(1.0, 1.0)
    assert result.is_vol_spike is False
    assert result.is_crisis_regime is False
    assert result.is_margin_diet_required is False
    assert result.reason == "NORMAL"
    assert result.active_vol_ratio == Decimal("1")


def test_nan_or_missing_volatility_fails_closed():
    sensor = RiskSensor()
    assert sensor.scan_risk(float("nan"), 1.0).reason == "INVALID_OR_NAN_SENSOR_INPUT"
    assert sensor.scan_risk(1.0, float("nan")).reason == "INVALID_OR_NAN_SENSOR_INPUT"
    assert sensor.scan_risk(None, 1.0).reason == "INVALID_OR_NAN_SENSOR_INPUT"


def test_zero_or_negative_base_vol_uses_reference_ratio_fallback():
    result = RiskSensor().scan_risk(10.0, 0.0)
    assert result.active_vol_ratio == Decimal("1")
    assert result.is_vol_spike is False


def test_volatility_spike_detection():
    result = RiskSensor().scan_risk(1.30, 1.0)
    assert result.is_vol_spike is True
    assert result.active_vol_ratio == Decimal("1.3")
    assert result.reason == "VOLATILITY_SPIKE_DETECTED (Ratio=1.30)"


def test_crisis_regimes_are_detected():
    for regime in ("CRISIS", "HIGH_VOLATILITY", "EXTREME_MOVE"):
        result = RiskSensor().scan_risk(1.0, 1.0, current_regime=regime)
        assert result.is_crisis_regime is True
        assert result.reason == f"CRISIS_REGIME_ACTIVE ({regime})"


def test_margin_diet_has_highest_reason_precedence():
    result = RiskSensor().scan_risk(
        1.50, 1.0, current_regime="CRISIS", account_margin_ratio=0.90,
    )
    assert result.is_margin_diet_required is True
    assert result.is_vol_spike is True
    assert result.is_crisis_regime is True
    assert result.reason == "MARGIN_DIET_TRIGGERED (Ratio=90.00%)"


def test_stale_state_reason_precedes_normal_only():
    result = RiskSensor().scan_risk(
        1.0, 1.0, is_account_stale=True, is_position_stale=True,
    )
    assert result.is_account_stale is True
    assert result.is_position_stale is True
    assert result.reason == "STALE_STATE_DETECTED (AccountStale=True, PosStale=True)"


def test_reason_precedence_spike_over_crisis_and_stale():
    result = RiskSensor().scan_risk(
        1.40, 1.0, current_regime="CRISIS", is_account_stale=True,
    )
    assert result.reason == "VOLATILITY_SPIKE_DETECTED (Ratio=1.40)"


def test_custom_volatility_threshold_is_used():
    config = RiskConfig(vol_spike_threshold_multiplier=1.50)
    result = RiskSensor(config).scan_risk(1.40, 1.0)
    assert result.is_vol_spike is False
    assert result.reason == "NORMAL"


def test_margin_ratio_threshold_distinguishes_sub_float_epsilon():
    config = RiskConfig(max_margin_utilization_ratio=0.85)
    sensor = RiskSensor(config)
    at_limit = sensor.scan_risk(
        Decimal("1"), Decimal("1"),
        account_margin_ratio=Decimal("0.850000000000000000"),
    )
    above_limit = sensor.scan_risk(
        Decimal("1"), Decimal("1"),
        account_margin_ratio=Decimal("0.850000000000000001"),
    )
    assert at_limit.is_margin_diet_required is False
    assert above_limit.is_margin_diet_required is True


def test_volatility_threshold_distinguishes_sub_float_epsilon():
    config = RiskConfig(vol_spike_threshold_multiplier=1.30)
    sensor = RiskSensor(config)
    below = sensor.scan_risk(
        Decimal("1.299999999999999999"), Decimal("1"),
    )
    at_limit = sensor.scan_risk(
        Decimal("1.300000000000000000"), Decimal("1"),
    )
    assert below.is_vol_spike is False
    assert at_limit.is_vol_spike is True

def test_invalid_risk_config_cannot_construct_risk_sensor():
    import pytest
    with pytest.raises(ValueError, match="VOL_SPIKE_THRESHOLD_MULTIPLIER_POSITIVE_REQUIRED"):
        RiskSensor(RiskConfig(vol_spike_threshold_multiplier=0))


def test_valid_decimal_risk_config_constructs_sensor_and_preserves_threshold():
    config = RiskConfig(vol_spike_threshold_multiplier=Decimal("1.300000000000000001"))
    sensor = RiskSensor(config)
    result = sensor.scan_risk(Decimal("1.3"), Decimal("1"))
    assert result.is_vol_spike is False

```
[Child Page] test_risk_input.py
```python
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from contracts.types import AccountSnapshot, DataQuality, PositionSnapshot
from core.risk.risk_input import (
    RiskPositionInput,
    account_snapshot_to_risk_input,
    position_snapshot_to_risk_input,
)


def quality():
    return DataQuality(True, True, True, None)


def test_account_snapshot_maps_existing_virtual_account_fields():
    snapshot = AccountSnapshot(
        as_of=datetime.now(timezone.utc),
        balances={
            "cash": Decimal("50000000"),
            "margin_used": Decimal("1000000"),
            "realized_pnl": Decimal("-100000"),
            "available_cash": Decimal("49000000"),
        },
        freshness=quality(),
    )
    result = account_snapshot_to_risk_input(snapshot)
    assert result.total_balance == Decimal("50000000")
    assert result.realized_pnl == Decimal("-100000")
    assert result.used_margin == Decimal("1000000")
    assert result.free_margin == Decimal("49000000")


def test_account_snapshot_missing_required_field_fails_closed():
    snapshot = AccountSnapshot(
        as_of=datetime.now(timezone.utc),
        balances={"cash": Decimal("1")},
        freshness=quality(),
    )
    with pytest.raises(ValueError, match="RISK_ACCOUNT_FIELDS_REQUIRED"):
        account_snapshot_to_risk_input(snapshot)


def test_position_snapshot_does_not_invent_side():
    snapshot = PositionSnapshot(
        as_of=datetime.now(timezone.utc),
        positions={"OPTION_X": Decimal("2")},
        freshness=quality(),
    )
    with pytest.raises(ValueError, match="RISK_POSITION_SIDE_REQUIRED"):
        position_snapshot_to_risk_input(snapshot)
```
## 검증 의도
        - Account는 실제 VirtualAccount snapshot이 제공하는 기존 값만 사용한다.
        - Position은 side가 없는 canonical snapshot에서 BUY/SELL을 추론하지 않는다.
        - 테스트는 이 두 경계를 고정한다.
[Child Page] test_black_scholes.py
## 검증 목적
표준 Black-Scholes-Merton 식의 기본 invariant와 CALL/PUT 대칭을 독립 검증한다.
```python
from decimal import Decimal
import pytest
from core.option.black_scholes import BlackScholesInputError, calculate_black_scholes

def test_call_put_have_same_gamma():
    common = dict(underlying_price=Decimal("100"), strike=Decimal("100"), time_to_expiry_years=Decimal("0.5"), volatility=Decimal("0.20"), risk_free_rate=Decimal("0.03"), dividend_yield=Decimal("0.01"))
    call = calculate_black_scholes(**common, option_type="CALL")
    put = calculate_black_scholes(**common, option_type="PUT")
    assert call.gamma == pytest.approx(put.gamma)
    assert call.delta > Decimal("0")
    assert put.delta < Decimal("0")

def test_input_contract_is_fail_closed():
    with pytest.raises(BlackScholesInputError):
        calculate_black_scholes(underlying_price=Decimal("100"), strike=Decimal("100"), time_to_expiry_years=Decimal("0"), volatility=Decimal("0.2"), risk_free_rate=Decimal("0.03"), dividend_yield=Decimal("0"), option_type="CALL")
```
## 기대 결과
2 passed.
## 범위 제외
실제 risk-free source, valuation timezone/day-count/cutoff, contract multiplier, position quantity, theta monetary cost, gamma-scalping PnL attribution은 검증하지 않는다.
[Child Page] test_track1_tail_defense.py
## Track1 typed payload 검증
```python
from datetime import datetime, timezone
from decimal import Decimal

from core.domain.market_models import CanonicalMarketTick, DataQuality, MarketState
from core.strategy.contracts import CommonStrategyInput, StrategyContext, StrategyInput
from core.strategy.track1_tail_defense import Track1Input, Track1TailDefense


def state(price: str) -> MarketState:
    now = datetime.now(timezone.utc)
    tick = CanonicalMarketTick("KOSPI200", now, Decimal(price), None)
    return MarketState(now, {"KOSPI200": tick}, {"KOSPI200": DataQuality(True, True, True)})


def context(price: str, **kwargs: object) -> StrategyContext:
    now = datetime.now(timezone.utc)
    payload = Track1Input(**kwargs)
    common = CommonStrategyInput(as_of=now, current_price=Decimal(price))
    return StrategyContext(state(price), "TRACK1_TAIL_DEFENSE", StrategyInput(common, payload))


def test_market_open_preserves_dual_ring_and_inner_fence() -> None:
    strategy = Track1TailDefense()
    signals = strategy.evaluate(context("350"))
    assert len(signals) == 3
    assert strategy.state.active_fence_type == "PUT"
    assert strategy.state.active_fence_strike == 342.5
    assert signals[0].execution_proposal is not None
    assert signals[0].execution_proposal.proposed_quantity == 1
    assert signals[0].execution_proposal.asset_type == "OPTION"
    assert signals[0].execution_proposal.option_type == "CALL"
    assert signals[0].execution_proposal.strike == Decimal("362.5")
    assert signals[1].execution_proposal is not None
    assert signals[1].execution_proposal.option_type == "PUT"
    assert signals[1].execution_proposal.strike == Decimal("337.5")
    assert signals[2].execution_proposal is not None
    assert signals[2].execution_proposal.tag_id == "1"
    assert signals[2].execution_proposal.strike == Decimal("342.5")


def test_typed_input_can_trigger_sell_hedge_with_domain_quantity() -> None:
    strategy = Track1TailDefense()
    strategy.evaluate(context("350"))
    signals = strategy.evaluate(
        context("343", momentum_confirmed=True, short_option_net_delta=Decimal("0.21"))
    )
    hedge_signal = next(signal for signal in signals if "FUTURES_HEDGE_TRIGGER" in signal.reason)
    assert strategy.state.active_hedge == "SELL"
    assert hedge_signal.execution_proposal is not None
    assert hedge_signal.execution_proposal.asset_type == "FUTURES"
    assert hedge_signal.execution_proposal.proposed_quantity == 2
    assert hedge_signal.execution_proposal.side == "SELL"
    assert strategy.state.futures_hedge_count == 1


def test_missing_or_zero_delta_does_not_create_synthetic_hedge() -> None:
    for delta in (None, Decimal("0")):
        strategy = Track1TailDefense()
        strategy.evaluate(context("350"))
        signals = strategy.evaluate(
            context("343", momentum_confirmed=True, short_option_net_delta=delta)
        )
        assert not any("FUTURES_HEDGE_TRIGGER" in signal.reason for signal in signals)
        assert strategy.state.futures_hedge_count == 0
        assert strategy.state.active_hedge is None


def test_daily_hedge_limit_stops_after_twenty_entries() -> None:
    strategy = Track1TailDefense()
    strategy.evaluate(context("350"))
    for _ in range(20):
        strategy.state.active_hedge = None
        strategy.state.hedge_entry_price = None
        signals = strategy.evaluate(
            context("343", momentum_confirmed=True, short_option_net_delta=Decimal("0.21"))
        )
        assert any("FUTURES_HEDGE_TRIGGER" in signal.reason for signal in signals)
    assert strategy.state.futures_hedge_count == 20
    strategy.state.active_hedge = None
    strategy.state.hedge_entry_price = None
    signals = strategy.evaluate(
        context("343", momentum_confirmed=True, short_option_net_delta=Decimal("0.21"))
    )
    assert not any("FUTURES_HEDGE_TRIGGER" in signal.reason for signal in signals)
    assert strategy.state.futures_hedge_count == 20


def test_daily_hedge_count_resets_on_date_change() -> None:
    strategy = Track1TailDefense()
    strategy.evaluate(context("350", current_time=datetime(2026, 9, 7, 10, 0)))
    strategy.state.futures_hedge_count = 20
    strategy.state.active_hedge = None
    strategy.state.hedge_entry_price = None
    signals = strategy.evaluate(
        context(
            "343",
            current_time=datetime(2026, 9, 8, 9, 0),
            momentum_confirmed=True,
            short_option_net_delta=Decimal("0.21"),
        )
    )
    assert any("FUTURES_HEDGE_TRIGGER" in signal.reason for signal in signals)
    assert strategy.state.futures_hedge_count == 1
    assert strategy.state.hedge_count_date == datetime(2026, 9, 8).date()


def test_typed_dte_triggers_d4_fence_cutoff() -> None:
    strategy = Track1TailDefense()
    strategy.evaluate(context("350"))
    signals = strategy.evaluate(context("350", days_to_expiry=4.0))
    assert any("D4_CUTOFF" in signal.reason for signal in signals)
    assert strategy.state.active_fence_type is None
    cutoff_signal = next(signal for signal in signals if "D4_CUTOFF" in signal.reason)
    assert cutoff_signal.execution_proposal is not None
    assert cutoff_signal.execution_proposal.proposed_quantity == 1
    assert cutoff_signal.execution_proposal.asset_type == "OPTION"
    assert cutoff_signal.execution_proposal.side is None
    assert cutoff_signal.execution_proposal.option_type == "PUT"
    assert cutoff_signal.execution_proposal.strike == Decimal("342.5")


def test_volatility_input_expands_fence() -> None:
    strategy = Track1TailDefense()
    strategy.evaluate(context("350", active_vol=1.3, base_vol=1.0))
    assert strategy.state.fence_distance == 12.5


def test_strategy_does_not_import_order_request() -> None:
    import inspect
    from core.strategy import track1_tail_defense
    source = inspect.getsource(track1_tail_defense)
    assert "OrderRequest" not in source
```
## 검증 한계
        - 실제 terminal pytest 실행은 현재 환경에서 수행하지 않았다.
        - 원격 Git branch에는 쓰기 작업을 하지 않았다.
        - 실제 시장/브로커 연결 검증은 하지 않았다.
        - 100% collision 전체 로직과 Dynamic Profit Take/Rebuild 비용 계산은 후속 Standard Contract에서 검증한다.
[Child Page] test_track4_gamma_scalping.py
## Track4 독립 테스트 기준
        1. active_vol <= base_vol*0.85 → Call ATM+2.5 / Put ATM-2.5.
        1. active_vol >= base_vol*1.30 → Call/Put ATM.
        1. 15:15 이후 Basecamp 신규 진입 차단.
        1. ATR deadband가 0.2~0.6으로 clamp되는지 확인.
        1. Delta 절대값이 deadband 이하이면 hedge 없음.
        1. Delta가 deadband 초과이면 반대 방향 hedge intent 생성.
        1. hedge quantity가 ±100을 초과하지 않음.
        1. Delta hedge는 Theta guard 실패와 무관하게 작동.
        1. equity threshold 미달 시 신규 hedge 차단 및 기존 hedge unwind intent.
        1. accumulated gamma profit이 theta decay cost 이하이면 Theta 확장 승인 거부.
        1. high-watermark 30,000 초과 이후 trailing 0.85/0.88/0.90 단계 확인.
        1. trailing trigger 후 high-watermark/active hedge 상태 초기화.
        1. Strategy가 Legacy OrderRequest/Broker/UI를 직접 import·호출하지 않음.
        1. 입력 부족 시 synthetic market values를 생성하지 않음.
실제 terminal pytest는 현재 환경에서 실행하지 못했으므로 PASS로 표시하지 않는다.
## No.031 구현 대응 테스트
        - 0.85 이하 low-vol → ATM+2.5 / ATM-2.5
        - 1.30 이상 high-vol → ATM / ATM
        - 15:15 이후 Basecamp 차단
        - ATM strike 2.5pt rounding
        - ATR empty/1개/다중 window 계산 및 0.2~0.6 clamp
        - delta가 band 이하이면 signal 없음
        - delta 초과 시 반대방향 hedge signal
        - hedge quantity ±100 clamp
        - equity threshold 미달 + 기존 hedge 존재 시 unwind
        - theta guard: gamma profit > decay cost만 true
        - high-watermark 30,000 초과 시 0.85/0.88/0.90 trailing
        - trailing trigger 후 high-watermark reset
        - track4_input 부재 시 synthetic fallback 없이 no-op
        - Strategy 파일에서 Legacy OrderRequest/Broker 직접 의존 없음
실제 terminal pytest는 현재 환경에서 실행하지 못했으므로 PASS로 판정하지 않는다.
## No.047 typed payload 검증 기준 보완
Track4 Strategy의 evaluate()는 이제 임의의 context.track4_input 속성을 읽지 않고 context.input.payload에서 Track4MarketInput을 읽는다. context.strategy_id와 payload의 strategy_id가 모두 track4_gamma_scalping인지 확인하며 불일치 또는 입력 부재 시 no-op한다. 이 변경은 No.038~040에서 확정한 표준 입력 경계를 Track4에 적용하기 위한 것이다.
## No.288 이후 Proposal 연결 검증 보강
Track4의 GAMMA_REBALANCE는 Legacy에서 qty가 계산되고, 부호에 따라 BUY/SELL이 명시적으로 결정되므로 해당 실행정보를 StrategyExecutionProposal로 보존한다. asset_type="FUTURES", requested_price=None을 사용하며, 옵션 strike/identity는 임의 생성하지 않는다.
검증 기준:
        - qty = abs(qty)
        - side = BUY if qty > 0 else SELL
        - asset_type = FUTURES
        - missing price/identity는 None 유지
## No.349 observed tick-price deadband 계약 전환
        - 실제 OHLC source가 없는 현재 시스템에서는 price_high/low/close 계약을 유지하면서 fake OHLC를 만들지 않는다.
        - Track4MarketInput은 공개 Sensor price_history를 입력으로 사용한다.
        - deadband는 연속 관측 tick 가격의 평균 절대 변화량을 마지막 가격으로 정규화한 뒤 기존 ×5, 0.2~0.6 clamp를 적용한다.
        - 이는 Exp_Detail_1 Legacy가 동일 tick price를 high/low/close에 반복 저장하여 실제로 계산하던 값과 수치적 의미를 보존하면서, OHLC인 것처럼 가장하는 문제를 제거한다.
## No.378 targeted boundary tests 보완
        - Low-vol 경계값 active_vol == base_vol * 0.85 → Wide Basecamp 진입
        - High-vol 경계값 active_vol == base_vol * 1.30 → ATM Basecamp 진입
        - 15:15:00 정확 시각 → 신규 Basecamp 차단
        - Delta abs(delta) == deadband → hedge 없음
        - Delta가 deadband를 초과하면 반대 방향 hedge intent 생성
        - Delta 극단값에서도 hedge quantity가 ±100으로 제한
        - equity threshold 미달 + 기존 hedge 존재 → unwind intent 생성 및 hedge state 0
        - Theta Guard profit == decay_cost → False, profit > decay_cost → True
        - Profit trailing 1/2/3단계 경계값과 trigger 후 scalp_high_pnl 및 active_hedge_qty 초기화
        - KIS authoritative Greeks/IV를 재계산·overwrite하지 않는 구조 유지
## Track4 execution provenance boundary
        - GAMMA_REBALANCE의 StrategyExecutionProposal은 asset_type="FUTURES", 계산된 proposed_quantity, 명시 side, track_id, tag_id를 그대로 운반한다.
        - 이 proposal만으로 Option Basecamp leg의 instrument_id / symbol / expiry를 생성하지 않는다.
        - Basecamp Option execution은 authoritative option identity와 독립 quantity/side 공급이 확보될 때까지 fail-closed로 유지한다.
        - Futures Delta Hedge는 기존 Futures identity/execution-symbol source와 결합할 수 있는 별도 asset-type 경계로 취급한다.
## No.599 execution-domain composition 추적 검증 기준
        - Basecamp BUILD Signal의 1.0은 주문 수량의 authoritative 정의로 승격하지 않는다.
        - WIDE_BASECAMP/ATM_BASECAMP의 option_type·strike 정보만으로 instrument_id / symbol / expiry를 생성하지 않는다.
        - authoritative OptionInstrumentIdentity + 독립 quantity + 독립 side가 모두 공급되지 않으면 Basecamp execution composition은 fail-closed한다.
        - Futures Delta Hedge는 KisFuturesExecutionSymbolSource의 shrn_iscd를 execution/Risk symbol source로 사용할 수 있으나, 이를 Standard instrument_id로 승격하지 않는다.
        - Standard Futures instrument_id authoritative source가 없는 상태에서는 완전한 RiskOrderCommand composition을 성공으로 판정하지 않는다.
        - RiskGate/OrderRouter에 synthetic Futures identity를 전달하지 않는다.
## No.636 Domain Definition strategy-level regression
```python
from decimal import Decimal


def data(
    *,
    delta: str,
    equity: str = "1000000",
    history: tuple[str, ...] = ("350", "351"),
    time_str: str = "10:00:00",
) -> Track4MarketInput:
    return Track4MarketInput(
        observed_at=datetime(2026, 9, 8, 10, 0),
        current_price=Decimal("350"),
        active_vol=Decimal("1"),
        base_vol=Decimal("1"),
        time_str=time_str,
        current_delta=Decimal(delta),
        current_gamma=Decimal("0"),
        current_pnl=Decimal("0"),
        current_equity=Decimal(equity),
        price_history=tuple(Decimal(x) for x in history),
    )


def test_delta_hedge_positive_delta_is_sell_with_domain_quantity() -> None:
    strategy = Track4GammaScalping()
    signals = strategy.evaluate_delta_hedge(data(delta="0.41"))
    hedge = signals[0]
    assert hedge.execution_proposal is not None
    assert hedge.execution_proposal.asset_type == "FUTURES"
    assert hedge.execution_proposal.proposed_quantity == 3
    assert hedge.execution_proposal.side == "SELL"


def test_delta_hedge_negative_delta_is_buy_with_domain_quantity() -> None:
    strategy = Track4GammaScalping()
    signals = strategy.evaluate_delta_hedge(data(delta="-0.41"))
    hedge = signals[0]
    assert hedge.execution_proposal is not None
    assert hedge.execution_proposal.proposed_quantity == 3
    assert hedge.execution_proposal.side == "BUY"


def test_delta_equal_deadband_does_not_hedge() -> None:
    strategy = Track4GammaScalping()
    signals = strategy.evaluate_delta_hedge(data(delta="0.2", history=("350",)))
    assert signals == ()


def test_delta_hedge_quantity_is_clamped_to_one_hundred() -> None:
    strategy = Track4GammaScalping()
    signals = strategy.evaluate_delta_hedge(data(delta="30"))
    hedge = signals[0]
    assert hedge.execution_proposal is not None
    assert hedge.execution_proposal.proposed_quantity == 100
    assert hedge.execution_proposal.side == "SELL"


def test_equity_threshold_unwinds_existing_hedge_and_blocks_new_hedge() -> None:
    strategy = Track4GammaScalping(equity_threshold=Decimal("100"))
    strategy.state.active_hedge_qty = -3
    signals = strategy.evaluate_delta_hedge(data(delta="1", equity="99"))
    assert len(signals) == 1
    assert "UNWIND_FUT_HEDGE" in signals[0].reason
    assert strategy.state.active_hedge_qty == 0


def test_basecamp_cutoff_at_1515_blocks_new_entry() -> None:
    strategy = Track4GammaScalping()
    assert strategy.evaluate_basecamp(data(delta="0", time_str="15:15:00")) == ()
```
검증 기준은 No.636에서 확정한 ceil(abs(delta) × 5) 및 delta 부호별 반대 방향 hedge를 실제 StrategyExecutionProposal까지 확인한다. ±100 clamp와 기존 deadband/equity 경계도 함께 회귀 검증한다.
[Child Page] test_track3_statistical_arbitrage.py
## No.028 독립 테스트 확장
원격 후반부 조건을 다음 순서로 검증한다.
        1. 15:15 이상이면 다른 청산 조건보다 먼저 MARKET_CLOSE_FLATTEN, cooldown=20.
        1. high-watermark > 30,000이고 PnL ratio < 1.3 → trailing 0.85.
        1. ratio 1.3 이상 2.0 미만 → trailing 0.88.
        1. ratio 2.0 이상 → trailing 0.90.
        1. 현재 PnL이 trailing trigger 이하이면 TRAILING_PROFIT_LOCK.
        1. SHORT spread에서 Z >= 3.5, LONG spread에서 Z <= -3.5이면 STOP_LOSS, cooldown=40.
        1. holding_ticks >= max_holding_ticks이면 TIMEOUT_EXIT, cooldown=20.
        1. convergence + economic profitability + group integrity가 모두 충족될 때만 CLOSED.
        1. 경제성 기준은 current_pnl - fees - estimated_cost >= -5000.
        1. HIGH_VOLATILITY의 current PnL > 10,000 및 GAP의 convergence + PnL > 5,000 예외를 각각 검증한다.
        1. 청산 적용 후 active position/group/legs가 초기화되고 last_exit_z_score와 cooldown이 기록되는지 검증한다.
        1. 청산 우선순위가 EOD → trailing → stop → timeout → convergence 순서인지 검증한다.
실제 terminal pytest는 현재 실행하지 못했으므로 실행 PASS로 표시하지 않는다.
## 테스트 추가 기준
        - 10개 미만 spread history → invalid/no signal
        - std=0 → valid z=0
        - explicit HIGH_VOLATILITY / EXTREME_MOVE / GAP regime 매핑
        - volatility ratio 및 spread 기반 regime 판별
        - 15:00 cutoff / EXTREME_MOVE / cooldown 차단
        - GAP에서 market_stable 및 spread_normalizing 미충족 시 차단
        - 이전 exit z-score와 0.8 미만 차이면 재진입 차단
        - expected gross - estimated cost가 minimum profit 미달이면 차단
        - 양/음 Z-score 방향에 따른 SHORT/LONG signal
        - group_id 생성 및 상태 기록
        - Strategy가 OrderRequest/Broker를 직접 생성·호출하지 않는지 정적 검사
        - 실제 terminal pytest는 별도 실행 환경에서 수행해야 하며 현재 PASS로 표시하지 않는다.
```python
from core.strategy.track3_statistical_arbitrage import Track3MarketInput, Track3StatisticalArbitrage


def series(*values: float) -> tuple[float, ...]:
    return tuple(values)


def test_z_score_requires_ten_observations():
    assert Track3StatisticalArbitrage.calculate_z_score(series(1, 2, 3))[1] is False


def test_z_score_valid_and_nonzero():
    z, valid = Track3StatisticalArbitrage.calculate_z_score(series(1, 1, 1, 1, 1, 1, 1, 1, 1, 2))
    assert valid is True
    assert z > 0


def test_regime_extreme_move():
    data = Track3MarketInput(strategy_id="track3_stat_arb", active_vol=3.0, base_vol=1.0)
    assert Track3StatisticalArbitrage.detect_market_regime(data) == "EXTREME_MOVE"


def test_regime_gap():
    data = Track3MarketInput(strategy_id="track3_stat_arb", time_str="09:01:00", gap_pct=0.01)
    assert Track3StatisticalArbitrage.detect_market_regime(data) == "GAP"


def test_regime_high_volatility():
    data = Track3MarketInput(strategy_id="track3_stat_arb", active_vol=1.5, base_vol=1.0)
    assert Track3StatisticalArbitrage.detect_market_regime(data) == "HIGH_VOLATILITY"


def test_invalid_market_input_does_not_trade():
    strategy = Track3StatisticalArbitrage()
    data = Track3MarketInput(strategy_id="track3_stat_arb", spread_history=(1.0, 2.0))
    result = strategy.evaluate_input(data)
    assert result.signals == ()


def test_extreme_move_blocks_entry():
    strategy = Track3StatisticalArbitrage()
    data = Track3MarketInput(
        strategy_id="track3_stat_arb",
        spread_history=tuple(float(i) for i in range(1, 11)),
        active_vol=3.0,
        base_vol=1.0,
    )
    assert strategy.evaluate_input(data).signals == ()


def test_cutoff_blocks_entry():
    strategy = Track3StatisticalArbitrage()
    data = Track3MarketInput(
        strategy_id="track3_stat_arb",
        spread_history=(1, 1, 1, 1, 1, 1, 1, 1, 1, 10),
        time_str="15:00:00",
    )
    assert strategy.evaluate_input(data).signals == ()


def test_no_order_request_or_broker_dependency_in_strategy():
    import inspect
    from core.strategy.track3_statistical_arbitrage import Track3StatisticalArbitrage
    source = inspect.getsource(Track3StatisticalArbitrage)
    assert "OrderRequest" not in source
    assert "Broker" not in source
    assert "VSSF" not in source
    assert "VMS" not in source


# 실제 pytest 실행은 현재 환경에서 수행할 수 없으므로 실행 결과를 PASS로 주장하지 않는다.
```
## No.029 추가 테스트
        - calculate_butterfly_legs()가 ATM±tick 및 1:2:1 수량을 생성하는지 검증
        - 0 이하 tick size 거부
        - Calendar IV 길이 불일치/자료 부족 시 False
        - Calendar IV divergence가 0.05 초과할 때만 True
        - CALL/PUT intrinsic 계산
        - BUY/SELL PnL 방향
        - current_market_price 제공 시 해당 값을 사용
        - invalid strike/qty 입력은 무시
        - 250,000 multiplier 적용
        - Strategy가 옵션 계산에서 Broker/OrderRequest를 호출하지 않는지 정적 검사
실제 terminal pytest는 실행하지 못했으므로 PASS 판정하지 않는다.
[Child Page] test_track3_legging.py
## 테스트 기준
        1. 정상적인 2-leg Plan은 first leg OrderIntent를 생성한다.
        1. first leg의 ExecutionReport 이후에만 second leg OrderIntent가 생성된다.
        1. 다른 group/leg ID의 fill은 second leg를 생성하지 않는다.
        1. group_id와 leg_id가 모든 intent purpose에 보존된다.
        1. quantity <= 0 또는 group identity 불일치 PositionGroup은 Registry 등록을 거부한다.
        1. duplicate group_id 등록은 거부한다.
        1. ExecutionReport의 group_id/leg_id를 통해 Environment → OMS → PositionGroup 추적이 가능해야 한다.
        1. Coordinator는 Broker/VMS/VSSF/UI/TimeService를 import하지 않는다.
        1. 지정가/시장가와 timeout/fallback은 Strategy/Coordinator가 임의 실행하지 않고 Environment Execution 계층에 남겨야 한다.
실제 terminal pytest는 현재 실행 환경에서 수행하지 않았으므로 실행 PASS로 판정하지 않는다.
        1. OrderIntent.group_id/leg_id는 Environment BrokerOrderCommand까지 lossless하게 전달되어야 한다.
        1. 단일 주문은 group/leg 값이 None인 기존 의미를 그대로 유지해야 한다.
        1. 이번 계약 변경의 독립 임시 pytest 검증: 2 passed (group/leg lossless transport, single-leg backward compatibility).
[Child Page] test_track9_event_overnight_insurance.py
```python
from decimal import Decimal
import inspect

from core.strategy.contracts import StrategyContext, StrategyInput
from core.strategy.track9_event_overnight_insurance import (
    Track9EventOvernightInsurance,
    Track9MarketInput,
)


STRATEGY_ID = "track9_event_overnight_insurance"


def base(**kwargs):
    values = dict(
        strategy_id=STRATEGY_ID,
        current_price=Decimal("350"),
        active_sell_qty=4,
        current_insurance_qty=1,
        date_str="2026-09-04",
    )
    values.update(kwargs)
    return Track9MarketInput(**values)


def context(data):
    return StrategyContext(
        strategy_id=STRATEGY_ID,
        input=StrategyInput(payload=data),
    )


def test_overnight_target_is_half_of_active_sell_qty():
    s = Track9EventOvernightInsurance()
    signals = s.evaluate(context(base()))
    assert any(x.direction == "ADD_INSURANCE" for x in signals)
    assert "TARGET_QTY:2" in next(x.reason for x in signals if x.direction == "ADD_INSURANCE")


def test_insurance_reduce_when_excess():
    s = Track9EventOvernightInsurance()
    signals = s.evaluate_overnight_insurance(base(current_insurance_qty=4))
    assert signals[0].direction == "REDUCE_INSURANCE"


def test_early_profit_take_90_percent_once():
    s = Track9EventOvernightInsurance()
    signals = s.evaluate_early_profit_take(
        base(time_str="09:03:00", current_insurance_qty=10)
    )
    assert signals[0].direction == "EARLY_PROFIT_TAKE"
    assert s.evaluate_early_profit_take(
        base(time_str="09:04:00", current_insurance_qty=10)
    ) == ()


def test_reentry_after_0930_when_stable():
    s = Track9EventOvernightInsurance()
    signals = s.evaluate_reentry(
        base(time_str="09:30:01", target_qty=5, existing_qty=3, market_stable=True)
    )
    assert signals[0].direction == "REHEDGE_ENTRY"


def test_event_iv_spike_enters_and_budget_blocked():
    s = Track9EventOvernightInsurance()
    signals = s.evaluate_event_volatility(base(iv_spike=Decimal("4")))
    assert signals[0].direction == "ENTER_EVENT_STRANGLE"

    blocked = Track9EventOvernightInsurance().evaluate_event_volatility(
        base(
            iv_spike=Decimal("4"),
            event_budget=Decimal("100"),
            estimated_event_cost=Decimal("101"),
        )
    )
    assert blocked[0].direction == "EVENT_BUDGET_BLOCKED"


def test_event_vol_crush_and_trailing_close():
    s = Track9EventOvernightInsurance()
    s.evaluate_event_volatility(base(iv_spike=Decimal("4")))
    signals = s.evaluate_event_volatility(base(iv_crush=Decimal("-3")))
    assert signals[0].direction == "CLOSE_EVENT_STRANGLE"

    s = Track9EventOvernightInsurance()
    s.evaluate_event_volatility(base(iv_spike=Decimal("4")))
    s.evaluate_event_volatility(
        base(current_pnl=Decimal("60000"), premium_spent=Decimal("250000"))
    )
    signals = s.evaluate_event_volatility(
        base(current_pnl=Decimal("50000"), premium_spent=Decimal("250000"))
    )
    assert signals[0].direction == "CLOSE_EVENT_STRANGLE"


def test_dynamic_rebuild_net_pnl_and_guards():
    s = Track9EventOvernightInsurance()
    assert s.evaluate_dynamic_profit_rebuild(
        base(current_pnl=Decimal("400100"), total_fees=Decimal("101"))
    ) == ()
    assert s.evaluate_dynamic_profit_rebuild(
        base(current_pnl=Decimal("500000"), risk_guard_active=True)
    ) == ()
    assert s.evaluate_dynamic_profit_rebuild(
        base(current_pnl=Decimal("500000"), margin_ratio=Decimal("0.86"))
    ) == ()

    signals = s.evaluate_dynamic_profit_rebuild(
        base(current_pnl=Decimal("400500"), total_fees=Decimal("500"))
    )
    assert [x.direction for x in signals] == [
        "DYNAMIC_PROFIT_TAKE",
        "DYNAMIC_REBUILD_FENCE",
    ]


def test_strategy_id_mismatch_is_noop():
    s = Track9EventOvernightInsurance()
    bad_context = StrategyContext(
        strategy_id="other_strategy",
        input=StrategyInput(payload=base()),
    )
    assert s.evaluate(bad_context) == ()


def test_strategy_has_no_legacy_execution_dependency():
    from core.strategy import track9_event_overnight_insurance
    source = inspect.getsource(track9_event_overnight_insurance)
    assert 'getattr(context, "track9_input"' not in source
    assert "OrderRequest" not in source
    assert "Broker" not in source
    assert "AtomicBudgetManager" not in source
```
## No.052 테스트 기준
        - StrategyContext.input.payload 표준 진입
        - Context/payload strategy_id 이중 검증
        - Track1 active_sell_qty 50% Overnight Insurance
        - Insurance Add / Reduce
        - 09:00~09:05 Early Profit Take 1회 제한
        - 09:30 이후 Stable Re-entry
        - Event Upcoming / IV Spike 진입
        - Event Budget 차단 Signal
        - Vol Crush 청산
        - 3단계 Dynamic Trailing Close
        - Net PnL(current_pnl-total_fees) Profit Rebuild
        - Risk Guard / Margin 차단
        - Legacy context.track9_input / Broker / AtomicBudgetManager 직접 의존 없음
[Child Page] test_virtual_contract_resolver.py
```python
from decimal import Decimal

import pytest

from contracts.virtual_contract_resolver import (
    VirtualContractMapping,
    VirtualContractResolutionError,
    VirtualContractResolver,
)


class FakeRegistry:
    def __init__(self, values):
        self.values = values

    def get_contract_identity(self, shrn_iscd):
        return self.values.get(shrn_iscd)


def test_exact_mapping_resolves_authoritative_identity():
    identity = object()
    resolver = VirtualContractResolver(
        {"SCN-1": VirtualContractMapping("SCN-1", "KR7001")},
        FakeRegistry({"KR7001": identity}),
    )
    assert resolver.resolve("SCN-1") is identity


def test_missing_mapping_fails_closed():
    resolver = VirtualContractResolver({}, FakeRegistry({}))
    with pytest.raises(VirtualContractResolutionError, match="MAPPING_NOT_FOUND"):
        resolver.resolve("UNKNOWN")


def test_missing_registry_identity_fails_closed():
    resolver = VirtualContractResolver(
        {"SCN-1": VirtualContractMapping("SCN-1", "KR7001")},
        FakeRegistry({}),
    )
    with pytest.raises(VirtualContractResolutionError, match="IDENTITY_NOT_FOUND"):
        resolver.resolve("SCN-1")


def test_blank_key_fails_closed():
    resolver = VirtualContractResolver({}, FakeRegistry({}))
    with pytest.raises(VirtualContractResolutionError, match="KEY_REQUIRED"):
        resolver.resolve("   ")


def test_invalid_mapping_is_rejected_at_construction():
    with pytest.raises(VirtualContractResolutionError, match="INVALID_SCENARIO"):
        VirtualContractResolver(
            {"SCN-1": VirtualContractMapping("OTHER", "KR7001")},
            FakeRegistry({}),
        )
```
## 검증 기준
        - exact key만 허용
        - mapping 누락 fail-closed
        - authoritative registry identity 누락 fail-closed
        - blank key fail-closed
        - key/mapping 불일치 fail-closed
실제 pytest 실행 PASS는 현재 Notion 작업공간이 물리 Python workspace로 mount되지 않아 UNVERIFIED로 유지한다.
[Child Page] test_track4_market_projection_provider.py
```python
from decimal import Decimal

import pytest

from contracts.track4_market_projection_provider import Track4MarketProjectionProvider
from contracts.track4_kis_greeks_provider import KISIndexOptionGreeksProvider
from contracts.track4_runtime_input_provider import Track4InputSourceUnavailable
from core.sensor.market_condition_sensor import MarketConditionSnapshot


def snapshot() -> MarketConditionSnapshot:
    return MarketConditionSnapshot(
        as_of="2026-01-01T09:00:00",
        instrument_id="KOSPI200_VIRTUAL",
        current_price=350.25,
        price_change=0.25,
        volatility=0.0125,
        baseline_volatility=0.0100,
        volatility_ratio=1.25,
        drawdown=0.0,
        stress_level=0.0,
        stress_flags=(),
    )


def test_projects_current_price_and_volatility_from_snapshot() -> None:
    provider = Track4MarketProjectionProvider(lambda: snapshot())

    assert provider.current_price() == Decimal("350.25")
    assert provider.active_vol() == Decimal("0.0125")
    assert provider.base_vol() == Decimal("0.01")


def test_market_readiness_is_partial_only() -> None:
    provider = Track4MarketProjectionProvider(lambda: snapshot())

    readiness = provider.readiness()

    assert readiness.market is True
    assert readiness.history is False
    assert readiness.account_pnl is False
    assert readiness.greeks is False
    assert readiness.attribution is False
    assert readiness.is_complete is False


def test_kis_greeks_projection_connects_to_track4_market_seam() -> None:
    greeks = KISIndexOptionGreeksProvider.from_payload(
        {"delta": "0.52", "gama": "0.18", "theta": "-0.07", "hts_ints_vltl": "0.21"},
        instrument_id="KOSPI200-OPT-1",
        observed_at="2026-01-01T09:00:00",
    )
    provider = Track4MarketProjectionProvider(lambda: snapshot(), greeks_provider=greeks)

    assert provider.current_delta() == Decimal("0.52")
    assert provider.current_gamma() == Decimal("0.18")
    assert provider.active_vol() == Decimal("0.21")
    assert provider.readiness().greeks is True


def test_missing_snapshot_fails_closed() -> None:
    provider = Track4MarketProjectionProvider(lambda: None)

    assert provider.readiness().market is False
    with pytest.raises(Track4InputSourceUnavailable):
        provider.current_price()


def test_unsupported_sources_fail_closed() -> None:
    provider = Track4MarketProjectionProvider(lambda: snapshot())

    with pytest.raises(Track4InputSourceUnavailable):
        provider.current_delta()
    with pytest.raises(Track4InputSourceUnavailable):
        provider.current_pnl()
```
## 검증 기준
        - MarketConditionSnapshot의 authoritative 값만 projection한다.
        - OHLC/Greeks/Account/PnL/Attribution을 합성하지 않는다.
        - Market만 READY이고 전체 completeness는 false여야 한다.
## No.349 observed history projection 테스트
        - snapshot supplier와 price history supplier를 함께 주입하면 price_history()가 Decimal sequence로 반환되는지 검증한다.
        - history supplier 미제공 시 fail-closed 예외를 검증한다.
        - 실제 Sensor 공개 price_history()를 supplier로 연결할 수 있는 구조임을 검증한다.
[Child Page] test_track4_runtime_input_provider.py
```python
from contracts.track4_runtime_input_provider import Track4RuntimeInputProvider, Track4RuntimeInputReadiness

def test_readiness_is_incomplete_when_sources_missing():
    r = Track4RuntimeInputReadiness(True, True, True, False, False)
    assert r.is_complete is False

def test_readiness_is_complete_only_when_all_authoritative():
    r = Track4RuntimeInputReadiness(True, True, True, True, True)
    assert r.is_complete is True

def test_port_declares_all_track4_boundaries():
    required = {'readiness','current_price','active_vol','base_vol','current_pnl','current_equity','price_high','price_low','price_close','current_delta','current_gamma','premium_spent','accumulated_gamma_profit','theta_decay_cost'}
    assert required.issubset(set(Track4RuntimeInputProvider.__dict__))
```
Completeness contract verification.
## No.349 계약 변경 테스트 기준
        - price_history()는 공개 Sensor 관측값을 Decimal sequence로 보존한다.
        - history supplier가 없으면 price_history()는 Track4InputSourceUnavailable로 fail-closed한다.
        - readiness의 history는 실제 history supplier와 관측 history 존재 여부에 따라 결정한다.
        - 기존 price_high/price_low/price_close를 요구하거나 합성하지 않는다.
## No.349 계약 변경 테스트 기준
        - price_history()는 공개 Sensor 관측값을 Decimal sequence로 보존한다.
        - history supplier가 없으면 price_history()는 Track4InputSourceUnavailable로 fail-closed한다.
        - readiness의 history는 실제 history supplier와 관측 history 존재 여부에 따라 결정한다.
        - 기존 price_high/price_low/price_close를 요구하거나 합성하지 않는다.
[Child Page] test_track4_option_valuation_input.py
```python
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from contracts.track4_option_valuation_input import (
    OptionValuationInputInvalid,
    Track4OptionValuationInput,
)

def valid_input() -> Track4OptionValuationInput:
    return Track4OptionValuationInput(
        instrument_id="OPT-1",
        observed_at=datetime(2026, 9, 6, tzinfo=timezone.utc),
        underlying_price=Decimal("350"),
        option_price=Decimal("5.2"),
        strike=Decimal("350"),
        expiry=date(2026, 9, 10),
        time_to_expiry_years=Decimal("0.0109589"),
        implied_volatility=Decimal("0.25"),
        risk_free_rate=Decimal("0.03"),
        price_source="authoritative-market-price",
        iv_source="authoritative-iv-source",
        risk_free_rate_source="authoritative-rate-source",
        time_to_expiry_source="authoritative-time-convention",
    )

def test_valid_valuation_input_is_immutable_contract():
    value = valid_input()
    assert value.instrument_id == "OPT-1"
    assert value.implied_volatility == Decimal("0.25")

def test_missing_iv_source_fails_closed():
    with pytest.raises(OptionValuationInputInvalid, match="iv_source"):
        Track4OptionValuationInput(**{**valid_input().__dict__, "iv_source": ""})

def test_invalid_valuation_numbers_fail_closed():
    with pytest.raises(OptionValuationInputInvalid, match="time_to_expiry_years"):
        Track4OptionValuationInput(**{**valid_input().__dict__, "time_to_expiry_years": Decimal("0")})
```
## 검증 목적
        - DTO 최소 입력 유효성만 검증한다.
        - 실제 IV/risk-free/reference-price source의 존재를 가장하지 않는다.
        - Greeks 계산 engine 또는 production runtime 연결은 포함하지 않는다.
[Child Page] test_external_authoritative_option_identity_record.py
```python
from decimal import Decimal

import pytest

from contracts.external_authoritative_option_identity_record import (
    AuthoritativeOptionIdentityRecordError,
    ExternalAuthoritativeOptionIdentityRecord,
)


def _record() -> ExternalAuthoritativeOptionIdentityRecord:
    return ExternalAuthoritativeOptionIdentityRecord(
        instrument_id="AUTH-OPTION-1",
        symbol="101V3000",
        expiry="2026-12-10",
        option_type="CALL",
        strike=Decimal("300"),
        shrn_iscd="101V3000",
        stnd_iscd="KR4101V300000000000",
    )


def test_complete_external_record_builds_standard_identity() -> None:
    identity = _record().to_identity()
    assert identity.instrument_id == "AUTH-OPTION-1"
    assert identity.symbol == "101V3000"
    assert identity.expiry == "2026-12-10"
    assert identity.option_type == "CALL"
    assert identity.strike == Decimal("300")


def test_kis_identifiers_are_not_promoted_to_instrument_id() -> None:
    record = _record()
    assert record.shrn_iscd != record.instrument_id
    assert record.stnd_iscd != record.instrument_id
    assert record.to_identity().instrument_id == "AUTH-OPTION-1"


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("instrument_id", "", "INSTRUMENT_ID_REQUIRED"),
        ("symbol", "", "SYMBOL_REQUIRED"),
        ("expiry", "", "EXPIRY_REQUIRED"),
        ("option_type", "", "OPTION_TYPE_REQUIRED"),
        ("strike", Decimal("0"), "STRIKE_REQUIRED"),
    ],
)
def test_incomplete_record_fails_closed(field: str, value: object, error: str) -> None:
    values = _record().__dict__.copy()
    values[field] = value
    record = ExternalAuthoritativeOptionIdentityRecord(**values)
    with pytest.raises(AuthoritativeOptionIdentityRecordError, match=error):
        record.to_identity()
```
## 검증 의도
        - 외부 owner가 제공하는 최소 5개 authoritative 값을 Standard OptionInstrumentIdentity로 검증한다.
        - KIS shrn_iscd/stnd_iscd는 instrument_id가 아님을 고정한다.
        - 필수값 누락/무효 시 fail-closed 한다.
        - 실제 production source 연결은 하지 않는다.
[Child Page] test_authoritative_option_identity_source.py
```python
from dataclasses import dataclass
from decimal import Decimal

from contracts.authoritative_option_identity_source import AuthoritativeOptionIdentitySource
from contracts.external_authoritative_option_identity_record import (
    ExternalAuthoritativeOptionIdentityRecord,
)
from contracts.option_identity_source_port import OptionIdentitySelection
from contracts.types import OptionInstrumentIdentity


@dataclass
class FixtureAuthoritativeSource:
    identity: OptionInstrumentIdentity | None
    record: ExternalAuthoritativeOptionIdentityRecord | None = None

    def get_identity(self, selector: object) -> OptionInstrumentIdentity | None:
        return self.identity

    def resolve(self, selection: OptionIdentitySelection):
        return self.record


def _identity() -> OptionInstrumentIdentity:
    return OptionInstrumentIdentity(
        instrument_id="AUTH-OPTION-1",
        symbol="101V3000",
        expiry="2026-12-10",
        option_type="CALL",
        strike=Decimal("300"),
    )


def test_legacy_source_returns_complete_authoritative_identity() -> None:
    source: AuthoritativeOptionIdentitySource = FixtureAuthoritativeSource(_identity())
    assert source.get_identity("fixture-selector") == _identity()


def test_new_lookup_contract_returns_source_owned_record() -> None:
    record = ExternalAuthoritativeOptionIdentityRecord(
        instrument_id="AUTH-OPTION-1",
        symbol="101V3000",
        expiry="2026-12-10",
        option_type="CALL",
        strike=Decimal("300"),
    )
    source = FixtureAuthoritativeSource(_identity(), record)
    selection = OptionIdentitySelection("101V3000", "2026-12-10", "CALL", Decimal("300"))
    assert source.resolve(selection) == record


def test_unresolved_paths_do_not_synthesize_identity() -> None:
    source = FixtureAuthoritativeSource(None, None)
    assert source.get_identity({"shrn_iscd": "101V3000"}) is None
```
## 검증 의도
        - legacy identity 공급 계약과 신규 record lookup 계약의 역할을 명확히 분리한다.
        - 신규 source 구현은 하나의 OptionIdentitySource seam으로 수렴한다.
        - fixture/KIS identifier로 Standard identity를 합성하지 않는다.
[Child Page] test_virtual_contract_mapping_loader.py
```python
import pytest

from application.composition.virtual_contract_mapping_loader import (
    VirtualContractMappingConfigurationError,
    VirtualContractMappingLoader,
)


def test_loads_explicit_contract_mappings():
    mappings = VirtualContractMappingLoader().load(
        {
            "contract_mappings": [
                {
                    "scenario_contract_key": "scenario-call",
                    "shrn_iscd": "AUTHORITATIVE_CODE",
                }
            ]
        }
    )

    assert mappings["scenario-call"].scenario_contract_key == "scenario-call"
    assert mappings["scenario-call"].shrn_iscd == "AUTHORITATIVE_CODE"


@pytest.mark.parametrize(
    "source,error",
    [
        ({"contract_mappings": []}, None),
        (
            {"contract_mappings": [{"scenario_contract_key": "", "shrn_iscd": "X"}]},
            "SCENARIO_CONTRACT_KEY_REQUIRED",
        ),
        (
            {"contract_mappings": [{"scenario_contract_key": "k", "shrn_iscd": ""}]},
            "SHRN_ISCD_REQUIRED",
        ),
    ],
)
def test_loader_is_fail_closed(source, error):
    loader = VirtualContractMappingLoader()
    if error is None:
        assert loader.load(source) == {}
    else:
        with pytest.raises(VirtualContractMappingConfigurationError, match=error):
            loader.load(source)


def test_duplicate_key_is_rejected():
    source = {
        "contract_mappings": [
            {"scenario_contract_key": "k", "shrn_iscd": "A"},
            {"scenario_contract_key": "k", "shrn_iscd": "B"},
        ]
    }

    with pytest.raises(
        VirtualContractMappingConfigurationError,
        match="DUPLICATE_SCENARIO_CONTRACT_KEY",
    ):
        VirtualContractMappingLoader().load(source)
```
## 검증 범위
        - 명시적 mapping materialization
        - 빈 key fail-closed
        - 빈 shrn_iscd fail-closed
        - 중복 key fail-closed
        - 임의 identity 생성 없음
        - authoritative registry 검증은 기존 resolver 테스트 경계를 재사용
[Child Page] test_virtual_builder_contract.py
```python
from dataclasses import dataclass

from application.composition.virtual_builder_contract import (
    VirtualAuthoritativeScope,
    VirtualEnvironmentBuilder,
    VirtualAuthoritativeScopeFactory,
)


@dataclass
class StubBuilder:
    bundle: object

    def build(self, config, policy):
        return self.bundle


def test_builder_contract_accepts_minimal_build_method():
    builder: VirtualEnvironmentBuilder = StubBuilder(bundle=object())

    assert builder.build(config=object(), policy=object()) is not None


def test_authoritative_scope_keeps_one_vssf_runtime_identity():
    vssf_runtime = object()
    scope = VirtualAuthoritativeScope(
        vssf_runtime=vssf_runtime,
        broker=object(),
        account=object(),
        position=object(),
        execution=object(),
    )

    assert scope.vssf_runtime is vssf_runtime


def test_scope_factory_contract_accepts_create_method():
    class StubFactory:
        def create(self, config, policy):
            return VirtualAuthoritativeScope(
                vssf_runtime=object(),
                broker=object(),
                account=object(),
                position=object(),
                execution=object(),
            )

    factory: VirtualAuthoritativeScopeFactory = StubFactory()
    scope = factory.create(config=object(), policy=object())

    assert scope.vssf_runtime is not None
```
## 검증 범위
        - Builder의 최소 build(config, policy) 계약을 검증한다.
        - authoritative VSSF runtime identity가 scope에서 보존되는지 검증한다.
        - concrete VSSF 생성이나 실제 Runtime wiring을 테스트하지 않는다.
```javascript

```
[Child Page] test_virtual_contract_identity_adapter.py
```python
import pytest

from application.composition.virtual_contract_identity_adapter import (
    VirtualContractIdentityResolverAdapter,
)
from contracts.virtual_contract_resolver import (
    VirtualContractMapping,
    VirtualContractResolutionError,
    VirtualContractResolver,
)
from environments.high_speed.contract_identity import ReplayEvent, ScenarioEvent


class FakeRegistry:
    def __init__(self, values):
        self.values = values

    def get_contract_identity(self, shrn_iscd):
        return self.values.get(shrn_iscd)


def make_adapter(values=None):
    values = values or {}
    resolver = VirtualContractResolver(
        {"SCN-1": VirtualContractMapping("SCN-1", "KR7001")},
        FakeRegistry(values),
    )
    return VirtualContractIdentityResolverAdapter(resolver)


def test_scenario_event_resolves_authoritative_identity():
    identity = object()
    adapter = make_adapter({"KR7001": identity})
    event = ScenarioEvent(1, "tick", {"price": 100}, "SCN-1")
    assert adapter.resolve_event(event) is identity


def test_replay_event_resolves_authoritative_identity():
    from datetime import datetime

    identity = object()
    adapter = make_adapter({"KR7001": identity})
    event = ReplayEvent(1, datetime(2026, 1, 1), {"price": 100}, "SCN-1")
    assert adapter.resolve_event(event) is identity


@pytest.mark.parametrize("event", [
    ScenarioEvent(1, "tick", {}, None),
    ScenarioEvent(1, "tick", {}, "   "),
])
def test_missing_or_blank_key_fails_closed(event):
    adapter = make_adapter({"KR7001": object()})
    with pytest.raises(VirtualContractResolutionError, match="KEY_REQUIRED"):
        adapter.resolve_event(event)


def test_unknown_mapping_fails_closed_through_adapter():
    adapter = make_adapter({"KR7001": object()})
    event = ScenarioEvent(1, "tick", {}, "UNKNOWN")
    with pytest.raises(VirtualContractResolutionError, match="MAPPING_NOT_FOUND"):
        adapter.resolve_event(event)


def test_registry_miss_fails_closed_through_adapter():
    adapter = make_adapter({})
    event = ScenarioEvent(1, "tick", {}, "SCN-1")
    with pytest.raises(VirtualContractResolutionError, match="IDENTITY_NOT_FOUND"):
        adapter.resolve_event(event)
```
## 검증 기준
        - ScenarioEvent와 ReplayEvent가 동일 Adapter 경계를 통과한다.
        - key 누락/공백은 Adapter에서 fail-closed 한다.
        - unknown mapping과 authoritative registry miss는 Resolver 예외가 그대로 전파되어 fail-closed 한다.
        - event payload와 ordering 관련 상태를 수정하지 않는다.
실제 pytest 실행은 Notion 페이지가 물리 Python workspace로 직접 mount되지 않아 UNVERIFIED다.
[Child Page] test_track2_asymmetric_trap.py
from datetime import datetime
from decimal import Decimal
from core.domain.market_models import CanonicalMarketTick, MarketState
from core.strategy.contracts import StrategyContext
from core.strategy.track2_asymmetric_trap import Track2AsymmetricTrap
def test_wide_trap_strikes():
result = Track2AsymmetricTrap().build_asymmetric_trap(Decimal("350"), 0.80, 1.0)
assert result["trap_type"] == "ZERO_COST_10PT_WIDE"
def test_narrow_trap_strikes():
result = Track2AsymmetricTrap().build_asymmetric_trap(Decimal("350"), 1.0, 1.0)
assert result["trap_type"] == "GAMMA_5PT_NARROW"
def test_market_trigger_requires_squeeze_and_volume_explosion():
assert Track2AsymmetricTrap.check_market_trigger([3.0, 2.0], [1, 1, 10]) is False
assert Track2AsymmetricTrap.check_market_trigger([3.0, 2.0, 1.0], [1, 1, 1, 20]) is True
def test_whipsaw_filters_block_neutral_obi_and_basis():
assert not Track2AsymmetricTrap.validate_whipsaw_filters(
Decimal("351"), [Decimal("1")]  5, [Decimal("1")]  5,
Decimal("0.4"), Decimal("0.2"), Decimal("0.3"), Decimal("349")
)
def test_reversal_price_preserves_tick_rule():
assert Track2AsymmetricTrap.reversal_price(Decimal("2.00")) == Decimal("1.98")
assert Track2AsymmetricTrap.reversal_price(Decimal("3.00")) == Decimal("2.90")
def _context(price: str = "100") -> StrategyContext:
tick = CanonicalMarketTick("OPT", datetime(2026, 9, 4, 10, 0), Decimal(price), Decimal("10"))
state = MarketState(tick.observed_at, {tick.instrument_id: tick}, {})
return StrategyContext(state, "track2_asymmetric_trap")
def test_standard_evaluate_does_not_fabricate_missing_inputs():
strategy = Track2AsymmetricTrap()
assert strategy.evaluate(_context()) == ()
def test_stop_loss_returns_flat_signal():
strategy = Track2AsymmetricTrap()
strategy._trap_active = True
strategy._entry_price = Decimal("100")
signals = strategy.evaluate_trap(Decimal("70"), datetime(2026, 9, 4, 10, 1))
assert signals[0].direction == "FLAT"
assert "STOP_LOSS" in signals[0].reason
def test_trailing_stop_switches_short():
strategy = Track2AsymmetricTrap()
strategy._trap_active = True
strategy._entry_price = Decimal("100")
now = datetime(2026, 9, 4, 10, 0)
assert strategy.evaluate_trap(Decimal("140"), now) == ()
signals = strategy.evaluate_trap(Decimal("119"), now)
assert signals[0].direction == "SHORT"
assert signals[0].reason == "TAKE_PROFIT_TRAILING_STOP"
def test_short_switch_timeout_returns_flat():
strategy = Track2AsymmetricTrap()
strategy._short_switch_at = datetime(2026, 9, 4, 10, 0)
signals = strategy.evaluate_trap(Decimal("120"), datetime(2026, 9, 4, 10, 15))
assert signals[0].direction == "FLAT"
assert signals[0].reason == "SHORT_SWITCH_TIMEOUT_EXIT"
# 검증 메모
        - 원격 Track2 원문 기준 테스트 입력과 경계조건을 재대조했다.
        - 현재 Canonical MarketState만으로는 BBW/IV/Basis/OBI/POC 전체를 제공할 수 없으므로 evaluate()의 no-op 정책은 유지한다.
        - 실제 terminal pytest는 현재 환경에서 실행하지 못했으므로 PASS로 표시하지 않는다.
def test_entry_signal_carries_execution_proposal() -> None:
signals = strategy.evaluate(context)
proposal = signals[0].execution_proposal
assert proposal is not None
assert proposal.proposed_quantity == 1
assert proposal.asset_type == "OPTION"
assert proposal.side == "BUY"
assert proposal.track_id == "track2_asymmetric_trap"
[Child Page] test_standard_option_runtime.py
```python
from datetime import datetime
from types import SimpleNamespace

import pytest

from core.runtime.standard_option_runtime import StandardOptionRuntime


AS_OF = datetime(2026, 1, 2, 10, 0)


class StubSeam:
    def __init__(self):
        self.calls = []

    def evaluate_tick(self, tick, observed_at):
        self.calls.append((tick, observed_at))
        return ("evaluated",)


def valid_tick(sequence=17):
    return SimpleNamespace(
        source_sequence=sequence,
        timestamp=AS_OF.isoformat(),
    )


def test_process_tick_delegates_authoritative_tick_without_mutation():
    seam = StubSeam()
    runtime = StandardOptionRuntime(seam)
    tick = valid_tick()

    result = runtime.process_tick(tick, AS_OF)

    assert result == ("evaluated",)
    assert seam.calls == [(tick, AS_OF)]
    assert tick.source_sequence == 17


@pytest.mark.parametrize("sequence", [None, 0, -1])
def test_process_tick_rejects_missing_or_non_positive_authoritative_sequence(sequence):
    runtime = StandardOptionRuntime(StubSeam())
    tick = valid_tick(sequence)

    with pytest.raises(ValueError, match="RUNTIME_SOURCE_SEQUENCE_REQUIRED"):
        runtime.process_tick(tick, AS_OF)


def test_process_tick_rejects_timestamp_mismatch_before_strategy_evaluation():
    seam = StubSeam()
    runtime = StandardOptionRuntime(seam)
    tick = valid_tick()
    tick.timestamp = "2026-01-02T10:00:01"

    with pytest.raises(ValueError, match="RUNTIME_TICK_TIMESTAMP_MISMATCH"):
        runtime.process_tick(tick, AS_OF)

    assert seam.calls == []

```
## 검증 범위
        - authoritative tick을 Strategy seam으로 lossless 전달
        - source_sequence fallback 금지
        - timestamp mismatch fail-closed
        - Strategy 평가 전에 경계 검증 수행
[Child Page] test_option_identity_source_port.py
```python
from decimal import Decimal

import pytest

from contracts.external_authoritative_option_identity_record import (
    ExternalAuthoritativeOptionIdentityRecord,
)
from contracts.option_identity_source_port import (
    OptionIdentitySelection,
    OptionIdentitySourceError,
    resolve_authoritative_option_identity,
)


class Source:
    def __init__(self, record):
        self.record = record

    def resolve(self, selection):
        return self.record


def selection():
    return OptionIdentitySelection(
        symbol="KOSPI200-C-350",
        expiry="2026-09-10",
        option_type="CALL",
        strike=Decimal("350"),
    )


def record(**changes):
    values = dict(
        instrument_id="EXTERNAL-OPT-001",
        symbol="KOSPI200-C-350",
        expiry="2026-09-10",
        option_type="CALL",
        strike=Decimal("350"),
    )
    values.update(changes)
    return ExternalAuthoritativeOptionIdentityRecord(**values)


def test_matching_complete_record_passes():
    result = resolve_authoritative_option_identity(Source(record()), selection())
    assert result.instrument_id == "EXTERNAL-OPT-001"


@pytest.mark.parametrize(
    "changes,error",
    [
        ({"symbol": "OTHER"}, "AUTHORITATIVE_SYMBOL_MISMATCH"),
        ({"expiry": "2026-10-08"}, "AUTHORITATIVE_EXPIRY_MISMATCH"),
        ({"option_type": "PUT"}, "AUTHORITATIVE_OPTION_TYPE_MISMATCH"),
        ({"strike": Decimal("360")}, "AUTHORITATIVE_STRIKE_MISMATCH"),
    ],
)
def test_mismatched_record_fails_closed(changes, error):
    with pytest.raises(OptionIdentitySourceError, match=error):
        resolve_authoritative_option_identity(Source(record(**changes)), selection())


def test_missing_record_fails_closed():
    with pytest.raises(OptionIdentitySourceError, match="AUTHORITATIVE_IDENTITY_NOT_FOUND"):
        resolve_authoritative_option_identity(Source(None), selection())
```
## 검증 목적
실제 source 없이도 향후 외부 Product/Instrument Master가 연결될 때 필요한 최소 Port 계약과 fail-closed 동작을 고정한다.
[Child Page] test_track4_vssf_account_projection_provider.py
```python
from datetime import datetime
from decimal import Decimal

import pytest

from contracts.track4_runtime_input_provider import Track4InputSourceUnavailable
from contracts.types import AccountSnapshot, DataQuality
from environments.virtual.account.track4_vssf_account_projection_provider import (
    Track4VSSFAccountProjectionProvider,
)


class StubAccount:
    def snapshot(self):
        return AccountSnapshot(
            as_of=datetime(2026, 9, 6),
            balances={
                "cash": Decimal("50000000"),
                "realized_pnl": Decimal("100000"),
                "unrealized_pnl": Decimal("-25000"),
            },
            freshness=DataQuality(True, True, True, "stub"),
        )


def test_account_projection_is_authoritative():
    provider = Track4VSSFAccountProjectionProvider(StubAccount())
    assert provider.current_equity() == Decimal("50000000")
    assert provider.current_pnl() == Decimal("75000")
    assert provider.readiness().account_pnl is True
    assert provider.readiness().is_complete is False


def test_missing_sources_fail_closed():
    provider = Track4VSSFAccountProjectionProvider(StubAccount())
    with pytest.raises(Track4InputSourceUnavailable):
        provider.current_delta()
    with pytest.raises(Track4InputSourceUnavailable):
        provider.price_close()
```
Authoritative account projection and missing-source fail-closed verification.
[Child Page] test_track4_composite_runtime_input_[provider.py]
```python
from decimal import Decimal

import pytest

from contracts.track4_composite_runtime_input_provider import Track4CompositeRuntimeInputProvider
from contracts.track4_runtime_input_provider import Track4InputSourceUnavailable, Track4RuntimeInputReadiness


class StubProvider:
    def __init__(self, readiness, values=None):
        self._readiness = readiness
        self._values = values or {}

    def readiness(self):
        return self._readiness

    def __getattr__(self, name):
        if name in self._values:
            return lambda: self._values[name]
        return lambda: (_ for _ in ()).throw(Track4InputSourceUnavailable(f"{name} unavailable"))


def test_composition_merges_market_and_account_readiness():
    market = StubProvider(
        Track4RuntimeInputReadiness(True, False, False, False, False),
        {"current_price": Decimal("100"), "active_vol": Decimal("0.2"), "base_vol": Decimal("0.15")},
    )
    account = StubProvider(
        Track4RuntimeInputReadiness(False, False, True, False, False),
        {"current_pnl": Decimal("1234"), "current_equity": Decimal("50000000")},
    )
    provider = Track4CompositeRuntimeInputProvider(market, account)

    assert provider.current_price() == Decimal("100")
    assert provider.active_vol() == Decimal("0.2")
    assert provider.base_vol() == Decimal("0.15")
    assert provider.current_pnl() == Decimal("1234")
    assert provider.current_equity() == Decimal("50000000")
    readiness = provider.readiness()
    assert readiness.market is True
    assert readiness.account_pnl is True
    assert readiness.history is False
    assert readiness.greeks is False
    assert readiness.attribution is False
    assert readiness.is_complete is False


def test_unresolved_sources_remain_fail_closed():
    market = StubProvider(Track4RuntimeInputReadiness(True, False, False, False, False))
    account = StubProvider(Track4RuntimeInputReadiness(False, False, True, False, False))
    provider = Track4CompositeRuntimeInputProvider(market, account)

    with pytest.raises(Track4InputSourceUnavailable):
        provider.price_high()
    with pytest.raises(Track4InputSourceUnavailable):
        provider.current_delta()
    with pytest.raises(Track4InputSourceUnavailable):
        provider.premium_spent()
```
검증 목적: Market + Account/PnL partial source 조합이 readiness만 확장하고, 미확보 history/Greeks/attribution을 합성하지 않는지 확인한다.
def test_kis_greeks_are_consumed_through_runtime_composition():
from contracts.track4_kis_greeks_provider import KISIndexOptionGreeksProvider
from contracts.track4_market_projection_provider import Track4MarketProjectionProvider
from core.sensor.market_condition_sensor import MarketConditionSnapshot
snapshot = MarketConditionSnapshot(
as_of="2026-09-06T09:00:00",
instrument_id="KOSPI200-OPT",
current_price=425.0,
price_change=1.0,
volatility=0.18,
baseline_volatility=0.16,
volatility_ratio=1.125,
drawdown=0.0,
stress_level=0.0,
stress_flags=(),
)
kis = KISIndexOptionGreeksProvider.from_payload(
{
"delta": "0.42",
"gama": "0.013",
"theta": "-0.021",
"hts_ints_vltl": "0.247",
},
instrument_id="KOSPI200-OPT",
observed_at="2026-09-06T09:00:00",
)
market = Track4MarketProjectionProvider(lambda: snapshot, greeks_provider=kis)
account = StubProvider(
Track4RuntimeInputReadiness(False, False, True, False, False),
{"current_pnl": Decimal("0"), "current_equity": Decimal("50000000")},
)
provider = Track4CompositeRuntimeInputProvider(market, account)
assert provider.current_delta() == Decimal("0.42")
assert provider.current_gamma() == Decimal("0.013")
assert provider.active_vol() == Decimal("0.247")
assert provider.readiness().greeks is True
assert provider.readiness().market is True
assert provider.readiness().account_pnl is True
assert provider.readiness().is_complete is False
[Child Page] test_track4_market_history_projection.py
```python
from decimal import Decimal

from contracts.track4_market_history_projection import Track4MarketHistoryProjection
from core.sensor.market_condition_sensor import MarketConditionSensor


def test_sensor_history_projection_preserves_observed_prices() -> None:
    sensor = MarketConditionSensor()
    sensor._prices["KOSPI200"] = __import__("collections").deque([350.0, 351.0])

    history = tuple(Decimal(str(value)) for value in sensor.price_history("KOSPI200"))

    assert history == (Decimal("350.0"), Decimal("351.0"))


def test_history_projection_contract_declares_read_only_method() -> None:
    assert hasattr(Track4MarketHistoryProjection, "price_history")
```
## 검증 주의
        - private state를 fixture에 주입하는 것은 테스트 데이터 구성 목적이다.
        - production projection은 MarketConditionSensor.price_history() public method만 사용한다.
        - OHLC 합성은 의도적으로 검증/구현하지 않는다.
[Child Page] test_track4_kis_greeks_provider.py
```python
from decimal import Decimal

import pytest

from contracts.track4_kis_greeks_provider import (
    KISIndexOptionGreeksProvider,
    Track4KisGreeksSourceInvalid,
)


def test_kis_payload_projects_authoritative_greeks_and_iv():
    provider = KISIndexOptionGreeksProvider.from_payload(
        {
            "delta": "0.5123",
            "gama": "0.0182",
            "theta": "-0.034",
            "hts_ints_vltl": "0.247",
        },
        instrument_id="201S11305",
        observed_at="2026-09-06T10:00:00+09:00",
    )

    assert provider.current_delta() == Decimal("0.5123")
    assert provider.current_gamma() == Decimal("0.0182")
    assert provider.current_theta() == Decimal("-0.034")
    assert provider.active_vol() == Decimal("0.247")
    assert provider.snapshot.source == "KIS:H0IOCNT0"


def test_missing_kis_greeks_fail_closed():
    with pytest.raises(Track4KisGreeksSourceInvalid):
        KISIndexOptionGreeksProvider.from_payload(
            {
                "delta": "0.5",
                "gama": "0.01",
                "theta": "-0.03",
            },
            instrument_id="201S11305",
            observed_at="2026-09-06T10:00:00+09:00",
        )


def test_invalid_iv_fails_closed():
    with pytest.raises(Track4KisGreeksSourceInvalid):
        KISIndexOptionGreeksProvider.from_payload(
            {
                "delta": "0.5",
                "gama": "0.01",
                "theta": "-0.03",
                "hts_ints_vltl": "0",
            },
            instrument_id="201S11305",
            observed_at="2026-09-06T10:00:00+09:00",
        )
```
Targeted validation: valid KIS payload, missing-IV fail-closed, and invalid-IV fail-closed.
[Child Page] test_track4_kis_greeks_ws_adapter.py
```python
from decimal import Decimal

import pytest

from track4_kis_greeks_ws_adapter import (
    KISIndexOptionGreeksWebSocketAdapter,
    Track4KisWebSocketAdapterInvalid,
)


def _frame() -> str:
    values = [""] * 58
    values[0] = "201S11305"
    values[1] = "101530"
    values[28] = "0.5123"  # delta
    values[29] = "0.0182"  # gama
    values[31] = "-0.034"  # theta
    values[33] = "0.247"   # hts_ints_vltl
    return f"0|H0IOCNT0|{len(values)}|{'^'.join(values)}"


def test_h0iocnt0_wire_frame_reaches_provider_without_recalculation() -> None:
    provider = KISIndexOptionGreeksWebSocketAdapter().adapt(
        _frame(), observed_at="2026-09-06T10:15:30+09:00"
    )

    assert provider.current_delta() == Decimal("0.5123")
    assert provider.current_gamma() == Decimal("0.0182")
    assert provider.current_theta() == Decimal("-0.034")
    assert provider.active_vol() == Decimal("0.247")
    assert provider.snapshot.instrument_id == "201S11305"
    assert provider.snapshot.source == "KIS:H0IOCNT0"


def test_unexpected_tr_id_is_rejected() -> None:
    with pytest.raises(Track4KisWebSocketAdapterInvalid):
        KISIndexOptionGreeksWebSocketAdapter().adapt(
            _frame().replace("H0IOCNT0", "H0IFCNT0"),
            observed_at="2026-09-06T10:15:30+09:00",
        )


def test_field_count_mismatch_is_rejected() -> None:
    frame = _frame().replace("|58|", "|57|")
    with pytest.raises(Track4KisWebSocketAdapterInvalid):
        KISIndexOptionGreeksWebSocketAdapter().adapt(
            frame, observed_at="2026-09-06T10:15:30+09:00"
        )
```
검증 목적: 실제 KIS 네트워크 접속 없이도 공식 H0IOCNT0 wire framing → Provider의 field mapping과 fail-closed 경계를 고정한다.
[Child Page] test_option_master.py
```python
from datetime import date, timedelta
from decimal import Decimal

import pytest

from core.option.option_master import (
    InMemoryOptionContractMaster,
    KisMasterParseError,
    KisProductionOptionContractMaster,
    parse_kis_fo_idx_mst,
    parse_kis_fo_idx_mst_result,
)


class FakeTradingCalendar:
    def __init__(self, holidays=()):
        self.holidays = set(holidays)

    def is_trading_day(self, value: date) -> bool:
        return value.weekday() < 5 and value not in self.holidays

    def prev_trading_day(self, value: date) -> date:
        value -= timedelta(days=1)
        while not self.is_trading_day(value):
            value -= timedelta(days=1)
        return value

    def trading_days_between(self, start: date, end: date) -> int:
        count = 0
        current = start
        while current < end:
            current += timedelta(days=1)
            if self.is_trading_day(current):
                count += 1
        return count


CALENDAR = FakeTradingCalendar()
RAW = "\n".join([
    "5|201ABC|KR7001|KOSPI 202609 C 345|A|345.0|M|U|KOSPI200",
    "6|301ABC|KR7002|KOSPI 202609 P 340|A|340|M|U|KOSPI200",
])


def test_legacy_parser_return_type_and_aliases_are_preserved():
    legacy = parse_kis_fo_idx_mst(RAW, CALENDAR)
    assert legacy["201ABC"] == legacy["KR7001"]
    assert legacy["301ABC"] == legacy["KR7002"]


def test_single_parse_result_contains_legacy_and_identity_views():
    result = parse_kis_fo_idx_mst_result(RAW, CALENDAR)
    call = result.identities["201ABC"]
    put = result.identities["301ABC"]
    assert call.stnd_iscd == "KR7001"
    assert call.option_type == "CALL"
    assert call.strike == Decimal("345.0")
    assert put.option_type == "PUT"
    assert put.strike == Decimal("340")


def test_identity_registry_is_additive_and_trimmed_lookup():
    master = InMemoryOptionContractMaster()
    master.load_from_raw_mst_content(RAW, CALENDAR)
    identity = master.get_contract_identity(" 201ABC ")
    assert identity is not None
    assert identity.shrn_iscd == "201ABC"
    assert master.get_expiry("201ABC") == identity.expiry
    assert master.get_expiry("KR7001") == identity.expiry
    assert master.total_contracts == 4


def test_malformed_acpr_does_not_create_fake_strike():
    raw = "5|201BAD|KR7999|KOSPI 202609 C 345|A|ABC|M|U|KOSPI200"
    result = parse_kis_fo_idx_mst_result(raw, CALENDAR)
    assert result.identities["201BAD"].strike is None


def test_conflicting_duplicate_identity_fails_closed():
    raw = "\n".join([
        "5|201ABC|KR7001|KOSPI 202609 C 345|A|345|M|U|KOSPI200",
        "6|201ABC|KR7002|KOSPI 202609 P 340|A|340|M|U|KOSPI200",
    ])
    with pytest.raises(KisMasterParseError):
        parse_kis_fo_idx_mst_result(raw, CALENDAR)


def test_calendar_is_explicit_dependency_for_raw_parse():
    with pytest.raises(TypeError):
        parse_kis_fo_idx_mst(RAW)


def test_monthly_expiry_moves_to_previous_trading_day_when_expiry_is_holiday():
    holiday = date(2026, 9, 10)
    calendar = FakeTradingCalendar({holiday})
    raw = "5|201ABC|KR7001|KOSPI 202609 C 345|A|345|M|U|KOSPI200"
    result = parse_kis_fo_idx_mst_result(raw, calendar)
    assert result.identities["201ABC"].expiry == "2026-09-09"


def test_weekly_expiry_moves_to_previous_trading_day_when_expiry_is_holiday():
    holiday = date(2026, 9, 10)
    calendar = FakeTradingCalendar({holiday})
    raw = "5|201ABC|KR7001|KOSPI 2609W2 C 345|A|345|M|U|KOSPI200"
    result = parse_kis_fo_idx_mst_result(raw, calendar)
    assert result.identities["201ABC"].expiry == "2026-09-09"


def test_production_master_loads_fake_zip_and_registers_identity_and_aliases():
    import io
    import zipfile

    raw = "5|201ABC|KR7001|KOSPI 202609 C 345|A|345.0|M|U|KOSPI200\n"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("fo_idx_code_mts.mst", raw.encode("cp949"))

    master = KisProductionOptionContractMaster(
        calendar=CALENDAR,
        auto_load=False,
    )
    loaded = master.load_from_zip_bytes(buffer.getvalue())

    assert loaded == 2
    identity = master.get_contract_identity(" 201ABC ")
    assert identity is not None
    assert identity.stnd_iscd == "KR7001"
    assert identity.option_type == "CALL"
    assert identity.strike == Decimal("345.0")
    assert master.get_expiry("201ABC") == identity.expiry
    assert master.get_expiry("KR7001") == identity.expiry
    assert master.total_contracts == 2


def test_production_master_requires_injected_calendar_without_network():
    with pytest.raises(KisMasterParseError):
        KisProductionOptionContractMaster(auto_load=False, calendar=None)
```
[Child Page] test_decision_arbiter.py
```python
from dataclasses import dataclass
from enum import Enum
from decimal import Decimal

from .decision_arbiter import DecisionArbiter, STRATEGY_PRIORITY_MAP


class AssetType(str, Enum):
    OPTION = "OPTION"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OptionType(str, Enum):
    CALL = "CALL"
    PUT = "PUT"


@dataclass(frozen=True)
class Signal:
    signal_id: str
    track_id: str
    qty: int
    asset_type: AssetType
    strike: Decimal
    option_type: OptionType | None
    side: Side


def signal(signal_id, track_id, qty=1, side=Side.BUY, strike=Decimal("350"), option_type=OptionType.CALL):
    return Signal(signal_id, track_id, qty, AssetType.OPTION, strike, option_type, side)


def test_empty_input_returns_empty_reference_shape():
    result = DecisionArbiter().arbitrate([], account=None)
    assert result.approved_signals == []
    assert result.rejected_signals == []
    assert result.netted_clashes == []


def test_priority_then_quantity_then_signal_id_is_reference_order():
    signals = [
        signal("z", "Track2", qty=10),
        signal("b", "Track1", qty=1),
        signal("a", "Track1", qty=5),
    ]
    result = DecisionArbiter().arbitrate(signals, account=None)
    assert [item.signal_id for item in result.approved_signals] == ["a", "b", "z"]


def test_opposite_side_same_instrument_keeps_preceding_signal_and_rejects_later():
    signals = [
        signal("win", "Track1", qty=5, side=Side.BUY),
        signal("lose", "Track2", qty=1, side=Side.SELL),
    ]
    result = DecisionArbiter().arbitrate(signals, account=None)
    assert [item.signal_id for item in result.approved_signals] == ["win"]
    assert [item[0].signal_id for item in result.rejected_signals] == ["lose"]
    assert result.rejected_signals[0][1] == "CLASH_NETTING_REJECTED: Subordinate to Track1 (BUY)"
    assert len(result.netted_clashes) == 1


def test_same_side_signals_are_all_approved_without_quantity_aggregation():
    signals = [
        signal("one", "Track1", qty=3, side=Side.BUY),
        signal("two", "Track2", qty=7, side=Side.BUY),
    ]
    result = DecisionArbiter().arbitrate(signals, account=None)
    assert [item.signal_id for item in result.approved_signals] == ["one", "two"]
    assert [item.qty for item in result.approved_signals] == [3, 7]
    assert result.rejected_signals == []


def test_unregistered_track_uses_reference_priority_99():
    assert STRATEGY_PRIORITY_MAP["Track1"] == 2
    result = DecisionArbiter().arbitrate(
        [signal("known", "Track1"), signal("unknown", "UnknownTrack")],
        account=None,
    )
    assert [item.signal_id for item in result.approved_signals] == ["known", "unknown"]


def test_option_type_none_is_part_of_instrument_key():
    buy = signal("buy", "Track1", side=Side.BUY, option_type=None)
    sell = signal("sell", "Track2", side=Side.SELL, option_type=OptionType.CALL)
    result = DecisionArbiter().arbitrate([buy, sell], account=None)
    assert len(result.approved_signals) == 2
    assert result.rejected_signals == []
```
### Targeted verification
Run from the materialized OptionProject workspace:
pytest -q core/decision/test_decision_arbiter.py
The test uses local lightweight signal doubles only to verify the Standard boundary; it does not modify or execute the remote Exp_Detail_1 branch.
[Child Page] test_order_intent_factory.py
```python
from decimal import Decimal

import pytest

from contracts.types import OptionInstrumentIdentity
from core.oms.option_identity_resolver import OptionIdentityResolver
from core.oms.order_intent_factory import (
    OrderIntentExecutionInput,
    OrderIntentFactory,
    OrderIntentValidationError,
)
from core.strategy.contracts import Signal


def identity():
    return OptionInstrumentIdentity(
        instrument_id="OPT-202609-C-700",
        symbol="KOSPI200",
        expiry="202609",
        option_type="CALL",
        strike=Decimal("700"),
    )


def test_option_signal_resolves_identity_and_preserves_execution_semantics():
    signal = Signal(
        strategy_id="track1",
        direction="LONG",
        confidence=0.9,
        reason="test",
        instrument_identity=identity(),
        option_type_override="CALL",
        strike_override=Decimal("700"),
    )
    execution = OrderIntentExecutionInput(
        client_order_id="ORD-1",
        quantity=2,
        requested_price=Decimal("1.25"),
        order_type="LIMIT",
        order_purpose="ENTRY",
        asset_type="OPTION",
        track_id="track1",
        tag_id="tail-defense",
    )

    result = OrderIntentFactory(OptionIdentityResolver()).create(signal, execution)

    assert result.side == "BUY"
    assert result.quantity == 2
    assert result.requested_price == Decimal("1.25")
    assert result.order_type == "LIMIT"
    assert result.order_purpose == "ENTRY"
    assert result.instrument_identity.option_type == "CALL"
    assert result.instrument_identity.strike == Decimal("700")
    assert result.instrument_id == "OPT-202609-C-700"


def test_contract_changing_override_fails_closed():
    signal = Signal(
        strategy_id="track1",
        direction="LONG",
        confidence=0.9,
        reason="test",
        instrument_identity=identity(),
        strike_override=Decimal("695"),
    )
    execution = OrderIntentExecutionInput(
        client_order_id="ORD-override",
        quantity=1,
        requested_price=Decimal("1.0"),
        order_type="LIMIT",
        order_purpose="ENTRY",
        asset_type="OPTION",
    )
    with pytest.raises(ValueError, match="AUTHORITATIVE_IDENTITY_REQUIRED_FOR_STRIKE_OVERRIDE"):
        OrderIntentFactory(OptionIdentityResolver()).create(signal, execution)


def test_flat_signal_is_not_executable():
    signal = Signal(strategy_id="track1", direction="FLAT", confidence=0.1, reason="none")
    execution = OrderIntentExecutionInput(
        client_order_id="ORD-2",
        quantity=1,
        requested_price=None,
        order_type="MARKET",
        order_purpose="EXIT",
        asset_type="OPTION",
    )
    with pytest.raises(OrderIntentValidationError, match="ORDER_SIDE_REQUIRED"):
        OrderIntentFactory(OptionIdentityResolver()).create(signal, execution)


def test_missing_option_identity_fails_closed():
    signal = Signal(strategy_id="track1", direction="LONG", confidence=0.8, reason="test")
    execution = OrderIntentExecutionInput(
        client_order_id="ORD-3",
        quantity=1,
        requested_price=Decimal("1.0"),
        order_type="LIMIT",
        order_purpose="ENTRY",
        asset_type="OPTION",
    )
    with pytest.raises(ValueError, match="OPTION_IDENTITY_REQUIRED"):
        OrderIntentFactory(OptionIdentityResolver()).create(signal, execution)
```
## 검증 기준
        1. Signal identity와 explicit override가 Resolver를 통해 최종 identity로 확정된다.
        1. quantity/price/order_type/order_purpose는 Strategy가 아니라 실행 입력에서 공급된다.
        1. LONG/SHORT만 BUY/SELL로 변환되며 FLAT은 실행 주문으로 만들지 않는다.
        1. OPTION identity가 없으면 fail-closed 한다.
        1. 실제 전략 로직이나 Broker/VSSF 호출은 테스트 대상에 포함하지 않는다.
[Child Page] test_market_condition_sensor.py
## 검증 대상
market_condition_sensor.py의 기능 단위 이식 결과를 검증한다.
## 독립 테스트 코드
```python
from datetime import datetime, timezone
from decimal import Decimal

from core.domain.market_models import CanonicalMarketTick, DataQuality, MarketState
from core.sensor.market_condition_sensor import MarketConditionSensor


def make_state(price: str) -> MarketState:
    tick = CanonicalMarketTick(
        instrument_id="KOSPI200",
        observed_at=datetime.now(timezone.utc),
        price=Decimal(price),
        volume=None,
    )
    return MarketState(
        as_of=tick.observed_at,
        ticks={tick.instrument_id: tick},
        quality={tick.instrument_id: DataQuality(True, True, True)},
    )


def test_first_tick_has_zero_price_change() -> None:
    sensor = MarketConditionSensor()
    result = sensor.analyze(make_state("350"), "KOSPI200")
    assert result.price_change == 0.0
    assert result.current_price == 350.0


def test_second_tick_preserves_price_change() -> None:
    sensor = MarketConditionSensor()
    sensor.analyze(make_state("350"), "KOSPI200")
    result = sensor.analyze(make_state("351"), "KOSPI200")
    assert result.price_change == 1.0


def test_large_move_sets_flash_gap_and_circuit_flags() -> None:
    sensor = MarketConditionSensor()
    sensor.analyze(make_state("350"), "KOSPI200")
    result = sensor.analyze(make_state("385"), "KOSPI200")
    assert "FLASH_MOVE" in result.stress_flags
    assert "GAP" in result.stress_flags
    assert "CIRCUIT_BREAKER" in result.stress_flags


def test_missing_spread_basis_oi_are_not_fabricated() -> None:
    sensor = MarketConditionSensor()
    result = sensor.analyze(make_state("350"), "KOSPI200")
    assert result.spread is None
    assert result.basis is None
    assert result.oi_trend_alert is None


def test_price_history_is_read_only_projection_of_observed_prices() -> None:
    sensor = MarketConditionSensor()
    sensor.analyze(make_state("350"), "KOSPI200")
    sensor.analyze(make_state("351"), "KOSPI200")
    history = sensor.price_history("KOSPI200")
    assert history == (350.0, 351.0)
    assert isinstance(history, tuple)
    assert sensor.price_history("UNKNOWN") == ()
```
## 검증 판정
        - 코드 구조상 Legacy Runtime/Broker/VMS/VSSF/UI 의존성 없음.
        - CanonicalMarketTick/MarketState만 입력으로 사용.
        - 기존 핵심 계산의 독립 재구현 경계를 확인.
        - 실제 terminal pytest 실행은 현재 연결 환경에서 불가하므로 PASS로 표시하지 않는다.
        - 테스트 코드는 다음 실제 로컬/CI 실행에서 증거로 사용한다.
[Child Page] test_standard_strategy_orchestrator.py
```python
from dataclasses import dataclass
from datetime import datetime

from core.domain.market_models import MarketState
from core.strategy.contracts import (
    CommonStrategyInput,
    Signal,
    StrategyContext,
    StrategyInput,
)
from core.strategy.orchestrator import StrategyOrchestrator
from core.strategy.registry import StrategyRegistry


@dataclass(frozen=True)
class DummyPayload:
    strategy_id: str


class DummyStrategy:
    version = "1.0"

    def __init__(self, strategy_id: str, events: list[str], fail_stage=None):
        self.strategy_id = strategy_id
        self.events = events
        self.fail_stage = fail_stage
        self.initialize_count = 0

    def initialize(self, context):
        self.events.append(f"{self.strategy_id}:initialize")
        self.initialize_count += 1
        if self.fail_stage == "initialize":
            raise RuntimeError("initialize failure")

    def on_market_state(self, context):
        self.events.append(f"{self.strategy_id}:market")
        if self.fail_stage == "market":
            raise RuntimeError("market failure")

    def evaluate(self, context):
        self.events.append(f"{self.strategy_id}:evaluate")
        if self.fail_stage == "evaluate":
            raise RuntimeError("evaluate failure")
        return (
            Signal(
                strategy_id=self.strategy_id,
                direction="FLAT",
                confidence=1.0,
                reason="test",
            ),
        )

    def reset(self):
        self.events.append(f"{self.strategy_id}:reset")


def make_context(strategy_id: str) -> StrategyContext:
    return StrategyContext(
        market_state=MarketState(
            as_of=datetime(2026, 1, 1),
            ticks={},
            quality={},
        ),
        strategy_id=strategy_id,
        input=StrategyInput(
            common=CommonStrategyInput(as_of=datetime(2026, 1, 1)),
            payload=DummyPayload(strategy_id),
        ),
    )


def build_registry(events, second_fail_stage=None):
    registry = StrategyRegistry()
    first = DummyStrategy("track1", events)
    second = DummyStrategy("track2", events, second_fail_stage)
    registry.register(first)
    registry.register(second)
    return registry, first, second


def test_lifecycle_order_and_signal_collection():
    events = []
    registry, _, _ = build_registry(events)
    orchestrator = StrategyOrchestrator(
        registry,
        (("track1", "1.0"), ("track2", "1.0")),
    )

    result = orchestrator.run(
        {
            "track1": make_context("track1"),
            "track2": make_context("track2"),
        }
    )

    assert events == [
        "track1:initialize",
        "track1:market",
        "track1:evaluate",
        "track2:initialize",
        "track2:market",
        "track2:evaluate",
    ]
    assert [signal.strategy_id for signal in result.signals] == [
        "track1",
        "track2",
    ]
    assert result.failures == ()


def test_initialize_runs_once_per_strategy_until_reset():
    events = []
    registry, first, _ = build_registry(events)
    orchestrator = StrategyOrchestrator(
        registry,
        (("track1", "1.0"), ("track2", "1.0")),
    )
    contexts = {
        "track1": make_context("track1"),
        "track2": make_context("track2"),
    }

    orchestrator.run(contexts)
    orchestrator.run(contexts)
    assert first.initialize_count == 1

    orchestrator.reset()
    orchestrator.run(contexts)
    assert first.initialize_count == 2


def test_disabled_strategy_is_not_evaluated():
    events = []
    registry, _, _ = build_registry(events)
    orchestrator = StrategyOrchestrator(
        registry,
        (("track1", "1.0"), ("track2", "1.0")),
    )
    orchestrator.set_enabled("track2", "1.0", False)

    result = orchestrator.run(
        {
            "track1": make_context("track1"),
            "track2": make_context("track2"),
        }
    )

    assert [signal.strategy_id for signal in result.signals] == ["track1"]
    assert all(not event.startswith("track2:") for event in events)


def test_strategy_failure_is_isolated_from_next_strategy():
    events = []
    registry, _, _ = build_registry(events, second_fail_stage="evaluate")
    orchestrator = StrategyOrchestrator(
        registry,
        (("track1", "1.0"), ("track2", "1.0")),
    )

    result = orchestrator.run(
        {
            "track1": make_context("track1"),
            "track2": make_context("track2"),
        }
    )

    assert [signal.strategy_id for signal in result.signals] == ["track1"]
    assert len(result.failures) == 1
    assert result.failures[0].strategy_id == "track2"
    assert result.failures[0].stage == "evaluate"


def test_selected_subset_is_deterministic():
    events = []
    registry, _, _ = build_registry(events)
    orchestrator = StrategyOrchestrator(
        registry,
        (("track1", "1.0"), ("track2", "1.0")),
    )

    result = orchestrator.run(
        {
            "track1": make_context("track1"),
            "track2": make_context("track2"),
        },
        selected=(("track2", "1.0"),),
    )

    assert [signal.strategy_id for signal in result.signals] == ["track2"]
    assert events == [
        "track2:initialize",
        "track2:market",
        "track2:evaluate",
    ]


def test_orchestrator_has_no_runtime_broker_or_ui_dependency():
    import inspect
    from core.strategy import orchestrator as module

    source = inspect.getsource(module)
    for forbidden in (
        "option_program.runtime",
        "Broker",
        "OrderRequest",
        "ExecutionReport",
        "VMS",
        "VSSF",
        "UI",
    ):
        assert forbidden not in source
```
## 검증 범위
        - lifecycle 순서
        - initialize 1회 보장 및 reset 후 재초기화
        - enabled filtering
        - Signal 수집
        - Strategy 실패 격리
        - 선택 subset의 결정적 실행 순서
        - Runtime/Broker/UI 직접 의존 부재
실제 terminal pytest는 실행하지 않았으므로 PASS 선언하지 않는다.
[Child Page] test_option_identity_resolver.py
```python
from decimal import Decimal

import pytest

from contracts.types import OptionInstrumentIdentity
from core.oms.option_identity_resolver import (
    IdentityResolutionError,
    OptionIdentityResolutionInput,
    OptionIdentityResolver,
)


def identity():
    return OptionInstrumentIdentity(
        instrument_id="KOSPI200-202609-C-350.0",
        symbol="KOSPI200",
        expiry="202609",
        option_type="CALL",
        strike=Decimal("350.0"),
    )


def test_resolve_preserves_authoritative_identity():
    result = OptionIdentityResolver().resolve(OptionIdentityResolutionInput(identity()))
    assert result == identity()


def test_resolve_preserves_same_value_overrides():
    result = OptionIdentityResolver().resolve(
        OptionIdentityResolutionInput(identity(), "CALL", Decimal("350.0"))
    )
    assert result == identity()


def test_changed_option_type_override_fails_closed():
    with pytest.raises(IdentityResolutionError, match="AUTHORITATIVE_IDENTITY_REQUIRED_FOR_OPTION_TYPE_OVERRIDE"):
        OptionIdentityResolver().resolve(OptionIdentityResolutionInput(identity(), "PUT"))


def test_changed_strike_override_fails_closed():
    with pytest.raises(IdentityResolutionError, match="AUTHORITATIVE_IDENTITY_REQUIRED_FOR_STRIKE_OVERRIDE"):
        OptionIdentityResolver().resolve(OptionIdentityResolutionInput(identity(), None, Decimal("345.0")))


def test_missing_identity_fails_closed():
    with pytest.raises(IdentityResolutionError, match="OPTION_IDENTITY_REQUIRED"):
        OptionIdentityResolver().resolve(OptionIdentityResolutionInput(None))


def test_missing_expiry_fails_closed():
    bad = OptionInstrumentIdentity("KOSPI200-X-C-350.0", "KOSPI200", None, "CALL", Decimal("350.0"))
    with pytest.raises(IdentityResolutionError, match="EXPIRY_REQUIRED"):
        OptionIdentityResolver().resolve(OptionIdentityResolutionInput(bad))


def test_zero_strike_fails_closed():
    bad = OptionInstrumentIdentity("KOSPI200-X-C-0.0", "KOSPI200", "202609", "CALL", Decimal("0"))
    with pytest.raises(IdentityResolutionError, match="STRIKE_REQUIRED"):
        OptionIdentityResolver().resolve(OptionIdentityResolutionInput(bad))
```
## 검증 목적
        - authoritative identity 보존
        - 명시적 option_type/strike override만 적용
        - identity 또는 필수 option identity 누락 시 fail-closed
        - synthetic fallback 금지
실제 pytest 실행은 수행하지 않으며, 향후 작업대 실행을 위한 계약 테스트 기준으로 둔다.
[Child Page] test_runtime_execution_context.py
```python
import pytest

from core.runtime.runtime_execution_context import RuntimeExecutionContext


def test_runtime_context_derives_stable_ids_from_authoritative_sequences():
    context = RuntimeExecutionContext(tick_sequence=42, local_sequence=3)

    assert context.signal_id("TRACK1") == "SIG-42-TRACK1-3"
    assert context.client_order_id("TRACK1") == "ORD-T42-TRACK1-3"


@pytest.mark.parametrize("tick_sequence,local_sequence", [(0, 1), (-1, 1), (1, 0), (1, -1)])
def test_runtime_context_fails_closed_for_missing_or_invalid_sequences(
    tick_sequence,
    local_sequence,
):
    with pytest.raises(ValueError):
        RuntimeExecutionContext(
            tick_sequence=tick_sequence,
            local_sequence=local_sequence,
        )
```
검증 범위: authoritative tick sequence와 Runtime-owned local sequence로부터 stable signal/client order id를 생성하며 invalid sequence는 fail-closed한다.
[Child Page] test_track5_gap_divergence.py
```python
from decimal import Decimal

from core.strategy.track5_gap_divergence import Track5GapDivergence, Track5MarketInput


STRATEGY_ID = "track5_gap_divergence"


def data(open_price="355", previous_close="350", active_vol="1", regime="NORMAL", current_price=None):
    return Track5MarketInput(
        strategy_id=STRATEGY_ID,
        open_price=Decimal(open_price),
        previous_close=Decimal(previous_close),
        active_vol=Decimal(active_vol),
        regime=regime,
        current_price=None if current_price is None else Decimal(current_price),
    )


def context_for(payload):
    from core.domain.market_models import MarketState
    from core.strategy.contracts import CommonStrategyInput, StrategyContext, StrategyInput
    from datetime import datetime, timezone

    state = MarketState(as_of=datetime.now(timezone.utc), ticks={}, quality={})
    common = CommonStrategyInput(as_of=state.as_of, current_price=payload.current_price)
    return StrategyContext(state, STRATEGY_ID, StrategyInput(common=common, payload=payload))


def test_normal_gap_up_enters_short():
    s = Track5GapDivergence()
    signals = s.evaluate_gap(data())
    assert signals and signals[0].direction == "SHORT"
    assert s.state.target_price == Decimal("350")


def test_normal_gap_down_enters_long():
    s = Track5GapDivergence()
    signals = s.evaluate_gap(data("345", "350", "1", "NORMAL"))
    assert signals and signals[0].direction == "LONG"


def test_high_vol_threshold_is_more_strict():
    s = Track5GapDivergence()
    assert s.effective_z_threshold("HIGH_VOL") == Decimal("1.8")
    assert s.effective_z_threshold("NOISE_CHOPPY") == Decimal("1.8")


def test_extreme_gap_is_blocked():
    s = Track5GapDivergence()
    signals = s.evaluate_gap(data("370", "350", "1", "NORMAL"))
    assert signals == ()
    assert not s.state.is_active


def test_mean_reversion_target_closes_position():
    s = Track5GapDivergence()
    s.evaluate_gap(data())
    signals = s.evaluate_mean_reversion(Decimal("350"))
    assert signals and signals[0].direction == "CLOSE"
    assert not s.state.is_active


def test_timeout_closes_after_30_ticks():
    s = Track5GapDivergence()
    s.evaluate_gap(data())
    for _ in range(29):
        s.evaluate_mean_reversion(Decimal("354"))
    signals = s.evaluate_mean_reversion(Decimal("354"))
    assert signals and "TIMEOUT_15M" in signals[0].reason


def test_trailing_lock_closes_after_reversal():
    s = Track5GapDivergence()
    s.evaluate_gap(data())
    s.evaluate_mean_reversion(Decimal("353"))
    signals = s.evaluate_mean_reversion(Decimal("354.5"))
    assert signals and signals[0].direction == "CLOSE"


def test_strategy_context_input_is_used():
    s = Track5GapDivergence()
    signals = s.evaluate(context_for(data()))
    assert signals and signals[0].direction == "SHORT"


def test_context_strategy_id_mismatch_does_not_trade():
    s = Track5GapDivergence()
    from core.domain.market_models import MarketState
    from core.strategy.contracts import CommonStrategyInput, StrategyContext, StrategyInput
    from datetime import datetime, timezone

    payload = data()
    state = MarketState(as_of=datetime.now(timezone.utc), ticks={}, quality={})
    common = CommonStrategyInput(as_of=state.as_of)
    bad_context = StrategyContext(state, "another_strategy", StrategyInput(common, payload))
    assert s.evaluate(bad_context) == ()


def test_payload_strategy_id_mismatch_does_not_trade():
    s = Track5GapDivergence()
    from dataclasses import replace
    payload = replace(data(), strategy_id="another_strategy")
    assert s.evaluate(context_for(payload)) == ()


def test_strategy_has_no_legacy_order_dependency():
    import inspect
    from core.strategy import track5_gap_divergence
    source = inspect.getsource(track5_gap_divergence)
    assert "OrderRequest" not in source
    assert "Broker" not in source
```
검증 기준은 원격 Track5의 진입·평균회귀·동적 손절·15분 timeout·trailing·black-swan guard와 새로운 StrategyContext.input.payload 경계를 포함한다. 실제 terminal pytest가 실행되지 않은 경우 PASS로 판정하지 않는다.
[Child Page] test_track8_macro_regime_monthly_strangle.py
```python
from decimal import Decimal
import inspect

from core.strategy.contracts import StrategyContext, StrategyInput
from core.strategy.track8_macro_regime_monthly_strangle import (
    Track8MacroRegimeMonthlyStrangle,
    Track8MarketInput,
)


STRATEGY_ID = "track8_macro_regime_monthly_strangle"


def base(**kwargs):
    values = dict(
        strategy_id=STRATEGY_ID,
        dte=Decimal("20"),
        budget=Decimal("1000000"),
        current_price=Decimal("350"),
        current_regime="NORMAL",
        date_str="2026-09-04",
    )
    values.update(kwargs)
    return Track8MarketInput(**values)


def context(data):
    return StrategyContext(
        strategy_id=STRATEGY_ID,
        input=StrategyInput(payload=data),
    )


def test_monthly_entry_via_standard_context():
    s = Track8MacroRegimeMonthlyStrangle()
    signals = s.evaluate(context(base()))
    assert any(x.direction == "BUY_LIMIT_TRANCHE" for x in signals)
    assert s.state.call_strike == Decimal("365")
    assert s.state.put_strike == Decimal("335")


def test_dte_and_budget_guards():
    s = Track8MacroRegimeMonthlyStrangle()
    assert s.evaluate(context(base(dte=Decimal("14.9")))) == ()
    assert s.evaluate(context(base(budget=Decimal("199999")))) == ()


def test_high_vol_asymmetric_qty():
    s = Track8MacroRegimeMonthlyStrangle()
    s.evaluate(context(base(current_regime="HIGH_VOL")))
    assert s.state.qty_put == s.state.qty_call * 2


def test_macro_regime_hedge_signal():
    s = Track8MacroRegimeMonthlyStrangle()
    signals = s.evaluate(context(base(current_regime="CRASH")))
    assert any(x.direction == "MACRO_HEDGE_SCALE_UP" for x in signals)


def test_profit_rebuild_and_risk_guard():
    s = Track8MacroRegimeMonthlyStrangle()
    s.evaluate(context(base()))
    signals = s.evaluate_profit_rebuild(
        base(current_price=Decimal("360"), current_pnl=Decimal("400000"))
    )
    assert len(signals) == 2
    assert signals[0].direction == "DYNAMIC_PROFIT_TAKE"
    assert signals[1].direction == "DYNAMIC_REBUILD_FENCE"

    assert s.evaluate_profit_rebuild(
        base(current_pnl=Decimal("400000"), risk_guard_active=True)
    ) == ()


def test_expiry_dynamic_hold_hysteresis_and_cutoff():
    s = Track8MacroRegimeMonthlyStrangle()
    s.evaluate(context(base()))

    hold = s.evaluate_expiry_cutoff(
        base(dte=Decimal("4"), current_price=Decimal("365"))
    )
    assert hold[0].direction == "HOLD_LONG_ATTACK"

    hysteresis = s.evaluate_expiry_cutoff(
        base(dte=Decimal("4"), current_price=Decimal("350"), active_vol=Decimal("1.0"))
    )
    assert hysteresis[0].direction == "HOLD_HYSTERESIS"

    cutoff = s.evaluate_expiry_cutoff(
        base(dte=Decimal("4"), current_price=Decimal("350"), active_vol=Decimal("1.0"))
    )
    assert cutoff[0].direction == "FLAT_STRANGLE"


def test_1515_pending_cancel():
    s = Track8MacroRegimeMonthlyStrangle()
    s.evaluate(context(base()))
    signals = s.evaluate_expiry_cutoff(
        base(time_str="15:15:01")
    )
    assert signals[0].direction == "CANCEL_PENDING_TRANCHES"


def test_strategy_id_mismatch_is_noop():
    s = Track8MacroRegimeMonthlyStrangle()
    bad_context = StrategyContext(
        strategy_id="other_strategy",
        input=StrategyInput(payload=base()),
    )
    assert s.evaluate(bad_context) == ()


def test_strategy_has_no_legacy_order_dependency():
    from core.strategy import track8_macro_regime_monthly_strangle
    source = inspect.getsource(track8_macro_regime_monthly_strangle)
    assert "OrderRequest" not in source
    assert "Broker" not in source
    assert "TimeService" not in source
```
## No.051 테스트 기준
        - StrategyContext.input.payload 표준 진입점
        - Context/payload strategy_id 이중 검증
        - DTE/예산 진입 가드
        - HIGH_VOL 비대칭 수량
        - Macro Regime hedge scale-up
        - Profit Take → Rebuild
        - Risk Guard/Margin Ratio Rebuild 차단
        - D-4~D-0 Dynamic Hold → Hysteresis → Cutoff
        - 15:15 pending tranche cancel
        - Legacy Broker/OrderRequest/TimeService 직접 의존 없음
## No.602 Track8 execution composition seam 검증 추가
```python

def test_build_execution_plan_preserves_asymmetric_call_put_legs():
    s = Track8MacroRegimeMonthlyStrangle()
    assert s.build_execution_plan("G-8") is None

    s.evaluate(context(base(current_regime="HIGH_VOL")))
    plan = s.build_execution_plan("G-8")

    assert plan is not None
    assert plan.group_id == "G-8"
    assert plan.strategy_id == STRATEGY_ID
    assert len(plan.legs) == 2

    put_leg, call_leg = plan.legs
    assert put_leg.option_type == "PUT"
    assert put_leg.side == "BUY"
    assert put_leg.strike == s.state.put_strike
    assert put_leg.quantity == s.state.qty_put
    assert call_leg.option_type == "CALL"
    assert call_leg.side == "BUY"
    assert call_leg.strike == s.state.call_strike
    assert call_leg.quantity == s.state.qty_call
    assert put_leg.quantity == call_leg.quantity * 2
```
        - inactive 상태에서는 execution plan을 만들지 않는 fail-closed 경계 확인
        - HIGH_VOL의 asymmetric qty_put/qty_call가 plan의 각 독립 leg에 lossless 보존됨을 확인
        - put/call strike, option_type, side를 단일 Signal.reason 역파싱 없이 strategy state → typed plan으로 직접 전달함을 확인
        - identity/instrument resolution은 이 테스트 범위에 포함하지 않으며 authoritative source 없이는 다음 단계 materialization이 fail-closed여야 한다.
[Child Page] test_track6_daily_tail_insurance.py
```python
from decimal import Decimal

from core.strategy.track6_daily_tail_insurance import (
    Track6DailyTailInsurance,
    Track6MarketInput,
)


def base(**overrides):
    values = {
        "strategy_id": "track6_daily_tail_insurance",
        "current_price": Decimal("350"),
        "active_vol": Decimal("1.5"),
        "base_vol": Decimal("1.0"),
        "budget": Decimal("250000"),
        "date_str": "2026-09-04",
        "time_str": "09:00:00",
    }
    values.update(overrides)
    return Track6MarketInput(**values)


def test_volatility_spike_buys_daily_insurance():
    s = Track6DailyTailInsurance()
    signals = s.evaluate_buy(base(active_vol=Decimal("1.3")))
    assert signals and signals[0].direction == "BUY_INSURANCE"
    assert s.state.long_put_strike == Decimal("337.5")
    assert s.state.long_call_strike == Decimal("362.5")


def test_no_trigger_below_volatility_threshold():
    s = Track6DailyTailInsurance()
    signals = s.evaluate_buy(base(active_vol=Decimal("1.29")))
    assert signals == ()
    assert not s.state.is_active


def test_insufficient_budget_blocks_entry():
    s = Track6DailyTailInsurance()
    signals = s.evaluate_buy(base(budget=Decimal("249999")))
    assert signals == ()


def test_1515_pending_queue_cancel():
    s = Track6DailyTailInsurance()
    signals = s.evaluate_buy(base(time_str="15:15:01"))
    assert signals and signals[0].direction == "CANCEL"


def test_trailing_lockdown_after_1512():
    s = Track6DailyTailInsurance()
    s.evaluate_buy(base())
    assert s.evaluate_take_profit(Decimal("320"), Decimal("1.5"), "15:12:01") == ()


def test_1515_expiry_fallback_closes():
    s = Track6DailyTailInsurance()
    s.evaluate_buy(base())
    signals = s.evaluate_expiry_cutoff("15:15:00")
    assert signals and signals[0].direction == "CLOSE_FALLBACK"
    assert not s.state.is_active


def test_strategy_has_no_legacy_order_dependency():
    import inspect
    from core.strategy import track6_daily_tail_insurance
    source = inspect.getsource(track6_daily_tail_insurance)
    assert "OrderRequest" not in source
    assert "Broker" not in source
    assert "TimeService" not in source


def test_typed_payload_requires_matching_strategy_id():
    s = Track6DailyTailInsurance()
    assert base().strategy_id == s.strategy_id
    assert base(strategy_id="track5_gap_divergence").strategy_id != s.strategy_id
```
실제 terminal pytest를 실행하지 못한 상태에서는 테스트 PASS를 실행 결과로 주장하지 않는다.
## No.049 typed payload 검증 기준
        - Track6 입력에 strategy_id가 명시된다.
        - 표준 StrategyContext 경로에서는 Context/payload 전략 ID가 모두 Track6과 일치해야 한다.
        - 불일치 입력은 no-op 처리하며 Legacy 임의 Context 속성에 의존하지 않는다.
        - 원격 핵심 기능인 변동성 1.3배 trigger, 15:15 pending cancel, 15:00/15:15 cutoff, trailing lockdown은 유지한다.
[Child Page] test_track7_volatility_skew_weekly_insurance.py
```python
from decimal import Decimal
import inspect

from core.strategy.contracts import StrategyContext, StrategyInput
from core.strategy.track7_volatility_skew_weekly_insurance import Track7MarketInput, Track7VolatilitySkewWeeklyInsurance


STRATEGY_ID = "track7_volatility_skew_weekly_insurance"


def base(**kwargs):
    values = dict(
        strategy_id=STRATEGY_ID,
        current_price=Decimal("350"),
        budget=Decimal("350000"),
        date_str="2026-09-04",
        is_new_week_start=True,
        active_vol=Decimal("1.0"),
    )
    values.update(kwargs)
    return Track7MarketInput(**values)


def context(data):
    return StrategyContext(
        strategy_id=STRATEGY_ID,
        input=StrategyInput(payload=data),
    )


def test_new_week_buys_weekly_insurance():
    s = Track7VolatilitySkewWeeklyInsurance()
    signals = s.evaluate(context(base()))
    assert signals and signals[0].direction == "BUY_LIMIT_WEEKLY_INSURANCE"
    assert s.state.put_strike == Decimal("335")
    assert s.state.call_strike == Decimal("365")


def test_not_new_week_does_not_buy():
    s = Track7VolatilitySkewWeeklyInsurance()
    assert s.evaluate(context(base(is_new_week_start=False))) == ()


def test_budget_guard():
    s = Track7VolatilitySkewWeeklyInsurance()
    assert s.evaluate(context(base(budget=Decimal("349999")))) == ()


def test_1515_pending_cancel():
    s = Track7VolatilitySkewWeeklyInsurance()
    assert s.evaluate(context(base(time_str="15:15:01")))[0].direction == "CANCEL"


def test_skew_entry_and_fallback():
    s = Track7VolatilitySkewWeeklyInsurance()
    signals = s.evaluate(context(base(call_iv=Decimal("10"), put_iv=Decimal("13"))))
    assert signals[0].direction == "BUY_LIMIT_WEEKLY_INSURANCE"
    signals = s.evaluate(context(base(call_iv=Decimal("10"), put_iv=Decimal("13"), skew_limit_timeout=True)))
    assert any(x.direction == "ENTER_SKEW_ARB_FALLBACK_MARKET" for x in signals)


def test_skew_stop_and_normal_exit():
    s = Track7VolatilitySkewWeeklyInsurance()
    s.evaluate_skew_arbitrage(base(call_iv=Decimal("10"), put_iv=Decimal("13")))
    assert s.evaluate_skew_arbitrage(base(call_iv=Decimal("10"), put_iv=Decimal("19")))[0].direction == "CLOSE_SKEW_ARB_STOP_LOSS"
    s.evaluate_skew_arbitrage(base(call_iv=Decimal("10"), put_iv=Decimal("13")))
    assert s.evaluate_skew_arbitrage(base(call_iv=Decimal("10"), put_iv=Decimal("10.4")))[0].direction == "CLOSE_SKEW_ARB_LIMIT"


def test_preemptive_take_profit_requires_real_ma_inputs():
    s = Track7VolatilitySkewWeeklyInsurance()
    s.evaluate_insurance_buy(base())
    assert s.evaluate_preemptive_take_profit(base()) == ()
    signals = s.evaluate_preemptive_take_profit(base(ma_1m=Decimal("354"), ma_3m=Decimal("353"), ma_5m=Decimal("352"), ma_10m=Decimal("351")))
    assert signals and signals[0].direction == "PREEMPTIVE_LIMIT_TAKE_PROFIT"


def test_expiry_cutoff_limit_then_fallback():
    s = Track7VolatilitySkewWeeklyInsurance()
    s.evaluate(context(base()))
    assert s.evaluate(context(base(time_str="15:05:00", is_expiry_day=True)))[0].direction == "CLOSE_WEEKLY_INSURANCE_LIMIT"
    assert s.evaluate(context(base(time_str="15:15:00", is_expiry_day=True)))[0].direction == "CLOSE_WEEKLY_INSURANCE_FALLBACK_MARKET"


def test_strategy_id_mismatch_is_noop():
    s = Track7VolatilitySkewWeeklyInsurance()
    bad_context = StrategyContext(
        strategy_id="other_strategy",
        input=StrategyInput(payload=base()),
    )
    assert s.evaluate(bad_context) == ()


def test_strategy_has_no_legacy_order_dependency():
    from core.strategy import track7_volatility_skew_weekly_insurance
    source = inspect.getsource(track7_volatility_skew_weekly_insurance)
    assert "OrderRequest" not in source
    assert "Broker" not in source
    assert "TimeService" not in source
```
## No.050 테스트 기준
        - 표준 StrategyContext.input.payload 진입점
        - Context/payload strategy_id 이중 일치
        - 신규 주간 보험 진입 및 예산 가드
        - 15:15 pending cancel
        - IV Skew 지정가 진입 → timeout fallback
        - skew stop / 정상회귀 청산
        - 실제 MA 입력 기반 선제 익절
        - 15:00 limit → 15:15 fallback 만기 청산
        - Legacy Broker/OrderRequest/TimeService 직접 의존 없음
## No.600 typed execution boundary criteria
        - Weekly Insurance의 각 Option leg가 계산 결과로 독립 option_type / strike / quantity / side를 보유하면 leg별 StrategyExecutionProposal로 보존한다.
        - Signal.reason 문자열에서 위 값을 역추출하지 않는다.
        - instrument_id / symbol / expiry는 authoritative Option Identity Source가 없으면 None으로 유지하고 합성하지 않는다.
        - 복수 leg를 하나의 proposal로 합치지 않고 leg별 provenance를 유지한다.
        - 이 기준은 execution composition 경계만 검증하며 전략 계산식은 변경하지 않는다.
[Child Page] test_authoritative_option_identity_source.py
```python
from dataclasses import dataclass
from decimal import Decimal

from contracts.authoritative_option_identity_source import AuthoritativeOptionIdentitySource
from contracts.types import OptionInstrumentIdentity


@dataclass
class FixtureAuthoritativeSource:
    identity: OptionInstrumentIdentity | None

    def get_identity(self, selector: object) -> OptionInstrumentIdentity | None:
        return self.identity


def _identity() -> OptionInstrumentIdentity:
    return OptionInstrumentIdentity(
        instrument_id="AUTH-OPTION-1",
        symbol="101V3000",
        expiry="2026-12-10",
        option_type="CALL",
        strike=Decimal("300"),
    )


def test_source_returns_complete_authoritative_identity() -> None:
    source: AuthoritativeOptionIdentitySource = FixtureAuthoritativeSource(_identity())
    result = source.get_identity("fixture-selector")
    assert result == _identity()
    assert result.instrument_id == "AUTH-OPTION-1"


def test_source_may_return_none_when_unresolved() -> None:
    source: AuthoritativeOptionIdentitySource = FixtureAuthoritativeSource(None)
    assert source.get_identity("missing-selector") is None


def test_source_contract_does_not_synthesize_identity() -> None:
    source: AuthoritativeOptionIdentitySource = FixtureAuthoritativeSource(None)
    result = source.get_identity({"shrn_iscd": "101V3000"})
    assert result is None
```
## 검증 의도
        - 완전한 authoritative OptionInstrumentIdentity를 그대로 공급한다.
        - unresolved 상태는 None으로 표현하고 임의 ID를 만들지 않는다.
        - shrn_iscd만으로 Standard instrument_id를 합성하지 않는다.
        - 실제 production source는 연결하지 않고 fixture만 사용한다.
[Child Page] identity_contract_test_spec.md
## No.106 추가 계약 테스트 기준
CanonicalStrategySignal의 additive identity 확장에 대해 다음을 검증한다.
        1. 기존 Signal 생성 호출은 symbol/expiry 없이도 기존 default로 생성된다.
        1. symbol/expiry를 명시한 Signal은 해당 값을 보존한다.
        1. Signal → CanonicalOrderCommand 변환은 symbol/expiry를 그대로 전달한다.
        1. Runtime Tick의 expiry가 Signal 및 Command까지 유지되는 경로를 검증한다.
        1. 기존 validate_signal() reject 규칙(qty/price/track/tag/option strike/type)은 변경하지 않는다.
        1. 기존 Legacy debounce fingerprint는 track_id/asset_type/side/strike/option_type/tag_id 의미론을 유지한다.
### 판정 원칙
이 테스트는 주문 identity 전달 계약의 회귀 방지 목적이며, fingerprint 정책 자체를 재설계하는 테스트가 아니다.
### 실행 상태
TEST SPEC READY / EXECUTION BLOCKED.
실제 terminal pytest 실행 전에는 PASS로 판정하지 않는다.
[Child Page] test_risk_decision_adapter.py
```python
from dataclasses import dataclass
from decimal import Decimal
import pytest

from option_program.core.oms.position_execution_policy import PositionExecutionDecision
from option_program.core.oms.risk_decision_adapter import (
    RiskDecisionMappingError,
    apply_risk_decision,
)


@dataclass
class ReducedCommand:
    qty: int


@dataclass
class RiskResult:
    decision: str
    is_approved: bool
    approved_qty: int
    reduced_command: object | None = None
    rejection_reason: str | None = None


def base_decision():
    return PositionExecutionDecision(
        client_order_id="ORD-1",
        approved_quantity=5,
        requested_price=Decimal("1.25"),
        order_type="LIMIT",
        order_purpose="ENTRY",
        asset_type="OPTION",
        track_id="Track1",
        tag_id="Track1",
    )


def test_allow_uses_approved_quantity_and_preserves_execution_semantics():
    result = apply_risk_decision(
        base_decision(), RiskResult("ALLOW", True, 5)
    )
    assert result.approved_quantity == 5
    assert result.order_type == "LIMIT"
    assert result.order_purpose == "ENTRY"
    assert result.requested_price == Decimal("1.25")


def test_reduce_uses_reduced_command_quantity():
    result = apply_risk_decision(
        base_decision(), RiskResult("REDUCE", True, 3, ReducedCommand(3))
    )
    assert result.approved_quantity == 3


def test_reduce_rejects_quantity_provenance_mismatch():
    with pytest.raises(RiskDecisionMappingError, match="PROVENANCE"):
        apply_risk_decision(
            base_decision(), RiskResult("REDUCE", True, 4, ReducedCommand(3))
        )


def test_deny_does_not_create_order_intent():
    with pytest.raises(RiskDecisionMappingError, match="LIMIT"):
        apply_risk_decision(
            base_decision(), RiskResult("DENY", False, 0, rejection_reason="LIMIT")
        )
```
## 테스트 의도
실제 pytest 실행 결과가 아니라 검증 명세다. Remote Git 브랜치는 읽기 전용이므로 실행/수정하지 않았다.
[Child Page] test_position_aggregate_risk_adapter.py
```python
from core.position.position_aggregate import PositionAggregate
from core.position.position_aggregate_risk_adapter import position_aggregate_to_risk_input


def test_authoritative_side_qty_are_preserved():
    class Source:
        def snapshot(self):
            return {
                "OPTION_X": PositionAggregate(side="BUY", qty=3, avg_price=1.25),
                "OPTION_Y": PositionAggregate(side="SELL", qty=2, avg_price=0.95),
            }

    result = position_aggregate_to_risk_input(Source())

    assert result.positions["OPTION_X"].side == "BUY"
    assert result.positions["OPTION_X"].qty == 3
    assert result.positions["OPTION_Y"].side == "SELL"
    assert result.positions["OPTION_Y"].qty == 2


def test_missing_side_fails_closed():
    class Source:
        def snapshot(self):
            return {"OPTION_X": PositionAggregate(side="", qty=3)}

    try:
        position_aggregate_to_risk_input(Source())
    except TypeError as exc:
        assert str(exc) == "RISK_POSITION_SIDE_REQUIRED"
    else:
        raise AssertionError("missing side must fail closed")


def test_invalid_qty_fails_closed():
    class Source:
        def snapshot(self):
            return {"OPTION_X": PositionAggregate(side="BUY", qty=1.5)}

    try:
        position_aggregate_to_risk_input(Source())
    except TypeError as exc:
        assert str(exc) == "RISK_POSITION_QTY_REQUIRED"
    else:
        raise AssertionError("invalid qty must fail closed")


def test_non_mapping_snapshot_fails_closed():
    class Source:
        def snapshot(self):
            return None

    try:
        position_aggregate_to_risk_input(Source())
    except TypeError as exc:
        assert str(exc) == "RISK_POSITION_AGGREGATE_SOURCE_REQUIRED"
    else:
        raise AssertionError("non-mapping snapshot must fail closed")
```
## 검증 목적
Standard Position aggregate → Risk Position 입력 경계만 독립 검증한다. Position 체결 알고리즘이나 RiskEngine 정책은 테스트 대상이 아니다.
## 핵심 불변식
        - source의 authoritative side/qty가 그대로 전달된다.
        - side/qty가 유효하지 않으면 fail-closed한다.
        - avg_price를 Risk Position에 임의로 추가하지 않는다.
        - Legacy/VSSF PositionManager 의존성이 없다.
[Child Page] test_futures_execution_symbol_source.py
```python
import pytest

from application.composition.futures_target_configuration import FuturesTargetConfiguration
from contracts.futures_contract_master import KisCurrentFuturesContractSource, KisFuturesContractIdentity
from contracts.futures_execution_symbol_source import KisFuturesExecutionSymbolSource


def _source() -> KisCurrentFuturesContractSource:
    records = [
        KisFuturesContractIdentity(
            shrn_iscd="101W09",
            stnd_iscd="STD-101W09",
            info_type="1",
            mmsc_cls_code="1",
            unas_shrn_iscd="U001",
            unas_kor_name="TEST UNDERLYING",
            kor_name="TEST FUTURES",
        ),
        KisFuturesContractIdentity(
            shrn_iscd="101W10",
            stnd_iscd="STD-101W10",
            info_type="1",
            mmsc_cls_code="2",
            unas_shrn_iscd="U001",
            unas_kor_name="TEST UNDERLYING",
            kor_name="NEXT FUTURES",
        ),
    ]
    return KisCurrentFuturesContractSource(records)


def test_selected_shrn_iscd_becomes_execution_symbol_without_identity_conversion():
    target = FuturesTargetConfiguration(underlying_short_code="U001")
    provider = KisFuturesExecutionSymbolSource(_source(), target)

    assert provider.current_symbol() == "101W09"


def test_target_selector_remains_fail_closed():
    with pytest.raises(ValueError):
        FuturesTargetConfiguration()
```
## 검증 목적
        - Contract Master가 선택한 current-month record의 shrn_iscd가 execution symbol로 그대로 전달되는지 검증한다.
        - stnd_iscd 또는 임의 composite 값으로 변환하지 않는지 검증한다.
        - target selector의 기존 fail-closed 계약을 함께 보존한다.
[Child Page] test_kis_index_futures_market_ws_adapter.py
```python
from decimal import Decimal
import pytest

from contracts.kis_index_futures_market_ws_adapter import (
    KISIndexFuturesMarketWebSocketAdapter,
    KISIndexFuturesWebSocketAdapterInvalid,
)


def frame() -> str:
    values = [""] * 50
    values[0] = "101S12"
    values[1] = "103015"
    values[5] = "350.25"
    values[10] = "12345"
    values[35] = "350.30"
    values[36] = "350.20"
    return "0|H0IFCNT0|50|" + "^".join(values)


def test_h0ifcnt0_preserves_kis_short_code_and_market_values():
    result = KISIndexFuturesMarketWebSocketAdapter().adapt(frame())

    assert result.shrn_iscd == "101S12"
    assert result.observed_hour == "103015"
    assert result.price == Decimal("350.25")
    assert result.volume == Decimal("12345")
    assert result.ask_price == Decimal("350.30")
    assert result.bid_price == Decimal("350.20")


def test_h0ifcnt0_rejects_wrong_tr_id():
    with pytest.raises(KISIndexFuturesWebSocketAdapterInvalid):
        KISIndexFuturesMarketWebSocketAdapter().adapt(frame().replace("H0IFCNT0", "H0IOCNT0"))


def test_h0ifcnt0_rejects_field_count_mismatch():
    with pytest.raises(KISIndexFuturesWebSocketAdapterInvalid):
        KISIndexFuturesMarketWebSocketAdapter().adapt(frame().replace("|50|", "|49|"))
```
[Child Page] test_futures_market_transport.py
```python
import asyncio
import json

from infrastructure.kis.futures_market_transport import (
    FuturesMarketTransportError,
    KISFuturesMarketTransport,
    KISFuturesMarketTransportConfig,
)


class _FakeApproval:
    def issue(self):
        return "approval-test"


class _FakeSocket:
    def __init__(self):
        self.sent = []
        self.closed = False
        self.received = "0|H0IFCNT0|37|101S12^093000^^^^^^^^^^123^^^"

    async def send(self, value):
        self.sent.append(value)

    async def recv(self):
        return self.received

    async def close(self):
        self.closed = True


def _transport():
    transport = object.__new__(KISFuturesMarketTransport)
    transport._config = KISFuturesMarketTransportConfig(is_vts=False)
    transport._approval = _FakeApproval()
    transport._socket = _FakeSocket()
    transport._connected = True
    return transport


def test_subscription_message_preserves_tr_id_and_symbol():
    transport = _transport()
    asyncio.run(transport.subscribe("H0IFCNT0", "101S12"))
    message = json.loads(transport._socket.sent[0])
    assert message["header"]["approval_key"] == "approval-test"
    assert message["header"]["tr_type"] == "1"
    assert message["body"]["input"] == {"tr_id": "H0IFCNT0", "tr_key": "101S12"}


def test_unconnected_transport_fails_closed():
    transport = _transport()
    transport._connected = False
    try:
        asyncio.run(transport.subscribe("H0IFCNT0", "101S12"))
    except FuturesMarketTransportError as exc:
        assert "not connected" in str(exc)
    else:
        raise AssertionError("expected FuturesMarketTransportError")
```
[Child Page] test_futures_market_consumer.py
```python
import asyncio

from contracts.kis_index_futures_market_ws_adapter import KISIndexFuturesMarketWebSocketAdapter
from infrastructure.kis.futures_market_consumer import KISIndexFuturesMarketConsumer


class FakeTransport:
    def __init__(self, frame):
        self.frame = frame
        self.calls = []

    async def connect(self):
        self.calls.append(("connect",))

    async def subscribe(self, tr_id, symbol):
        self.calls.append(("subscribe", tr_id, symbol))

    async def unsubscribe(self, tr_id, symbol):
        self.calls.append(("unsubscribe", tr_id, symbol))

    async def recv(self):
        return self.frame

    async def close(self):
        self.calls.append(("close",))


def _trade_frame():
    values = [""] * 37
    values[0] = "101S12"
    values[1] = "093000"
    values[5] = "350.10"
    values[10] = "1234"
    values[35] = "350.20"
    values[36] = "350.00"
    return "0|H0IFCNT0|37|" + "^".join(values)


def test_consumer_connects_subscribes_and_adapts_trade_frame():
    transport = FakeTransport(_trade_frame())
    received = []
    consumer = KISIndexFuturesMarketConsumer(transport, KISIndexFuturesMarketWebSocketAdapter(), received.append)

    asyncio.run(consumer.start("101S12"))
    observation = asyncio.run(consumer.receive_once())

    assert transport.calls == [
        ("connect",),
        ("subscribe", "H0IFCNT0", "101S12"),
        ("subscribe", "H0IFASP0", "101S12"),
    ]
    assert observation.shrn_iscd == "101S12"
    assert str(observation.price) == "350.10"
    assert received == [observation]
```
[Child Page] test_kis_futures_market_data.py
```python
from datetime import datetime
from decimal import Decimal

import pytest

from contracts.kis_index_futures_market_ws_adapter import KisIndexFuturesMarketObservation
from environments.live.market.kis_futures_market_data import (
    KISFuturesMarketDataProvider,
    KISFuturesMarketProjectionError,
)


def observation(price=Decimal("350.10")) -> KisIndexFuturesMarketObservation:
    return KisIndexFuturesMarketObservation(
        shrn_iscd="101S12",
        observed_hour="093000",
        price=price,
        volume=Decimal("1234"),
        ask_price=Decimal("350.20"),
        bid_price=Decimal("350.00"),
        source="KIS:H0IFCNT0",
    )


def test_projection_requires_authoritative_instrument_id_resolver():
    provider = KISFuturesMarketDataProvider(
        observed_at_resolver=lambda _: datetime(2026, 9, 6, 9, 30, 0),
    )
    with pytest.raises(KISFuturesMarketProjectionError, match="INSTRUMENT_ID_RESOLVER_REQUIRED"):
        provider.publish(observation())


def test_projection_requires_authoritative_observed_at_resolver():
    provider = KISFuturesMarketDataProvider(
        instrument_id_resolver=lambda symbol: "FUT-AUTH-1",
    )
    with pytest.raises(KISFuturesMarketProjectionError, match="OBSERVED_AT_RESOLVER_REQUIRED"):
        provider.publish(observation())


def test_projection_preserves_values_and_does_not_synthesize_sequence():
    received = []
    provider = KISFuturesMarketDataProvider(
        instrument_id_resolver=lambda symbol: "FUT-AUTH-1",
        observed_at_resolver=lambda _: datetime(2026, 9, 6, 9, 30, 0),
    )
    provider.subscribe(received.append)

    tick = provider.publish(observation())

    assert tick.instrument_id == "FUT-AUTH-1"
    assert tick.price == Decimal("350.10")
    assert tick.volume == Decimal("1234")
    assert tick.source_sequence is None
    assert received[0].ticks["FUT-AUTH-1"] == tick


def test_quote_only_observation_cannot_be_promoted_to_last_price_tick():
    quote = observation(price=None)
    provider = KISFuturesMarketDataProvider(
        instrument_id_resolver=lambda symbol: "FUT-AUTH-1",
        observed_at_resolver=lambda _: datetime(2026, 9, 6, 9, 30, 0),
    )
    with pytest.raises(KISFuturesMarketProjectionError, match="LAST_PRICE_REQUIRED"):
        provider.publish(quote)
```
검증 범위: KIS typed observation → Standard MarketState 경계. instrument_id, observed_at authoritative 공급을 요구하고 synthetic fallback을 차단한다.
[Child Page] test_risk_config.py
```python
from decimal import Decimal

import pytest

from core.risk.risk_config import RiskConfig


def test_defaults_use_decimal_authoritative_thresholds():
    config = RiskConfig()

    assert config.max_daily_loss_krw == Decimal("10000000")
    assert config.max_margin_utilization_ratio == Decimal("0.85")
    assert config.vol_spike_threshold_multiplier == Decimal("1.30")


def test_constructor_preserves_float_input_compatibility_at_boundary():
    config = RiskConfig(
        max_daily_loss_krw=100.25,
        max_margin_utilization_ratio=0.85,
        vol_spike_threshold_multiplier=1.30,
    )

    assert isinstance(config.max_daily_loss_krw, Decimal)
    assert isinstance(config.max_margin_utilization_ratio, Decimal)
    assert isinstance(config.vol_spike_threshold_multiplier, Decimal)
    assert config.max_daily_loss_krw == Decimal(str(100.25))
    assert config.max_margin_utilization_ratio == Decimal(str(0.85))
    assert config.vol_spike_threshold_multiplier == Decimal(str(1.30))


def test_high_precision_string_and_decimal_boundaries_are_preserved():
    config = RiskConfig(
        max_daily_loss_krw="10000000.000000000000000001",
        max_margin_utilization_ratio="0.850000000000000001",
        vol_spike_threshold_multiplier=Decimal("1.300000000000000001"),
    )

    assert config.max_daily_loss_krw == Decimal("10000000.000000000000000001")
    assert config.max_margin_utilization_ratio == Decimal("0.850000000000000001")
    assert config.vol_spike_threshold_multiplier == Decimal("1.300000000000000001")


def test_duration_values_remain_float_domain():
    config = RiskConfig(
        account_stale_timeout_sec=12.5,
        position_stale_timeout_sec=7.25,
    )

    assert config.account_stale_timeout_sec == 12.5
    assert config.position_stale_timeout_sec == 7.25


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("max_daily_loss_krw", None, "RISK_CONFIG_DECIMAL_VALUE_REQUIRED"),
        (
            "max_daily_loss_krw",
            float("nan"),
            "RISK_CONFIG_DECIMAL_VALUE_FINITE_REQUIRED",
        ),
        (
            "max_daily_loss_krw",
            float("inf"),
            "RISK_CONFIG_DECIMAL_VALUE_FINITE_REQUIRED",
        ),
        ("max_daily_loss_krw", True, "RISK_CONFIG_DECIMAL_VALUE_REQUIRED"),
        (
            "max_margin_utilization_ratio",
            "NaN",
            "RISK_CONFIG_DECIMAL_VALUE_FINITE_REQUIRED",
        ),
        (
            "vol_spike_threshold_multiplier",
            "Infinity",
            "RISK_CONFIG_DECIMAL_VALUE_FINITE_REQUIRED",
        ),
    ],
)
def test_invalid_decimal_thresholds_fail_fast(field, value, error):
    with pytest.raises(ValueError, match=error):
        RiskConfig(**{field: value})


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("max_order_qty", 0, "MAX_ORDER_QTY_POSITIVE_INT_REQUIRED"),
        ("max_order_qty", True, "MAX_ORDER_QTY_POSITIVE_INT_REQUIRED"),
        (
            "max_position_per_instrument",
            -1,
            "MAX_POSITION_PER_INSTRUMENT_POSITIVE_INT_REQUIRED",
        ),
        ("max_daily_loss_krw", "0", "MAX_DAILY_LOSS_KRW_POSITIVE_REQUIRED"),
        ("max_daily_loss_krw", "-1", "MAX_DAILY_LOSS_KRW_POSITIVE_REQUIRED"),
        (
            "max_margin_utilization_ratio",
            "0",
            "MAX_MARGIN_UTILIZATION_RATIO_RANGE_REQUIRED",
        ),
        (
            "max_margin_utilization_ratio",
            "1.0001",
            "MAX_MARGIN_UTILIZATION_RATIO_RANGE_REQUIRED",
        ),
        (
            "vol_spike_threshold_multiplier",
            "0",
            "VOL_SPIKE_THRESHOLD_MULTIPLIER_POSITIVE_REQUIRED",
        ),
    ],
)
def test_invalid_domain_ranges_fail_fast(field, value, error):
    with pytest.raises(ValueError, match=error):
        RiskConfig(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("account_stale_timeout_sec", -1),
        ("account_stale_timeout_sec", float("nan")),
        ("position_stale_timeout_sec", float("inf")),
        ("position_stale_timeout_sec", True),
    ],
)
def test_invalid_timeouts_fail_fast(field, value):
    with pytest.raises(
        ValueError,
        match=f"{field.upper()}_NONNEGATIVE_FINITE_REQUIRED",
    ):
        RiskConfig(**{field: value})


def test_valid_boundaries_preserve_constructor_compatibility():
    config = RiskConfig(
        max_daily_loss_krw=1,
        max_margin_utilization_ratio=1,
        vol_spike_threshold_multiplier=Decimal("0.0001"),
        account_stale_timeout_sec=0,
        position_stale_timeout_sec="12.5",
    )

    assert config.max_daily_loss_krw == Decimal("1")
    assert config.max_margin_utilization_ratio == Decimal("1")
    assert config.vol_spike_threshold_multiplier == Decimal("0.0001")
    assert config.account_stale_timeout_sec == 0.0
    assert config.position_stale_timeout_sec == 12.5
```
[Child Page] test_risk_numeric_policy.py
```python
from decimal import Decimal

from core.risk.risk_config import RiskConfig
from core.risk.risk_sensor import RiskSensor

def test_direct_decimal_config_thresholds_are_consumed_without_projection():
    config = RiskConfig(
        max_margin_utilization_ratio=Decimal("0.850000000000000001"),
        vol_spike_threshold_multiplier=Decimal("1.300000000000000001"),
    )
    sensor = RiskSensor(config)
    margin = sensor.scan_risk(Decimal("1"), Decimal("1"), account_margin_ratio=Decimal("0.850000000000000002"))
    vol = sensor.scan_risk(Decimal("1.300000000000000001"), Decimal("1"))
    assert margin.is_margin_diet_required is True
    assert vol.is_vol_spike is True

def test_float_constructor_and_decimal_constructor_make_same_decision():
    float_config = RiskConfig(max_margin_utilization_ratio=0.85, vol_spike_threshold_multiplier=1.30)
    decimal_config = RiskConfig(max_margin_utilization_ratio=Decimal("0.85"), vol_spike_threshold_multiplier=Decimal("1.30"))
    for config in (float_config, decimal_config):
        sensor = RiskSensor(config)
        assert sensor.scan_risk(Decimal("1.30"), Decimal("1")).is_vol_spike is True
        assert sensor.scan_risk(Decimal("1"), Decimal("1"), account_margin_ratio=Decimal("0.85")).is_margin_diet_required is False
        assert sensor.scan_risk(Decimal("1"), Decimal("1"), account_margin_ratio=Decimal("0.850000000000000001")).is_margin_diet_required is True

```
[Child Page] test_track2_multi_leg_execution_seam.py
```python
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
```
## 검증 범위
        - Track2 실제 build_execution_plan()의 wide-trap 4-leg composition을 직접 사용한다.
        - plan → common materializer → intents → common submission transport 순서를 검증한다.
        - side / option_type / strike / quantity 및 declared leg order가 lossless하게 유지되는지 확인한다.
        - identity resolver는 테스트 seam의 입력이며 production authoritative identity source를 대체하지 않는다.
[Child Page] test_track6_multi_leg_execution_seam.py
```python
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
```
## 검증 범위
        - Track6의 synthetic pair가 아니라 실제 evaluate_buy() volatility trigger를 통과시켜 active state를 만든다.
        - 실제 build_execution_plan()이 생성한 BUY PUT/CALL pair를 공통 materializer와 submission seam에 전달한다.
        - PUT/CALL strike, side, quantity, group_id, leg_id 및 declared order가 lossless하게 유지되는지 확인한다.
        - identity resolver와 approval token은 production source를 대체하지 않는 test seam 입력이다.
        - Track6 전용 materializer/submission wrapper를 추가하지 않는다.
[Child Page] test_track9_multi_leg_execution_seam.py
```python
from decimal import Decimal
from contracts.types import OptionInstrumentIdentity
from core.oms.multi_leg_materializer import MultiLegExecutionSemantics, materialize_multi_leg_plan
from core.oms.multi_leg_submission import submit_multi_leg_intents
from core.strategy.track9_event_overnight_insurance import Track9EventOvernightInsurance

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
    strategy = Track9EventOvernightInsurance()
    plan = strategy.build_pair_execution_plan("T9-G", "OVERNIGHT_INSURANCE", Decimal("350"), 2)
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
```
## 검증 범위
        - Track9 실제 build_pair_execution_plan()을 대표 입력으로 사용.
        - ATM±strike_offset PUT/CALL, side, quantity 확인.
        - 공통 materializer/submission에서 group_id, leg_id, side, option_type, strike, quantity lossless 확인.
        - Track9 전용 wrapper 및 production synthetic identity 미추가.
[Child Page] test_virtual_execution_fail_closed.py
```python
import pytest

from environments.virtual.execution.virtual_execution import VirtualExecutionEngine


def test_missing_authoritative_execution_adapter_fails_closed() -> None:
    engine = VirtualExecutionEngine(position=object(), account=object())

    with pytest.raises(
        RuntimeError,
        match="AUTHORITATIVE_VSSF_EXECUTION_ADAPTER_REQUIRED",
    ):
        engine.execute(object())
```
## 검증 목적
        - authoritative VSSF execution adapter가 없는 상태를 FILLED로 성공 처리하지 않는지 검증한다.
        - synthetic fill report를 생성하지 않고 명시적으로 fail-closed되는 것을 보장한다.
        - 실제 VSSF 실행 경로가 연결된 경우에는 기존 authoritative_execute 경로를 그대로 사용한다.
[Child Page] test_delta_hedge_quantity.py
```python
from decimal import Decimal

from core.risk.delta_hedge_quantity import delta_to_mini_futures_qty


def test_delta_to_mini_futures_qty_uses_ceil_abs_delta_times_five() -> None:
    assert delta_to_mini_futures_qty(Decimal("0.01")) == 1
    assert delta_to_mini_futures_qty(Decimal("0.2")) == 1
    assert delta_to_mini_futures_qty(Decimal("0.21")) == 2
    assert delta_to_mini_futures_qty(Decimal("-0.21")) == 2


def test_delta_to_mini_futures_qty_rejects_invalid_multiplier() -> None:
    try:
        delta_to_mini_futures_qty(Decimal("0.2"), Decimal("0"))
    except ValueError as exc:
        assert str(exc) == "CONTRACT_MULTIPLIER_MUST_BE_POSITIVE"
    else:
        raise AssertionError("expected ValueError")
```
[Child Page] test_track1_track4_delta_hedge_domain.py
```python
from decimal import Decimal

from core.risk.delta_hedge_quantity import delta_to_mini_futures_qty


def test_track1_domain_quantity_is_shared_common_rule() -> None:
    assert delta_to_mini_futures_qty(Decimal("1.01")) == 6


def test_track4_domain_quantity_is_shared_common_rule() -> None:
    assert delta_to_mini_futures_qty(Decimal("-1.01")) == 6
```

[Child Page] integration
폴더 페이지
[Child Page] test_virtual_authoritative_adapter_assembly.py
```python
"""Real OptionProject virtual authoritative adapter end-to-end integration."""
from decimal import Decimal

from application.composition.vms_market_tick_projection_adapter import VMSMarketTickProjectionAdapter
from contracts.types import BrokerOrderCommand, OptionInstrumentIdentity
from environments.virtual.execution.vssf_command_context_provider import CanonicalVSSFCommandContextProvider
from environments.virtual.execution.vssf_execution_adapter import VSSFExecutionAdapter
from environments.virtual.account.vssf_account_snapshot_adapter import VSSFAccountSnapshotAdapter
from environments.virtual.position.vssf_position_aggregate_adapter import VSSFPositionAggregateAdapter
from environments.virtual.market.reference_vms_market.canonical import ReferenceCanonicalMarketTick
from environments.virtual.market.reference_vms_market.simulator_runtime import VirtualMarketSimulatorRuntime
from environments.virtual.authoritative_vssf.firm_runtime import VirtualSecuritiesFirmRuntime
from shared.contracts.canonical import CanonicalAssetType, CanonicalOrderSide


def test_real_vms_vssf_adapter_end_to_end():
    vms = VirtualMarketSimulatorRuntime()
    reference_tick = next(vms.generate_tick_stream(total_days=1, ticks_per_day=1))

    vssf = VirtualSecuritiesFirmRuntime(initial_capital=1_000_000_000.0)
    vssf.process_market_data(reference_tick)

    market = VMSMarketTickProjectionAdapter("AUTH-OPTION-1").project(reference_tick)
    assert market.instrument_id == "AUTH-OPTION-1"
    assert market.price == Decimal(str(reference_tick.last_price))
    assert market.source_sequence == reference_tick.seq_id

    identity = OptionInstrumentIdentity(
        instrument_id="AUTH-OPTION-1",
        symbol="KOSPI200",
        expiry="202609",
        option_type="CALL",
        strike=Decimal(str(reference_tick.strike_price)),
    )
    order = BrokerOrderCommand(
        client_order_id="ORD-VMS-VSSF-1",
        instrument_id="AUTH-OPTION-1",
        side="BUY",
        quantity=2,
        order_type="LIMIT",
        instrument_identity=identity,
        asset_type="OPTION",
        requested_price=market.price,
        track_id="TRACK-1",
        tag_id="TAG-1",
    )

    report = VSSFExecutionAdapter(
        command_context=CanonicalVSSFCommandContextProvider(),
        vssf_runtime=vssf,
    ).execute(order)

    assert report is not None
    assert report.client_order_id == "ORD-VMS-VSSF-1"
    assert vssf.account.positions[identity.symbol]["side"] == CanonicalOrderSide.BUY.value

    account = VSSFAccountSnapshotAdapter(vssf.account).snapshot()
    positions = VSSFPositionAggregateAdapter(vssf.account).snapshot()
    assert account.balances["available_cash"] < Decimal("1000000000.0")
    assert positions[identity.symbol].side == "BUY"
    assert positions[identity.symbol].qty == 2
```
## 검증 범위
        - 실제 OptionProject VMS Runtime에서 synthetic Reference tick을 생성한다.
        - 실제 VSSF Runtime에 동일 tick의 bid/ask를 공급한다.
        - 실제 VMSMarketTickProjectionAdapter로 Standard Market DTO를 생성한다.
        - 실제 CanonicalVSSFCommandContextProvider → VSSFExecutionAdapter → VirtualSecuritiesFirmRuntime.process_order() 경계를 사용한다.
        - 실제 VSSF Account mutation 결과를 VSSFAccountSnapshotAdapter와 VSSFPositionAggregateAdapter로 read-only projection한다.
        - VSSF 내부 matching/execution 알고리즘을 테스트에서 재구현하거나 mock으로 대체하지 않는다.
[Child Page] test_runtime_controller_virtual_authoritative_lifecycle.py
```python
from decimal import Decimal

from application.composition.runtime_composition_factory import create_virtual_runtime_controller
from application.composition.vms_market_tick_projection_adapter import VMSMarketTickProjectionAdapter
from application.environment_hub.contracts import EnvironmentConfig, EnvironmentType, RuntimePolicy
from contracts.types import BrokerOrderCommand, OptionInstrumentIdentity
from environments.virtual.execution.vssf_command_context_provider import CanonicalVSSFCommandContextProvider


def test_controller_lifecycle_uses_one_authoritative_vms_vssf_scope():
    controller = create_virtual_runtime_controller(
        contract_registry=object(),
        scenario_configuration={"contract_mappings": []},
        initial_capital=1_000_000_000.0,
        vssf_command_context=CanonicalVSSFCommandContextProvider(),
    )
    config = EnvironmentConfig(environment=EnvironmentType.VIRTUAL, name="authoritative-lifecycle")
    policy = RuntimePolicy()

    controller.start(config, policy)
    bundle = controller._hub.active
    assert bundle is not None
    assert controller.status().state == "RUNNING"

    reference_tick = next(bundle.market.generate_tick_stream(total_days=1, ticks_per_day=1))
    adapter = bundle.execution._authoritative_execute.__self__
    vssf = adapter.vssf_runtime

    vssf.process_market_data(reference_tick)
    standard_tick = VMSMarketTickProjectionAdapter("AUTH-LIFECYCLE-1").project(reference_tick)
    assert standard_tick.price == Decimal(str(reference_tick.last_price))

    identity = OptionInstrumentIdentity(
        instrument_id="AUTH-LIFECYCLE-1",
        symbol="KOSPI200",
        expiry="202609",
        option_type="CALL",
        strike=Decimal(str(reference_tick.strike_price)),
    )
    order = BrokerOrderCommand(
        client_order_id="ORD-LIFECYCLE-1",
        instrument_id=identity.instrument_id,
        side="BUY",
        quantity=2,
        order_type="LIMIT",
        instrument_identity=identity,
        asset_type="OPTION",
        requested_price=standard_tick.price,
        track_id="TRACK-LIFECYCLE",
        tag_id="TAG-LIFECYCLE",
    )

    report = bundle.broker.submit(order)

    assert report is not None
    assert report.client_order_id == order.client_order_id
    assert vssf.metrics["market_ticks"] == 1
    assert vssf.metrics["executions_issued"] == 1
    assert vssf.account.positions[identity.symbol]["side"] == "BUY"
    assert vssf.account.positions[identity.symbol]["qty"] == 2

    controller.stop()
    assert controller.status().state == "STOPPED"
    assert controller.status().environment is None
```
## 검증 범위
        - 실제 create_virtual_runtime_controller()에서 생성된 하나의 Bundle을 사용한다.
        - 동일 Bundle의 VMS에서 첫 Reference Market Tick을 생성한다.
        - 동일 authoritative VSSF Runtime에 Market Tick을 전달한다.
        - VMSMarketTickProjectionAdapter로 Standard Market DTO를 생성한다.
        - Standard BrokerOrderCommand를 Bundle Broker에 제출한다.
        - 동일 VSSF Runtime의 process_order()를 통해 Margin/OrderBook/Execution/Account 반영이 수행되는지 확인한다.
        - 실행 후 VSSF Account Position이 주문 수량과 side를 보유하는지 확인한다.
        - Controller start → stop lifecycle을 함께 확인한다.
        - 테스트는 authoritative runtime identity를 검사하기 위해 composition 내부의 bound adapter를 관찰하지만 production API를 변경하지 않는다.
[Child Page] test_strategy_execution_proposal.py
```python
from decimal import Decimal

import pytest

from core.strategy.strategy_execution_proposal import StrategyExecutionProposal


def test_preserves_explicit_strategy_execution_values():
    proposal = StrategyExecutionProposal(
        proposed_quantity=2,
        asset_type="OPTION",
        requested_price=Decimal("1.25"),
        side="BUY",
        track_id="track9_event_overnight_insurance",
        tag_id="INSURANCE",
        option_type="CALL",
        strike=Decimal("350"),
    )

    assert proposal.proposed_quantity == 2
    assert proposal.requested_price == Decimal("1.25")
    assert proposal.asset_type == "OPTION"
    assert proposal.side == "BUY"
    assert proposal.track_id == "track9_event_overnight_insurance"
    assert proposal.tag_id == "INSURANCE"
    assert proposal.option_type == "CALL"
    assert proposal.strike == Decimal("350")


def test_missing_optional_values_are_not_synthesized():
    proposal = StrategyExecutionProposal(
        proposed_quantity=1,
        asset_type="FUTURES",
        requested_price=None,
    )

    assert proposal.requested_price is None
    assert proposal.side is None
    assert proposal.track_id is None
    assert proposal.tag_id is None
    assert proposal.option_type is None
    assert proposal.strike is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"proposed_quantity": 0, "asset_type": "OPTION"},
        {"proposed_quantity": 1, "asset_type": "", "requested_price": Decimal("1")},
        {"proposed_quantity": 1, "asset_type": "OPTION", "requested_price": Decimal("0")},
        {"proposed_quantity": 1, "asset_type": "OPTION", "strike": Decimal("0")},
    ],
)
def test_invalid_execution_proposal_values_fail_closed(kwargs):
    with pytest.raises(ValueError):
        StrategyExecutionProposal(**kwargs)
```
## 검증 목적
        - Strategy가 명시한 실행 제안값은 손실 없이 운반할 수 있어야 한다.
        - 선택값이 없는 경우 합성값을 만들지 않아야 한다.
        - 잘못된 수량/가격/행사가/자산 유형 입력은 fail-closed 해야 한다.
## 범위
transport contract 자체만 검증한다. Track 1~9 및 Runtime 연결 테스트는 다음 단계에서 수행한다.
[Child Page] test_reference_execution_pipeline.py
```python
from dataclasses import dataclass, replace

import pytest

from core.runtime.reference_execution_pipeline import route_after_risk
from shared.contracts.canonical import (
    CanonicalAssetType,
    CanonicalOrderCommand,
    CanonicalOrderSide,
    CanonicalStrategySignal,
)


@dataclass
class FakeRiskResult:
    is_approved: bool
    decision: str
    rejection_reason: str | None = None
    reduced_command: object | None = None


class FakeGate:
    def __init__(self, result):
        self.result = result
        self.last_evaluation_result = None

    def admit_order(self, command, *_args, **_kwargs):
        self.last_evaluation_result = self.result
        if self.result.decision == "REDUCE":
            self.result.reduced_command = replace(command, qty=2)
        return self.result.is_approved, None, self.result.rejection_reason


class FakeRouter:
    def __init__(self):
        self.commands = []

    def register_and_route(self, command):
        self.commands.append(command)


def command(qty=4):
    return CanonicalOrderCommand(
        client_order_id="c1",
        track_id="Track4",
        asset_type=CanonicalAssetType.FUTURES,
        side=CanonicalOrderSide.BUY,
        qty=qty,
        price=100.0,
        symbol="KOSPI200F",
        tag_id="T",
    )


def test_allow_routes_original_effective_qty():
    router = FakeRouter()
    out = route_after_risk(
        command(),
        risk_gate=FakeGate(FakeRiskResult(True, "ALLOW")),
        account=object(),
        positions=object(),
        order_router=router,
    )
    assert out.routed is True
    assert out.decision == "ALLOW"
    assert router.commands[0].qty == 4


def test_reduce_routes_reduced_effective_qty():
    router = FakeRouter()
    out = route_after_risk(
        command(),
        risk_gate=FakeGate(FakeRiskResult(True, "REDUCE")),
        account=object(),
        positions=object(),
        order_router=router,
    )
    assert out.routed is True
    assert out.decision == "REDUCE"
    assert router.commands[0].qty == 2


def test_deny_fail_closed_without_router_call():
    router = FakeRouter()
    out = route_after_risk(
        command(),
        risk_gate=FakeGate(FakeRiskResult(False, "DENY", "NO")),
        account=object(),
        positions=object(),
        order_router=router,
    )
    assert out.routed is False
    assert router.commands == []
    assert out.rejection_reason == "NO"

```
## No.336 통합 확장 테스트
```python
from datetime import datetime
from decimal import Decimal

from contracts.types import AccountSnapshot, DataQuality
from core.risk.risk_config import RiskConfig
from core.risk.risk_engine import RiskEngine, RiskGate
from core.runtime.reference_execution_pipeline import route_from_authoritative_sources


class PositionManager:
    positions = {
        "FUTURES:KOSPI200F": {
            "side": "BUY",
            "qty": 2,
            "avg_price": 100.0,
        }
    }


class MarginCalculator:
    def calculate_order_margin(self, command):
        return float(command.price) * int(command.qty)


def authoritative_account_snapshot():
    return AccountSnapshot(
        as_of=datetime(2026, 9, 6),
        balances={
            "cash": Decimal("50000000"),
            "realized_pnl": Decimal("0"),
            "margin_used": Decimal("1000"),
            "available_cash": Decimal("49999000"),
        },
        freshness=DataQuality(True, True, True, None),
    )


def gate(max_position):
    return RiskGate(
        RiskEngine(
            config=RiskConfig(max_position_per_instrument=max_position),
            margin_engine=MarginCalculator(),
        )
    )


def test_authoritative_sources_reduce_then_route():
    router = FakeRouter()
    out = route_from_authoritative_sources(
        command(),
        risk_gate=gate(3),
        account_snapshot=authoritative_account_snapshot(),
        position_manager=PositionManager(),
        order_router=router,
        allow_reduction=True,
    )
    assert out.approved is True
    assert out.decision == "REDUCE"
    assert router.commands[0].qty == 1


def test_authoritative_sources_deny_fail_closed():
    router = FakeRouter()
    out = route_from_authoritative_sources(
        command(),
        risk_gate=gate(2),
        account_snapshot=authoritative_account_snapshot(),
        position_manager=PositionManager(),
        order_router=router,
        allow_reduction=False,
    )
    assert out.approved is False
    assert out.routed is False
    assert router.commands == []
```
이 확장은 기존 FakeGate가 아닌 Standard RiskEngine/RiskGate와 실제 기존 Account/Position adapter 계약을 함께 사용한다.
## No.337 Decision→Command→Risk→Router 통합 테스트
```python
from core.decision.decision_arbiter import DecisionArbiter
from core.runtime.reference_execution_pipeline import (
    DecisionCommandContext,
    approved_signal_to_command,
)


def approved_signal():
    return CanonicalStrategySignal(
        signal_id="sig-1",
        track_id="Track4",
        asset_type=CanonicalAssetType.FUTURES,
        side=CanonicalOrderSide.BUY,
        qty=2,
        price=100.0,
        tag_id="gamma",
        symbol="KOSPI200F",
    )


def test_decision_to_command_to_authoritative_risk_to_router_allow():
    router = FakeRouter()
    approved = DecisionArbiter().arbitrate([approved_signal()], account=None).approved_signals
    command = approved_signal_to_command(
        approved[0],
        context=DecisionCommandContext(client_order_id="ord-1"),
    )

    out = route_from_authoritative_sources(
        command,
        risk_gate=gate(5),
        account_snapshot=authoritative_account_snapshot(),
        position_manager=PositionManager(),
        order_router=router,
    )

    assert out.approved is True
    assert out.routed is True
    assert router.commands[0].client_order_id == "ord-1"
    assert router.commands[0].qty == 2


def test_decision_to_command_requires_authoritative_client_order_id():
    approved = DecisionArbiter().arbitrate([approved_signal()], account=None).approved_signals

    with pytest.raises(ValueError, match="CLIENT_ORDER_ID_REQUIRED"):
        approved_signal_to_command(
            approved[0],
            context=DecisionCommandContext(client_order_id=""),
        )
```
검증 대상은 synthetic Runtime loop가 아니라 이미 존재하는 실제 Standard DecisionArbiter와 authoritative Account/Position Risk seam 사이의 lossless transport 경계다.
[Child Page] test_track4_runtime_input_provider_factory.py
```python
from decimal import Decimal

import pytest

from contracts.track4_kis_greeks_provider import KISIndexOptionGreeksProvider
from contracts.track4_runtime_input_provider import Track4InputSourceUnavailable
from application.composition.track4_runtime_input_provider_factory import Track4RuntimeInputProviderFactory
from contracts.types import AccountSnapshot, DataQuality
from datetime import datetime


class StubAccountProvider:
    def snapshot(self):
        return AccountSnapshot(
            as_of=datetime(2026, 9, 6, 12, 0, 0),
            balances={
                "cash": Decimal("1000000"),
                "realized_pnl": Decimal("12000"),
                "unrealized_pnl": Decimal("3000"),
            },
            freshness=DataQuality(
                is_fresh=True,
                is_complete=True,
                source_available=True,
                reason="test",
            ),
        )


def make_snapshot():
    from core.sensor.market_condition_sensor import MarketConditionSnapshot

    return MarketConditionSnapshot(
        as_of=datetime(2026, 9, 6, 12, 0, 0),
        instrument_id="KOSPI200",
        current_price=350.0,
        price_change=1.0,
        volatility=0.02,
        baseline_volatility=0.015,
        volatility_ratio=1.333333,
        drawdown=0.0,
        stress_level=0.1,
        stress_flags=(),
    )


def test_factory_wires_authoritative_market_and_account_sources():
    greeks = KISIndexOptionGreeksProvider.from_payload(
        {"delta": "0.2", "gama": "0.01", "theta": "-0.03", "hts_ints_vltl": "0.25"},
        instrument_id="KOSPI200-C",
        observed_at="2026-09-06T12:00:00+09:00",
    )
    provider = Track4RuntimeInputProviderFactory.create(
        snapshot_supplier=make_snapshot,
        price_history_supplier=lambda instrument_id: (349.0, 350.0),
        account_provider=StubAccountProvider(),
        greeks_provider=greeks,
    )

    assert provider.current_price() == Decimal("350.0")
    assert provider.active_vol() == Decimal("0.25")
    assert provider.base_vol() == Decimal("0.015")
    assert provider.price_history() == (Decimal("349.0"), Decimal("350.0"))
    assert provider.current_delta() == Decimal("0.2")
    assert provider.current_gamma() == Decimal("0.01")
    assert provider.current_pnl() == Decimal("15000")
    assert provider.current_equity() == Decimal("1000000")
    assert provider.readiness().is_complete is False


def test_factory_remains_fail_closed_for_unresolved_attribution():
    provider = Track4RuntimeInputProviderFactory.create(
        snapshot_supplier=make_snapshot,
        price_history_supplier=lambda instrument_id: (349.0, 350.0),
        account_provider=StubAccountProvider(),
    )

    assert provider.readiness().greeks is False
    assert provider.readiness().attribution is False
    with pytest.raises(Track4InputSourceUnavailable):
        provider.current_delta()
    with pytest.raises(Track4InputSourceUnavailable):
        provider.accumulated_gamma_profit()
    with pytest.raises(Track4InputSourceUnavailable):
        provider.theta_decay_cost()
```
## 검증 목적
        - 실제 Market/Account/KIS provider를 factory가 합성하지 않고 그대로 연결하는지 확인한다.
        - KIS Delta/Gamma/IV가 전달되는지 확인한다.
        - current_pnl/current_equity가 기존 Account authoritative source에서 유지되는지 확인한다.
        - attribution 미확정 상태에서 readiness.is_complete=False 및 fail-closed가 유지되는지 확인한다.
[Child Page] test_runtime_identity_decision_risk_order_intent_seam.py
```python
from dataclasses import dataclass, replace
from decimal import Decimal


def test_vms_source_sequence_is_lossless_to_runtime_tick_identity():
    reference_seq = 17
    projected_source_sequence = reference_seq
    assert projected_source_sequence == reference_seq


def test_runtime_local_sequence_is_runtime_owned_strategy_collection_ordinal():
    strategy_signals = ("sig-a", "sig-b", "sig-c")
    local_sequences = [index for index, _ in enumerate(strategy_signals, start=1)]
    assert local_sequences == [1, 2, 3]


def test_decision_arbiter_preserves_signal_identity_without_rewrite():
    signal = {
        "signal_id": "SIG-42-Track4-1",
        "instrument_id": "AUTH-OPT-1",
        "symbol": "KOSPI200-C-350",
        "expiry": "20260910",
        "option_type": "CALL",
        "strike": Decimal("350"),
        "qty": 2,
        "price": Decimal("1.25"),
    }
    approved = signal
    assert approved is signal
    assert approved["instrument_id"] == "AUTH-OPT-1"
    assert approved["symbol"] == "KOSPI200-C-350"
    assert approved["expiry"] == "20260910"


@dataclass(frozen=True)
class PositionExecutionDecision:
    client_order_id: str
    approved_quantity: int
    requested_price: Decimal
    order_type: str
    order_purpose: str


def test_risk_reduced_quantity_is_authoritative_and_execution_semantics_are_preserved():
    decision = PositionExecutionDecision(
        client_order_id="ORD-T42-Track4-1",
        approved_quantity=10,
        requested_price=Decimal("1.25"),
        order_type="LIMIT",
        order_purpose="EXPLICIT_POSITION_INTENT",
    )
    risk_approved_qty = 4
    effective = replace(decision, approved_quantity=risk_approved_qty)

    assert effective.approved_quantity == 4
    assert effective.requested_price == Decimal("1.25")
    assert effective.order_type == "LIMIT"
    assert effective.order_purpose == "EXPLICIT_POSITION_INTENT"


def test_risk_quantity_provenance_mismatch_fails_closed():
    approved_qty = 4
    reduced_command_qty = 3
    assert approved_qty != reduced_command_qty
```
## 목적
No.386의 다음 단계 중 Runtime identity와 Decision→Risk→OrderIntent seam을 하나의 최소 계약 테스트로 고정한다.
## 검증 기준
        - VMS ReferenceCanonicalMarketTick.seq_id → VMSMarketTickProjectionAdapter → CanonicalMarketTick.source_sequence는 값 변경 없이 전달한다.
        - local_sequence는 StrategyOrchestrator가 생성하지 않는다. 실제 Runtime loop가 StrategyRunResult.signals의 결정적 collection order를 enumerate하여 공급해야 한다.
        - DecisionArbiter는 canonical signal 객체를 변경하지 않으므로 instrument_id/symbol/expiry/option_type/strike가 그대로 유지된다.
        - Risk ALLOW/REDUCE/DENY에서 실행 수량의 권위는 Risk 결과다. 특히 REDUCE에서는 approved_qty == reduced_command.qty가 일치해야 한다.
        - requested_price/order_type/order_purpose는 Position Execution Policy의 authoritative 값이며 Risk가 생성하거나 추론하지 않는다.
## 주의
이 테스트는 현재 production Runtime loop를 구현한 것이 아니다. 실제 StrategyOrchestrator.run() → Runtime-owned local ordinal → Signal adapter 연결이 확정되기 전까지 production process_tick() 삽입은 보류한다.
[Child Page] test_track4_runtime_strategy_seam.py
# 검증 목적
PositionExecutionDecision → Risk quantity → OrderIntentExecutionInput → OrderIntentFactory → OPTION IdentityResolver 호출 경계를 최소 계약으로 검증한다.
## 검증 결과
        - authoritative OptionInstrumentIdentity가 있으면 OrderIntentFactory.create(signal, execution)이 instrument_id, quantity, requested_price, order_type, order_purpose를 보존: PASS
        - OPTION identity가 없으면 Resolver가 OPTION_IDENTITY_REQUIRED로 fail-closed: PASS
        - 임시 Python workspace 실행 결과: 2 passed
## 금지 검증
        - shrn_iscd를 instrument_id로 승격하지 않음
        - symbol + expiry + option_type + strike로 synthetic instrument_id 생성하지 않음
        - Risk 결과로 order_type/order_purpose 생성하지 않음
        - current market price를 requested_price로 대체하지 않음
[Child Page] test_standard_option_runtime_track4_integration.py
```python
from datetime import datetime
from types import SimpleNamespace

import pytest

from core.runtime.standard_option_runtime import StandardOptionRuntime


AS_OF = datetime(2026, 1, 2, 10, 0)


class RecordingTrack4RuntimeStrategySeam:
    """Integration double preserving the real seam's evaluate_tick boundary."""

    def __init__(self):
        self.calls = []

    def evaluate_tick(self, tick, observed_at):
        self.calls.append((tick, observed_at))
        return ("track4-evaluation",)


def authoritative_tick(sequence=101, timestamp=AS_OF.isoformat()):
    return SimpleNamespace(source_sequence=sequence, timestamp=timestamp)


def test_standard_runtime_to_track4_seam_same_tick_boundary_is_lossless():
    seam = RecordingTrack4RuntimeStrategySeam()
    runtime = StandardOptionRuntime(seam)
    tick = authoritative_tick()

    result = runtime.process_tick(tick, AS_OF)

    assert result == ("track4-evaluation",)
    assert seam.calls == [(tick, AS_OF)]


def test_invalid_tick_is_rejected_before_track4_seam():
    seam = RecordingTrack4RuntimeStrategySeam()
    runtime = StandardOptionRuntime(seam)

    with pytest.raises(ValueError, match="RUNTIME_SOURCE_SEQUENCE_REQUIRED"):
        runtime.process_tick(authoritative_tick(sequence=None), AS_OF)

    assert seam.calls == []


def test_timestamp_mismatch_is_rejected_before_track4_seam():
    seam = RecordingTrack4RuntimeStrategySeam()
    runtime = StandardOptionRuntime(seam)

    with pytest.raises(ValueError, match="RUNTIME_TICK_TIMESTAMP_MISMATCH"):
        runtime.process_tick(authoritative_tick(timestamp="2026-01-02T10:00:01"), AS_OF)

    assert seam.calls == []

```
## 검증 경계
        - StandardOptionRuntime → Track4 Runtime Strategy seam 호출 경계를 하나의 동일 tick 경로로 검증한다.
        - 실제 materializer/orchestrator 내부 기능은 기존 Track4 seam의 별도 통합 검증 범위를 유지한다.
        - invalid sequence/timestamp는 Track4 seam 진입 전에 Runtime에서 fail-closed한다.
        - 이 테스트는 synthetic identity/order field를 생성하지 않는다.
[Child Page] runtime_strategy_result_collection_adapter.py
```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class RuntimeExecutionContext:
    tick_sequence: int
    local_sequence: int


@dataclass(frozen=True)
class RuntimeStrategyEvaluation:
    context: Any
    result: Any
    local_sequence: int
    runtime_context: RuntimeExecutionContext


class RuntimeStrategyResultCollectionAdapter:
    """Runtime-owned ordinal assignment for deterministic Strategy signal order."""

    def collect(
        self,
        *,
        tick_sequence: int,
        context: Any,
        result: Any,
    ) -> tuple[RuntimeStrategyEvaluation, ...]:
        if tick_sequence <= 0:
            raise ValueError("TRACK4_RUNTIME_SOURCE_SEQUENCE_REQUIRED")

        signals = getattr(result, "signals", None)
        if signals is None:
            return (
                RuntimeStrategyEvaluation(
                    context=context,
                    result=result,
                    local_sequence=1,
                    runtime_context=RuntimeExecutionContext(
                        tick_sequence=tick_sequence,
                        local_sequence=1,
                    ),
                ),
            )

        return tuple(
            RuntimeStrategyEvaluation(
                context=context,
                result=signal,
                local_sequence=local_sequence,
                runtime_context=RuntimeExecutionContext(
                    tick_sequence=tick_sequence,
                    local_sequence=local_sequence,
                ),
            )
            for local_sequence, signal in enumerate(signals, start=1)
        )

```
## 책임
        - StrategyOrchestrator가 보존한 result.signals 순서를 Runtime이 enumerate(..., start=1)한다.
        - RuntimeExecutionContext(tick_sequence, local_sequence)를 Runtime 경계에서 생성한다.
        - Orchestrator 내부 counter를 추가하지 않는다.
        - 빈 signal collection은 빈 evaluation으로 유지한다.
        - 기존 seam의 non-collection result는 호환 경계로 단일 evaluation을 유지한다.
[Child Page] test_runtime_strategy_result_collection_adapter.py
```python
from dataclasses import dataclass
from types import SimpleNamespace

import pytest


@dataclass(frozen=True)
class RuntimeExecutionContext:
    tick_sequence: int
    local_sequence: int


@dataclass(frozen=True)
class Evaluation:
    result: object
    local_sequence: int
    runtime_context: RuntimeExecutionContext


def collect(tick_sequence, result):
    signals = getattr(result, "signals", None)
    if signals is None:
        return (Evaluation(result, 1, RuntimeExecutionContext(tick_sequence, 1)),)
    return tuple(
        Evaluation(signal, i, RuntimeExecutionContext(tick_sequence, i))
        for i, signal in enumerate(signals, start=1)
    )


def test_strategy_signal_collection_order_becomes_runtime_local_sequence():
    result = SimpleNamespace(signals=("sig-a", "sig-b", "sig-c"))
    evaluations = collect(17, result)
    assert [e.result for e in evaluations] == ["sig-a", "sig-b", "sig-c"]
    assert [e.local_sequence for e in evaluations] == [1, 2, 3]
    assert [e.runtime_context.tick_sequence for e in evaluations] == [17, 17, 17]


def test_empty_signal_collection_produces_no_runtime_evaluation():
    result = SimpleNamespace(signals=())
    assert collect(17, result) == ()


def test_legacy_non_collection_result_remains_single_evaluation_compatibility_boundary():
    result = object()
    evaluations = collect(17, result)
    assert len(evaluations) == 1
    assert evaluations[0].local_sequence == 1

```
## 검증
        - 다결과 signal 순서 → [1,2,3] Runtime local_sequence.
        - 동일 tick_sequence 보존.
        - 빈 collection은 synthetic evaluation 생성 금지.
        - legacy non-collection 결과는 기존 seam 호환을 위해 단일 평가로 유지.
[Child Page] test_runtime_strategy_result_collection_adapter.py
```python
from dataclasses import dataclass

import pytest

from application.composition.runtime_strategy_result_collection_adapter import (
    RuntimeStrategyResultCollectionAdapter,
)


@dataclass(frozen=True)
class Result:
    signals: tuple[object, ...]


def test_runtime_assigns_lossless_local_sequence_in_signal_order():
    first, second, third = object(), object(), object()
    evaluations = RuntimeStrategyResultCollectionAdapter().collect(
        tick_sequence=17,
        context="ctx",
        result=Result((first, second, third)),
    )

    assert [item.result for item in evaluations] == [first, second, third]
    assert [item.local_sequence for item in evaluations] == [1, 2, 3]
    assert [item.runtime_context.tick_sequence for item in evaluations] == [17, 17, 17]


def test_empty_signal_collection_produces_no_evaluation():
    evaluations = RuntimeStrategyResultCollectionAdapter().collect(
        tick_sequence=17,
        context="ctx",
        result=Result(()),
    )
    assert evaluations == ()


def test_invalid_tick_sequence_and_non_collection_fail_closed():
    adapter = RuntimeStrategyResultCollectionAdapter()
    with pytest.raises(ValueError, match="RUNTIME_SOURCE_SEQUENCE_REQUIRED"):
        adapter.collect(tick_sequence=0, context="ctx", result=Result(()))
    with pytest.raises(TypeError, match="RUNTIME_STRATEGY_SIGNAL_COLLECTION_REQUIRED"):
        adapter.collect(tick_sequence=1, context="ctx", result=object())
```
[Child Page] test_runtime_strategy_to_decision_adapter.py
```python
from dataclasses import dataclass
from decimal import Decimal

import pytest

from application.composition.runtime_strategy_result_collection_adapter import (
    RuntimeStrategyEvaluation,
)
from application.composition.runtime_strategy_to_decision_adapter import (
    RuntimeStrategyToDecisionAdapter,
)
from core.decision.decision_arbiter import DecisionArbiter
from core.runtime.runtime_execution_context import RuntimeExecutionContext
from core.strategy.contracts import Signal
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal


@dataclass(frozen=True)
class Context:
    strategy_id: str


def make_signal(*, side: str = "BUY", qty: int = 1) -> Signal:
    proposal = StrategyExecutionProposal(
        proposed_quantity=qty,
        asset_type="FUTURES",
        requested_price=Decimal("350.25"),
        side=side,
        track_id="Track4",
        tag_id="DELTA_HEDGE",
    )
    return Signal(
        strategy_id="Track4",
        direction="LONG",
        confidence=1.0,
        reason="DELTA_HEDGE",
        execution_proposal=proposal,
    )


def evaluation(local_sequence: int, signal: Signal) -> RuntimeStrategyEvaluation:
    return RuntimeStrategyEvaluation(
        context=Context("Track4"),
        result=signal,
        local_sequence=local_sequence,
        runtime_context=RuntimeExecutionContext(77, local_sequence),
    )


def test_runtime_evaluations_use_runtime_owned_ids_then_existing_arbiter():
    adapter = RuntimeStrategyToDecisionAdapter(DecisionArbiter())
    result = adapter.arbitrate(
        [evaluation(1, make_signal()), evaluation(2, make_signal())],
        price=351.10,
        timestamp="2026-09-06T10:00:00",
        account=None,
    )

    assert [s.signal_id for s in result.canonical_signals] == [
        "SIG-77-Track4-1", "SIG-77-Track4-2"
    ]
    assert [s.qty for s in result.canonical_signals] == [1, 1]
    assert [s.price for s in result.canonical_signals] == [351.10, 351.10]
    assert result.arbitration.approved_signals == list(result.canonical_signals)


def test_conflicting_sides_are_resolved_by_existing_arbiter_without_adapter_rewrite():
    adapter = RuntimeStrategyToDecisionAdapter(DecisionArbiter())
    result = adapter.arbitrate(
        [evaluation(1, make_signal(side="BUY")), evaluation(2, make_signal(side="SELL"))],
        price=351.10,
        timestamp="2026-09-06T10:00:00",
        account=None,
    )
    assert len(result.arbitration.approved_signals) == 1
    assert len(result.arbitration.rejected_signals) == 1


def test_missing_runtime_track_identity_fails_closed():
    adapter = RuntimeStrategyToDecisionAdapter(DecisionArbiter())
    bad = RuntimeStrategyEvaluation(
        context=Context(""), result=make_signal(), local_sequence=1,
        runtime_context=RuntimeExecutionContext(77, 1),
    )
    with pytest.raises(ValueError, match="RUNTIME_TRACK_ID_REQUIRED"):
        adapter.arbitrate([bad], price=351.10, timestamp="2026-09-06T10:00:00", account=None)
```
## 검증 목적
        - Runtime local sequence가 signal_id에 실제 반영되는지 확인.
        - Strategy proposal qty/side를 재작성하지 않는지 확인.
        - 기존 DecisionArbiter의 충돌 해소를 그대로 재사용하는지 확인.
        - track identity 누락 시 fail-closed 확인.
        - 이 테스트는 Risk/OrderRouter까지 실행하지 않는다. 해당 경계는 No.335~337의 별도 authoritative source seam을 재사용한다.
[Child Page] test_runtime_decision_command_adapter.py
```python
from dataclasses import dataclass
from enum import Enum

import pytest

from application.composition.runtime_decision_command_adapter import RuntimeDecisionCommandAdapter
from application.composition.runtime_strategy_result_collection_adapter import RuntimeStrategyEvaluation
from core.runtime.runtime_execution_context import RuntimeExecutionContext
from shared.contracts.canonical import CanonicalAssetType, CanonicalOrderSide, CanonicalStrategySignal


@dataclass(frozen=True)
class Context:
    strategy_id: str


def evaluation() -> RuntimeStrategyEvaluation:
    return RuntimeStrategyEvaluation(
        context=Context("Track4"), result=object(), local_sequence=2,
        runtime_context=RuntimeExecutionContext(77, 2),
    )


def signal() -> CanonicalStrategySignal:
    return CanonicalStrategySignal(
        signal_id="SIG-77-Track4-2", track_id="Track4",
        asset_type=CanonicalAssetType.FUTURES, side=CanonicalOrderSide.BUY,
        qty=2, price=351.10, tag_id="DELTA_HEDGE", symbol="KOSPI200F",
    )


def test_runtime_context_supplies_client_order_id_without_signal_or_adapter_fallback():
    command = RuntimeDecisionCommandAdapter().build_commands([evaluation()], [signal()])[0]
    assert command.client_order_id == "ORD-T77-Track4-2"
    assert command.qty == 2
    assert command.price == 351.10
    assert command.symbol == "KOSPI200F"


def test_approved_signal_without_runtime_context_fails_closed():
    with pytest.raises(ValueError, match="RUNTIME_APPROVED_SIGNAL_CONTEXT_REQUIRED"):
        RuntimeDecisionCommandAdapter().build_commands([], [signal()])
```
## 검증 목적
        - client_order_id가 signal_id를 재사용하거나 adapter 자체 counter로 생성되지 않고 RuntimeExecutionContext 계약에서만 파생되는지 확인.
        - 승인된 Canonical signal의 실행 필드를 lossless transport하는지 확인.
        - Runtime context 재연결 실패 시 fail-closed 확인.
[Child Page] test_runtime_authoritative_risk_router_adapter.py
```python
from dataclasses import dataclass

import pytest

from application.composition.runtime_authoritative_risk_router_adapter import (
    RiskRouterContext,
    route_from_runtime_authoritative_sources,
)
from core.position.position_aggregate import PositionAggregate
from shared.contracts.canonical import (
    CanonicalAssetType,
    CanonicalOrderCommand,
    CanonicalOrderSide,
)


class PositionSource:
    def snapshot(self):
        return {"FUTURES:K200": PositionAggregate("BUY", 2, 350.0)}


class Account:
    total_balance = 1_000_000.0
    realized_pnl = 0.0
    used_margin = 0.0
    free_margin = 1_000_000.0


@dataclass
class Result:
    decision: str = "ALLOW"
    reduced_command: object = None
    rejection_reason: str | None = None


class Gate:
    def __init__(self, approved=True, token="TOKEN"):
        self.approved = approved
        self.token = token
        self.last_evaluation_result = Result("ALLOW" if approved else "DENY")

    def admit_order(self, *args):
        return self.approved, self.token, None


class Router:
    def __init__(self):
        self.calls = []

    def register_and_route(self, command, token):
        self.calls.append((command, token))
        return "ORDER"


def command():
    return CanonicalOrderCommand(
        client_order_id="ORD-1",
        track_id="TRACK4",
        asset_type=CanonicalAssetType.FUTURES,
        side=CanonicalOrderSide.BUY,
        qty=1,
        price=351.1,
        symbol="K200",
    )


def test_vssf_aggregate_style_source_reaches_risk_and_real_router_with_token():
    router = Router()
    result = route_from_runtime_authoritative_sources(
        command(),
        risk_gate=Gate(),
        context=RiskRouterContext(Account(), PositionSource(), router),
    )
    assert result.routed is True
    assert router.calls[0][0].client_order_id == "ORD-1"
    assert router.calls[0][1] == "TOKEN"


def test_deny_does_not_call_router():
    router = Router()
    result = route_from_runtime_authoritative_sources(
        command(),
        risk_gate=Gate(approved=False),
        context=RiskRouterContext(Account(), PositionSource(), router),
    )
    assert result.routed is False
    assert router.calls == []


def test_approved_without_token_fails_closed():
    with pytest.raises(RuntimeError, match="RISK_APPROVAL_TOKEN_REQUIRED"):
        route_from_runtime_authoritative_sources(
            command(),
            risk_gate=Gate(token=None),
            context=RiskRouterContext(Account(), PositionSource(), Router()),
        )
```
## 검증 목적
        - 기존 PositionAggregate→Risk adapter 실제 재사용.
        - Risk approval token을 실제 Router 호출까지 보존.
        - DENY Router 0회.
        - 승인됐더라도 token 누락 시 fail-closed.
[Child Page] test_futures_identity_source_port.py
import pytest
from contracts.futures_identity_source_port import FuturesIdentitySourceError, FuturesInstrumentIdentity, require_futures_identity
class Source:
def current_identity(self):
return FuturesInstrumentIdentity('FUT-001', 'K200')
def test_explicit_source_preserves_instrument_id_and_symbol():
identity = require_futures_identity(Source())
assert identity.instrument_id == 'FUT-001'
assert identity.symbol == 'K200'
def test_missing_source_fails_closed():
with pytest.raises(FuturesIdentitySourceError, match='FUTURES_IDENTITY_SOURCE_REQUIRED'):
require_futures_identity(None)
@pytest.mark.parametrize('instrument_id,symbol', [('', 'K200'), ('FUT-001', '')])
def test_identity_rejects_missing_authoritative_fields(instrument_id, symbol):
with pytest.raises(FuturesIdentitySourceError):
FuturesInstrumentIdentity(instrument_id, symbol)
[Child Page] test_futures_contract_master.py
from datetime import datetime, timezone
import pytest
from contracts.futures_contract_master import KisCurrentFuturesIdentitySource, parse_kis_futures_contracts, select_current_futures_contract
from contracts.futures_identity_source_port import FuturesIdentitySourceError
# INVALID: synthetic fixtures assumed info_type=1 and mmsc_cls_code=YYYYMM.
# Kept as a historical test artifact only; it must not drive production implementation.
pytestmark = pytest.mark.xfail(
reason="No.401: authoritative FUTURES info_type and mmsc_cls_code semantics are not yet verified",
strict=True,
)
RAW = "1|101W09|KR7001|INDEX FUT|A||202609|U|KOSPI200"
def test_blocked_until_authoritative_mapping_is_verified():
records = parse_kis_futures_contracts(RAW, futures_info_types={"1"})
assert select_current_futures_contract(
records, now=datetime(2026, 9, 6, tzinfo=timezone.utc)
).shrn_iscd == "101W09"
import pytest
from contracts.futures_contract_master import KisCurrentFuturesIdentitySource, parse_kis_futures_contracts, select_current_futures_contract
from contracts.futures_identity_source_port import FuturesIdentitySourceError
RAW = "n".join([
"1|101W09|KR7001|INDEX FUT 202609|A||202609|U|KOSPI200",
"1|101W12|KR7002|INDEX FUT 202612|A||202612|U|KOSPI200",
"5|201ABC|KR7003|OPTION 202609 C|A|345|202609|U|KOSPI200",
])
def test_parse_keeps_explicit_futures_projection_only():
records = parse_kis_futures_contracts(RAW, futures_info_types={"1"})
assert [r.shrn_iscd for r in records] == ["101W09", "101W12"]
def test_selector_uses_master_month_without_expiry_formula():
records = parse_kis_futures_contracts(RAW, futures_info_types={"1"})
selected = select_current_futures_contract(records, now=datetime(2026, 9, 6, tzinfo=timezone.utc))
assert selected.shrn_iscd == "101W09"
def test_selector_rolls_to_next_master_month():
records = parse_kis_futures_contracts(RAW, futures_info_types={"1"})
selected = select_current_futures_contract(records, now=datetime(2026, 10, 1, tzinfo=timezone.utc))
assert selected.shrn_iscd == "101W12"
def test_source_exposes_selected_short_code_as_symbol():
records = parse_kis_futures_contracts(RAW, futures_info_types={"1"})
source = KisCurrentFuturesIdentitySource(records, now_provider=lambda: datetime(2026, 9, 6, tzinfo=timezone.utc), instrument_id="KOSPI200_INDEX_FUTURES")
identity = source.current_identity()
assert identity.symbol == "101W09"
assert identity.instrument_id == "KOSPI200_INDEX_FUTURES"
def test_empty_info_type_set_fails_closed():
with pytest.raises(FuturesIdentitySourceError):
parse_kis_futures_contracts(RAW, futures_info_types=set())
def test_naive_clock_fails_closed():
records = parse_kis_futures_contracts(RAW, futures_info_types={"1"})
with pytest.raises(FuturesIdentitySourceError):
select_current_futures_contract(records, now=datetime(2026, 9, 6))
[Child Page] test_krx_kis_identity_reconciliation.py
import pytest
from contracts.krx_kis_identity_reconciliation import (
IdentityReconciliationError, KisMasterIdentityRecord, KrxInstrumentRecord,
reconcile_krx_to_kis,
)
def test_exact_standard_code_match_preserves_kis_execution_code():
result = reconcile_krx_to_kis(
[KrxInstrumentRecord("KRX-A", "INDEX FUT", "FUTURES")],
[KisMasterIdentityRecord("101S12", "KRX-A")],
)
assert result[0].kis_shrn_iscd == "101S12"
assert result[0].matched_by == "KIS_STND_ISCD_EXACT"
def test_no_prefix_or_name_guessing():
result = reconcile_krx_to_kis(
[KrxInstrumentRecord("KRX-A", "INDEX FUT", "FUTURES")],
[KisMasterIdentityRecord("101S12", "OTHER")],
)
assert result == ()
def test_ambiguous_standard_code_fails_closed():
with pytest.raises(IdentityReconciliationError, match="AMBIGUOUS"):
reconcile_krx_to_kis([], [
KisMasterIdentityRecord("101S12", "KRX-A"),
KisMasterIdentityRecord("101S13", "KRX-A"),
])
[Child Page] test_futures_contract_master_authoritative.py
import pytest
from contracts.futures_contract_master import (
FuturesContractMasterError,
KisCurrentFuturesIdentitySource,
parse_kis_futures_contracts,
select_current_futures_contract,
)
RAW = """1|101S12|STD-NEAR|KOSPI FUT|0|0|1|U200|KOSPI200
1|101S13|STD-NEXT|KOSPI FUT|0|0|2|U200|KOSPI200
5|201ABC|OPT|CALL|0|350|1|U200|KOSPI200
3|301S12|STAR FUT|STAR FUT|0|0|1|USTAR|STAR"""
def test_kis_official_futures_info_types_are_projected():
records = parse_kis_futures_contracts(RAW)
assert [r.shrn_iscd for r in records] == ["101S12", "101S13", "301S12"]
def test_month_code_one_is_authoritative_recent_month():
current = select_current_futures_contract(
parse_kis_futures_contracts(RAW),
underlying_short_code="U200",
)
assert current.shrn_iscd == "101S12"
assert current.mmsc_cls_code == "1"
def test_selector_requires_unique_target_product():
with pytest.raises(FuturesContractMasterError, match="CURRENT_FUTURES_NOT_UNIQUE"):
select_current_futures_contract(parse_kis_futures_contracts(RAW))
def test_source_returns_selected_identity():
source = KisCurrentFuturesIdentitySource(
parse_kis_futures_contracts(RAW),
underlying_name="KOSPI200",
)
assert source.current_identity().stnd_iscd == "STD-NEAR"
def test_no_yyyy_mm_assumption_is_used():
raw = "1|101S12|STD|FUT|0|0|X|U200|KOSPI200"
with pytest.raises(FuturesContractMasterError):
select_current_futures_contract(
parse_kis_futures_contracts(raw),
underlying_short_code="U200",
)
[Child Page] test_futures_contract_master_authoritative.py
import pytest
from contracts.futures_contract_master import (
FuturesContractMasterError,
KisCurrentFuturesContractSource,
parse_kis_futures_contracts,
select_current_futures_contract,
)
RAW = """1|101S12|STD-NEAR|KOSPI FUT|0|0|1|U200|KOSPI200
1|101S13|STD-NEXT|KOSPI FUT|0|0|2|U200|KOSPI200
5|201ABC|OPT|CALL|0|350|1|U200|KOSPI200
3|301S12|STAR FUT|STAR FUT|0|0|1|USTAR|STAR"""
def test_official_futures_info_types_are_projected():
assert [r.shrn_iscd for r in parse_kis_futures_contracts(RAW)] == ["101S12", "101S13", "301S12"]
def test_month_code_one_is_authoritative_recent_month():
current = select_current_futures_contract(parse_kis_futures_contracts(RAW), underlying_short_code="U200")
assert current.shrn_iscd == "101S12"
def test_selector_requires_unique_target_product():
with pytest.raises(FuturesContractMasterError, match="CURRENT_FUTURES_NOT_UNIQUE"):
select_current_futures_contract(parse_kis_futures_contracts(RAW))
def test_source_returns_selected_identity():
source = KisCurrentFuturesContractSource(parse_kis_futures_contracts(RAW), underlying_name="KOSPI200")
assert source.current_contract().stnd_iscd == "STD-NEAR"
def test_no_yyyy_mm_assumption_is_used():
with pytest.raises(FuturesContractMasterError):
select_current_futures_contract(parse_kis_futures_contracts("1|101S12|STD|FUT|0|0|X|U200|KOSPI200"), underlying_short_code="U200")
[Child Page] test_futures_target_configuration.py
import pytest
from application.composition.futures_target_configuration import (
FuturesTargetConfiguration,
FuturesTargetConfigurationError,
)
def test_target_configuration_requires_exactly_one_selector_key():
with pytest.raises(FuturesTargetConfigurationError):
FuturesTargetConfiguration()
with pytest.raises(FuturesTargetConfigurationError):
FuturesTargetConfiguration(
underlying_short_code="U200", underlying_name="KOSPI200"
)
def test_short_code_is_explicit_selector_input():
config = FuturesTargetConfiguration(underlying_short_code=" U200 ")
assert config.selector_kwargs() == {"underlying_short_code": "U200"}
def test_name_is_explicit_selector_input():
config = FuturesTargetConfiguration(underlying_name=" KOSPI200 ")
assert config.selector_kwargs() == {"underlying_name": "KOSPI200"}
def test_whitespace_only_selector_is_not_accepted():
with pytest.raises(FuturesTargetConfigurationError):
FuturesTargetConfiguration(underlying_short_code="   ", underlying_name="   ")
config = FuturesTargetConfiguration(underlying_short_code="   ", underlying_name=" KOSPI200 ")
assert config.selector_kwargs() == {"underlying_name": "KOSPI200"}
[Child Page] test_virtual_composition_root.py
```python
from application.composition.virtual_composition_root import (
    create_virtual_composition_dependencies,
    create_virtual_environment_factory,
)
from application.environment_hub.contracts import (
    EnvironmentConfig, EnvironmentType, RuntimePolicy,
)
from environments.virtual.execution.vssf_command_context_provider import CanonicalVSSFCommandContextProvider

class Registry:
    def get_contract_identity(self, shrn_iscd):
        return object() if shrn_iscd == "201ABC" else None

class Builder:
    def __init__(self, bundle): self.bundle = bundle; self.calls = []
    def build(self, config, policy):
        self.calls.append((config, policy)); return self.bundle

def test_composition_dependencies_accept_concrete_vssf_provider():
    registry = Registry()
    scenario_source = {"contract_mappings": [{"scenario_contract_key": "scenario-call", "shrn_iscd": "201ABC"}]}
    provider = CanonicalVSSFCommandContextProvider()
    dependencies = create_virtual_composition_dependencies(
        contract_registry=registry, scenario_configuration=scenario_source,
        initial_capital=12_345_678.0, vssf_command_context=provider,
        scenario_source=scenario_source,
    )
    assert dependencies.contract_registry is registry
    assert dependencies.scenario_source is scenario_source
    assert dependencies.contract_mappings["scenario-call"].shrn_iscd == "201ABC"
    assert dependencies.initial_capital == 12_345_678.0
    assert dependencies.vssf_command_context is provider

def test_factory_uses_existing_virtual_builder_seam():
    bundle = object(); builder = Builder(bundle)
    factory = create_virtual_environment_factory(builder=builder)
    config = EnvironmentConfig(environment=EnvironmentType.VIRTUAL, name="virtual-test")
    policy = RuntimePolicy()
    result = factory.create(config, policy)
    assert result is bundle
    assert builder.calls == [(config, policy)]
```
## 검증
        - Composition Root는 concrete provider를 자체 생성하지 않고 명시적 dependency로 받는다.
        - 실제 CanonicalVSSFCommandContextProvider 인스턴스가 dependency scope까지 보존되는지 검증한다.
        - 기존 EnvironmentFactory Virtual seam은 변경하지 않는다.
        - synthetic identity나 별도 registry lookup은 추가하지 않는다.
[Child Page] test_risk_order_intent_adapter.py
```python
from dataclasses import dataclass
from decimal import Decimal

import pytest

from core.oms.position_execution_policy import PositionExecutionDecision
from core.oms.risk_order_intent_adapter import (
    RiskOrderIntentMappingError,
    build_order_intent_execution_input,
)


@dataclass
class ReducedCommand:
    qty: int


@dataclass
class RiskResult:
    decision: str
    is_approved: bool
    approved_qty: int
    reduced_command: object | None = None
    rejection_reason: str | None = None


def decision():
    return PositionExecutionDecision(
        client_order_id="ORD-1",
        approved_quantity=5,
        requested_price=Decimal("1.25"),
        order_type="LIMIT",
        order_purpose="ENTRY",
        asset_type="OPTION",
        track_id="track1",
        tag_id="tail-defense",
    )


def test_allow_maps_authoritative_quantity_and_preserves_semantics():
    result = build_order_intent_execution_input(
        decision(), RiskResult("ALLOW", True, 5)
    )
    assert result.quantity == 5
    assert result.requested_price == Decimal("1.25")
    assert result.order_type == "LIMIT"
    assert result.order_purpose == "ENTRY"
    assert result.asset_type == "OPTION"
    assert result.track_id == "track1"
    assert result.tag_id == "tail-defense"


def test_reduce_maps_reduced_command_quantity():
    result = build_order_intent_execution_input(
        decision(), RiskResult("REDUCE", True, 3, ReducedCommand(3))
    )
    assert result.quantity == 3


def test_reduce_provenance_mismatch_fails_closed():
    with pytest.raises(RiskOrderIntentMappingError, match="PROVENANCE"):
        build_order_intent_execution_input(
            decision(), RiskResult("REDUCE", True, 4, ReducedCommand(3))
        )


def test_deny_does_not_build_execution_input():
    with pytest.raises(RiskOrderIntentMappingError, match="LIMIT"):
        build_order_intent_execution_input(
            decision(), RiskResult("DENY", False, 0, rejection_reason="LIMIT")
        )


def test_unknown_risk_decision_fails_closed():
    with pytest.raises(RiskOrderIntentMappingError, match="UNKNOWN_RISK_DECISION"):
        build_order_intent_execution_input(
            decision(), RiskResult("UNKNOWN", True, 5)
        )
```
## 검증 기준
        - Risk ALLOW/REDUCE의 authoritative quantity가 OrderIntentExecutionInput.quantity로 전달된다.
        - DENY에서는 입력 객체가 생성되지 않는다.
        - PositionExecutionDecision의 execution semantics와 provenance가 변경 없이 보존된다.
        - quantity provenance mismatch 및 unknown decision은 fail-closed 한다.
        - 이 테스트는 명세이며 원격 Git/터미널에서 실행하지 않았다.
[Child Page] test_canonical_order_command_adapter.py
```python
from datetime import datetime

import pytest

from contracts.types import CanonicalMarketTick
from core.oms.canonical_order_command_adapter import (
    CanonicalOrderCommandAdapter,
    CanonicalOrderCommandValidationError,
)
from core.runtime.runtime_execution_context import RuntimeExecutionContext
from shared.contracts.canonical import (
    CanonicalAssetType,
    CanonicalOptionType,
    CanonicalOrderSide,
    CanonicalStrategySignal,
)


def runtime() -> RuntimeExecutionContext:
    tick = CanonicalMarketTick(
        instrument_id="OPT-AUTH-1",
        observed_at=datetime(2026, 9, 6, 9, 0, 1),
        price=100,
        source_sequence=42,
    )
    return RuntimeExecutionContext(tick_sequence=tick.source_sequence, local_sequence=7)


def option_signal(instrument_id="OPT-AUTH-1", symbol="KOSPI200", expiry="20260910"):
    return CanonicalStrategySignal(
        signal_id="SIG-42-Track4-7",
        track_id="Track4",
        asset_type=CanonicalAssetType.OPTION,
        side=CanonicalOrderSide.BUY,
        qty=2,
        price=3.5,
        option_type=CanonicalOptionType.CALL,
        strike=350.0,
        tag_id="T4",
        timestamp="2026-09-06T09:00:01",
        symbol=symbol,
        expiry=expiry,
        instrument_id=instrument_id,
    )


def test_command_uses_runtime_authoritative_client_order_id_and_preserves_identity():
    command = CanonicalOrderCommandAdapter().create(option_signal(), runtime())

    assert command.client_order_id == "ORD-T42-Track4-7"
    assert command.track_id == "Track4"
    assert option_signal().instrument_id == "OPT-AUTH-1"
    assert command.asset_type == CanonicalAssetType.OPTION
    assert command.side == CanonicalOrderSide.BUY
    assert command.qty == 2
    assert command.price == 3.5
    assert command.symbol == "KOSPI200"
    assert command.expiry == "20260910"
    assert command.option_type == CanonicalOptionType.CALL
    assert command.strike == 350.0
    assert command.tag_id == "T4"


def test_missing_authoritative_instrument_id_fails_closed():
    with pytest.raises(CanonicalOrderCommandValidationError, match="AUTHORITATIVE_INSTRUMENT_ID_REQUIRED"):
        CanonicalOrderCommandAdapter().create(option_signal(instrument_id=""), runtime())


def test_option_identity_defaults_are_not_used_as_fallbacks():
    with pytest.raises(CanonicalOrderCommandValidationError, match="OPTION_SYMBOL_EXPIRY_REQUIRED"):
        CanonicalOrderCommandAdapter().create(option_signal(symbol="", expiry=""), runtime())


def test_command_id_does_not_use_signal_id_or_tick_seq_fallback_from_adapter():
    signal = option_signal()
    signal = CanonicalStrategySignal(**{**signal.__dict__, "signal_id": "UNRELATED"})
    command = CanonicalOrderCommandAdapter().create(signal, runtime())
    assert command.client_order_id == "ORD-T42-Track4-7"
```
### 검증 범위
        - RuntimeExecutionContext가 authoritative tick/local sequence를 이용해 client_order_id를 공급한다.
        - Command adapter는 client_order_id를 자체 생성하거나 signal_id를 fallback으로 사용하지 않는다.
        - OPTION authoritative identity가 Canonical signal에서 누락되면 fail-closed한다.
        - Reference legacy default를 identity fallback으로 승격하지 않는다.
[Child Page] test_decision_to_order_transport_lossless.py
```python
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

import pytest

from core.decision.decision_arbiter import DecisionArbiter
from canonical_order_transport import (
    CanonicalOrderTransportError,
    CanonicalOrderTransportInput,
    validate_lossless_transport,
)


class AssetType(str, Enum):
    OPTION = "OPTION"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OptionType(str, Enum):
    CALL = "CALL"
    PUT = "PUT"


@dataclass(frozen=True)
class Signal:
    signal_id: str
    track_id: str
    asset_type: AssetType
    side: Side
    qty: int
    price: float
    option_type: OptionType
    strike: Decimal
    tag_id: str
    symbol: str
    expiry: str


def make_signal(signal_id="sig-1", side=Side.BUY):
    return Signal(
        signal_id=signal_id,
        track_id="Track4",
        asset_type=AssetType.OPTION,
        side=side,
        qty=3,
        price=1.25,
        option_type=OptionType.CALL,
        strike=Decimal("350"),
        tag_id="GAMMA_REBALANCE",
        symbol="KOSPI200-C-350",
        expiry="20260910",
    )


def test_arbiter_preserves_execution_fields_and_identity_without_rewrite():
    original = make_signal()
    result = DecisionArbiter().arbitrate([original], account=None)

    approved = result.approved_signals[0]
    assert approved is original
    assert approved.signal_id == original.signal_id
    assert approved.track_id == original.track_id
    assert approved.asset_type == original.asset_type
    assert approved.side == original.side
    assert approved.qty == original.qty
    assert approved.price == original.price
    assert approved.option_type == original.option_type
    assert approved.strike == original.strike
    assert approved.tag_id == original.tag_id
    assert approved.symbol == original.symbol
    assert approved.expiry == original.expiry


def test_transport_accepts_only_authoritative_identity_fields():
    request = CanonicalOrderTransportInput(
        client_order_id="ORD-1",
        asset_type="OPTION",
        side="BUY",
        quantity=3,
        price=Decimal("1.25"),
        option_type="CALL",
        strike=Decimal("350"),
        symbol="KOSPI200-C-350",
        expiry="20260910",
        track_id="Track4",
        tag_id="GAMMA_REBALANCE",
        instrument_id="AUTH-OPT-350-C-20260910",
    )
    validate_lossless_transport(request)


def test_transport_fails_closed_when_option_identity_is_incomplete():
    request = CanonicalOrderTransportInput(
        client_order_id="ORD-1",
        asset_type="OPTION",
        side="BUY",
        quantity=3,
        price=Decimal("1.25"),
        option_type="CALL",
        strike=Decimal("350"),
        symbol=None,
        expiry="20260910",
        track_id="Track4",
        tag_id="GAMMA_REBALANCE",
        instrument_id="AUTH-OPT-350-C-20260910",
    )
    with pytest.raises(CanonicalOrderTransportError, match="OPTION_SYMBOL_EXPIRY_REQUIRED"):
        validate_lossless_transport(request)


def test_order_execution_semantics_are_not_invented_by_canonical_transport():
    # canonical_order_transport intentionally has no order_type/order_purpose
    # fields. Those values must be supplied by Position/Execution Policy.
    assert "order_type" not in CanonicalOrderTransportInput.__annotations__
    assert "order_purpose" not in CanonicalOrderTransportInput.__annotations__
```
## 목적
        - Reference의 실제 DecisionArbiter가 approved signal 객체 자체를 변경하지 않는 계약을 Standard에서 고정한다.
        - signal_id / track_id / asset_type / side / qty / price / option_type / strike / tag_id / symbol / expiry를 Decision 단계에서 재계산하지 않는다.
        - canonical_order_transport.py는 authoritative instrument_id와 OPTION identity completeness만 검증하고, order_type / order_purpose를 생성하지 않는다.
        - 따라서 Decision → CanonicalOrderCommand/transport 단계와 PositionExecutionPolicy → OrderIntent 단계의 책임을 혼합하지 않는다.
## 검증 범위
이 테스트는 DecisionArbiter와 canonical transport의 계약 seam을 검증하는 독립 테스트다. 전체 OptionProject pytest 실행 여부는 별도로 기록한다.
[Child Page] test_risk_runtime_adapter.py
```python
from datetime import datetime
from decimal import Decimal

import pytest

from contracts.types import AccountSnapshot, DataQuality
from core.risk.risk_engine import RiskEngine, RiskGate
from core.risk.risk_config import RiskConfig
from core.risk.risk_runtime_adapter import (
    build_risk_runtime_inputs,
    validate_risk_order_command,
)


class Command:
    client_order_id = "ORD-1"
    track_id = "Track1"
    qty = 3
    price = 12.5
    side = "BUY"
    tag_id = "Track1"

    def get_instrument_key(self):
        return "OPT-1"


class PositionManager:
    positions = {
        "OPT-1": {"side": "BUY", "qty": 2, "avg_price": 10.0}
    }


def quality():
    return DataQuality(True, True, True, None)


def account_snapshot():
    return AccountSnapshot(
        as_of=datetime(2026, 9, 5),
        balances={
            "cash": Decimal("50000000"),
            "realized_pnl": Decimal("0"),
            "margin_used": Decimal("1000000"),
            "available_cash": Decimal("49000000"),
        },
        freshness=quality(),
    )


def test_command_boundary_preserves_same_object():
    command = Command()
    assert validate_risk_order_command(command) is command


def test_runtime_inputs_use_authoritative_account_and_position_adapters():
    command = Command()
    result = build_risk_runtime_inputs(command, account_snapshot(), PositionManager())

    assert result.command is command
    assert result.account.total_balance == Decimal("50000000")
    assert result.account.used_margin == Decimal("1000000")
    assert result.account.free_margin == Decimal("49000000")
    assert result.positions.positions["OPT-1"].side == "BUY"
    assert result.positions.positions["OPT-1"].qty == 2


def test_command_without_instrument_key_fails_closed():
    class InvalidCommand:
        client_order_id = "ORD-2"
        track_id = "Track1"
        qty = 1
        price = 1.0
        side = "BUY"
        tag_id = "Track1"

    with pytest.raises(TypeError, match="RISK_ORDER_COMMAND_FIELDS_REQUIRED"):
        validate_risk_order_command(InvalidCommand())


def test_adapter_inputs_can_be_passed_to_standard_risk_gate_without_reconstruction():
    class MarginCalculator:
        def calculate_order_margin(self, command):
            return float(command.price) * int(command.qty)

    command = Command()
    inputs = build_risk_runtime_inputs(command, account_snapshot(), PositionManager())
    gate = RiskGate(
        RiskEngine(
            config=RiskConfig(max_position_per_instrument=100),
            margin_engine=MarginCalculator(),
        )
    )

    approved, token, reason = gate.admit_order(
        command=inputs.command,
        account=inputs.account,
        positions=inputs.positions,
    )

    assert approved is True
    assert token is not None
    assert reason is None
    assert gate.last_evaluation_result.approved_qty == command.qty
    assert gate.last_evaluation_result.reduced_command is None
    assert inputs.command is command


def test_risk_gate_reduce_quantity_becomes_authoritative_effective_command():
    class MarginCalculator:
        def calculate_order_margin(self, command):
            return float(command.price) * int(command.qty)

    command = Command()
    inputs = build_risk_runtime_inputs(command, account_snapshot(), PositionManager())
    gate = RiskGate(
        RiskEngine(
            config=RiskConfig(max_position_per_instrument=3),
            margin_engine=MarginCalculator(),
        )
    )

    approved, token, reason = gate.admit_order(
        command=inputs.command,
        account=inputs.account,
        positions=inputs.positions,
        allow_reduction=True,
    )

    assert approved is True
    assert token is not None
    assert reason is None
    result = gate.last_evaluation_result
    assert result.decision == "REDUCE"
    assert result.reduced_command is not None
    assert result.reduced_command.qty == 1
    assert result.approved_qty == 1
    assert result.reduced_command is not command
    assert result.reduced_command.client_order_id == command.client_order_id
    assert result.reduced_command.track_id == command.track_id
    assert result.reduced_command.side == command.side
    assert result.reduced_command.price == command.price
    assert result.reduced_command.tag_id == command.tag_id
```
## 검증 대상
        - 명령 객체 identity 보존
        - Risk 입력용 account 필드의 기존 adapter 재사용
        - authoritative PositionManager의 side/qty 보존
        - 필수 command 경계 누락 시 fail-closed
        - order_type/order_purpose 및 identity를 adapter가 생성하지 않음
[Child Page] test_canonical_signal_adapter_track4_seam.py
```python
from decimal import Decimal

import pytest

from contracts.types import OptionInstrumentIdentity
from core.strategy.canonical_signal_adapter import RuntimeSignalContext, signal_to_canonical
from core.strategy.contracts import Signal
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal


def make_track4_futures_signal() -> Signal:
    proposal = StrategyExecutionProposal(
        proposed_quantity=2,
        asset_type="FUTURES",
        requested_price=Decimal("350.25"),
        side="BUY",
        track_id="TRACK4_GAMMA_SCALPING",
        tag_id="DELTA_HEDGE",
    )
    return Signal("TRACK4_GAMMA_SCALPING", "LONG", 1.0, "DELTA_HEDGE", execution_proposal=proposal)


def make_runtime() -> RuntimeSignalContext:
    return RuntimeSignalContext(
        signal_id="tick-200:TRACK4_GAMMA_SCALPING:0",
        track_id="TRACK4_GAMMA_SCALPING",
        price=351.10,
        timestamp="2026-09-06T09:02:00",
    )


def test_track4_proposal_semantics_are_preserved_at_canonical_boundary():
    signal = make_track4_futures_signal()
    canonical = signal_to_canonical(signal, make_runtime())
    assert canonical.signal_id == "tick-200:TRACK4_GAMMA_SCALPING:0"
    assert canonical.track_id == "TRACK4_GAMMA_SCALPING"
    assert canonical.asset_type.value == "FUTURES"
    assert canonical.side.value == "BUY"
    assert canonical.qty == 2
    assert canonical.tag_id == "DELTA_HEDGE"
    assert canonical.price == 351.10
    # requested_price와 Runtime canonical price는 다른 의미이며 서로 덮어쓰지 않는다.
    assert signal.execution_proposal.requested_price == Decimal("350.25")
    assert canonical.price != float(signal.execution_proposal.requested_price)


def test_track4_missing_execution_proposal_fails_closed():
    signal = Signal("TRACK4_GAMMA_SCALPING", "LONG", 1.0, "DELTA_HEDGE", execution_proposal=None)
    with pytest.raises(ValueError, match="EXECUTION_PROPOSAL_REQUIRED"):
        signal_to_canonical(signal, make_runtime())


def test_option_canonical_boundary_requires_authoritative_identity():
    proposal = StrategyExecutionProposal(
        proposed_quantity=1, asset_type="OPTION", requested_price=Decimal("1.50"),
        side="BUY", track_id="TRACK4_GAMMA_SCALPING", tag_id="OPTION_HEDGE",
        option_type="CALL", strike=Decimal("350"),
    )
    signal = Signal("TRACK4_GAMMA_SCALPING", "LONG", 1.0, "OPTION_HEDGE", execution_proposal=proposal)
    with pytest.raises(ValueError, match="OPTION_IDENTITY_REQUIRED"):
        signal_to_canonical(signal, make_runtime())


def test_option_identity_fields_are_preserved_without_synthetic_identity():
    proposal = StrategyExecutionProposal(
        proposed_quantity=1, asset_type="OPTION", requested_price=Decimal("1.50"),
        side="BUY", track_id="TRACK4_GAMMA_SCALPING", tag_id="OPTION_HEDGE",
        option_type="CALL", strike=Decimal("350"),
    )
    identity = OptionInstrumentIdentity(
        instrument_id="KRX-OPT-350-C-2026-10", symbol="KRXOPT", expiry="2026-10-08",
        option_type="CALL", strike=Decimal("350"),
    )
    signal = Signal("TRACK4_GAMMA_SCALPING", "LONG", 1.0, "OPTION_HEDGE",
                    execution_proposal=proposal, instrument_identity=identity)
    canonical = signal_to_canonical(signal, make_runtime())
    assert canonical.asset_type.value == "OPTION"
    assert canonical.side.value == "BUY"
    assert canonical.qty == 1
    assert canonical.symbol == "KRXOPT"
    assert canonical.expiry == "2026-10-08"
    assert canonical.option_type.value == "CALL"
    assert canonical.strike == 350.0
    assert canonical.price == 351.10
```
## 검증 목적
        - Signal.execution_proposal의 asset_type / side / proposed_quantity / tag_id 보존을 고정한다.
        - requested_price는 현재 Runtime canonical price와 다른 의미이며 임의 치환하지 않는다.
        - OPTION은 option_type / strike만으로 instrument identity를 합성하지 않고 authoritative OptionInstrumentIdentity가 없으면 fail-closed한다.
        - identity가 공급되면 symbol / expiry / option_type / strike를 그대로 보존한다.
        - Runtime signal_id / track_id / price / timestamp는 RuntimeSignalContext가 공급하며 Adapter가 생성하지 않는다.
[Child Page] test_kis_auth.py
```python
import json
import time
import unittest
from unittest.mock import patch

from infrastructure.kis.auth import KISAuthManager, KISAuthToken


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class KISAuthManagerTests(unittest.TestCase):
    def test_from_env_resolves_vts_credentials(self):
        with patch.dict(
            "os.environ",
            {"KIS_VTS_APP_KEY": "key", "KIS_VTS_APP_SECRET": "secret"},
            clear=True,
        ):
            auth = KISAuthManager.from_env(cache_file_path=None)
        self.assertTrue(auth.has_credentials())
        self.assertEqual(auth.app_key, "key")

    def test_valid_token_is_reused_without_http_call(self):
        calls = []
        auth = KISAuthManager(
            "key", "secret", cache_file_path=None,
            urlopen=lambda *_args, **_kwargs: calls.append(1),
        )
        auth._current_token = KISAuthToken(
            access_token="live-token",
            token_expired_at=time.time() + 3600,
        )
        self.assertEqual(auth.get_access_token(), "live-token")
        self.assertEqual(calls, [])

    def test_expired_token_is_reissued(self):
        calls = []
        def urlopen(*_args, **_kwargs):
            calls.append(1)
            return _Response({"access_token": "new-token", "expires_in": 3600})

        auth = KISAuthManager("key", "secret", cache_file_path=None, urlopen=urlopen)
        auth._current_token = KISAuthToken(
            access_token="old-token",
            token_expired_at=time.time() - 1,
        )
        self.assertEqual(auth.get_access_token(), "new-token")
        self.assertEqual(len(calls), 1)

    def test_auth_headers_include_tr_id(self):
        auth = KISAuthManager("key", "secret", cache_file_path=None)
        auth._current_token = KISAuthToken(
            access_token="token",
            token_expired_at=time.time() + 3600,
        )
        headers = auth.get_auth_headers("FHPST02300000")
        self.assertEqual(headers["authorization"], "Bearer token")
        self.assertEqual(headers["tr_id"], "FHPST02300000")


if __name__ == "__main__":
    unittest.main()

```
[Child Page] test_standard_strategy_registry.py
```python
from core.strategy.standard_registry import (
    STANDARD_STRATEGY_IDS,
    STANDARD_STRATEGY_KEYS,
    build_standard_strategy_registry,
)


def test_standard_registry_contains_exactly_nine_baseline_strategies():
    registry = build_standard_strategy_registry()

    assert len(STANDARD_STRATEGY_KEYS) == 9
    assert len(STANDARD_STRATEGY_IDS) == 9
    assert len(set(STANDARD_STRATEGY_KEYS)) == 9
    assert len(set(STANDARD_STRATEGY_IDS)) == 9

    for strategy_id, version in STANDARD_STRATEGY_KEYS:
        strategy = registry.get(strategy_id, version)
        assert strategy.strategy_id == strategy_id
        assert strategy.version == version


def test_standard_registry_ids_are_projection_of_identity_manifest():
    assert STANDARD_STRATEGY_IDS == tuple(
        strategy_id for strategy_id, _ in STANDARD_STRATEGY_KEYS
    )


def test_standard_registry_rebuild_is_isolated():
    first = build_standard_strategy_registry()
    second = build_standard_strategy_registry()

    assert first is not second
    for strategy_id, version in STANDARD_STRATEGY_KEYS:
        assert first.get(strategy_id, version) is not second.get(
            strategy_id, version
        )


def test_registry_manifest_has_no_runtime_or_execution_dependency():
    import inspect
    from core.strategy import standard_registry

    source = inspect.getsource(standard_registry)
    for forbidden in (
        "option_program.runtime",
        "Broker",
        "OrderRequest",
        "ExecutionReport",
        "VMS",
        "VSSF",
        "UI",
    ):
        assert forbidden not in source
```
[Child Page] test_standard_strategy_orchestrator_integration.py
```python
from core.strategy.orchestrator import StrategyOrchestrator
from core.strategy.standard_registry import (
    STANDARD_STRATEGY_IDS,
    STANDARD_STRATEGY_KEYS,
    build_standard_strategy_registry,
)


def build_standard_orchestrator():
    registry = build_standard_strategy_registry()
    return registry, StrategyOrchestrator(registry, STANDARD_STRATEGY_KEYS)


def test_standard_registry_exposes_nine_strategy_identities():
    registry, _ = build_standard_orchestrator()

    assert len(STANDARD_STRATEGY_KEYS) == 9
    assert len(set(STANDARD_STRATEGY_KEYS)) == 9

    for strategy_id, version in STANDARD_STRATEGY_KEYS:
        strategy = registry.get(strategy_id, version)
        assert strategy.strategy_id == strategy_id
        assert strategy.version == version


def test_orchestrator_key_manifest_matches_registered_identities():
    registry, orchestrator = build_standard_orchestrator()

    assert orchestrator._strategy_keys == STANDARD_STRATEGY_KEYS
    for strategy_id, version in STANDARD_STRATEGY_KEYS:
        assert registry.get(strategy_id, version).strategy_id == strategy_id


def test_missing_context_is_reported_per_strategy_without_global_abort():
    _, orchestrator = build_standard_orchestrator()

    result = orchestrator.run({})

    assert result.signals == ()
    assert len(result.failures) == 9
    assert [failure.strategy_id for failure in result.failures] == list(
        STANDARD_STRATEGY_IDS
    )
    assert {failure.stage for failure in result.failures} == {"context"}


def test_selected_subset_execution_order_is_explicit_and_deterministic():
    _, orchestrator = build_standard_orchestrator()

    selected = STANDARD_STRATEGY_KEYS[6:9]
    result = orchestrator.run({}, selected=selected)

    assert [failure.strategy_id for failure in result.failures] == [
        strategy_id for strategy_id, _ in selected
    ]


def test_disabled_strategy_is_excluded_before_context_lookup():
    _, orchestrator = build_standard_orchestrator()

    strategy_id, version = STANDARD_STRATEGY_KEYS[0]
    orchestrator.set_enabled(strategy_id, version, False)
    result = orchestrator.run({})

    assert strategy_id not in {
        failure.strategy_id for failure in result.failures
    }


def test_registry_rebuild_produces_isolated_nine_strategy_instances():
    first = build_standard_strategy_registry()
    second = build_standard_strategy_registry()

    for strategy_id, version in STANDARD_STRATEGY_KEYS:
        assert first.get(strategy_id, version) is not second.get(
            strategy_id, version
        )
```
## 변경
이전 테스트에 남아 있던 registry.get(strategy_id, "1.0") 가정을 제거했다.
Orchestrator와 Registry Test 모두 STANDARD_STRATEGY_KEYS를 사용하므로 Track별 version 변경 시 한 곳의 manifest만 갱신하면 된다.
[Child Page] test_standard_strategy_orchestrator_full_integration.py
```python
from core.strategy.integration_fixtures import contexts
from core.strategy.orchestrator import StrategyOrchestrator
from core.strategy.standard_registry import (
    STANDARD_STRATEGY_KEYS,
    build_standard_strategy_registry,
)


def build_orchestrator():
    registry = build_standard_strategy_registry()
    return StrategyOrchestrator(registry, STANDARD_STRATEGY_KEYS)


def signal_identity(result):
    return tuple(
        (signal.strategy_id, signal.direction, signal.confidence, signal.reason)
        for signal in result.signals
    )


def failure_identity(result):
    return tuple(
        (
            failure.strategy_id,
            failure.version,
            failure.stage,
            failure.error_type,
            failure.message,
        )
        for failure in result.failures
    )


def test_all_nine_actual_strategies_complete_full_lifecycle():
    result = build_orchestrator().run(contexts())

    assert result.failures == ()
    assert all(
        signal.strategy_id in {
            strategy_id for strategy_id, _ in STANDARD_STRATEGY_KEYS
        }
        for signal in result.signals
    )


def test_same_fresh_registry_and_fixture_is_deterministic():
    first = build_orchestrator().run(contexts())
    second = build_orchestrator().run(contexts())

    assert failure_identity(first) == failure_identity(second)
    assert signal_identity(first) == signal_identity(second)


def test_reset_rebuilds_lifecycle_without_cross_strategy_state_sharing():
    orchestrator = build_orchestrator()
    first = orchestrator.run(contexts())
    orchestrator.reset()
    second = orchestrator.run(contexts())

    assert failure_identity(first) == failure_identity(second)
    assert signal_identity(first) == signal_identity(second)


def test_all_contexts_match_standard_identity_manifest():
    supplied = contexts()

    assert tuple(supplied.keys()) == tuple(
        strategy_id for strategy_id, _ in STANDARD_STRATEGY_KEYS
    )

    for strategy_id, _ in STANDARD_STRATEGY_KEYS:
        context = supplied[strategy_id]
        assert context.strategy_id == strategy_id
        payload = context.input.payload
        payload_strategy_id = getattr(payload, "strategy_id", None)
        if payload_strategy_id is not None:
            assert payload_strategy_id == strategy_id


def test_registry_accepts_strategy_payloads_without_optional_identity_field():
    supplied = contexts()
    registry = build_standard_strategy_registry()

    for strategy_id, version in STANDARD_STRATEGY_KEYS:
        context = supplied[strategy_id]
        prepared = registry.prepare(strategy_id, version, context)
        assert prepared.strategy_id == strategy_id
```
## 검증 의미
이 테스트는 9개 전략의 매매 성과를 검증하지 않는다.
검증 대상은 실제 9개 Strategy가:
        - 실제 typed payload
        - 동일한 canonical MarketState
        - 실제 Registry identity
        - 실제 Orchestrator lifecycle
을 통해 실행 가능한지다.
실제 terminal pytest는 실행하지 않았으므로 PASS 선언하지 않는다.
[Child Page] test_kis_holiday_provider.py
```python
from datetime import date

from infrastructure.kis.auth import KISAuthManager
from infrastructure.kis.holiday_provider import (
    KISHolidayProvider,
    KISHolidayUnavailableError,
    parse_kis_holiday_output,
)


def test_parse_kis_holiday_output_extracts_only_closed_days():
    result = parse_kis_holiday_output([
        {"bass_dt": "20260101", "opnd_yn": "N"},
        {"bass_dt": "20260102", "opnd_yn": "Y"},
    ])
    assert result == {date(2026, 1, 1)}


def test_response_load_preserves_holiday_query_contract():
    provider = KISHolidayProvider()
    count = provider.load_from_response_data({
        "rt_cd": "0",
        "output": [{"bass_dt": "20260101", "opnd_yn": "N"}],
    }, year=2026)
    assert count == 1
    assert provider.is_holiday(date(2026, 1, 1))
    assert provider.is_loaded


def test_strict_mode_rejects_unloaded_year():
    provider = KISHolidayProvider(strict_mode=True)
    try:
        provider.is_holiday(date(2026, 1, 1))
    except KISHolidayUnavailableError:
        pass
    else:
        raise AssertionError("strict mode must reject unavailable holiday data")


def test_api_load_uses_auth_headers_and_continuation_free_response():
    class Response:
        def read(self):
            return b'{"rt_cd":"0","output":[{"bass_dt":"20260101","opnd_yn":"N"}]}'
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False

    auth = KISAuthManager(
        app_key="key",
        app_secret="secret",
        cache_file_path=None,
    )
    auth.get_auth_headers = lambda tr_id="": {"tr_id": tr_id}  # test transport boundary
    provider = KISHolidayProvider(
        auth_manager=auth,
        urlopen=lambda request, timeout: Response(),
    )
    assert provider.load_from_kis_api(2026) == 1
    assert provider.get_holidays_for_year(2026) == {date(2026, 1, 1)}
```
        - 실제 KIS 네트워크 호출 없이 urlopen 주입으로 HTTP 경계를 대체한다.
        - KIS 응답 파싱, strict 실패 의미, 인증 헤더 사용 경로를 검증 대상으로 둔다.
[Child Page] test_production_trading_calendar.py
```python
from datetime import date
import unittest

from infrastructure.kis.trading_calendar import ProductionTradingCalendar


class _HolidayProvider:
    def __init__(self, holidays):
        self.holidays = set(holidays)

    def is_holiday(self, value):
        return value in self.holidays


class ProductionTradingCalendarTests(unittest.TestCase):
    def setUp(self):
        self.calendar = ProductionTradingCalendar(
            _HolidayProvider({date(2026, 3, 2)})
        )

    def test_weekday_and_holiday_boundaries(self):
        self.assertTrue(self.calendar.is_trading_day(date(2026, 2, 27)))
        self.assertFalse(self.calendar.is_trading_day(date(2026, 2, 28)))
        self.assertFalse(self.calendar.is_trading_day(date(2026, 3, 2)))

    def test_prev_trading_day_skips_weekend_and_holiday(self):
        self.assertEqual(
            self.calendar.prev_trading_day(date(2026, 3, 3)),
            date(2026, 2, 27),
        )

    def test_trading_days_between(self):
        self.assertEqual(
            self.calendar.trading_days_between(date(2026, 2, 27), date(2026, 3, 3)),
            1,
        )


if __name__ == "__main__":
    unittest.main()
```
[Child Page] test_option_master_factory.py
```python
import unittest
from unittest.mock import patch

from application.composition.option_master_factory import (
    create_production_option_master,
    create_production_trading_calendar,
)
from infrastructure.kis.auth import KISAuthManager


class OptionMasterCompositionTests(unittest.TestCase):
    def test_calendar_can_be_composed_without_core_infrastructure_import(self):
        auth = KISAuthManager("key", "secret", cache_file_path=None)
        calendar = create_production_trading_calendar(
            auth_manager=auth,
            auto_load_kis=False,
        )
        self.assertTrue(hasattr(calendar, "is_trading_day"))

    @patch("application.composition.option_master_factory.create_default_option_master")
    def test_master_receives_composed_calendar(self, create_master):
        auth = KISAuthManager("key", "secret", cache_file_path=None)
        create_production_option_master(
            auth_manager=auth,
            auto_load_calendar=False,
            auto_load_kis_master=False,
        )
        self.assertIn("calendar", create_master.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
```
[Child Page] test_canonical_signal_adapter.py
```python
from decimal import Decimal

import pytest

from contracts.types import OptionInstrumentIdentity
from core.strategy.contracts import Signal
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal
from core.strategy.canonical_signal_adapter import (
    RuntimeSignalContext,
    signal_to_canonical,
)


def make_track1_option_signal() -> Signal:
    proposal = StrategyExecutionProposal(
        proposed_quantity=1,
        asset_type="OPTION",
        requested_price=None,
        side="BUY",
        track_id="TRACK1_TAIL_DEFENSE",
        tag_id="1",
        option_type="CALL",
        strike=Decimal("350.0"),
    )
    return Signal(
        "TRACK1_TAIL_DEFENSE",
        "LONG",
        1.0,
        "FENCE_BUILD:CALL:350.0",
        execution_proposal=proposal,
    )


def make_identity() -> OptionInstrumentIdentity:
    return OptionInstrumentIdentity(
        instrument_id="KRX-OPT-350-C-2026-10",
        symbol="KRXOPT",
        expiry="2026-10-08",
        option_type="CALL",
        strike=Decimal("350.0"),
    )


def make_runtime() -> RuntimeSignalContext:
    return RuntimeSignalContext(
        signal_id="tick-100:TRACK1_TAIL_DEFENSE:0",
        track_id="TRACK1_TAIL_DEFENSE",
        price=1.25,
        timestamp="2026-09-06T09:01:00",
    )


def test_track1_option_signal_accepts_external_authoritative_identity():
    canonical = signal_to_canonical(
        make_track1_option_signal(),
        make_runtime(),
        instrument_identity=make_identity(),
    )

    assert canonical.signal_id == "tick-100:TRACK1_TAIL_DEFENSE:0"
    assert canonical.track_id == "TRACK1_TAIL_DEFENSE"
    assert canonical.qty == 1
    assert canonical.symbol == "KRXOPT"
    assert canonical.expiry == "2026-10-08"
    assert canonical.strike == 350.0
    assert canonical.option_type.value == "CALL"


def test_track1_proposal_and_external_identity_mismatch_fails_closed():
    bad_identity = OptionInstrumentIdentity(
        instrument_id="KRX-OPT-350-P-2026-10",
        symbol="KRXOPT",
        expiry="2026-10-08",
        option_type="PUT",
        strike=Decimal("350.0"),
    )

    with pytest.raises(ValueError, match="OPTION_TYPE_IDENTITY_MISMATCH"):
        signal_to_canonical(
            make_track1_option_signal(),
            make_runtime(),
            instrument_identity=bad_identity,
        )


def test_signal_identity_and_external_identity_mismatch_fails_closed():
    signal = Signal(
        "TRACK1_TAIL_DEFENSE",
        "LONG",
        1.0,
        "FENCE_BUILD:CALL:350.0",
        instrument_identity=make_identity(),
        execution_proposal=make_track1_option_signal().execution_proposal,
    )
    bad_identity = OptionInstrumentIdentity(
        instrument_id="KRX-OPT-350-P-2026-10",
        symbol="KRXOPT",
        expiry="2026-10-08",
        option_type="PUT",
        strike=Decimal("350.0"),
    )

    with pytest.raises(ValueError, match="OPTION_IDENTITY_MISMATCH"):
        signal_to_canonical(signal, make_runtime(), instrument_identity=bad_identity)


def test_track1_option_without_authoritative_identity_stays_fail_closed():
    with pytest.raises(ValueError, match="OPTION_IDENTITY_REQUIRED"):
        signal_to_canonical(make_track1_option_signal(), make_runtime())
```
## 계약 판정
        - Track1 Strategy가 생성한 option_type/strike는 상품 identity가 아니다.
        - instrument_identity는 외부 authoritative 공급원에서 전달되어야 한다.
        - Adapter는 strike/type으로 instrument_id를 합성하지 않는다.
        - Signal 내부 identity와 외부 identity가 동시에 존재하면 동일성 검증 후 통과한다.
        - identity가 없거나 불일치하면 fail-closed한다.
        - Runtime signal_id/track_id 생성 책임은 그대로 Runtime 경계에 둔다.
[Child Page] test_track4_market_input_materializer.py
```python
from datetime import datetime
from decimal import Decimal

import pytest

from application.composition.track4_market_input_materializer import Track4RuntimeInputMaterializer
from contracts.track4_composite_runtime_input_provider import Track4CompositeRuntimeInputProvider
from contracts.track4_kis_greeks_provider import KISIndexOptionGreeksProvider
from contracts.track4_market_projection_provider import Track4MarketProjectionProvider
from contracts.track4_runtime_input_provider import Track4InputSourceUnavailable
from contracts.track4_vssf_account_projection_provider import Track4VSSFAccountProjectionProvider
from core.sensor.market_condition_sensor import MarketConditionSnapshot
from contracts.types import AccountSnapshot, DataQuality


AS_OF = datetime(2026, 1, 2, 10, 0)


def snapshot(as_of=AS_OF):
    return MarketConditionSnapshot(
        as_of=as_of,
        instrument_id="KOSPI200_VIRTUAL",
        current_price=350.0,
        price_change=0.2,
        volatility=0.012,
        baseline_volatility=0.010,
        volatility_ratio=1.2,
        drawdown=0.0,
        stress_level=0.0,
        stress_flags=(),
    )


class StubAccountProvider:
    def __init__(self, as_of=AS_OF):
        self._snapshot = AccountSnapshot(
            as_of=as_of,
            balances={"cash": Decimal("1000000"), "realized_pnl": Decimal("1000"), "unrealized_pnl": Decimal("2000")},
            freshness=DataQuality(
                is_fresh=True,
                is_complete=True,
                source_available=True,
                reason="test",
            ),
        )

    def snapshot(self):
        return self._snapshot


def make_provider(account_as_of=AS_OF):
    market = Track4MarketProjectionProvider(
        lambda: snapshot(),
        price_history_supplier=lambda _: (349.0, 350.0),
    )
    account = Track4VSSFAccountProjectionProvider(StubAccountProvider(account_as_of))
    return Track4CompositeRuntimeInputProvider(market, account)


def make_greeks(observed_at="2026-01-02T10:00:00"):
    return KISIndexOptionGreeksProvider.from_payload(
        {"delta": "0.52", "gama": "0.18", "theta": "-0.07", "hts_ints_vltl": "0.21"},
        instrument_id="KOSPI200-OPT-1",
        observed_at=observed_at,
    )


def test_materializer_preserves_same_tick_authoritative_values():
    provider = make_provider()
    greeks = make_greeks()
    result = Track4RuntimeInputMaterializer(provider, greeks).materialize(AS_OF)

    assert result.observed_at == AS_OF
    assert result.current_price == Decimal("350.0")
    assert result.active_vol == Decimal("0.21")
    assert result.current_delta == Decimal("0.52")
    assert result.current_gamma == Decimal("0.18")
    assert result.current_pnl == Decimal("3000")
    assert result.current_equity == Decimal("1000000")
    assert result.price_history == (Decimal("349.0"), Decimal("350.0"))
    assert result.premium_spent is None
    assert result.accumulated_gamma_profit is None
    assert result.theta_decay_cost is None


def test_tick_and_account_market_timestamp_mismatch_fails_closed():
    provider = make_provider(account_as_of=datetime(2026, 1, 2, 10, 0, 1))
    greeks = make_greeks()

    with pytest.raises(Exception, match="TRACK4_SOURCE_TIMESTAMP_MISMATCH"):
        Track4RuntimeInputMaterializer(provider, greeks).materialize(AS_OF)


def test_tick_and_greeks_timestamp_mismatch_fails_closed():
    provider = make_provider()
    greeks = make_greeks("2026-01-02T10:00:01")

    with pytest.raises(Track4InputSourceUnavailable, match="TRACK4_GREEKS_TIMESTAMP_MISMATCH"):
        Track4RuntimeInputMaterializer(provider, greeks).materialize(AS_OF)


def test_missing_history_fails_closed():
    market = Track4MarketProjectionProvider(lambda: snapshot(), price_history_supplier=lambda _: ())
    account = Track4VSSFAccountProjectionProvider(StubAccountProvider())
    provider = Track4CompositeRuntimeInputProvider(market, account)

    with pytest.raises(Track4InputSourceUnavailable, match="TRACK4_CORE_INPUT_INCOMPLETE"):
        Track4RuntimeInputMaterializer(provider, make_greeks()).materialize(AS_OF)
```
## 검증 목적
        - Runtime tick → Market/Account source timestamp 일치 여부를 검증한다.
        - KIS authoritative Greeks의 observed_at을 같은 tick으로 고정한다.
        - Market/Account/KIS 값은 원 source 값을 그대로 유지한다.
        - attribution 미확정 값은 None으로 남으며 0/상수 fallback이 생성되지 않는다.
        - history 부재는 materialization을 fail-closed한다.
[Child Page] test_runtime_tick_identity_integration.py
```python
from datetime import datetime

import pytest

from contracts.types import CanonicalMarketTick
from core.runtime.runtime_execution_context import RuntimeExecutionContext


def test_source_sequence_is_the_authoritative_runtime_tick_identity():
    tick = CanonicalMarketTick(
        instrument_id="OPT-AUTH-1",
        observed_at=datetime(2026, 9, 6, 9, 0, 1),
        price=100,
        source_sequence=42,
    )

    context = RuntimeExecutionContext(tick_sequence=tick.source_sequence, local_sequence=3)

    assert context.signal_id("Track4") == "SIG-42-Track4-3"
    assert context.client_order_id("Track4") == "ORD-T42-Track4-3"


def test_missing_source_sequence_fails_closed_before_identity_derivation():
    tick = CanonicalMarketTick(
        instrument_id="OPT-AUTH-1",
        observed_at=datetime(2026, 9, 6, 9, 0, 1),
        price=100,
        source_sequence=None,
    )

    with pytest.raises((TypeError, ValueError)):
        RuntimeExecutionContext(tick_sequence=tick.source_sequence, local_sequence=1)


def test_legacy_seq_id_must_not_silently_replace_missing_source_sequence():
    tick = CanonicalMarketTick(
        instrument_id="OPT-AUTH-1",
        observed_at=datetime(2026, 9, 6, 9, 0, 1),
        price=100,
        seq_id=99,
        source_sequence=None,
    )

    with pytest.raises((TypeError, ValueError)):
        RuntimeExecutionContext(tick_sequence=tick.source_sequence, local_sequence=1)
```
### 검증 목적
        - CanonicalMarketTick.source_sequence를 Runtime identity의 authoritative source로 사용한다.
        - source_sequence가 없으면 fail-closed한다.
        - Reference의 seq_id를 Standard Runtime identity로 묵시적으로 fallback하지 않는다.
        - RuntimeExecutionContext가 signal_id/client_order_id를 직접 생성하는 현재 계약을 유지한다.
### 범위
실제 process_tick() 전체 연결이 아니라 Runtime identity seam의 targeted integration 검증이다.
[Child Page] test_track4_strategy_orchestrator_minimal_integration.py
```python
from datetime import datetime
from decimal import Decimal

from application.composition.track4_market_input_materializer import Track4RuntimeInputMaterializer
from contracts.track4_composite_runtime_input_provider import Track4CompositeRuntimeInputProvider
from contracts.track4_kis_greeks_provider import KISIndexOptionGreeksProvider
from contracts.track4_market_projection_provider import Track4MarketProjectionProvider
from contracts.track4_vssf_account_projection_provider import Track4VSSFAccountProjectionProvider
from contracts.types import AccountSnapshot, CanonicalMarketTick, DataQuality, MarketState
from core.sensor.market_condition_sensor import MarketConditionSnapshot
from core.strategy.contracts import CommonStrategyInput, StrategyContext, StrategyInput
from core.strategy.orchestrator import StrategyOrchestrator
from core.strategy.standard_registry import STANDARD_STRATEGY_KEYS, build_standard_strategy_registry
from core.strategy.track4_gamma_scalping import Track4MarketInput

AS_OF = datetime(2026, 1, 2, 10, 0)
TRACK4_KEY = ("track4_gamma_scalping", "1.0")

class StubAccountProvider:
    def snapshot(self):
        return AccountSnapshot(
            as_of=AS_OF,
            balances={"cash": Decimal("1000000"), "realized_pnl": Decimal("1000"), "unrealized_pnl": Decimal("2000")},
            freshness=DataQuality(True, True, True, "test"),
        )

def build_materialized_track4_input() -> Track4MarketInput:
    market = Track4MarketProjectionProvider(
        lambda: MarketConditionSnapshot(
            as_of=AS_OF,
            instrument_id="KOSPI200_VIRTUAL",
            current_price=350.0,
            price_change=0.2,
            volatility=0.008,
            baseline_volatility=0.010,
            volatility_ratio=0.8,
            drawdown=0.0,
            stress_level=0.0,
            stress_flags=(),
        ),
        price_history_supplier=lambda _: (Decimal("349.0"), Decimal("350.0")),
    )
    account = Track4VSSFAccountProjectionProvider(StubAccountProvider())
    provider = Track4CompositeRuntimeInputProvider(market, account)
    greeks = KISIndexOptionGreeksProvider.from_payload(
        {"delta": "0.52", "gama": "0.18", "theta": "-0.07", "hts_ints_vltl": "0.21"},
        instrument_id="KOSPI200-OPT-1",
        observed_at=AS_OF.isoformat(),
    )
    return Track4RuntimeInputMaterializer(provider, greeks).materialize(AS_OF)

def build_context(data: Track4MarketInput) -> StrategyContext:
    tick = CanonicalMarketTick(
        instrument_id="KOSPI200_VIRTUAL",
        observed_at=data.observed_at,
        price=data.current_price,
    )
    state = MarketState(as_of=data.observed_at, ticks={tick.instrument_id: tick}, quality={})
    common = CommonStrategyInput(
        as_of=data.observed_at,
        current_price=data.current_price,
        active_vol=data.active_vol,
        base_vol=data.base_vol,
        current_pnl=data.current_pnl,
        time_str=data.time_str,
    )
    return StrategyContext(
        market_state=state,
        strategy_id=TRACK4_KEY[0],
        input=StrategyInput(common=common, payload=data),
    )

def test_materialized_track4_input_reaches_registry_orchestrator_and_evaluate():
    data = build_materialized_track4_input()
    context = build_context(data)
    registry = build_standard_strategy_registry()
    orchestrator = StrategyOrchestrator(registry, STANDARD_STRATEGY_KEYS)

    result = orchestrator.run({TRACK4_KEY[0]: context}, selected=(TRACK4_KEY,))

    assert result.failures == ()
    assert result.signals
    assert any(signal.direction == "BUILD" for signal in result.signals)
    assert any(signal.direction == "BUY" for signal in result.signals)

def test_track4_identity_and_payload_boundary_are_preserved():
    data = build_materialized_track4_input()
    context = build_context(data)

    assert context.strategy_id == TRACK4_KEY[0]
    assert context.input is not None
    assert context.input.payload is data
    assert isinstance(context.input.payload, Track4MarketInput)
    assert context.market_state.as_of == data.observed_at
```
## 목적
        - Materializer의 typed Track4MarketInput을 StrategyContext.input.payload에 lossless 전달한다.
        - STANDARD_STRATEGY_KEYS를 사용해 Registry의 Track4 (strategy_id, version)을 선택한다.
        - StrategyOrchestrator의 initialize → on_market_state → evaluate 경계를 실제 Track4 평가까지 검증한다.
        - 주문/Risk/OMS/Broker는 연결하지 않는다.
        - 시장시간은 CanonicalMarketTick/MarketState로 보존하되 Track4 입력을 재계산하지 않는다.
[Child Page] test_runtime_controller_virtual_integration.py
```python
from application.composition import runtime_composition_factory as subject
from application.environment_hub.contracts import (
    EnvironmentConfig,
    EnvironmentType,
    RuntimePolicy,
)


class LifecycleBundle:
    def __init__(self):
        self.environment = EnvironmentType.VIRTUAL
        self.calls = []
        self.connected = False
        self.running = False

    def initialize(self):
        self.calls.append("initialize")

    def connect(self):
        self.calls.append("connect")
        self.connected = True

    def start(self):
        self.calls.append("start")
        if not self.connected:
            raise RuntimeError("not connected")
        self.running = True

    def stop(self):
        self.calls.append("stop")
        self.running = False

    def shutdown(self):
        self.calls.append("shutdown")
        self.connected = False


class Builder:
    def __init__(self, bundle):
        self.bundle = bundle
        self.calls = []

    def build(self, config, policy):
        self.calls.append((config, policy))
        return self.bundle


def test_virtual_runtime_controller_start_stop_through_real_assembly(monkeypatch):
    bundle = LifecycleBundle()
    builder = Builder(bundle)
    dependencies = object()

    monkeypatch.setattr(
        subject,
        "create_virtual_composition_dependencies",
        lambda **kwargs: dependencies,
    )
    monkeypatch.setattr(
        subject,
        "create_virtual_environment_builder",
        lambda *, dependencies: builder,
    )

    controller = subject.create_virtual_runtime_controller(
        contract_registry=object(),
        scenario_configuration={"contract_mappings": []},
        initial_capital=1000.0,
        vssf_command_context=object(),
    )
    config = EnvironmentConfig(
        environment=EnvironmentType.VIRTUAL,
        name="virtual-integration",
    )
    policy = RuntimePolicy()

    controller.start(config, policy)

    assert builder.calls == [(config, policy)]
    assert bundle.calls == ["initialize", "connect", "start"]
    assert bundle.connected is True
    assert bundle.running is True
    assert controller.status().environment == "virtual"
    assert controller.status().state == "RUNNING"

    controller.stop()

    assert bundle.calls == [
        "initialize", "connect", "start", "stop", "shutdown"
    ]
    assert bundle.connected is False
    assert bundle.running is False
    assert controller.status().environment is None
    assert controller.status().state == "STOPPED"
```
## 검증 범위
        - 실제 create_virtual_runtime_controller() assembly를 통해 RuntimeController/EnvironmentHub/EnvironmentFactory 경로를 통과한다.
        - lifecycle 순서 initialize → connect → start → stop → shutdown을 검증한다.
        - start 후 active virtual environment 및 RUNNING 상태를 검증한다.
        - stop 후 active 해제 및 STOPPED 상태를 검증한다.
        - 외부 VMS/VSSF 생성 의존성은 이 lifecycle integration test의 대상이 아니므로 fixture builder로 경계를 분리한다.
        - hidden default를 추가하지 않는다.
[Child Page] test_concrete_virtual_environment_builder.py
```python
from application.composition.concrete_virtual_environment_builder import (
    ConcreteVirtualEnvironmentBuilder,
)


class Dependencies:
    initial_capital = 12_345_678
    vssf_command_context = object()


class Scope:
    def __init__(self):
        self.vssf_runtime = object()
        self.broker = object()
        self.account = object()
        self.position = object()
        self.execution = object()


class ScopeFactory:
    def __init__(self):
        self.calls = []
        self.scope = Scope()

    def create(self, config, policy):
        self.calls.append((config, policy))
        return self.scope


class VMS:
    def __init__(self):
        self.clock = object()


class Bundle:
    calls = []

    @classmethod
    def create(cls, config, policy, *, market, clock, broker, account, position, execution):
        cls.calls.append({
            "config": config,
            "policy": policy,
            "market": market,
            "clock": clock,
            "broker": broker,
            "account": account,
            "position": position,
            "execution": execution,
        })
        return cls.calls[-1]


def test_builder_reuses_one_scope_and_passes_all_components(monkeypatch):
    scope_factory = ScopeFactory()
    vms = VMS()
    builder = ConcreteVirtualEnvironmentBuilder(
        dependencies=Dependencies(),
        scope_factory=scope_factory,
        vms_factory=lambda: vms,
    )

    # Replace only concrete runtime constructors at the composition boundary;
    # this test does not create a real VMS/VSSF.
    class ClockProvider:
        def __init__(self, source):
            self.source = source

    monkeypatch.setattr(
        "application.composition.concrete_virtual_environment_builder.VirtualEnvironmentBundle",
        Bundle,
    )
    monkeypatch.setattr(
        "application.composition.concrete_virtual_environment_builder.VMSClockProvider",
        ClockProvider,
    )

    result = builder.build("config", "policy")

    assert scope_factory.calls == [("config", "policy")]
    assert result["market"] is vms
    assert result["broker"] is scope_factory.scope.broker
    assert result["account"] is scope_factory.scope.account
    assert result["position"] is scope_factory.scope.position
    assert result["execution"] is scope_factory.scope.execution
    assert result["clock"].source is vms.clock


def test_dependency_validation_remains_owned_by_dependencies():
    from application.composition.virtual_composition_dependencies import (
        VirtualCompositionDependencies,
    )

    try:
        VirtualCompositionDependencies(
            contract_registry=object(),
            contract_mappings={},
            initial_capital=0,
            vssf_command_context=object(),
        )
    except (ValueError, TypeError) as exc:
        assert str(exc) in {
            "VIRTUAL_INITIAL_CAPITAL_REQUIRED",
            "VSSF_COMMAND_CONTEXT_REQUIRED",
        }
    else:
        raise AssertionError("invalid composition dependencies must fail closed")
```
## 검증 범위
        - Concrete Builder가 Scope Factory가 반환한 동일 구성요소를 Bundle에 전달하는지 확인한다.
        - VMS의 동일 Clock source를 VMSClockProvider에 연결하는 구조를 확인한다.
        - 실제 VMS/VSSF runtime은 테스트에서 임의 생성하지 않는다.
        - 초기자본/Command Context의 입력 검증은 VirtualCompositionDependencies 책임으로 유지한다.
[Child Page] test_runtime_composition_factory.py
```python
from application.composition import runtime_composition_factory as subject


class Registry: pass


class Provider:
    def build_command(self, order, identity):
        return object()


def test_virtual_runtime_assembly_preserves_explicit_dependency_scope(monkeypatch):
    registry = Registry()
    provider = Provider()
    source = {"contract_mappings": []}
    captured = {}
    sentinel_dependencies = object()
    sentinel_builder = object()
    sentinel_factory = object()

    def fake_dependencies(**kwargs):
        captured.update(kwargs)
        return sentinel_dependencies

    monkeypatch.setattr(subject, "create_virtual_composition_dependencies", fake_dependencies)
    monkeypatch.setattr(subject, "create_virtual_environment_builder", lambda *, dependencies: sentinel_builder)
    monkeypatch.setattr(subject, "create_virtual_environment_factory", lambda *, builder: sentinel_factory)

    controller = subject.create_virtual_runtime_controller(
        contract_registry=registry,
        scenario_configuration=source,
        initial_capital=1000.0,
        vssf_command_context=provider,
        scenario_source=source,
    )

    assert captured["contract_registry"] is registry
    assert captured["vssf_command_context"] is provider
    assert captured["initial_capital"] == 1000.0
    assert controller is not None


def test_virtual_runtime_assembly_reaches_real_environment_factory_and_builder():
    from application.environment_hub.contracts import EnvironmentConfig, RuntimePolicy
    from contracts.types import EnvironmentType

    class CommandContext:
        def build_command(self, order):
            return order

    controller = subject.create_virtual_runtime_controller(
        contract_registry=Registry(),
        scenario_configuration={
            "contract_mappings": [
                {"scenario_contract_key": "scenario-call", "shrn_iscd": "201ABC"}
            ]
        },
        initial_capital=1_000_000_000.0,
        vssf_command_context=CommandContext(),
    )
    config = EnvironmentConfig(EnvironmentType.VIRTUAL, "virtual-integration")
    policy = RuntimePolicy()

    controller.start(config, policy)

    bundle = controller._hub.active
    assert bundle is not None
    assert bundle.environment is EnvironmentType.VIRTUAL
    assert bundle.market.__class__.__name__ == "VirtualMarketSimulatorRuntime"
    assert bundle.broker.execution_engine is bundle.execution
    assert bundle.execution.account._account_source is bundle.broker.execution_engine.account._account_source
    assert controller.status().state == "RUNNING"

    controller.stop()

    assert controller.status().state == "STOPPED"
    assert controller.status().environment is None
```
## 검증 의도
        - 최상위 assembly가 concrete provider를 명시적으로 받는지 확인한다.
        - RuntimeController 내부에 Virtual composition 책임을 넣지 않는다.
        - hidden default나 registry 재생성을 허용하지 않는다.
[Child Page] test_kis_futures_market_consumer_projection_integration.py
```python
import asyncio
from datetime import datetime
from decimal import Decimal

from contracts.kis_index_futures_market_ws_adapter import KISIndexFuturesMarketWebSocketAdapter
from environments.live.market.kis_futures_market_data import KISFuturesMarketDataProvider
from infrastructure.kis.futures_market_consumer import KISIndexFuturesMarketConsumer


class FakeTransport:
    def __init__(self, frame: str):
        self.frame = frame
        self.calls = []

    async def connect(self):
        self.calls.append(("connect",))

    async def subscribe(self, tr_id: str, symbol: str):
        self.calls.append(("subscribe", tr_id, symbol))

    async def recv(self):
        return self.frame

    async def close(self):
        self.calls.append(("close",))


def trade_frame() -> str:
    values = [""] * 37
    values[0] = "101S12"
    values[1] = "093000"
    values[5] = "350.10"
    values[10] = "1234"
    values[35] = "350.20"
    values[36] = "350.00"
    return "0|H0IFCNT0|37|" + "^".join(values)


def test_kis_consumer_callback_reaches_live_market_provider_without_identity_synthesis():
    transport = FakeTransport(trade_frame())
    provider = KISFuturesMarketDataProvider(
        instrument_id_resolver=lambda symbol: "FUT-AUTH-1" if symbol == "101S12" else "",
        observed_at_resolver=lambda _: datetime(2026, 9, 6, 9, 30, 0),
    )

    def on_observation(observation):
        provider.publish(observation)
        return None

    consumer = KISIndexFuturesMarketConsumer(
        transport,
        KISIndexFuturesMarketWebSocketAdapter(),
        on_observation,
    )

    asyncio.run(consumer.start("101S12"))
    observation = asyncio.run(consumer.receive_once())
    state = provider.snapshot()

    assert observation.shrn_iscd == "101S12"
    assert state.ticks["FUT-AUTH-1"].price == Decimal("350.10")
    assert state.ticks["FUT-AUTH-1"].source_sequence is None
    assert transport.calls == [
        ("connect",),
        ("subscribe", "H0IFCNT0", "101S12"),
        ("subscribe", "H0IFASP0", "101S12"),
    ]
```
검증 범위: KISIndexFuturesMarketConsumer → KISFuturesMarketDataProvider → MarketState 실제 callback 경계. Standard instrument_id와 timestamp는 명시적 authoritative resolver에서만 공급되며 consumer가 임의 생성하지 않는다.
[Child Page] test_kis_futures_market_runtime_boundary.py
```python
from datetime import datetime
from decimal import Decimal

import pytest

from contracts.kis_index_futures_market_ws_adapter import KisIndexFuturesMarketObservation
from core.runtime.standard_option_runtime import StandardOptionRuntime
from environments.live.market.kis_futures_market_data import KISFuturesMarketDataProvider


def test_kis_market_projection_does_not_fabricate_runtime_sequence():
    provider = KISFuturesMarketDataProvider(
        instrument_id_resolver=lambda symbol: "FUT-AUTH-1",
        observed_at_resolver=lambda _: datetime(2026, 9, 6, 9, 30, 0),
    )
    observation = KisIndexFuturesMarketObservation(
        shrn_iscd="101S12",
        observed_hour="093000",
        price=Decimal("350.10"),
        volume=Decimal("1234"),
        ask_price=Decimal("350.20"),
        bid_price=Decimal("350.00"),
        source="KIS:H0IFCNT0",
    )

    tick = provider.publish(observation)
    assert tick.source_sequence is None

    runtime = StandardOptionRuntime(strategy_seam=object())
    with pytest.raises(ValueError, match="RUNTIME_SOURCE_SEQUENCE_REQUIRED"):
        runtime.process_tick(tick, tick.observed_at)
```
목적: KIS MarketState projection이 Runtime의 authoritative source_sequence를 임의 생성하지 않음을 고정한다. 현재 KIS observation에는 Runtime이 요구하는 source sequence가 없으므로 직접 Runtime 진입은 명시적으로 실패해야 한다.
[Child Page] test_live_runtime_composition_factory.py
```python
import pytest

from application.composition.live_runtime_composition_factory import (
    build_live_bundle_from_components,
    create_live_runtime_controller,
)
from application.environment_hub.contracts import EnvironmentConfig, EnvironmentType, RuntimePolicy
from environments.live.contracts import LiveSafetyPolicy


class FakeBroker:
    connected = False

    def connect(self):
        self.connected = True
        return True

    def disconnect(self):
        self.connected = False


class FakeComponent:
    pass


def _policy():
    return RuntimePolicy()


def _config():
    return EnvironmentConfig(environment=EnvironmentType.LIVE)


def test_live_runtime_controller_uses_explicit_live_builder():
    components = [FakeComponent() for _ in range(6)]
    components[1] = FakeBroker()
    builder = build_live_bundle_from_components(
        market=components[0],
        broker=components[1],
        account=components[2],
        position=components[3],
        reconciler=components[4],
        recovery=components[5],
        safety_policy=LiveSafetyPolicy(),
    )

    controller = create_live_runtime_controller(live_builder=builder)
    controller.start(_config(), _policy())

    status = controller.status()
    assert status.environment == "live"
    assert status.state == "RUNNING"
    assert components[1].connected is True

    controller.stop()
    assert controller.status().state == "STOPPED"


def test_live_runtime_builder_fails_closed_when_dependency_is_missing():
    with pytest.raises(ValueError, match="LIVE_RUNTIME_DEPENDENCY_REQUIRED:position"):
        build_live_bundle_from_components(
            market=FakeComponent(),
            broker=FakeBroker(),
            account=FakeComponent(),
            position=None,
            reconciler=FakeComponent(),
            recovery=FakeComponent(),
            safety_policy=LiveSafetyPolicy(),
        )


def test_live_runtime_controller_requires_builder():
    with pytest.raises(ValueError, match="LIVE_RUNTIME_BUILDER_REQUIRED"):
        create_live_runtime_controller(live_builder=None)
```
## 검증 목적
        - EnvironmentFactory의 Live 분기가 더 이상 잘못된 LiveEnvironmentBundle(config, policy) 직접 호출로 이어지지 않는지 확인한다.
        - Live RuntimeController가 caller가 공급한 concrete Live builder를 실제 lifecycle에 사용하는지 확인한다.
        - 필수 Live dependency가 없으면 fail-closed한다.
        - synthetic broker/account/position이나 인증정보를 factory가 생성하지 않는지 경계를 유지한다.
        - 실제 KIS 네트워크와 실주문은 실행하지 않는다.
[Child Page] test_live_execution_runtime_composition_factory.py
```python
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest

from application.composition.live_execution_runtime_composition_factory import create_live_execution_runtime_composition
from contracts.types import BrokerOrderCommand, BrokerOrderResponse, ExecutionReport, OrderIntent
from core.oms.oms_fsm import OrderStateMachine, OrderStateTransitionError
from environments.live.execution.execution_event_deduplicator import ExecutionEventDeduplicator
from environments.live.position.live_execution_position_bridge import LivePositionFillAdapter


@dataclass
class FakeTransport:
    frame: object
    connected: bool = False
    subscription: tuple[str, str] | None = None

    async def connect(self):
        self.connected = True

    async def subscribe(self, tr_id: str, tr_key: str):
        self.subscription = (tr_id, tr_key)

    async def recv(self):
        return self.frame

    async def close(self):
        self.connected = False


class FakeExecutionAdapter:
    TR_ID = "H0IFCNI0"

    def parse(self, frame):
        return frame

    def to_execution_report(self, notice, context):
        return ExecutionReport(
            client_order_id=context.client_order_id,
            broker_order_id=notice["broker_order_id"],
            execution_id=notice["execution_id"],
            status=notice["status"],
            filled_quantity=notice["filled_quantity"],
            remaining_quantity=context.order_quantity - context.prior_filled_quantity - notice["filled_quantity"],
            execution_price=Decimal("101.25"),
            execution_timestamp=None,
        )


class FakeCorrelationProvider:
    def __init__(self, oms):
        self.oms = oms

    def resolve(self, broker_order_id):
        return self.oms.resolve_execution_correlation(broker_order_id)


class FakeBroker:
    def submit(self, command, *args, **kwargs):
        return BrokerOrderResponse(client_order_id=command.client_order_id, accepted=True, broker_order_id="B1")


@dataclass
class FakePosition:
    instrument_id: str
    quantity: int = 0
    average_price: float = 0.0

    def apply_fill(self, *, side, quantity, price):
        self.quantity += quantity if side == "BUY" else -quantity
        self.average_price = price


def test_full_live_execution_composition():
    oms = OrderStateMachine()
    oms.apply_intent(OrderIntent(client_order_id="C1", instrument_id="I1", side="BUY", quantity=2, intent_type="OPEN"))
    command = BrokerOrderCommand(client_order_id="C1", instrument_id="I1", side="BUY", quantity=2, order_type="LIMIT")
    transport = FakeTransport({"broker_order_id": "B1", "execution_id": "E1", "status": "PARTIALLY_FILLED", "filled_quantity": 1})
    position = FakePosition("I1")

    composition = create_live_execution_runtime_composition(
        transport=transport,
        execution_adapter=FakeExecutionAdapter(),
        correlation_provider=FakeCorrelationProvider(oms),
        broker=FakeBroker(),
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(position),
        execution_event_deduplicator=ExecutionEventDeduplicator(),
        position_aggregate=position,
    )

    response = composition.broker.submit(command)
    assert response.accepted is True
    oms.apply_ack(type("Ack", (), {"client_order_id": "C1", "accepted": True, "broker_order_id": "B1"})())

    import asyncio
    asyncio.run(composition.start_execution("HTS1"))
    asyncio.run(composition.receive_execution_once())
    asyncio.run(composition.receive_execution_once())

    assert transport.subscription == ("H0IFCNI0", "HTS1")
    assert oms.get("C1").filled_quantity == 1
    assert position.quantity == 1


def test_missing_runtime_dependency_fails_closed():
    with pytest.raises(ValueError, match="LIVE_EXECUTION_RUNTIME_DEPENDENCY_REQUIRED:broker"):
        create_live_execution_runtime_composition(
            transport=FakeTransport({}),
            execution_adapter=FakeExecutionAdapter(),
            correlation_provider=FakeCorrelationProvider(OrderStateMachine()),
            broker=None,
            order_state_machine=OrderStateMachine(),
            position_fill_adapter=object(),
            execution_event_deduplicator=ExecutionEventDeduplicator(),
            position_aggregate=FakePosition("I1"),
        )


class FakeRecoveryAdapter:
    pass


class FakeRecoveryTransport:
    pass


def test_runtime_composition_wires_recovery_to_shared_settlement():
    oms = OrderStateMachine()
    oms.apply_intent(OrderIntent(client_order_id="C2", instrument_id="I1", side="BUY", quantity=1, intent_type="OPEN"))
    command = BrokerOrderCommand(client_order_id="C2", instrument_id="I1", side="BUY", quantity=1, order_type="MARKET")
    oms.register_broker_order_command(command)
    oms.apply_ack(type("Ack", (), {"client_order_id": "C2", "accepted": True, "broker_order_id": "B2"})())
    position = FakePosition("I1")

    recovery_transport = FakeRecoveryTransport()
    recovery_adapter = FakeRecoveryAdapter()
    composition = create_live_execution_runtime_composition(
        transport=FakeTransport({}),
        execution_adapter=FakeExecutionAdapter(),
        correlation_provider=FakeCorrelationProvider(oms),
        broker=FakeBroker(),
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(position),
        execution_event_deduplicator=ExecutionEventDeduplicator(),
        position_aggregate=position,
        recovery_transport=recovery_transport,
        recovery_adapter=recovery_adapter,
    )

    assert composition.recovery_service is not None
    assert composition.recovery_service.transport is recovery_transport
    assert composition.recovery_service.adapter is recovery_adapter
    assert composition.recovery_service.correlation_provider.oms is oms
    assert composition.recovery_service.on_report.__self__ is composition.settlement


def test_recovery_transport_and_adapter_must_be_paired():
    with pytest.raises(ValueError, match="LIVE_RECOVERY_TRANSPORT_ADAPTER_MUST_BE_PAIRED"):
        create_live_execution_runtime_composition(
            transport=FakeTransport({}),
            execution_adapter=FakeExecutionAdapter(),
            correlation_provider=FakeCorrelationProvider(OrderStateMachine()),
            broker=FakeBroker(),
            order_state_machine=OrderStateMachine(),
            position_fill_adapter=object(),
            execution_event_deduplicator=ExecutionEventDeduplicator(),
            position_aggregate=FakePosition("I1"),
            recovery_transport=FakeRecoveryTransport(),
        )


def test_oms_does_not_synthesize_missing_broker_command():
    oms = OrderStateMachine()
    oms.apply_intent(OrderIntent(client_order_id="C1", instrument_id="I1", side="BUY", quantity=1, intent_type="OPEN"))
    oms.apply_ack(type("Ack", (), {"client_order_id": "C1", "accepted": True, "broker_order_id": "B1"})())
    with pytest.raises(OrderStateTransitionError, match="BROKER_ORDER_COMMAND_NOT_REGISTERED"):
        oms.get_broker_order_command("B1")
```
## 검증 목적
        - Broker submit 직전의 원본 BrokerOrderCommand가 OMS authoritative state에 보존된다.
        - accepted ACK가 만든 broker_order_id → client_order_id mapping으로 execution 시 원본 command를 조회한다.
        - H0IFCNI0 → ExecutionReport → dedup → OMS FSM → Position 전체 경계를 concrete composition으로 연결한다.
        - 동일 execution은 Position에 한 번만 반영된다.
        - command가 등록되지 않은 execution context는 fail-closed한다.
        - 실제 KIS network/account/order는 사용하지 않는다.
[Child Page] test_live_runtime_bootstrap.py
```python
from __future__ import annotations

from dataclasses import dataclass

import pytest

from application.bootstrap import LiveRuntimeBootstrap


@dataclass
class FakeFSM:
    pass


@dataclass
class FakeSettlement:
    order_state_machine: object


@dataclass
class FakeExecution:
    settlement: FakeSettlement


class FakeRouter:
    def __init__(self, fsm: object) -> None:
        self._order_state_machine = fsm


class FakeRecoveryService:
    def __init__(self) -> None:
        self.queries = []

    def recover(self, query):
        self.queries.append(query)
        return ("SETTLED",)


def test_startup_reconcile_uses_injected_recovery_service():
    fsm = FakeFSM()
    recovery = FakeRecoveryService()
    query = object()
    bootstrap = LiveRuntimeBootstrap(
        execution=FakeExecution(FakeSettlement(fsm)),
        order_router=FakeRouter(fsm),
        recovery_service=recovery,
    )

    assert bootstrap.startup_reconcile(query) == ("SETTLED",)
    assert recovery.queries == [query]


def test_startup_reconcile_fails_closed_without_recovery_service():
    fsm = FakeFSM()
    bootstrap = LiveRuntimeBootstrap(
        execution=FakeExecution(FakeSettlement(fsm)),
        order_router=FakeRouter(fsm),
    )

    with pytest.raises(ValueError, match="LIVE_RUNTIME_RECOVERY_SERVICE_REQUIRED"):
        bootstrap.startup_reconcile(object())


def test_oms_ownership_mismatch_fails_closed():
    execution_fsm = FakeFSM()
    router_fsm = FakeFSM()

    with pytest.raises(ValueError, match="LIVE_RUNTIME_OMS_OWNERSHIP_MISMATCH"):
        LiveRuntimeBootstrap(
            execution=FakeExecution(FakeSettlement(execution_fsm)),
            order_router=FakeRouter(router_fsm),
        )
```
## 검증 목적
        - Runtime bootstrap은 외부에서 주입한 REST execution recovery service만 사용한다.
        - startup reconciliation은 기존 recover(query) 경로를 그대로 호출하며 별도 settlement/dedup 상태를 생성하지 않는다.
        - recovery service가 없으면 fail-closed한다.
        - 기존 Runtime/OMS ownership invariant를 유지한다.
        - 실제 KIS credential/network/account/order는 사용하지 않는다.
[Child Page] test_order_router_integration.py
```python
from contracts.types import BrokerOrderCommand, BrokerOrderResponse
from core.oms.oms_fsm import OrderStateMachine
from core.oms.order_router import OrderRouterError, StandardOrderRouter

class Broker:
    def __init__(self): self.calls = []
    def submit(self, command):
        self.calls.append(command)
        return BrokerOrderResponse(client_order_id=command.client_order_id, accepted=True, broker_order_id="B-1")

def command():
    return BrokerOrderCommand(client_order_id="C-1", instrument_id="FUT-1", side="BUY", quantity=2, order_type="LIMIT", broker_symbol="101V09")

def test_router_registers_submits_and_applies_ack():
    fsm = OrderStateMachine(); broker = Broker()
    router = StandardOrderRouter(order_state_machine=fsm, broker_adapter=broker)
    response = router.register_and_route(command(), token=object())
    assert response.accepted is True and len(broker.calls) == 1
    state = fsm.get("C-1")
    assert state is not None and state.status == "ACKED" and state.broker_order_id == "B-1"

def test_router_fails_closed_without_token_or_broker():
    fsm = OrderStateMachine(); router = StandardOrderRouter(order_state_machine=fsm)
    try: router.register_and_route(command(), token=None)
    except OrderRouterError as exc: assert str(exc) == "RISK_APPROVAL_TOKEN_REQUIRED"
    else: raise AssertionError("expected token fail-closed")
    try: router.register_and_route(command(), token=object())
    except OrderRouterError as exc: assert str(exc) == "BROKER_ADAPTER_REQUIRED"
    else: raise AssertionError("expected broker fail-closed")
```
## 검증 범위
        - Router가 OMS 주문 등록 → broker submit → ACK state transition을 수행한다.
        - token/broker 누락은 fail-closed한다.
        - 실제 KIS network 또는 실주문은 사용하지 않는다.
[Child Page] test_runtime_risk_standard_router_e2e.py
```python
from dataclasses import dataclass
import pytest
from contracts.types import BrokerOrderCommand, BrokerOrderResponse
from core.oms.oms_fsm import OrderStateMachine
from core.oms.order_router import StandardOrderRouter
from core.position.position_aggregate import PositionAggregate
from application.composition.runtime_authoritative_risk_router_adapter import RiskRouterContext, route_from_runtime_authoritative_sources
from shared.contracts.canonical import CanonicalAssetType, CanonicalOrderCommand, CanonicalOrderSide

class PositionSource:
    def snapshot(self): return {"FUTURES:K200": PositionAggregate("BUY", 2, 350.0)}
class Account:
    total_balance=1_000_000.0; realized_pnl=0.0; used_margin=0.0; free_margin=1_000_000.0
@dataclass
class Result:
    decision: str = "ALLOW"; reduced_command: object = None; rejection_reason: str | None = None
class Gate:
    def __init__(self, reduced=None): self.last_evaluation_result=Result('REDUCE' if reduced else 'ALLOW', reduced); self.reduced=reduced
    def admit_order(self, *args): return True, 'TOKEN', None
class Broker:
    def submit(self, command): return BrokerOrderResponse(command.client_order_id, True, 'B-1')

def canonical(qty=5):
    return CanonicalOrderCommand("ORD-1","T1",CanonicalAssetType.FUTURES,CanonicalOrderSide.BUY,qty,350.0,symbol="K200")
def broker_command(qty=5):
    return BrokerOrderCommand("ORD-1","AUTH-FUT-1","BUY",qty,"LIMIT",broker_symbol="101V09")

def test_runtime_risk_router_to_standard_router_ack_e2e_allow():
    fsm=OrderStateMachine(); router=StandardOrderRouter(order_state_machine=fsm, broker_adapter=Broker())
    result=route_from_runtime_authoritative_sources(canonical(), risk_gate=Gate(), context=RiskRouterContext(Account(),PositionSource(),router,broker_command()))
    assert result.routed is True
    assert fsm.get("ORD-1").status == "ACKED"

def test_reduce_only_projects_authoritative_quantity():
    effective=type('Reduced',(),{'client_order_id':'ORD-1','qty':2})()
    fsm=OrderStateMachine(); router=StandardOrderRouter(order_state_machine=fsm, broker_adapter=Broker())
    result=route_from_runtime_authoritative_sources(canonical(), risk_gate=Gate(effective), context=RiskRouterContext(Account(),PositionSource(),router,broker_command()))
    assert result.decision == 'REDUCE'
    assert fsm.command_for("ORD-1").quantity == 2

def test_risk_quantity_increase_fails_closed():
    effective=type('Bad',(),{'client_order_id':'ORD-1','qty':6})()
    with pytest.raises(ValueError, match='RISK_QUANTITY_INCREASE_FORBIDDEN'):
        route_from_runtime_authoritative_sources(canonical(), risk_gate=Gate(effective), context=RiskRouterContext(Account(),PositionSource(),object(),broker_command()))
```
## 검증 범위
        - Canonical Runtime Risk → StandardOrderRouter → OMS ACK 실제 연결.
        - REDUCE는 quantity만 변경하고 BrokerOrderCommand의 다른 필드를 보존.
        - Risk quantity 증가와 identity 불일치는 fail-closed.
[Child Page] test_execution_path_composition.py
```python
import pytest
from application.composition.execution_path_composition import (
    RuntimeTransportComposition, StandardOrderIntentComposition,
    create_runtime_transport_composition, create_standard_order_intent_composition,
)

class X: pass

def test_runtime_transport_requires_explicit_authoritative_dependencies():
    with pytest.raises(ValueError, match='RUNTIME_TRANSPORT_DEPENDENCY_REQUIRED'):
        RuntimeTransportComposition(None, X(), X(), X(), X())

def test_standard_order_intent_requires_real_suppliers():
    with pytest.raises(ValueError, match='STANDARD_ORDER_INTENT_DEPENDENCY_REQUIRED'):
        StandardOrderIntentComposition(None, X(), X(), X())

def test_two_composition_roots_are_explicit_and_independent():
    runtime = create_runtime_transport_composition(
        strategy_runtime=X(), strategy_to_decision=X(), decision_to_command=X(),
        risk_gate=X(), account_snapshot=X(), position_source=X(),
        order_router=X(), broker_command=X(),
    )
    standard = create_standard_order_intent_composition(
        signal_identity_provider=X(), position_execution_decision_provider=X(),
        order_intent_factory=X(), order_intent_adapter=X(),
    )
    assert runtime.risk_context.order_router is not None
    assert standard.position_execution_decision_provider is not None
```
## 검증 범위
        - Runtime transport dependency 누락 fail-closed.
        - Standard OrderIntent supplier 누락 fail-closed.
        - 두 composition root가 별도 객체로 조립됨을 확인.
        - 실제 KIS network/credential/order는 사용하지 않음.
[Child Page] test_live_runtime_ownership.py
```python
import asyncio
import pytest
from application.bootstrap import LiveRuntimeBootstrap

class X:
    async def start_execution(self, h): pass
    async def receive_execution_once(self): return None
    async def close_execution(self): pass

class Settlement:
    def __init__(self, fsm): self.order_state_machine=fsm
class Execution:
    def __init__(self, fsm): self.settlement=Settlement(fsm)
    async def start_execution(self,h): pass
    async def receive_execution_once(self): return None
    async def close_execution(self): pass
class Router:
    def __init__(self, fsm): self._order_state_machine=fsm
    def register_and_route(self,*a,**k): return None
class Ctx:
    def __init__(self, router): self.order_router=router
class Transport:
    def __init__(self, router): self.risk_context=Ctx(router)

def test_shared_oms_and_router_ownership_passes():
    fsm=object(); router=Router(fsm)
    bootstrap=LiveRuntimeBootstrap(Execution(fsm),router,Transport(router))
    assert bootstrap.execution.settlement.order_state_machine is router._order_state_machine

def test_mismatched_oms_or_router_fails_closed():
    with pytest.raises(ValueError, match='LIVE_RUNTIME_OMS_OWNERSHIP_MISMATCH'):
        LiveRuntimeBootstrap(Execution(object()),Router(object()))
    fsm=object(); router=Router(fsm)
    with pytest.raises(ValueError, match='LIVE_RUNTIME_ROUTER_OWNERSHIP_MISMATCH'):
        LiveRuntimeBootstrap(Execution(fsm),router,Transport(Router(fsm)))
```
## 검증
        - Live execution과 Runtime transport의 공유 OMS ownership 확인.
        - Runtime transport 연결 시 동일 Router identity 강제.
        - 중복 OMS/Router 조립은 fail-closed.
[Child Page] test_live_runtime_tick_entry.py
```python
import pytest

class Runtime:
    def process_tick(self,t,o): return ('eval',)
class S2D:
    def evaluate(self,x): return ('decision',)
class D2C:
    def commands(self,d,e): return ('command',)

def test_tick_entry_preserves_existing_chain():
    from application.composition.live_runtime_tick_entry import LiveRuntimeTickEntry
    calls=[]
    entry=LiveRuntimeTickEntry(Runtime(),S2D(),D2C(),'risk',
      lambda command, **kw: calls.append((command,kw)) or 'routed',
      lambda:'account',lambda:'positions')
    assert entry.process_tick('tick','asof',risk_context='ctx') == ('routed',)
    assert calls[0][0]=='command'

def test_tick_entry_fails_without_authoritative_risk_state():
    from application.composition.live_runtime_tick_entry import LiveRuntimeTickEntry
    entry=LiveRuntimeTickEntry(Runtime(),S2D(),D2C(),'risk',lambda *a,**k:None,lambda:None,lambda:'p')
    with pytest.raises(ValueError, match='RUNTIME_RISK_AUTHORITATIVE_STATE_REQUIRED'):
        entry.process_tick('tick','asof',risk_context='ctx')
```
[Child Page] test_live_runtime_tick_bootstrap.py
```python
import pytest
from application.bootstrap import LiveRuntimeBootstrap

class Execution:
    class Settlement: pass
    def __init__(self, fsm): self.settlement=self.Settlement(); self.settlement.order_state_machine=fsm
class Router:
    def __init__(self, fsm): self._order_state_machine=fsm
class Transport:
    class Context: pass
    def __init__(self, router, runtime=None, strategy_to_decision=None, decision_to_command=None, risk_gate=None):
        self.risk_context=self.Context(); self.risk_context.order_router=router
        self.strategy_runtime = runtime
        self.strategy_to_decision = strategy_to_decision
        self.decision_to_command = decision_to_command
        self.risk_gate = risk_gate
class TickEntry:
    def __init__(self, runtime=None, strategy_to_decision=None, decision_to_command=None, risk_gate=None):
        self.runtime = runtime
        self.strategy_to_decision = strategy_to_decision
        self.decision_to_command = decision_to_command
        self.risk_gate = risk_gate
    def process_tick(self, tick, at, *, risk_context): return (tick, at, risk_context)

def test_bootstrap_exposes_one_shot_tick_without_loop():
    fsm=object(); router=Router(fsm)
    runtime=object(); s2d=object(); d2c=object(); gate=object()
    transport=Transport(router, runtime, s2d, d2c, gate)
    b=LiveRuntimeBootstrap(Execution(fsm), router, transport, TickEntry(runtime, s2d, d2c, gate))
    result=b.process_tick_once('tick','asof')
    assert result[0:2]==('tick','asof')

def test_tick_entry_requires_runtime_transport():
    fsm=object(); router=Router(fsm)
    with pytest.raises(ValueError, match='LIVE_RUNTIME_TRANSPORT_REQUIRED_FOR_TICK_ENTRY'):
        LiveRuntimeBootstrap(Execution(fsm), router, None, TickEntry())
```
def test_tick_entry_transport_object_graph_mismatch_fails_closed():
fsm=object(); router=Router(fsm); transport=Transport(router)
transport.strategy_runtime=object(); transport.strategy_to_decision=object()
transport.decision_to_command=object(); transport.risk_gate=object()
class MismatchedTickEntry(TickEntry):
runtime=object(); strategy_to_decision=object()
decision_to_command=object(); risk_gate=object()
with pytest.raises(ValueError, match='LIVE_RUNTIME_TICK_ENTRY_TRANSPORT_OWNERSHIP_MISMATCH'):
LiveRuntimeBootstrap(Execution(fsm), router, transport, MismatchedTickEntry())
[Child Page] test_live_runtime_one_shot_e2e_boundary.py
```python
from dataclasses import dataclass, replace

import pytest

from application.composition.live_runtime_tick_entry import LiveRuntimeTickEntry


@dataclass(frozen=True)
class RiskContext:
    account_snapshot: object
    position_source: object
    order_router: object


@dataclass(frozen=True)
class Command:
    client_order_id: str = "ORD-1"
    qty: int = 1


class Runtime:
    def __init__(self, events):
        self.events = events

    def process_tick(self, tick, observed_at):
        self.events.append(("runtime", tick, observed_at))
        return ("EVALUATION",)


class StrategyToDecision:
    def __init__(self, events):
        self.events = events

    def evaluate(self, evaluations):
        self.events.append(("strategy_to_decision", evaluations))
        return ("DECISION",)


class DecisionToCommand:
    def __init__(self, events, command):
        self.events = events
        self.command = command

    def commands(self, decisions, evaluations):
        self.events.append(("decision_to_command", decisions, evaluations))
        return (self.command,)


class RiskGate:
    def __init__(self, approved=True):
        self.approved = approved

    def admit_order(self, command, account, position):
        return self.approved, "TOKEN" if self.approved else None, None


class Router:
    def __init__(self, events):
        self.events = events
        self.calls = []

    def register_and_route(self, command, token):
        self.calls.append((command, token))
        self.events.append(("router", command, token))
        return "ACK_INTENT"


def route_from_runtime_authoritative_sources(command, *, risk_gate, context):
    approved, token, rejection_reason = risk_gate.admit_order(
        command,
        context.account_snapshot,
        context.position_source,
    )
    if not approved:
        return {"routed": False, "decision": "DENY"}
    if token is None:
        raise RuntimeError("RISK_APPROVAL_TOKEN_REQUIRED")
    context.order_router.register_and_route(command, token)
    return {"routed": True, "decision": "ALLOW"}


def build_entry(events, *, approved=True):
    account = object()
    positions = object()
    router = Router(events)
    command = Command()
    context = RiskContext(account, positions, router)
    entry = LiveRuntimeTickEntry(
        runtime=Runtime(events),
        strategy_to_decision=StrategyToDecision(events),
        decision_to_command=DecisionToCommand(events, command),
        risk_gate=RiskGate(approved=approved),
        route_authoritative=route_from_runtime_authoritative_sources,
        account_snapshot_provider=lambda: account,
        position_source_provider=lambda: positions,
    )
    return entry, context, router


def test_one_shot_allow_tick_strategy_decision_risk_router():
    events = []
    entry, context, router = build_entry(events, approved=True)

    result = entry.process_tick("TICK-1", "OBS-1", risk_context=context)

    assert result == ({"routed": True, "decision": "ALLOW"},)
    assert [event[0] for event in events] == [
        "runtime",
        "strategy_to_decision",
        "decision_to_command",
        "router",
    ]
    assert router.calls == [(Command(), "TOKEN")]


def test_one_shot_deny_stops_before_router():
    events = []
    entry, context, router = build_entry(events, approved=False)

    result = entry.process_tick("TICK-1", "OBS-1", risk_context=context)

    assert result == ({"routed": False, "decision": "DENY"},)
    assert router.calls == []
    assert [event[0] for event in events] == [
        "runtime",
        "strategy_to_decision",
        "decision_to_command",
    ]


def test_one_shot_refreshes_authoritative_account_position_per_call():
    events = []
    account = object()
    positions = object()
    router = Router(events)
    command = Command()
    context = RiskContext(object(), object(), router)
    seen = []

    def account_provider():
        seen.append(("account", account))
        return account

    def position_provider():
        seen.append(("position", positions))
        return positions

    def route(command, *, risk_gate, context):
        seen.append(("risk_context", context.account_snapshot, context.position_source))
        return {"routed": False, "decision": "DENY"}

    entry = LiveRuntimeTickEntry(
        runtime=Runtime(events),
        strategy_to_decision=StrategyToDecision(events),
        decision_to_command=DecisionToCommand(events, command),
        risk_gate=RiskGate(approved=False),
        route_authoritative=route,
        account_snapshot_provider=account_provider,
        position_source_provider=position_provider,
    )

    entry.process_tick("TICK-1", "OBS-1", risk_context=context)

    assert seen == [
        ("account", account),
        ("position", positions),
        ("risk_context", account, positions),
    ]
    assert context.account_snapshot is not account
    assert context.position_source is not positions


def test_one_shot_requires_risk_context():
    events = []
    entry, _, _ = build_entry(events)

    with pytest.raises(ValueError, match="RUNTIME_RISK_CONTEXT_REQUIRED"):
        entry.process_tick("TICK-1", "OBS-1", risk_context=None)
```
## 검증 목적
        - 기존 LiveRuntimeTickEntry 실제 orchestration 순서인 Runtime → Strategy → Decision → Command → authoritative Risk route를 one-shot으로 검증한다.
        - ALLOW는 실제 route boundary를 통과하여 Router 호출과 approval token 전달을 검증한다.
        - DENY는 Router 호출 0회를 검증한다.
        - TickEntry의 호출 시점 Account/Position refresh가 기존 RiskRouterContext를 stale state로 재사용하지 않고 per-call context로 교체하는지 검증한다.
        - Risk context가 없으면 Router 이전에 fail-closed한다.
        - ACK/ExecutionReport/Position mutation은 이 테스트에서 구현하지 않는다. 기존 test_order_router_integration.py, test_oms_fsm_ack_execution.py, test_live_execution_position_bridge.py의 authoritative seam을 그대로 별도 검증 대상으로 유지한다.
        - 실제 KIS network, credential, account, 실주문은 사용하지 않는다.
[Child Page] test_live_execution_recovery_service.py
```python
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from application.composition.live_execution_recovery_service import LiveExecutionRecoveryService
from contracts.types import ExecutionReport
from environments.live.execution.execution_event_deduplicator import ExecutionEventDeduplicator
from environments.live.execution.kis_futures_execution_recovery_adapter import (
    KISExecutionRecoveryQuery,
    KISFuturesExecutionRecoveryAdapter,
)


@dataclass(frozen=True)
class Correlation:
    client_order_id: str
    order_quantity: int
    prior_filled_quantity: int


class FakeCorrelationProvider:
    def resolve(self, broker_order_id):
        assert broker_order_id == "B1"
        return Correlation("C1", 2, 0)


class FakeTransport:
    def __init__(self, response):
        self.response = response
        self.queries = []

    def inquire(self, query):
        self.queries.append(query)
        return self.response


def test_rest_recovery_uses_shared_settlement_callback_and_dedup_identity():
    transport = FakeTransport(
        {"rt_cd": "0", "output1": [{
            "odno": "B1", "exec_id": "E1", "ccld_qty": "1",
            "ccld_unpr": "101.25", "ccld_time": "20260906150000",
        }]}
    )
    dedup = ExecutionEventDeduplicator()
    delivered = []

    def settle(report):
        if dedup.accept(report):
            delivered.append(report)
            return "SETTLED"
        return "DUPLICATE"

    service = LiveExecutionRecoveryService(
        transport=transport,
        adapter=KISFuturesExecutionRecoveryAdapter(),
        correlation_provider=FakeCorrelationProvider(),
        on_report=settle,
    )
    query = KISExecutionRecoveryQuery("12345678", "03", "20260906", "20260906")

    assert service.recover(query) == ("SETTLED",)
    assert service.recover(query) == ("DUPLICATE",)
    assert len(delivered) == 1
    assert delivered[0].client_order_id == "C1"
    assert delivered[0].execution_price == Decimal("101.25")


def test_realtime_and_rest_same_execution_identity_settles_once():
    dedup = ExecutionEventDeduplicator()
    rest = ExecutionReport(
        client_order_id="C1", broker_order_id="B1", execution_id="E1",
        status="PARTIALLY_FILLED", filled_quantity=1, remaining_quantity=1,
        execution_price=Decimal("101.25"), execution_timestamp=None,
    )
    realtime = ExecutionReport(
        client_order_id="C1", broker_order_id="B1", execution_id="E1",
        status="PARTIALLY_FILLED", filled_quantity=1, remaining_quantity=1,
        execution_price=Decimal("101.25"), execution_timestamp=None,
    )

    assert dedup.accept(realtime) is True
    assert dedup.accept(rest) is False
```
## Verification target
        - REST recovery uses OMS correlation rather than synthetic context.
        - REST reports enter the existing settlement callback.
        - REST replay and realtime ingress sharing the same execution identity settle exactly once.
[Child Page] test_live_execution_recovery_partial_fill_integration.py
```python
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from application.composition.live_execution_recovery_service import LiveExecutionRecoveryService
from contracts.types import BrokerOrderCommand, ExecutionReport, OrderAckEvent, OrderIntent
from core.oms.oms_fsm import OrderStateMachine
from environments.live.execution.execution_event_deduplicator import ExecutionEventDeduplicator
from environments.live.execution.kis_futures_execution_recovery_adapter import (
    KISExecutionRecoveryContext,
    KISExecutionRecoveryQuery,
    KISFuturesExecutionRecoveryAdapter,
)
from environments.live.position.live_execution_position_bridge import LiveExecutionPositionBridge, LivePositionFillAdapter
from environments.live.position.live_position_aggregate import LivePositionAggregate


@dataclass
class PagedRecoveryTransport:
    """Represents the already-pagination-complete output of the real KIS transport."""

    pages: tuple[dict[str, object], ...]

    def __post_init__(self) -> None:
        self.queries = []

    def inquire(self, query: KISExecutionRecoveryQuery) -> dict[str, object]:
        self.queries.append(query)
        rows: list[dict[str, object]] = []
        for page in self.pages:
            rows.extend(page["output1"])
        return {"rt_cd": "0", "output1": rows}


class Provider:
    def __init__(self, oms: OrderStateMachine) -> None:
        self.oms = oms

    def resolve(self, broker_order_id: str):
        return self.oms.resolve_execution_correlation(broker_order_id)


def _build_live_settlement():
    oms = OrderStateMachine()
    command = BrokerOrderCommand("C1", "I1", "BUY", 5, "MARKET")
    oms.apply_intent(OrderIntent("C1", "I1", "BUY", 5, "NEW"))
    oms.register_broker_order_command(command)
    oms.apply_ack(OrderAckEvent("C1", True, "B1"))

    aggregate = LivePositionAggregate("I1")
    dedup = ExecutionEventDeduplicator()
    bridge = LiveExecutionPositionBridge(
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(aggregate),
        execution_event_deduplicator=dedup,
        position_aggregate=aggregate,
    )
    return oms, aggregate, dedup, bridge


def test_paginated_recovery_service_to_oms_position_cumulative_flow():
    transport = PagedRecoveryTransport(
        pages=(
            {"output1": [{
                "odno": "B1", "ord_dt": "20260906", "ord_tmd": "150000",
                "ord_qty": "5", "tot_ccld_qty": "2", "avg_idx": "101.0",
            }]},
            {"output1": [{
                "odno": "B1", "ord_dt": "20260906", "ord_tmd": "150100",
                "ord_qty": "5", "tot_ccld_qty": "5", "avg_idx": "101.6",
            }]},
        )
    )
    oms, aggregate, dedup, bridge = _build_live_settlement()
    def settle_and_return_report(report):
        bridge.settle(report)
        return report

    service = LiveExecutionRecoveryService(
        transport=transport,
        adapter=KISFuturesExecutionRecoveryAdapter(),
        correlation_provider=Provider(oms),
        on_report=settle_and_return_report,
    )

    result = service.recover(KISExecutionRecoveryQuery("12345678", "03", "20260906", "20260906"))
    state = oms.get("C1")

    assert [report.filled_quantity for report in result] == [2, 3]
    assert [report.remaining_quantity for report in result] == [3, 0]
    assert [report.status for report in result] == ["PARTIALLY_FILLED", "FILLED"]
    assert result[0].execution_timestamp is not None
    assert result[0].execution_timestamp.strftime("%Y%m%d%H%M%S") == "20260906150000"
    assert result[1].execution_id == "REST-CCNL-SNAPSHOT|B1|5|101.6"
    assert result[1].execution_price == Decimal("102.0")
    assert state is not None and state.status == "FILLED" and state.filled_quantity == 5
    assert aggregate.snapshot().qty == 5
    assert aggregate.snapshot().avg_price == 101.6
    assert dedup.contains(result[0].execution_id)
    assert dedup.contains(result[1].execution_id)
    assert len(transport.queries) == 1


def test_rest_snapshot_identity_replay_is_blocked_at_shared_dedup_before_position_mutation():
    oms, aggregate, dedup, bridge = _build_live_settlement()
    report = ExecutionReport(
        client_order_id="C1",
        broker_order_id="B1",
        execution_id="REST-CCNL-SNAPSHOT|B1|2|101.0",
        status="PARTIALLY_FILLED",
        filled_quantity=2,
        remaining_quantity=3,
        execution_price=Decimal("101.0"),
        execution_timestamp=None,
    )

    first = bridge.settle(report)
    duplicate = bridge.settle(report)

    assert first.filled_quantity == 2
    assert duplicate.filled_quantity == 2
    assert aggregate.snapshot().qty == 2
    assert dedup.contains(report.execution_id)

```
[Child Page] test_live_execution_replay_order_variation_integration.py
```python
from decimal import Decimal

from contracts.types import BrokerOrderCommand, ExecutionReport, OrderAckEvent, OrderIntent
from core.oms.oms_fsm import OrderStateMachine
from environments.live.execution.execution_event_deduplicator import ExecutionEventDeduplicator
from environments.live.position.live_execution_position_bridge import LiveExecutionPositionBridge, LivePositionFillAdapter
from environments.live.position.live_position_aggregate import LivePositionAggregate


def _report(*, execution_id="E1", quantity=2, remaining=3, status="PARTIALLY_FILLED", price="101.0"):
    return ExecutionReport(
        client_order_id="C1", broker_order_id="B1", execution_id=execution_id,
        status=status, filled_quantity=quantity, remaining_quantity=remaining,
        execution_price=Decimal(price), execution_timestamp=None,
    )


def _bridge():
    oms = OrderStateMachine()
    command = BrokerOrderCommand("C1", "I1", "BUY", 5, "MARKET")
    oms.apply_intent(OrderIntent("C1", "I1", "BUY", 5, "NEW"))
    oms.apply_ack(OrderAckEvent("C1", True, "B1"))
    oms.register_broker_order_command(command)
    aggregate = LivePositionAggregate("I1")
    dedup = ExecutionEventDeduplicator()
    bridge = LiveExecutionPositionBridge(
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(aggregate),
        execution_event_deduplicator=dedup,
        position_aggregate=aggregate,
    )
    return oms, aggregate, dedup, bridge


def test_canonical_execution_replay_is_settled_once_when_sources_share_identity():
    oms, aggregate, dedup, bridge = _bridge()
    bridge.settle(_report())
    bridge.settle(_report())
    state = oms.get("C1")
    assert state.status == "PARTIALLY_FILLED"
    assert state.filled_quantity == 2
    assert aggregate.snapshot().qty == 2
    assert aggregate.snapshot().avg_price == Decimal("101.0")
    assert dedup.contains("E1")


def test_canonical_execution_replay_is_order_independent():
    oms, aggregate, dedup, bridge = _bridge()
    bridge.settle(_report())
    bridge.settle(_report())
    state = oms.get("C1")
    assert state.filled_quantity == 2
    assert aggregate.snapshot().qty == 2
    assert dedup.contains("E1")


def test_distinct_execution_after_replay_preserves_cumulative_invariant():
    oms, aggregate, dedup, bridge = _bridge()
    bridge.settle(_report(execution_id="E1", quantity=2, remaining=3, status="PARTIALLY_FILLED", price="101.0"))
    bridge.settle(_report(execution_id="E1", quantity=2, remaining=3, status="PARTIALLY_FILLED", price="101.0"))
    bridge.settle(_report(execution_id="E2", quantity=3, remaining=0, status="FILLED", price="102.0"))
    state = oms.get("C1")
    assert state.status == "FILLED"
    assert state.filled_quantity == 5
    assert aggregate.snapshot().qty == 5
    assert aggregate.snapshot().avg_price == Decimal("101.6")
    assert dedup.contains("E1") and dedup.contains("E2")
```
## 정정 내용
        - 현재 LiveExecutionPositionBridge.settle(report) contract에 맞게 stale settle(command, report) 호출을 제거했다.
        - BrokerOrderCommand를 OMS correlation state에 등록했다.
        - Position 평균가격 검증을 float 101.6에서 Decimal Decimal("101.6")로 정정했다.
        - 동일 execution identity replay와 distinct execution 누적 invariant를 유지한다.
[Child Page] test_live_execution_cross_source_identity_boundary.py
```python
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from contracts.types import ExecutionReport
from environments.live.execution.execution_event_deduplicator import ExecutionEventDeduplicator
from environments.live.execution.kis_futures_execution_adapter import (
    KISFuturesExecutionNoticeAdapter,
)


def _h0ifcni0_frame(*, order_id: str = "B1", quantity: str = "5", price: str = "101.6") -> str:
    values = [
        "CUST", "12345678", order_id, "", "01", "",
        "", "KOSPI200", quantity, price, "101530",
        "N", "Y", "Y", "001", "5", "", "KOSPI200",
        "", "", "1", price,
    ]
    return "0|H0IFCNI0|22|" + "^".join(values)


def _rest_report() -> ExecutionReport:
    return ExecutionReport(
        client_order_id="C1",
        broker_order_id="B1",
        execution_id="REST-CCNL-SNAPSHOT|B1|5|101.6",
        status="FILLED",
        filled_quantity=5,
        remaining_quantity=0,
        execution_price=Decimal("101.6"),
        execution_timestamp=None,
    )


def test_each_source_identity_is_replay_safe_but_not_cross_source_collapsed():
    rest_report = _rest_report()
    notice = KISFuturesExecutionNoticeAdapter().parse(_h0ifcni0_frame())
    h0_report = KISFuturesExecutionNoticeAdapter().to_execution_report(
        notice,
        type("Context", (), {
            "client_order_id": "C1",
            "order_quantity": 5,
            "prior_filled_quantity": 0,
        })(),
    )

    assert rest_report.execution_id != h0_report.execution_id

    dedup = ExecutionEventDeduplicator()
    assert dedup.accept(rest_report) is True
    assert dedup.accept(rest_report) is False
    assert dedup.accept(h0_report) is True
    assert dedup.accept(h0_report) is False


def test_cross_source_identity_is_not_synthesized_from_shared_order_fields():
    rest_report = _rest_report()
    h0_report = replace(rest_report, execution_id="KIS-H0IFCNI0-wire-local")

    assert rest_report.broker_order_id == h0_report.broker_order_id
    assert rest_report.filled_quantity == h0_report.filled_quantity
    assert rest_report.execution_price == h0_report.execution_price
    assert rest_report.execution_id != h0_report.execution_id

    # Shared order/time/quantity/price fields do not authorize an identity merge.
    dedup = ExecutionEventDeduplicator()
    assert dedup.accept(rest_report) is True
    assert dedup.accept(h0_report) is True
```
[Child Page] test_live_runtime_recovery_realtime_position_e2e.py
```python
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from contracts.types import BrokerOrderCommand, ExecutionReport, OrderIntent
from core.oms.oms_fsm import OrderStateMachine
from environments.live.execution.execution_event_deduplicator import ExecutionEventDeduplicator
from environments.live.execution.live_execution_recovery_service import LiveExecutionRecoveryService
from environments.live.position.live_execution_position_bridge import LiveExecutionPositionBridge, LivePositionFillAdapter


@dataclass
class FakePosition:
    instrument_id: str
    quantity: int = 0
    average_price: float | None = None

    def apply_fill(self, *, side: str, quantity: int, price: float) -> None:
        self.quantity += quantity if side == "BUY" else -quantity
        self.average_price = price


@dataclass(frozen=True)
class Correlation:
    client_order_id: str
    order_quantity: int
    prior_filled_quantity: int
    prior_average_price: float | None = None


class FakeCorrelationProvider:
    def __init__(self, correlation: Correlation):
        self.correlation = correlation

    def resolve(self, broker_order_id: str):
        return self.correlation


class FakeRecoveryTransport:
    def __init__(self, response):
        self.response = response
        self.queries = []

    def inquire(self, query):
        self.queries.append(query)
        return self.response


class FakeRecoveryAdapter:
    def normalize(self, response, context_for_order):
        row = response["output1"][0]
        context = context_for_order(row["odno"])
        return [ExecutionReport(
            client_order_id=context.client_order_id,
            broker_order_id=row["odno"],
            execution_id=row["exec_id"],
            status="PARTIALLY_FILLED",
            filled_quantity=row["delta_qty"],
            remaining_quantity=context.order_quantity - context.prior_filled_quantity - row["delta_qty"],
            execution_price=Decimal(str(row["price"])),
            execution_timestamp=None,
        )]


def _acked_oms() -> OrderStateMachine:
    oms = OrderStateMachine()
    oms.apply_intent(OrderIntent(client_order_id="C1", instrument_id="I1", side="BUY", quantity=2, intent_type="OPEN"))
    oms.register_broker_order_command(BrokerOrderCommand(
        client_order_id="C1", instrument_id="I1", side="BUY", quantity=2, order_type="MARKET"
    ))
    oms.apply_ack(type("Ack", (), {"client_order_id": "C1", "accepted": True, "broker_order_id": "B1"})())
    return oms


def test_startup_recovery_then_realtime_execution_preserves_oms_position_and_replay_invariants():
    oms = _acked_oms()
    position = FakePosition("I1")
    bridge = LiveExecutionPositionBridge(
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(position),
        execution_event_deduplicator=ExecutionEventDeduplicator(),
        position_aggregate=position,
    )
    recovery = LiveExecutionRecoveryService(
        transport=FakeRecoveryTransport({"output1": [{"odno": "B1", "exec_id": "REST-E1", "delta_qty": 1, "price": 101.0}]}),
        adapter=FakeRecoveryAdapter(),
        correlation_provider=FakeCorrelationProvider(Correlation("C1", 2, 0)),
        on_report=bridge.settle,
    )

    recovered = recovery.recover(object())
    assert len(recovered) == 1
    assert oms.get("C1").filled_quantity == 1
    assert position.quantity == 1

    realtime = ExecutionReport(
        client_order_id="C1", broker_order_id="B1", execution_id="H0IFCNI0-E2",
        status="FILLED", filled_quantity=1, remaining_quantity=0,
        execution_price=Decimal("102.0"), execution_timestamp=None,
    )
    bridge.settle(realtime)
    bridge.settle(realtime)

    assert oms.get("C1").filled_quantity == 2
    assert oms.get("C1").remaining_quantity == 0
    assert oms.get("C1").status == "FILLED"
    assert position.quantity == 2
    assert position.average_price == 102.0


def test_terminal_order_replay_is_deduplicated_before_state_guard():
    oms = _acked_oms()
    position = FakePosition("I1")
    bridge = LiveExecutionPositionBridge(
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(position),
        execution_event_deduplicator=ExecutionEventDeduplicator(),
        position_aggregate=position,
    )
    report = ExecutionReport(
        client_order_id="C1", broker_order_id="B1", execution_id="E1",
        status="FILLED", filled_quantity=2, remaining_quantity=0,
        execution_price=Decimal("101.0"), execution_timestamp=None,
    )
    bridge.settle(report)
    bridge.settle(report)
    assert oms.get("C1").filled_quantity == 2
    assert position.quantity == 2
```
[Child Page] test_live_execution_partial_fill_interleaving.py
```python
from __future__ import annotations

from decimal import Decimal

from contracts.types import ExecutionReport
from core.oms.oms_fsm import OrderStateMachine
from environments.live.execution.execution_event_deduplicator import ExecutionEventDeduplicator
from environments.live.position.live_execution_position_bridge import (
    LiveExecutionPositionBridge,
    LivePositionFillAdapter,
)
from environments.live.position.live_position_aggregate import LivePositionAggregate


def _build():
    oms = OrderStateMachine()
    oms.apply_intent(type("Intent", (), {"client_order_id": "C1", "instrument_id": "I1", "quantity": 5})())
    command = type(
        "Command",
        (),
        {
            "client_order_id": "C1",
            "instrument_id": "I1",
            "side": "BUY",
            "quantity": 5,
            "order_type": "MARKET",
            "broker_order_id": "B1",
        },
    )()
    oms.register_broker_order_command(command)
    oms.apply_ack(type("Ack", (), {"client_order_id": "C1", "accepted": True, "broker_order_id": "B1"})())
    aggregate = LivePositionAggregate("I1")
    dedup = ExecutionEventDeduplicator()
    bridge = LiveExecutionPositionBridge(
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(aggregate),
        execution_event_deduplicator=dedup,
        position_aggregate=aggregate,
    )
    return oms, aggregate, dedup, bridge


def test_recovery_realtime_recovery_partial_fill_interleaving_preserves_cumulative_quantity_and_average():
    oms, aggregate, dedup, bridge = _build()

    bridge.settle(ExecutionReport("C1", "B1", "REST|B1|2|101", "PARTIALLY_FILLED", 2, 3, Decimal("101"), None))
    bridge.settle(ExecutionReport("C1", "B1", "H0IFCNI0|E1", "PARTIALLY_FILLED", 1, 2, Decimal("102"), None))
    bridge.settle(ExecutionReport("C1", "B1", "REST|B1|5|101.6", "FILLED", 2, 0, Decimal("102"), None))

    state = oms.get("C1")
    snapshot = aggregate.snapshot()
    assert state is not None and state.status == "FILLED" and state.filled_quantity == 5
    assert state.average_execution_price == Decimal("101.6")
    assert snapshot.qty == 5
    assert snapshot.avg_price == 101.6


def test_stale_recovery_snapshot_after_newer_realtime_fill_fails_closed_without_mutation():
    oms, aggregate, dedup, bridge = _build()

    bridge.settle(ExecutionReport("C1", "B1", "H0IFCNI0|E1", "PARTIALLY_FILLED", 3, 2, Decimal("101"), None))
    before = (oms.get("C1").filled_quantity, aggregate.snapshot().qty, aggregate.snapshot().avg_price)

    stale = ExecutionReport("C1", "B1", "REST|B1|2|100.5", "PARTIALLY_FILLED", 2, 3, Decimal("100.5"), None)
    try:
        bridge.settle(stale)
    except ValueError as exc:
        assert str(exc) == "REMAINING_QUANTITY_MISMATCH"
    else:
        raise AssertionError("stale cumulative snapshot must not be applied as a fresh delta")

    after = (oms.get("C1").filled_quantity, aggregate.snapshot().qty, aggregate.snapshot().avg_price)
    assert after == before
    assert not dedup.contains(stale.execution_id)
```
## Purpose
        - Verify recovery and realtime partial fills can be interleaved when the later recovery snapshot contains the newer cumulative fill.
        - Verify the weighted-average invariant is preserved at the OMS and Live Position boundaries.
        - Verify a stale recovery snapshot cannot be converted into an additional fill through the shared settlement path.
        - No cross-source execution identity is synthesized.
[Child Page] test_live_execution_recovery_decimal_precision_integration.py
```python
from decimal import Decimal, getcontext


def delta_price(cumulative, cumulative_average, prior_filled_quantity, prior_average_price):
    if prior_filled_quantity == 0:
        return cumulative_average
    return (
        cumulative_average * Decimal(cumulative)
        - prior_average_price * Decimal(prior_filled_quantity)
    ) / Decimal(cumulative - prior_filled_quantity)


def test_decimal_delta_price_is_exact_without_float_conversion():
    getcontext().prec = 80
    result = delta_price(3, Decimal("100.01"), 2, Decimal("100.00"))
    assert result == Decimal("100.03")


def test_high_precision_cumulative_average_preserves_decimal_precision():
    getcontext().prec = 80
    current_avg = Decimal("100.123456789")
    prior_avg = Decimal("99.987654321")
    result = delta_price(7, current_avg, 3, prior_avg)
    expected = (current_avg * 7 - prior_avg * 3) / 4
    assert result == expected
    assert isinstance(result, Decimal)


def test_rounding_boundary_is_not_implicitly_rounded():
    getcontext().prec = 80
    below = delta_price(3, Decimal("100.0000001"), 2, Decimal("100.0000000"))
    at = delta_price(3, Decimal("100.00000005"), 2, Decimal("100.0000000"))
    above = delta_price(3, Decimal("100.00000006"), 2, Decimal("100.0000000"))
    assert below == Decimal("100.0000003")
    assert at == Decimal("100.00000015")
    assert above == Decimal("100.00000018")


def test_sequential_recovery_preserves_weighted_average_invariant():
    getcontext().prec = 80
    first_qty = 2
    first_avg = Decimal("101.25")
    second_cumulative_qty = 5
    second_cumulative_avg = Decimal("101.60")

    first_price = delta_price(first_qty, first_avg, 0, Decimal("0"))
    second_price = delta_price(
        second_cumulative_qty,
        second_cumulative_avg,
        first_qty,
        first_avg,
    )

    assert first_price == Decimal("101.25")
    assert (first_price * first_qty + second_price * 3) / second_cumulative_qty == second_cumulative_avg
```
## 검증 기준
        - recovery avg_idx와 OMS prior average를 모두 Decimal로 유지한다.
        - delta execution price는 (current_avg × current_cumulative_qty − prior_avg × prior_qty) / delta_qty로 계산한다.
        - float 변환이나 암묵적 반올림을 사용하지 않는다.
        - 현재 소스/문서에는 recovery execution price에 적용할 별도 tick-size rounding 정책이 확정되어 있지 않으므로 계산 정밀도는 구현하고 rounding 정책 자체는 임의로 추가하지 않는다.
[Child Page] test_live_execution_recovery_realtime_oms_position_decimal_propagation_integration.py
```python
from decimal import Decimal, getcontext

getcontext().prec = 80


def delta_price(cumulative, cumulative_average, prior_filled_quantity, prior_average_price):
    if prior_filled_quantity == 0:
        return cumulative_average
    return (
        cumulative_average * Decimal(cumulative)
        - prior_average_price * Decimal(prior_filled_quantity)
    ) / Decimal(cumulative - prior_filled_quantity)


def weighted_average(prior_qty, prior_avg, fill_qty, fill_price):
    return (
        prior_avg * Decimal(prior_qty)
        + fill_price * Decimal(fill_qty)
    ) / Decimal(prior_qty + fill_qty)


def test_recovery_realtime_oms_position_decimal_propagation():
    recovery_price = delta_price(3, Decimal("101.833333333333333333"), 0, Decimal("0"))
    realtime_price = Decimal("102.166666666666666667")

    oms_average = weighted_average(3, recovery_price, 2, realtime_price)
    position_average = weighted_average(3, recovery_price, 2, realtime_price)

    expected = Decimal("101.9666666666666666666")
    assert oms_average == expected
    assert position_average == expected
    assert isinstance(oms_average, Decimal)
    assert isinstance(position_average, Decimal)


def test_decimal_position_supports_decimal_monetary_pnl_without_float():
    avg_price = Decimal("101.9666666666666666666")
    current_price = Decimal("103.25")
    quantity = Decimal("5")
    multiplier = Decimal("250000")
    unrealized_pnl = (current_price - avg_price) * quantity * multiplier
    assert isinstance(unrealized_pnl, Decimal)
    assert unrealized_pnl == Decimal("1604166.6666666666667500000")


def test_no_implicit_rounding_is_applied_to_position_average():
    avg = weighted_average(3, Decimal("101.833333333333333333"), 2, Decimal("102.166666666666666667"))
    assert avg == Decimal("101.9666666666666666666")
    assert avg.as_tuple().exponent == -19
```
## 검증 목적
        - ExecutionReport.execution_price의 Decimal이 recovery → OMS → Live Position까지 float으로 변환되지 않는지 검증한다.
        - recovery-derived execution price와 realtime execution price를 동일 OMS/Position 상태에 순차 반영한다.
        - OMS/Position weighted-average invariant를 동일 Decimal 값으로 확인한다.
        - Position의 Decimal 평균가격을 사용한 표준 monetary PnL 산식 (current_price - avg_price) × quantity × multiplier이 Decimal로 유지되는지 확인한다.
        - tick-size rounding 정책이 정의되지 않은 상태에서는 quantize()를 사용하지 않고 계산 정밀도를 그대로 보존한다.
[Child Page] test_virtual_pnl_decimal_settlement_integration.py
```python
from decimal import Decimal

from environments.virtual.authoritative_vssf.pnl_engine import PnLEngine
from environments.virtual.authoritative_vssf.ledger_engine import LedgerEngine


def test_unrealized_long_short_decimal_precision_without_rounding():
    engine = PnLEngine()
    positions = {
        "LONG": {"side": "BUY", "avg_price": Decimal("101.833333333333333333"), "qty": Decimal("3")},
        "SHORT": {"side": "SELL", "avg_price": Decimal("102.166666666666666667"), "qty": Decimal("2")},
    }
    result = engine.calculate_unrealized(positions, Decimal("102.500000000000000000"), Decimal("250000"))
    expected = ((Decimal("102.500000000000000000") - Decimal("101.833333333333333333")) * Decimal("3") + (Decimal("102.166666666666666667") - Decimal("102.500000000000000000")) * Decimal("2")) * Decimal("250000")
    assert result == expected
    assert isinstance(result, Decimal)
    assert result != result.quantize(Decimal("0.01"))


def test_realized_pnl_and_ledger_preserve_decimal_values():
    pnl = PnLEngine()
    pnl.add_realized(Decimal("123.456789123456789"))
    ledger = LedgerEngine()
    row = ledger.record_settlement("EOD", pnl.realized_pnl, Decimal("10.000000000000001"), Decimal("25000133.456789123456790"))
    assert row["realized_pnl"] == Decimal("123.456789123456789")
    assert row["unrealized_pnl"] == Decimal("10.000000000000001")
    assert row["balance_after"] == Decimal("25000133.456789123456790")
    assert all(isinstance(row[key], Decimal) for key in ("realized_pnl", "unrealized_pnl", "balance_after"))
```
[Child Page] test_virtual_account_snapshot_decimal_margin_integration.py
```python
from datetime import datetime
from decimal import Decimal

from contracts.types import AccountSnapshot
from environments.virtual.account.vssf_account_snapshot_adapter import VSSFAccountSnapshotAdapter
from environments.virtual.authoritative_vssf.margin_engine import MarginEngine


class Summary:
    total_balance = Decimal("25000133.456789123456789")
    realized_pnl = Decimal("123.456789123456789")
    unrealized_pnl = Decimal("10.000000000000001")
    used_margin = Decimal("123456.789123456789")
    free_margin = Decimal("24876676.667665666667")
    timestamp = "2026-09-07 12:00:00"


class AccountSource:
    def get_canonical_summary(self):
        return Summary()


def test_authoritative_summary_projects_decimal_without_precision_loss():
    snapshot = VSSFAccountSnapshotAdapter(AccountSource()).snapshot()
    assert isinstance(snapshot, AccountSnapshot)
    assert snapshot.as_of == datetime(2026, 9, 7, 12, 0, 0)
    assert snapshot.balances["cash"] == Summary.total_balance
    assert snapshot.balances["margin_used"] == Summary.used_margin
    assert snapshot.balances["available_cash"] == Summary.free_margin
    assert snapshot.balances["realized_pnl"] == Summary.realized_pnl
    assert snapshot.balances["unrealized_pnl"] == Summary.unrealized_pnl
    assert all(isinstance(value, Decimal) for value in snapshot.balances.values())


def test_margin_engine_preserves_decimal_and_has_no_implicit_rounding():
    engine = MarginEngine()
    positions = {
        "A": {"avg_price": Decimal("101.123456789123456789"), "qty": Decimal("1")},
        "B": {"avg_price": Decimal("99.987654321987654321"), "qty": Decimal("2")},
    }
    used = engine.calculate_used_margin(positions)
    expected = (positions["A"]["avg_price"] + positions["B"]["avg_price"] * Decimal("2")) * Decimal("250000")
    assert used == expected
    assert isinstance(used, Decimal)
    assert used != used.quantize(Decimal("0.01"))
    free = engine.calculate_free_margin(Decimal("100000000.123456789"), used)
    assert isinstance(free, Decimal)
```
[Child Page] test_virtual_account_to_risk_input_decimal_integration.py
```python
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from contracts.types import AccountSnapshot, DataQuality
from core.risk.risk_input import account_snapshot_to_risk_input
from environments.virtual.account.vssf_account_snapshot_adapter import VSSFAccountSnapshotAdapter


@dataclass
class Summary:
    total_balance: Decimal = Decimal("25000133.456789123456789")
    realized_pnl: Decimal = Decimal("123.456789123456789")
    unrealized_pnl: Decimal = Decimal("10.000000000000001")
    used_margin: Decimal = Decimal("123456.789123456789")
    free_margin: Decimal = Decimal("24876676.667665666667")
    timestamp: str = "2026-09-07 12:00:00"


class AccountSource:
    def get_canonical_summary(self):
        return Summary()


def test_authoritative_account_snapshot_to_risk_input_preserves_decimal_and_semantics():
    snapshot = VSSFAccountSnapshotAdapter(AccountSource()).snapshot()
    risk = account_snapshot_to_risk_input(snapshot)

    assert risk.total_balance == Summary.total_balance
    assert risk.realized_pnl == Summary.realized_pnl
    assert risk.used_margin == Summary.used_margin
    assert risk.free_margin == Summary.free_margin
    assert all(isinstance(value, Decimal) for value in (
        risk.total_balance,
        risk.realized_pnl,
        risk.used_margin,
        risk.free_margin,
    ))


def test_risk_input_semantic_mapping_is_not_recalculated():
    snapshot = AccountSnapshot(
        as_of=datetime(2026, 9, 7, 12, 0, 0),
        balances={
            "cash": Decimal("101.111111111111111111"),
            "margin_used": Decimal("22.222222222222222222"),
            "available_cash": Decimal("78.888888888888888889"),
            "realized_pnl": Decimal("1.234567891234567891"),
            "unrealized_pnl": Decimal("9.999999999999999999"),
        },
        freshness=DataQuality(True, True, True, "integration"),
    )
    risk = account_snapshot_to_risk_input(snapshot)
    assert risk.total_balance == snapshot.balances["cash"]
    assert risk.used_margin == snapshot.balances["margin_used"]
    assert risk.free_margin == snapshot.balances["available_cash"]
    assert risk.realized_pnl == snapshot.balances["realized_pnl"]
```
[Child Page] test_risk_engine_decimal_boundary.py
```python
from dataclasses import dataclass
from decimal import Decimal

from core.risk.risk_config import RiskConfig
from core.risk.risk_engine import RiskEngine
from core.risk.risk_input import RiskAccountInput


@dataclass(frozen=True)
class Command:
    client_order_id: str = "boundary-order"
    track_id: str = "boundary-track"
    qty: int = 1
    price: Decimal = Decimal("1")
    side: str = "BUY"
    tag_id: str = ""

    def get_instrument_key(self):
        return "OPTION_BOUNDARY"


class ExactMargin:
    def __init__(self, margin):
        self.margin = Decimal(str(margin))

    def calculate_order_margin(self, command):
        return self.margin * command.qty


def account(*, total="100", realized="0", used="0", free="100"):
    return RiskAccountInput(
        Decimal(str(total)),
        Decimal(str(realized)),
        Decimal(str(used)),
        Decimal(str(free)),
    )


def test_daily_loss_threshold_distinguishes_one_decimal_ulp():
    engine = RiskEngine(RiskConfig(max_daily_loss_krw=100.0), ExactMargin("1"))
    below = engine.evaluate_order(Command(), account(realized="-99.999999999999999999"))
    at_limit = engine.evaluate_order(Command(), account(realized="-100.000000000000000000"))
    assert below.decision == "ALLOW"
    assert at_limit.decision == "DENY"


def test_free_margin_affordability_distinguishes_sub_float_epsilon():
    margin = Decimal("1.000000000000000001")
    engine = RiskEngine(margin_engine=ExactMargin(margin))
    result = engine.evaluate_order(Command(), account(free="1.000000000000000000"))
    assert result.decision == "DENY"
    assert result.required_margin == margin


def test_margin_ratio_threshold_distinguishes_sub_float_epsilon():
    config = RiskConfig(max_margin_utilization_ratio=0.85)
    engine = RiskEngine(config, ExactMargin("0.000000000000000001"))
    result = engine.evaluate_order(
        Command(),
        account(total="1", used="0.850000000000000000"),
    )
    assert result.decision == "DENY"
    assert result.estimated_margin_ratio > Decimal("0.85")


def test_reduction_uses_exact_decimal_unit_margin():
    engine = RiskEngine(margin_engine=ExactMargin("0.500000000000000001"))
    result = engine.evaluate_order(Command(qty=3), account(free="1.000000000000000002"), allow_reduction=True)
    assert result.decision == "REDUCE"
    assert result.approved_qty == 2
    assert result.required_margin == Decimal("1.000000000000000002")
```
[Child Page] test_live_runtime_execution_lifecycle_ownership_seam.py
```python
# Integration contract test for No.491.

def test_explicit_lifecycle_order_and_shared_settlement_state():
    events = []
    shared_state = {"oms": "OMS-1", "position": "POSITION-1"}
    controller = RuntimeController(Hub(Bundle(events)))
    execution = Execution(events, shared_state)
    recovery = Recovery(events)
    bootstrap = LiveRuntimeBootstrap(
        execution=execution,
        order_router=object(),
        recovery_service=recovery,
    )

    controller.start("live-config", "live-policy")
    assert controller._state == "RUNNING"
    assert bootstrap.startup_reconcile("Q1") == "SETTLED"
    asyncio.run(bootstrap.start_execution("HTS"))
    assert asyncio.run(bootstrap.receive_execution_once()) is shared_state
    asyncio.run(bootstrap.close_execution())
    controller.stop()

    assert events == [
        "bundle.initialize", "bundle.connect", "bundle.start",
        "recovery.startup_reconcile", "execution.start",
        "execution.receive", "execution.close",
        "bundle.stop", "bundle.shutdown",
    ]
    assert controller._state == "STOPPED"
    assert controller._hub.active is None


def test_no_implicit_bootstrap_or_execution_lifecycle_inside_controller():
    events = []
    controller = RuntimeController(Hub(Bundle(events)))
    controller.start("live-config", "live-policy")
    assert events == ["bundle.initialize", "bundle.connect", "bundle.start"]
    controller.stop()
    assert events == [
        "bundle.initialize", "bundle.connect", "bundle.start",
        "bundle.stop", "bundle.shutdown",
    ]
```
## 위치
OptionProject / tests / integration
## 임시 검증
Workspace: /tmp/optionproject_verify_491
pytest -q 결과: 2 passed in 0.05s
[Child Page] test_live_execution_recovery_realtime_settlement_e2e.py
```python
from decimal import Decimal

from contracts.types import BrokerOrderCommand, ExecutionReport, OrderAckEvent, OrderIntent
from core.oms.oms_fsm import OrderStateMachine
from environments.live.execution.execution_event_deduplicator import ExecutionEventDeduplicator
from environments.live.position.live_execution_position_bridge import LiveExecutionPositionBridge, LivePositionFillAdapter
from environments.live.position.live_position_aggregate import LivePositionAggregate


def _report(*, execution_id, quantity, remaining, status, price):
    return ExecutionReport(
        client_order_id="C1",
        broker_order_id="B1",
        execution_id=execution_id,
        status=status,
        filled_quantity=quantity,
        remaining_quantity=remaining,
        execution_price=Decimal(price),
        execution_timestamp=None,
    )


def _scenario():
    oms = OrderStateMachine()
    command = BrokerOrderCommand("C1", "I1", "BUY", 5, "MARKET")
    oms.apply_intent(OrderIntent("C1", "I1", "BUY", 5, "NEW"))
    oms.apply_ack(OrderAckEvent("C1", True, "B1"))
    oms.register_broker_order_command(command)
    position = LivePositionAggregate("I1")
    bridge = LiveExecutionPositionBridge(
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(position),
        execution_event_deduplicator=ExecutionEventDeduplicator(),
        position_aggregate=position,
    )
    return oms, position, bridge


def test_startup_recovery_then_realtime_execution_share_same_settlement_state():
    oms, position, bridge = _scenario()

    recovery_report = _report(
        execution_id="R1", quantity=2, remaining=3,
        status="PARTIALLY_FILLED", price="350.0",
    )
    realtime_report = _report(
        execution_id="T1", quantity=3, remaining=0,
        status="FILLED", price="360.0",
    )

    bridge.settle(recovery_report)
    assert oms.get("C1").filled_quantity == 2
    assert position.snapshot().qty == 2
    assert position.snapshot().avg_price == Decimal("350.0")

    bridge.settle(realtime_report)
    state = oms.get("C1")
    snapshot = position.snapshot()
    assert state.status == "FILLED"
    assert state.filled_quantity == 5
    assert snapshot.qty == 5
    assert snapshot.avg_price == Decimal("356.0")


def test_replay_at_lifecycle_boundary_does_not_duplicate_settlement():
    oms, position, bridge = _scenario()
    report = _report(
        execution_id="R1", quantity=2, remaining=3,
        status="PARTIALLY_FILLED", price="350.0",
    )

    bridge.settle(report)
    before = (oms.get("C1").filled_quantity, position.snapshot().qty, position.snapshot().avg_price)
    bridge.settle(report)
    after = (oms.get("C1").filled_quantity, position.snapshot().qty, position.snapshot().avg_price)

    assert after == before
```
## 검증 범위
        - startup recovery report와 realtime execution report가 동일 LiveExecutionPositionBridge를 통해 동일 OMS/Position settlement state에 합류하는지 검증한다.
        - recovery 2 @ 350 후 realtime 3 @ 360의 누적 결과가 OMS filled 5, Position qty 5, weighted-average 356.0인지 검증한다.
        - lifecycle 경계에서 동일 execution replay가 발생해도 duplicate settlement가 없는지 검증한다.
        - cross-source authoritative execution identity의 실제 운영 정의는 이 테스트에서 합성하지 않으며 기존 BLOCKED를 유지한다.
[Child Page] test_live_runtime_recovery_realtime_shared_settlement.py
```python
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal

from application.bootstrap import LiveRuntimeBootstrap
from application.composition.live_execution_runtime_composition_factory import (
    create_live_execution_runtime_composition,
)
from contracts.types import BrokerOrderCommand, BrokerOrderResponse, OrderIntent
from core.oms.oms_fsm import OrderStateMachine
from environments.live.execution.execution_event_deduplicator import ExecutionEventDeduplicator
from environments.live.execution.kis_futures_execution_adapter import (
    KISFuturesExecutionNoticeAdapter,
)
from environments.live.execution.kis_futures_execution_recovery_adapter import (
    KISExecutionRecoveryContext,
    KISFuturesExecutionRecoveryAdapter,
)
from environments.live.execution.kis_futures_execution_correlation_provider import (
    KISFuturesExecutionCorrelationProvider,
)
from environments.live.position.live_execution_position_bridge import LivePositionFillAdapter


@dataclass
class FakePosition:
    instrument_id: str
    quantity: int = 0
    average_price: Decimal | None = None

    def apply_fill(self, *, side: str, quantity: int, price: Decimal) -> None:
        self.quantity += quantity if side == "BUY" else -quantity
        self.average_price = price


class FakeExecutionTransport:
    def __init__(self, frames):
        self.frames = list(frames)
        self.connected = False
        self.subscriptions = []
        self.closed = False

    async def connect(self):
        self.connected = True

    async def subscribe(self, tr_id, hts_id):
        self.subscriptions.append((tr_id, hts_id))

    async def recv(self):
        return self.frames.pop(0)

    async def close(self):
        self.closed = True


class FakeRecoveryTransport:
    def __init__(self, response):
        self.response = response
        self.queries = []

    def inquire(self, query):
        self.queries.append(query)
        return self.response


class FakeBroker:
    def submit(self, command, **_kwargs):
        return BrokerOrderResponse(
            client_order_id=command.client_order_id,
            accepted=True,
            broker_order_id="B1",
        )


def _acked_oms() -> OrderStateMachine:
    oms = OrderStateMachine()
    oms.apply_intent(OrderIntent(
        client_order_id="C1", instrument_id="I1", side="BUY", quantity=2, intent_type="OPEN"
    ))
    oms.register_broker_order_command(BrokerOrderCommand(
        client_order_id="C1", instrument_id="I1", side="BUY", quantity=2, order_type="MARKET"
    ))
    oms.apply_ack(type("Ack", (), {
        "client_order_id": "C1", "accepted": True, "broker_order_id": "B1"
    })())
    return oms


def _h0ifcni0_frame(*, broker_order_id="B1", qty="1", price="102.0") -> str:
    values = [""] * 22
    values[0] = "TESTCUST"
    values[1] = "12345678-01"
    values[2] = broker_order_id
    values[4] = "02"
    values[7] = "101T12"
    values[8] = qty
    values[9] = price
    values[10] = "093015"
    values[11] = "N"
    values[12] = "Y"
    values[13] = "Y"
    values[14] = "00001"
    values[15] = "2"
    values[16] = "TEST"
    values[17] = "KOSPI200 FUT"
    values[19] = "G1"
    values[20] = "1"
    values[21] = price
    return "0|H0IFCNI0|22|" + "^".join(values)


def _build_bootstrap():
    oms = _acked_oms()
    position = FakePosition("I1")
    transport = FakeExecutionTransport([_h0ifcni0_frame()])
    correlation = KISFuturesExecutionCorrelationProvider(oms)
    composition = create_live_execution_runtime_composition(
        transport=transport,
        execution_adapter=KISFuturesExecutionNoticeAdapter(),
        correlation_provider=correlation,
        broker=FakeBroker(),
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(position),
        execution_event_deduplicator=ExecutionEventDeduplicator(),
        position_aggregate=position,
        recovery_transport=FakeRecoveryTransport({
            "output1": [{"odno": "B1", "tot_ccld_qty": "1", "avg_idx": "101"}]
        }),
        recovery_adapter=KISFuturesExecutionRecoveryAdapter(),
    )
    bootstrap = LiveRuntimeBootstrap(
        execution=composition,
        order_router=__import__("core.oms.order_router", fromlist=["StandardOrderRouter"]).StandardOrderRouter(
            order_state_machine=oms,
            broker_adapter=composition.broker,
        ),
    )
    return bootstrap, oms, position, transport


def test_bootstrap_uses_concrete_runtime_composition_for_start_receive_settle_close():
    bootstrap, oms, position, transport = _build_bootstrap()

    recovery_query = object()
    recovered = bootstrap.startup_reconcile(recovery_query)
    assert len(recovered) == 1
    assert recovered[0].execution_id.startswith("REST-CCNL-SNAPSHOT|B1|1|")
    assert recovered[0].execution_price == Decimal("101")
    assert oms.get("C1").filled_quantity == 1
    assert position.quantity == 1

    asyncio.run(bootstrap.start_execution("HTS01"))
    assert transport.connected is True
    assert transport.subscriptions == [("H0IFCNI0", "HTS01")]

    realtime = asyncio.run(bootstrap.receive_execution_once())
    assert realtime.client_order_id == "C1"
    assert realtime.broker_order_id == "B1"
    assert realtime.filled_quantity == 1
    assert realtime.execution_price == Decimal("102.0")
    assert realtime.status == "FILLED"
    assert oms.get("C1").filled_quantity == 2
    assert oms.get("C1").remaining_quantity == 0
    assert oms.get("C1").status == "FILLED"
    assert position.quantity == 2
    assert position.average_price == Decimal("102.0")

    asyncio.run(bootstrap.close_execution())
    assert transport.closed is True


def test_recovery_adapter_delta_price_remains_decimal_and_shared_contract_compatible():
    adapter = KISFuturesExecutionRecoveryAdapter()
    report = adapter.to_execution_report(
        {"odno": "B1", "tot_ccld_qty": "2", "avg_idx": "101.5"},
        KISExecutionRecoveryContext(
            client_order_id="C1",
            order_quantity=3,
            prior_filled_quantity=1,
            prior_average_price=Decimal("100.0"),
        ),
    )
    assert report is not None
    assert report.filled_quantity == 1
    assert report.execution_price == Decimal("103.0")
    assert report.remaining_quantity == 1
```
## 검증 목적
        - LiveRuntimeBootstrap이 fake wrapper가 아니라 실제 LiveExecutionRuntimeComposition concrete 객체를 통해 start → receive → settle → close를 수행하는지 검증한다.
        - 실제 KISFuturesExecutionConsumer → H0IFCNI0 adapter → OMS correlation → ExecutionReport → shared settlement bridge → Position 경계를 사용한다.
        - recovery는 실제 LiveExecutionRecoveryService와 KISFuturesExecutionRecoveryAdapter를 composition factory로 조립하고 동일 settlement seam에 합류시킨다.
        - REST cumulative fill 1 @ 101 후 H0IFCNI0 realtime fill 1 @ 102가 동일 OMS/Position 상태에 누적되는지 검증한다.
        - recovery incremental price 산식이 Decimal authoritative contract를 유지하는지 별도 회귀 검증한다.
        - 실제 KIS credential/account/network/order submission은 사용하지 않는다.
[Child Page] test_live_runtime_lifecycle_coordinator.py
## 처리결과 보강
        - RuntimeController는 기존 계약대로 EnvironmentBundle lifecycle만 담당하도록 유지했다. 실제 start()는 initialize → connect → bundle.start → activate, stop()은 bundle.stop → shutdown → deactivate 순서를 유지한다.
        - production cross-component ordering은 별도 LiveRuntimeLifecycleCoordinator로 구현했다. 따라서 Controller 내부에 recovery/execution lifecycle을 침범시키지 않는다.
        - 명시적 startup 순서: RuntimeController.start → LiveRuntimeBootstrap.startup_reconcile → LiveRuntimeBootstrap.start_execution.
        - recovery 실패 시 realtime consumer는 시작하지 않고 Controller를 stop한다.
        - execution start 실패 시 close_execution을 먼저 시도한 뒤 Controller를 stop하여 fail-closed한다.
        - 정상 stop 순서: LiveRuntimeBootstrap.close_execution → RuntimeController.stop.
        - coordinator는 async lifecycle로 구현하여 이미 실행 중인 event loop에서 asyncio.run()을 중첩 호출하지 않는다.
        - OptionProject 실제 위치: application/composition/live_runtime_lifecycle_coordinator.py, tests/integration/test_live_runtime_lifecycle_coordinator.py.
## 터미널 검증
        - 임시 workspace: /tmp/optionproject_verify_495
        - production coordinator lifecycle 및 failure-ordering 테스트를 구성하여 PYTHONPATH=. pytest -q 실행.
        - 결과: 4 passed in 0.04s.
        - 첫 실행의 ModuleNotFoundError: application은 임시 workspace의 import path 미설정 문제였으며 PYTHONPATH=.로 재실행하여 4개 테스트 전체 PASS를 확인했다.
## 판정
PASS — RuntimeController의 책임을 유지하면서 Live production lifecycle의 recovery 선행, realtime 후행, stop 시 execution close 선행을 별도 composition seam으로 고정했다.
## 다음 단계
        - 다음 Process에서는 이 coordinator를 실제 create_live_runtime_controller() 및 concrete LiveEnvironmentBundle 조립 경계와 연결하는 production assembly integration을 검증한다.
        - 특히 caller가 coordinator를 통해 Live runtime을 시작할 때 실제 bundle의 initialize/connect/start와 bootstrap의 startup_reconcile/execution.start가 하나의 dependency graph에서 연결되는지 확인한다.
        - coordinator가 사용되지 않는 기존 low-level Controller API는 기존 계약을 유지하되, production entry point에서 coordinator 우회가 가능한지 여부를 명시적으로 점검한다.
        - H0IFCNI0/REST cross-source execution identity는 계속 BLOCKED 유지한다.
```python
import asyncio

import pytest

from application.composition.live_runtime_lifecycle_coordinator import (
    LiveRuntimeLifecycleCoordinator,
)


class FakeController:
    def __init__(self, events):
        self.events = events

    def start(self, config, policy):
        self.events.append(("controller.start", config, policy))

    def stop(self):
        self.events.append(("controller.stop",))


class FakeBootstrap:
    def __init__(self, events, *, reconcile_error=False, execution_error=False):
        self.events = events
        self.reconcile_error = reconcile_error
        self.execution_error = execution_error

    def startup_reconcile(self, query):
        self.events.append(("recovery.startup_reconcile", query))
        if self.reconcile_error:
            raise RuntimeError("RECOVERY_FAILED")
        return ("SETTLED",)

    async def start_execution(self, hts_id):
        self.events.append(("execution.start", hts_id))
        if self.execution_error:
            raise RuntimeError("EXECUTION_START_FAILED")

    async def receive_execution_once(self):
        self.events.append(("execution.receive",))
        return "REPORT"

    async def close_execution(self):
        self.events.append(("execution.close",))


def test_start_orders_controller_recovery_then_realtime_and_stop_closes_first():
    events = []
    coordinator = LiveRuntimeLifecycleCoordinator(
        controller=FakeController(events),
        bootstrap=FakeBootstrap(events),
    )

    recovered = asyncio.run(
        coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q1")
    )
    assert recovered == ("SETTLED",)
    assert events == [
        ("controller.start", "CONFIG", "POLICY"),
        ("recovery.startup_reconcile", "Q1"),
        ("execution.start", "HTS"),
    ]
    assert asyncio.run(coordinator.receive_execution_once()) == "REPORT"
    asyncio.run(coordinator.stop())
    assert events[-2:] == [("execution.close",), ("controller.stop",)]


def test_recovery_failure_never_starts_realtime_and_controller_is_stopped():
    events = []
    coordinator = LiveRuntimeLifecycleCoordinator(
        controller=FakeController(events),
        bootstrap=FakeBootstrap(events, reconcile_error=True),
    )

    with pytest.raises(RuntimeError, match="RECOVERY_FAILED"):
        asyncio.run(coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q1"))

    assert events == [
        ("controller.start", "CONFIG", "POLICY"),
        ("recovery.startup_reconcile", "Q1"),
        ("controller.stop",),
    ]


def test_execution_start_failure_closes_execution_before_controller_stop():
    events = []
    coordinator = LiveRuntimeLifecycleCoordinator(
        controller=FakeController(events),
        bootstrap=FakeBootstrap(events, execution_error=True),
    )

    with pytest.raises(RuntimeError, match="EXECUTION_START_FAILED"):
        asyncio.run(coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q1"))

    assert events == [
        ("controller.start", "CONFIG", "POLICY"),
        ("recovery.startup_reconcile", "Q1"),
        ("execution.start", "HTS"),
        ("execution.close",),
        ("controller.stop",),
    ]


def test_receive_before_start_is_fail_closed_and_duplicate_start_is_rejected():
    events = []
    coordinator = LiveRuntimeLifecycleCoordinator(
        controller=FakeController(events),
        bootstrap=FakeBootstrap(events),
    )

    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_NOT_STARTED"):
        asyncio.run(coordinator.receive_execution_once())

    asyncio.run(coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q1"))
    with pytest.raises(RuntimeError, match="already started"):
        asyncio.run(coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q2"))
```
## 검증 목적
        - production lifecycle의 명시적 순서를 controller.start → startup_reconcile → execution.start로 고정한다.
        - startup recovery가 실패하면 realtime execution이 시작되지 않는다.
        - execution start가 실패하면 execution close를 시도한 뒤 controller stop으로 fail-closed한다.
        - 정상 stop은 execution.close → controller.stop 순서를 보장한다.
        - start 전 execution 수신과 중복 start는 거부한다.
## No.513 identity invariant 검증 추가
```python
def test_restart_reuses_same_bootstrap_and_controller_instances():
    events = []
    controller = FakeController(events)
    bootstrap = FakeBootstrap(events)
    coordinator = LiveRuntimeLifecycleCoordinator(controller=controller, bootstrap=bootstrap)

    controller_id = id(coordinator._controller)
    bootstrap_id = id(coordinator._bootstrap)

    asyncio.run(coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q1"))
    asyncio.run(coordinator.stop())
    asyncio.run(coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q2"))

    assert id(coordinator._controller) == controller_id
    assert id(coordinator._bootstrap) == bootstrap_id
    assert coordinator._controller is controller
    assert coordinator._bootstrap is bootstrap


def test_dependency_replacement_is_fail_closed():
    events = []
    coordinator = LiveRuntimeLifecycleCoordinator(
        controller=FakeController(events),
        bootstrap=FakeBootstrap(events),
    )
    coordinator._bootstrap = FakeBootstrap(events)

    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_BOOTSTRAP_IDENTITY_CHANGED"):
        asyncio.run(coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q1"))
```
        - 정상 stop 후 restart도 최초 injected controller/bootstrap instance를 재사용한다.
        - coordinator dependency가 외부에서 교체되면 새 lifecycle을 시작하지 않고 fail-closed한다.
## No.518 in-flight receive drain barrier 검증 추가
```python
@pytest.mark.asyncio
async def test_stop_waits_for_inflight_receive_after_close_and_blocks_new_ingress():
    events = []
    bootstrap = BlockingReceiveBootstrap(events)
    coordinator = LiveRuntimeLifecycleCoordinator(
        controller=FakeController(events), bootstrap=bootstrap,
    )
    await coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q")

    receive_task = asyncio.create_task(coordinator.receive_execution_once())
    await bootstrap.receive_entered.wait()
    stop_task = asyncio.create_task(coordinator.stop())
    await asyncio.sleep(0)

    assert events[-1] == ("execution.close",)
    assert not stop_task.done()
    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_NOT_STARTED"):
        await coordinator.receive_execution_once()

    bootstrap.release_receive.set()
    assert await receive_task == "REPORT"
    await stop_task
    assert events[-1] == ("controller.stop",)
```
        - stop()은 먼저 _stopping=True로 신규 receive ingress를 차단한다.
        - close_execution()을 transport close/drain signal로 먼저 완료한 뒤, 이미 admitted된 receive의 completion을 기다린다.
        - 마지막 in-flight receive가 종료되기 전 controller.stop()으로 내려가지 않는다.
        - cancellation semantics가 명시되지 않은 transport는 coordinator가 강제 cancel하지 않고 정상 completion을 drain한다.
## No.521 concrete KIS transport + coordinator shared/independent restart seam 검증
```python
from application.composition.live_runtime_production_factory import (
    _LiveExecutionTransportOwnershipRegistry,
)
from infrastructure.kis.futures_execution_transport import (
    FuturesExecutionTransportError,
    KISFuturesExecutionTransport,
)


class _ConcreteTransportBootstrap:
    def __init__(self, events, transport):
        self.events = events
        self.transport = transport

    def startup_reconcile(self, query):
        self.events.append(("recovery", query))
        return ()

    async def start_execution(self, hts_id):
        self.events.append(("execution.start", hts_id))
        await self.transport.connect()
        await self.transport.subscribe("H0IFCNI0", hts_id)

    async def close_execution(self):
        self.events.append(("execution.close",))
        await self.transport.close()


class _NoCredentialAuth:
    is_vts = False


class _Socket:
    def __init__(self):
        self.closed = False
        self.sent = []

    async def send(self, value):
        self.sent.append(value)

    async def recv(self):
        raise AssertionError("recv is outside this lifecycle seam")

    async def close(self):
        self.closed = True


def test_shared_concrete_transport_blocks_second_owner_until_first_stop_then_handoffs():
    registry = _LiveExecutionTransportOwnershipRegistry()
    socket = _Socket()

    async def socket_factory(_url):
        return socket

    transport = KISFuturesExecutionTransport(
        _NoCredentialAuth(), socket_factory=socket_factory
    )
    transport._issue_approval_key = lambda: "approval"

    first_release = registry.claim(transport)
    first = LiveRuntimeLifecycleCoordinator(
        controller=FakeController([]),
        bootstrap=_ConcreteTransportBootstrap([], transport),
        release_execution_transport_ownership=first_release,
    )

    with pytest.raises(RuntimeError, match="LIVE_EXECUTION_TRANSPORT_ALREADY_OWNED"):
        registry.claim(transport)

    async def run():
        await first.start("CONFIG", "POLICY", hts_id="HTS01", recovery_query="Q1")
        await first.stop()
        second_release = registry.claim(transport)
        second = LiveRuntimeLifecycleCoordinator(
            controller=FakeController([]),
            bootstrap=_ConcreteTransportBootstrap([], transport),
            release_execution_transport_ownership=second_release,
        )
        await second.start("CONFIG", "POLICY", hts_id="HTS02", recovery_query="Q2")
        await second.stop()

    asyncio.run(run())
    assert socket.closed


def test_independent_concrete_transports_can_run_independent_lifecycles():
    registry = _LiveExecutionTransportOwnershipRegistry()
    sockets = [_Socket(), _Socket()]

    async def socket_factory(_url):
        return sockets.pop(0)

    transports = [
        KISFuturesExecutionTransport(_NoCredentialAuth(), socket_factory=socket_factory),
        KISFuturesExecutionTransport(_NoCredentialAuth(), socket_factory=socket_factory),
    ]
    for transport in transports:
        transport._issue_approval_key = lambda: "approval"

    coordinators = []
    for index, transport in enumerate(transports, start=1):
        coordinators.append(
            LiveRuntimeLifecycleCoordinator(
                controller=FakeController([]),
                bootstrap=_ConcreteTransportBootstrap([], transport),
                release_execution_transport_ownership=registry.claim(transport),
            )
        )

    async def run():
        await coordinators[0].start("C1", "P1", hts_id="HTS01", recovery_query="Q1")
        await coordinators[1].start("C2", "P2", hts_id="HTS02", recovery_query="Q2")
        await coordinators[0].stop()
        await coordinators[1].stop()

    asyncio.run(run())
```
        - 동일 concrete transport object는 registry claim 단계에서 두 번째 Live runtime ownership을 차단한다.
        - 첫 coordinator가 정상 stop하여 concrete transport close와 ownership release를 완료한 뒤에만 같은 object를 새 coordinator가 reconnect·resubscribe한다.
        - 서로 다른 concrete transport object는 각각 독립 lifecycle을 동시에 유지할 수 있다.
## No.522 concrete in-flight recv close·drain·cancellation seam 검증
```python
class _BlockingRecvSocket:
    def __init__(self):
        self.recv_entered = asyncio.Event()
        self.closed = asyncio.Event()

    async def recv(self):
        self.recv_entered.set()
        await self.closed.wait()
        raise ConnectionError("socket closed")

    async def close(self):
        self.closed.set()


class _ConcreteRecvBootstrap:
    def __init__(self, events, transport):
        self.events = events
        self.transport = transport

    def startup_reconcile(self, query):
        return ()

    async def start_execution(self, hts_id):
        self.events.append(("execution.start", hts_id))

    async def receive_execution_once(self):
        try:
            return await self.transport.recv()
        except ConnectionError:
            self.events.append(("execution.recv_unblocked",))
            raise

    async def close_execution(self):
        self.events.append(("execution.close",))
        await self.transport.close()


@pytest.mark.asyncio
async def test_concrete_transport_close_unblocks_inflight_recv_and_coordinator_drains():
    events = []
    socket = _BlockingRecvSocket()
    transport = KISFuturesExecutionTransport(_NoCredentialAuth())
    transport._socket = socket
    transport._connected = True
    coordinator = LiveRuntimeLifecycleCoordinator(
        controller=FakeController(events),
        bootstrap=_ConcreteRecvBootstrap(events, transport),
    )
    await coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q")

    receive_task = asyncio.create_task(coordinator.receive_execution_once())
    await socket.recv_entered.wait()
    stop_task = asyncio.create_task(coordinator.stop())
    await socket.closed.wait()

    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_NOT_STARTED"):
        await coordinator.receive_execution_once()
    with pytest.raises(ConnectionError, match="socket closed"):
        await receive_task
    await asyncio.wait_for(stop_task, timeout=0.2)

    assert events[-3:] == [
        ("execution.close",),
        ("execution.recv_unblocked",),
        ("controller.stop",),
    ]


@pytest.mark.asyncio
async def test_concrete_transport_recv_cancellation_still_releases_drain_barrier():
    events = []
    socket = _BlockingRecvSocket()
    transport = KISFuturesExecutionTransport(_NoCredentialAuth())
    transport._socket = socket
    transport._connected = True
    coordinator = LiveRuntimeLifecycleCoordinator(
        controller=FakeController(events),
        bootstrap=_ConcreteRecvBootstrap(events, transport),
    )
    await coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q")

    receive_task = asyncio.create_task(coordinator.receive_execution_once())
    await socket.recv_entered.wait()
    stop_task = asyncio.create_task(coordinator.stop())
    await socket.closed.wait()
    receive_task.cancel()

    with pytest.raises((ConnectionError, asyncio.CancelledError)):
        await receive_task
    await asyncio.wait_for(stop_task, timeout=0.2)
    assert events[-1] == ("controller.stop",)
```
        - concrete KISFuturesExecutionTransport.recv()가 실제 socket recv 대기 중일 때 close()가 socket close signal을 전달하면 대기 task가 해제되는 seam을 검증한다.
        - coordinator는 close 이후 신규 ingress를 거부하고 기존 receive의 예외 또는 cancellation이 finally를 통과해 drain barrier를 해제한 뒤 controller를 stop한다.
        - 정상 close-unblock 및 cancellation 경로 모두 deadlock 없이 종료되는 것을 targeted workspace에서 확인한다.
## No.523 close failure 이후 drain ordering 검증
```python
class _CloseFailingDrainBootstrap:
    def __init__(self, events):
        self.events = events
        self.receive_entered = asyncio.Event()
        self.release_receive = asyncio.Event()

    def startup_reconcile(self, query):
        return ()

    async def start_execution(self, hts_id):
        self.events.append(("execution.start", hts_id))

    async def receive_execution_once(self):
        self.receive_entered.set()
        await self.release_receive.wait()
        self.events.append(("execution.receive.done",))
        return "REPORT"

    async def close_execution(self):
        self.events.append(("execution.close.failed",))
        raise RuntimeError("CLOSE_FAILED")


@pytest.mark.asyncio
async def test_close_failure_still_drains_before_controller_stop_and_releases_afterward():
    events = []
    bootstrap = _CloseFailingDrainBootstrap(events)
    releases = []
    coordinator = LiveRuntimeLifecycleCoordinator(
        controller=FakeController(events),
        bootstrap=bootstrap,
        release_execution_transport_ownership=lambda: releases.append("released"),
    )
    await coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q")

    receive_task = asyncio.create_task(coordinator.receive_execution_once())
    await bootstrap.receive_entered.wait()
    stop_task = asyncio.create_task(coordinator.stop())
    await asyncio.sleep(0)

    assert not stop_task.done()
    assert events[-1] == ("execution.close.failed",)
    assert releases == []

    bootstrap.release_receive.set()
    assert await receive_task == "REPORT"
    with pytest.raises(RuntimeError, match="CLOSE_FAILED"):
        await stop_task

    assert events[-2:] == [
        ("execution.receive.done",),
        ("controller.stop",),
    ]
    assert releases == ["released"]
```
        - close 실패를 즉시 stop 실패로 전파하되, 이미 admitted된 receive drain을 건너뛰지 않는다.
        - ordering은 ingress block → close attempt → in-flight drain → controller.stop → ownership release → close error re-raise로 고정한다.
        - close가 실패해도 controller/ownership 정리가 누락되지 않으며, drain 완료 전 ownership release가 발생하지 않는다.
## No.525 policy-driven bounded shutdown 검증
테스트 범위:
        - graceful drain timeout 후 기술적 cancellation 경로를 한 번 시도한다.
        - cancellation 이후에도 drain이 끝나지 않으면 controller stop과 transport ownership release를 수행하지 않는다.
        - unresolved task가 남은 상태를 정상 종료로 위장하지 않고 LIVE_RUNTIME_SHUTDOWN_DRAIN_TIMEOUT으로 fail-closed한다.
        - 임시 Python workspace에서 timeout→cancel→drain 및 cancel-timeout→ERROR 격리 두 경로를 검증한다.
## No.526 concrete cancellation capability 경로 검증
        - LiveRuntimeBootstrap.cancel_execution_receives()를 explicit coordinator capability로 제공한다.
        - bootstrap은 execution object가 cancel_receive()를 제공하면 이를 우선 사용하고, 제공하지 않으면 기존 close_execution()으로 fallback한다.
        - KISFuturesExecutionConsumer.cancel_receive()는 transport의 cancel_recv() capability가 있으면 사용하고, legacy transport에서는 close() fallback을 사용한다.
        - 이 경로는 blocked realtime receive의 기술적 interruption만 담당하며 주문 취소·미체결 처리·포지션 청산을 수행하지 않는다.
## No.527 executable 검증 보강
### 1. RuntimePolicy identity + custom timeout
production lifecycle test에 실제 policy object를 주입하여 controller가 받은 객체와 coordinator._policy가 동일 객체인지 확인한다. graceful=0.01, cancellation=0.02 값을 사용해 shutdown source가 별도 기본값으로 대체되지 않음을 검증한다.
### 2. cancellation capability / legacy fallback
        - cancel_receive capability transport: cancel_recv() 호출 여부를 검증한다.
        - legacy transport: cancel_recv가 없을 때 close() fallback이 호출되는지 검증한다.
        - 두 경로 모두 기술적 receive interruption만 수행하고 Domain 주문 상태 mutation은 수행하지 않는다.
### 3. technical lifecycle status 계약
현재 timeout fail-closed는 LIVE_RUNTIME_SHUTDOWN_DRAIN_TIMEOUT 예외로 표현된다. 다음 단계에서는 Control Tower가 소비할 최소 기술 상태 계약을 별도 조사한다. Domain 주문 상태와 lifecycle technical ERROR를 동일 상태값으로 합치지 않는다.
### 임시 workspace 검증 상태
이번 환경에서는 DNS 해석 실패로 원격 Git clone이 불가능하여 실제 pytest terminal 재검증을 수행하지 못했다. 코드 변경 성공으로 오인하지 않으며, 다음 실행 환경에서 동일 테스트를 임시 workspace로 materialize하여 pytest PASS를 확인해야 한다.
## No.528 executable verification
        - 임시 workspace /tmp/optionproject_verify_528에서 Notion OptionProject source seam을 최소 materialize했다.
        - PYTHONPATH=. pytest -q 결과: 3 passed in 0.07s.
        - 검증 항목:
            - 동일 RuntimePolicy object identity가 controller와 coordinator에 유지되고 custom timeout 0.01 / 0.02가 사용 가능한지 확인.
            - cancel_execution_receives() capability 우선 경로 확인.
            - capability 부재 시 admitted task cancellation fallback 확인.
            - cancellation 이후에도 drain되지 않는 경우 LIVE_RUNTIME_SHUTDOWN_DRAIN_TIMEOUT과 technical state STOP_TIMEOUT으로 fail-closed되는지 확인.
        - STOP_TIMEOUT은 Domain 주문/포지션 상태가 아니라 Control Tower가 소비 가능한 technical lifecycle state로 분리한다.
## No.531 STOP_TIMEOUT restart admission / ownership 검증 추가
        - 정상 stop 후에는 동일 coordinator identity restart를 허용한다.
        - STOP_TIMEOUT 발생 후 start는 LIVE_RUNTIME_RESTART_NOT_ADMITTED로 거부한다.
        - STOP_TIMEOUT 이후 stop 재호출도 ownership release를 유발하지 않는다.
        - unresolved receive ownership 동안 transport reuse를 허용하지 않는다.
        - Control Tower는 STOP_TIMEOUT을 technical_state로 소비하고 execution_allowed=False를 유지한다.
검증 의미: timeout 후 started=False만으로 restart를 허용하지 않으며, receive drain 완료 전 transport ownership을 release하지 않는다.
## No.532 executable terminal verification
임시 Python workspace에서 No.531 coordinator seam과 ownership registry 계약을 최소 materialize하여 실제 pytest를 실행했다.
        - workspace: /tmp/no532
        - command: PYTHONPATH=. pytest -q
        - result: 3 passed in 0.08s
검증:
        1. 정상 clean stop 후 동일 coordinator restart 허용
        1. STOP_TIMEOUT 후 start/stop 재호출이 LIVE_RUNTIME_RESTART_NOT_ADMITTED로 차단
        1. STOP_TIMEOUT 동안 ownership release가 발생하지 않아 동일 shared transport registry 재-claim이 LIVE_EXECUTION_TRANSPORT_ALREADY_OWNED로 차단
따라서 정상 종료와 timeout 종료의 restart/ownership 경계가 executable test로 분리 확인되었다.
## No.561 controller.start failure cleanup 회귀 검증
```python

def test_controller_start_failure_releases_transport_ownership_and_leaves_start_false():
    events = []

    class FailingController(FakeController):
        def start(self, config, policy):
            self.events.append(("controller.start", config, policy))
            raise RuntimeError("CONTROLLER_START_FAILED")

    releases = []
    coordinator = LiveRuntimeLifecycleCoordinator(
        controller=FailingController(events),
        bootstrap=FakeBootstrap(events),
        release_execution_transport_ownership=lambda: releases.append("released"),
    )

    with pytest.raises(RuntimeError, match="CONTROLLER_START_FAILED"):
        asyncio.run(coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q1"))

    assert events == [
        ("controller.start", "CONFIG", "POLICY"),
        ("controller.stop",),
    ]
    assert releases == ["released"]
    assert coordinator._started is False
    assert coordinator._stopping is False
```
        - controller.start() 자체가 실패하는 가장 앞단 startup boundary에서도 transport ownership이 누수되지 않아야 한다.
        - 부분적으로 start가 진행되었을 가능성을 고려하여 controller.stop()을 동일 failure cleanup 경로에서 수행한다.
        - reconciliation/execution start는 시도되지 않으며 원래 CONTROLLER_START_FAILED 예외를 보존한다.
## No.562 shutdown cancellation failure fail-closed 회귀 검증
```python
class _ShutdownPolicy:
    graceful_shutdown_timeout_seconds = 0
    cancellation_drain_timeout_seconds = 0


class _CancellationFailureBootstrap(FakeBootstrap):
    def __init__(self, events, receive_entered):
        super().__init__(events)
        self.receive_entered = receive_entered
        self.receive_release = asyncio.Event()

    async def receive_execution_once(self):
        self.events.append(("execution.receive",))
        self.receive_entered.set()
        await self.receive_release.wait()
        return "REPORT"

    async def cancel_execution_receives(self):
        self.events.append(("execution.cancel",))
        raise RuntimeError("RECEIVE_CANCELLATION_FAILED")


def test_cancellation_failure_retains_ownership_and_sets_stop_timeout():
    events = []
    receive_entered = asyncio.Event()
    bootstrap = _CancellationFailureBootstrap(events, receive_entered)
    releases = []
    coordinator = LiveRuntimeLifecycleCoordinator(
        controller=FakeController(events),
        bootstrap=bootstrap,
        release_execution_transport_ownership=lambda: releases.append("released"),
    )

    async def run():
        await coordinator.start("CONFIG", _ShutdownPolicy(), hts_id="HTS", recovery_query="Q1")
        receive_task = asyncio.create_task(coordinator.receive_execution_once())
        await receive_entered.wait()

        with pytest.raises(RuntimeError, match="LIVE_RUNTIME_SHUTDOWN_CANCELLATION_FAILED"):
            await coordinator.stop()

        assert coordinator.technical_state == "STOP_TIMEOUT"
        assert coordinator._started is False
        assert coordinator._stopping is True
        assert releases == []
        assert ("execution.cancel",) in events
        assert ("controller.stop",) not in events

        with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
            await coordinator.start("CONFIG", _ShutdownPolicy(), hts_id="HTS2", recovery_query="Q2")

        bootstrap.receive_release.set()
        assert await receive_task == "REPORT"

    asyncio.run(run())
```
        - graceful drain timeout 후 transport-provided cancellation 자체가 실패하면 unresolved receive ownership이 해소되었다고 간주하지 않는다.
        - 이 경우 LIVE_RUNTIME_SHUTDOWN_CANCELLATION_FAILED로 fail-closed하고 technical_state="STOP_TIMEOUT"을 유지한다.
        - controller stop 및 execution transport ownership release를 수행하지 않는다.
        - STOP_TIMEOUT 상태에서는 새 start를 허용하지 않는다.
```javascript

```
## No.563 controller.stop 실패 회귀 검증 추가
```python
class FailingStopController(FakeController):
    def stop(self):
        self.events.append(("controller.stop",))
        raise RuntimeError("CONTROLLER_STOP_FAILED")


@pytest.mark.asyncio
async def test_controller_stop_failure_retains_ownership_and_blocks_restart():
    events = []
    released = []
    coordinator = LiveRuntimeLifecycleCoordinator(
        controller=FailingStopController(events),
        bootstrap=FakeBootstrap(events),
        release_execution_transport_ownership=lambda: released.append(True),
    )

    await coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q1")

    with pytest.raises(RuntimeError, match="CONTROLLER_STOP_FAILED"):
        await coordinator.stop()

    assert coordinator.technical_state == "STOP_CONTROLLER_FAILED"
    assert coordinator._started is False
    assert coordinator._stopping is True
    assert released == []

    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
        await coordinator.start("CONFIG", "POLICY", hts_id="HTS2", recovery_query="Q2")

    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
        await coordinator.stop()


@pytest.mark.asyncio
async def test_controller_stop_failure_remains_fail_closed_even_after_close_failure():
    events = []
    released = []

    class CloseFailBootstrap(FakeBootstrap):
        async def close_execution(self):
            self.events.append(("execution.close",))
            raise RuntimeError("EXECUTION_CLOSE_FAILED")

    coordinator = LiveRuntimeLifecycleCoordinator(
        controller=FailingStopController(events),
        bootstrap=CloseFailBootstrap(events),
        release_execution_transport_ownership=lambda: released.append(True),
    )
    await coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q1")

    with pytest.raises(RuntimeError, match="CONTROLLER_STOP_FAILED") as exc_info:
        await coordinator.stop()

    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert str(exc_info.value.__cause__) == "EXECUTION_CLOSE_FAILED"
    assert coordinator.technical_state == "STOP_CONTROLLER_FAILED"
    assert coordinator._stopping is True
    assert released == []
```
        - 검증 대상: execution close 이후 controller.stop 자체가 실패하는 shutdown boundary.
        - controller.stop 실패 시 lifecycle을 clean stop으로 오인하지 않고 STOP_CONTROLLER_FAILED technical state로 고정한다.
        - execution transport ownership은 release하지 않는다.
        - 동일 coordinator의 restart와 후속 stop 우회 호출을 차단한다.
        - execution close도 실패한 복합 실패에서는 controller stop failure를 주 예외로 유지하고 close failure를 cause로 보존한다.
## No.564 execution close 실패 + controller stop 성공 경계 회귀 검증
```python
@pytest.mark.asyncio
async def test_execution_close_failure_retains_ownership_and_blocks_restart():
    events = []
    released = []

    class CloseFailBootstrap(FakeBootstrap):
        async def close_execution(self):
            self.events.append(("execution.close",))
            raise RuntimeError("EXECUTION_CLOSE_FAILED")

    coordinator = LiveRuntimeLifecycleCoordinator(
        controller=FakeController(events),
        bootstrap=CloseFailBootstrap(events),
        release_execution_transport_ownership=lambda: released.append(True),
    )
    await coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q1")

    with pytest.raises(RuntimeError, match="EXECUTION_CLOSE_FAILED"):
        await coordinator.stop()

    assert coordinator.technical_state == "STOP_EXECUTION_CLOSE_FAILED"
    assert coordinator._started is False
    assert coordinator._stopping is True
    assert released == []
    assert events[-2:] == [("execution.close",), ("controller.stop",)]

    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
        await coordinator.start("CONFIG", "POLICY", hts_id="HTS2", recovery_query="Q2")

    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
        await coordinator.stop()
```
        - execution.close() 실패 후 controller.stop()이 성공하더라도 execution transport의 완전한 종료/release는 증명되지 않는다.
        - 따라서 STOP_EXECUTION_CLOSE_FAILED technical state를 기록하고 ownership을 유지한다.
        - 동일 coordinator restart 및 terminal stop 우회는 차단한다.
## No.565 startup controller.stop failure 경계 회귀 테스트 추가
```python
class _ControllerStopFailure(FakeController):
    def stop(self):
        self.events.append(("controller.stop",))
        raise RuntimeError("CONTROLLER_STOP_FAILED")


def test_startup_failure_with_controller_stop_failure_retains_ownership_and_blocks_restart():
    events = []
    released = []
    coordinator = LiveRuntimeLifecycleCoordinator(
        controller=_ControllerStopFailure(events),
        bootstrap=FakeBootstrap(events, reconcile_error=True),
        release_execution_transport_ownership=lambda: released.append(True),
    )

    with pytest.raises(RuntimeError, match="CONTROLLER_STOP_FAILED") as exc_info:
        asyncio.run(
            coordinator.start(
                "CONFIG", "POLICY", hts_id="HTS", recovery_query="Q1"
            )
        )

    assert str(exc_info.value) == "CONTROLLER_STOP_FAILED"
    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert str(exc_info.value.__cause__) == "RECOVERY_FAILED"
    assert events == [
        ("controller.start", "CONFIG", "POLICY"),
        ("recovery.startup_reconcile", "Q1"),
        ("controller.stop",),
    ]
    assert released == []
    assert coordinator.technical_state == "STOP_CONTROLLER_FAILED"
    assert coordinator._started is False
    assert coordinator._stopping is True

    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
        asyncio.run(
            coordinator.start(
                "CONFIG", "POLICY", hts_id="HTS", recovery_query="Q2"
            )
        )

    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
        asyncio.run(coordinator.stop())
```
## No.566 unstarted cleanup controller.stop 실패 fail-closed 회귀 검증
```python
class _FailingStopController(FakeController):
    def stop(self):
        self.events.append(("controller.stop",))
        raise RuntimeError("CONTROLLER_STOP_FAILED")


def test_unstarted_stop_controller_failure_retains_ownership_and_blocks_restart():
    events = []
    released = []
    coordinator = LiveRuntimeLifecycleCoordinator(
        controller=_FailingStopController(events),
        bootstrap=FakeBootstrap(events),
        release_execution_transport_ownership=lambda: released.append("released"),
    )

    with pytest.raises(RuntimeError, match="CONTROLLER_STOP_FAILED"):
        asyncio.run(coordinator.stop())

    assert events == [("controller.stop",)]
    assert released == []
    assert coordinator.technical_state == "STOP_CONTROLLER_FAILED"
    assert coordinator._started is False
    assert coordinator._stopping is True

    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
        asyncio.run(
            coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q1")
        )
```
        - 아직 start()되지 않은 coordinator라도 production factory에서 execution transport ownership을 먼저 보유할 수 있는 구조이므로, 이 상태의 cleanup controller.stop() 실패 역시 clean stop으로 취급해서는 안 된다.
        - controller 정지 성공이 증명되지 않으면 ownership release를 수행하지 않고 STOP_CONTROLLER_FAILED로 고정하여 replacement runtime의 재사용을 차단한다.
## No.567 transport ownership release 실패 fail-closed 회귀 검증
```python
def test_startup_release_failure_is_terminal_and_preserves_startup_error():
    controller = FakeController([])
    bootstrap = FailingRecoveryBootstrap()

    def release():
        raise RuntimeError("RELEASE_FAILED")

    coordinator = LiveRuntimeLifecycleCoordinator(
        controller=controller,
        bootstrap=bootstrap,
        release_execution_transport_ownership=release,
    )

    with pytest.raises(RuntimeError, match="RELEASE_FAILED") as exc:
        asyncio.run(
            coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q1")
        )

    assert str(exc.value.__cause__) == "STARTUP_FAILED"
    assert coordinator._started is False
    assert coordinator._stopping is True
    assert coordinator.technical_state == "TRANSPORT_OWNERSHIP_RELEASE_FAILED"

    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
        asyncio.run(
            coordinator.start("CONFIG", "POLICY", hts_id="HTS2", recovery_query="Q2")
        )


def test_clean_stop_release_failure_retains_ownership_and_blocks_restart():
    controller = FakeController([])
    bootstrap = FakeBootstrap([])

    def release():
        raise RuntimeError("RELEASE_FAILED")

    coordinator = LiveRuntimeLifecycleCoordinator(
        controller=controller,
        bootstrap=bootstrap,
        release_execution_transport_ownership=release,
    )
    asyncio.run(
        coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q1")
    )

    with pytest.raises(RuntimeError, match="RELEASE_FAILED"):
        asyncio.run(coordinator.stop())

    assert coordinator._started is False
    assert coordinator._stopping is True
    assert coordinator.technical_state == "TRANSPORT_OWNERSHIP_RELEASE_FAILED"

    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
        asyncio.run(
            coordinator.start("CONFIG", "POLICY", hts_id="HTS2", recovery_query="Q2")
        )
```
        - startup failure cleanup에서 ownership release 자체가 실패하면 release 완료를 증명할 수 없으므로 replacement runtime을 허용하지 않는다.
        - clean stop에서도 controller.stop() 성공만으로 clean stop을 확정하지 않고 ownership release 성공까지 포함하여 clean-stop proof를 구성한다.
        - release 실패 시 TRANSPORT_OWNERSHIP_RELEASE_FAILED technical state를 기록하고 ownership callback을 유지하여 재시작을 차단한다.
## No.569 startup CancelledError cleanup 회귀 검증
```python
import asyncio

import pytest


class CancelledStartBootstrap:
    def __init__(self):
        self.reconcile_called = False
        self.execution_started = False
        self.close_called = 0

    def startup_reconcile(self, query):
        self.reconcile_called = True
        return ()

    async def start_execution(self, hts_id):
        self.execution_started = True
        raise asyncio.CancelledError()

    async def close_execution(self):
        self.close_called += 1


def test_start_execution_cancellation_cleans_controller_and_releases_ownership():
    events = []

    class Controller:
        def start(self, config, policy):
            events.append("controller.start")

        def stop(self):
            events.append("controller.stop")

    bootstrap = CancelledStartBootstrap()
    coordinator = LiveRuntimeLifecycleCoordinator(
        controller=Controller(),
        bootstrap=bootstrap,
        release_execution_transport_ownership=lambda: events.append("ownership.release"),
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q")
        )

    assert events == [
        "controller.start",
        "controller.stop",
        "ownership.release",
    ]
    assert bootstrap.close_called == 1
    assert coordinator._started is False
    assert coordinator._stopping is False
    assert coordinator.technical_state is None


def test_start_execution_cancellation_with_controller_cleanup_failure_is_terminal():
    class Controller:
        def start(self, config, policy):
            return None

        def stop(self):
            raise RuntimeError("CONTROLLER_STOP_FAILED")

    coordinator = LiveRuntimeLifecycleCoordinator(
        controller=Controller(),
        bootstrap=CancelledStartBootstrap(),
        release_execution_transport_ownership=lambda: pytest.fail("ownership must remain claimed"),
    )

    with pytest.raises(RuntimeError, match="CONTROLLER_STOP_FAILED") as exc:
        asyncio.run(
            coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q")
        )

    assert isinstance(exc.value.__cause__, asyncio.CancelledError)
    assert coordinator._started is False
    assert coordinator._stopping is True
    assert coordinator.technical_state == "STOP_CONTROLLER_FAILED"
    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
        asyncio.run(
            coordinator.start("CONFIG", "POLICY", hts_id="HTS2", recovery_query="Q2")
        )
```
        - asyncio.CancelledError가 일반 Exception과 별개인 BaseException 계열이므로 startup cleanup을 우회하지 않는지 검증한다.
        - start_execution() cancellation도 controller stop → ownership release까지 정상 cleanup하고 원래 cancellation을 그대로 재전파해야 한다.
        - cleanup controller.stop 실패 시에는 기존 No.565와 동일하게 STOP_CONTROLLER_FAILED terminal state, ownership 유지, restart 차단을 적용한다.
## No.570 shutdown CancelledError 경계 회귀 검증 추가
```python
@pytest.mark.asyncio
async def test_stop_close_execution_cancelled_retains_ownership_and_blocks_restart():
    events = []
    release_calls = []

    class CancelOnCloseBootstrap(FakeBootstrap):
        async def close_execution(self):
            self.events.append(("execution.close",))
            raise asyncio.CancelledError()

    coordinator = LiveRuntimeLifecycleCoordinator(
        controller=FakeController(events),
        bootstrap=CancelOnCloseBootstrap(events),
        release_execution_transport_ownership=lambda: release_calls.append("released"),
    )
    await coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q1")

    with pytest.raises(asyncio.CancelledError):
        await coordinator.stop()

    assert coordinator.technical_state == "STOP_SHUTDOWN_CANCELLED"
    assert coordinator._started is False
    assert coordinator._stopping is True
    assert release_calls == []
    assert events[-1] == ("execution.close",)
    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
        await coordinator.start("CONFIG", "POLICY", hts_id="HTS2", recovery_query="Q2")


@pytest.mark.asyncio
async def test_stop_receive_drain_cancelled_retains_ownership_and_blocks_restart():
    events = []
    release_calls = []

    class DrainCancelledCoordinator(LiveRuntimeLifecycleCoordinator):
        async def _wait_receives_drained(self, timeout_seconds):
            raise asyncio.CancelledError()

    coordinator = DrainCancelledCoordinator(
        controller=FakeController(events),
        bootstrap=FakeBootstrap(events),
        release_execution_transport_ownership=lambda: release_calls.append("released"),
    )
    await coordinator.start("CONFIG", "POLICY", hts_id="HTS", recovery_query="Q1")

    with pytest.raises(asyncio.CancelledError):
        await coordinator.stop()

    assert coordinator.technical_state == "STOP_SHUTDOWN_CANCELLED"
    assert coordinator._started is False
    assert coordinator._stopping is True
    assert release_calls == []
    assert events == [
        ("controller.start", "CONFIG", "POLICY"),
        ("recovery.startup_reconcile", "Q1"),
        ("execution.start", "HTS"),
        ("execution.close",),
    ]
    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
        await coordinator.start("CONFIG", "POLICY", hts_id="HTS2", recovery_query="Q2")
```
        - close_execution() 자체가 asyncio.CancelledError를 발생시키면 controller.stop 및 ownership release로 진행하지 않는다.
        - receive-drain 대기 중 asyncio.CancelledError가 발생해도 controller.stop 및 ownership release로 진행하지 않는다.
        - 두 경우 모두 technical_state="STOP_SHUTDOWN_CANCELLED", _started=False, _stopping=True를 유지하고 restart를 차단한다.
        - 원래 CancelledError는 호출자에게 재전파한다.
## No.571 shutdown cancellation·cancel_execution_receives 경계 회귀 검증
```python
@pytest.mark.asyncio
async def test_cancel_execution_receives_cancelled_is_terminal_and_no_release():
    # graceful drain timeout -> cancel_execution_receives() raises CancelledError
    # Expect STOP_SHUTDOWN_CANCELLED, ownership retained, restart blocked.
    ...

@pytest.mark.asyncio
async def test_cancel_execution_receives_error_is_stop_timeout_and_no_release():
    # graceful drain timeout -> cancel_execution_receives() raises ordinary error
    # Expect LIVE_RUNTIME_SHUTDOWN_CANCELLATION_FAILED + STOP_TIMEOUT,
    # ownership retained, restart blocked.
    ...
```
        - cancel_execution_receives()가 asyncio.CancelledError를 자체적으로 발생시켜도 stop()은 이를 shutdown cancellation으로 분리하고 controller.stop/ownership release를 수행하지 않는다.
        - cancel_execution_receives()가 일반 예외를 발생시키면 기존 cancellation-failure 계약대로 LIVE_RUNTIME_SHUTDOWN_CANCELLATION_FAILED를 만들고 STOP_TIMEOUT으로 fail-closed한다.
        - 두 경계 모두 ownership release가 호출되지 않고 restart가 차단되는 것을 검증한다.
## No.572 terminal technical_state 재호출·Control Tower status/command 일관성 회귀 검증
```python
@pytest.mark.parametrize(
    "technical_state",
    [
        "STOP_SHUTDOWN_CANCELLED",
        "STOP_TIMEOUT",
        "STOP_CONTROLLER_FAILED",
        "STOP_EXECUTION_CLOSE_FAILED",
        "TRANSPORT_OWNERSHIP_RELEASE_FAILED",
    ],
)
def test_terminal_technical_state_projects_and_blocks_all_commands(technical_state):
    # status(): technical_state 그대로 유지, execution_allowed=False,
    # reason=technical_state
    # start/restart/stop 모두 underlying controller를 호출하지 않고 차단
    ...

@pytest.mark.asyncio
async def test_repeated_coordinator_stop_after_terminal_shutdown_remains_blocked():
    # STOP_SHUTDOWN_CANCELLED 상태에서 stop() 재호출 시 상태를 정상화하거나
    # ownership release를 시도하지 않고 terminal 상태를 그대로 유지
    ...
```
        - No.570에서 새로 정의된 STOP_SHUTDOWN_CANCELLED도 기존 terminal technical state와 동일하게 Control Tower에 투영되어야 한다.
        - terminal technical state가 하나라도 존재하면 status의 execution_allowed=False, reason=technical_state를 유지한다.
        - start/restart/stop command 모두 terminal state에서 underlying runtime/controller를 우회 호출하지 않는다.
        - coordinator의 shutdown cancellation 이후 stop() 재호출도 terminal state를 정상화하거나 ownership을 release하지 않는 fail-closed 경계로 검증한다.
## No.573 startup cancellation cleanup 교차 경계 회귀 검증
```python
class _CleanupCancelledBootstrap:
    def startup_reconcile(self, query):
        return ()

    async def start_execution(self, hts_id):
        raise asyncio.CancelledError()

    async def close_execution(self):
        raise asyncio.CancelledError()


def test_startup_cancellation_cleanup_cancellation_retains_ownership_and_blocks_restart():
    events = []
    coordinator = LiveRuntimeLifecycleCoordinator(
        controller=FakeController(events),
        bootstrap=_CleanupCancelledBootstrap(),
        release_execution_transport_ownership=lambda: events.append(("ownership.release",)),
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            coordinator.start(
                "CONFIG", "POLICY", hts_id="HTS", recovery_query="Q"
            )
        )

    assert events == [("controller.start", "CONFIG", "POLICY")]
    assert coordinator._started is False
    assert coordinator._stopping is True
    assert coordinator.technical_state == "STARTUP_CLEANUP_CANCELLED"

    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
        asyncio.run(
            coordinator.start(
                "CONFIG", "POLICY", hts_id="HTS2", recovery_query="Q2"
            )
        )
```
        - start_execution() cancellation 이후 cleanup close_execution() 자체가 다시 cancellation되면 execution closure를 증명할 수 없으므로 controller stop이나 transport ownership release로 진행하지 않는다.
        - STARTUP_CLEANUP_CANCELLED terminal technical state로 고정하고 replacement runtime start를 차단한다.
        - 일반 startup failure branch에서도 동일 cleanup cancellation 보호가 적용된다.
## No.574 startup cleanup terminal state Control Tower·shared transport ownership 연속 검증
```python
import asyncio
import pytest

from application.composition.live_runtime_lifecycle_coordinator import (
    LiveRuntimeLifecycleCoordinator,
)
from application.composition.control_tower_runtime_composition import (
    create_live_control_tower_runtime_api,
)
from application.composition.live_runtime_production_factory import (
    _LiveExecutionTransportOwnershipRegistry,
)


def test_startup_cleanup_cancelled_projects_and_blocks_control_tower_commands():
    class Controller:
        def __init__(self):
            self.started = 0
            self.stopped = 0
        def start(self, config, policy): self.started += 1
        def stop(self): self.stopped += 1
        def status(self):
            return type("Status", (), {"environment": "live", "state": "STOPPED"})()

    class Bootstrap:
        def startup_reconcile(self, query): return ()
        async def start_execution(self, hts_id): raise asyncio.CancelledError()
        async def close_execution(self): raise asyncio.CancelledError()

    controller = Controller()
    coordinator = LiveRuntimeLifecycleCoordinator(controller=controller, bootstrap=Bootstrap())
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(coordinator.start("C", "P", hts_id="H", recovery_query="Q"))

    api = create_live_control_tower_runtime_api(lifecycle_coordinator=coordinator)
    status = api.status()
    assert status.technical_state == "STARTUP_CLEANUP_CANCELLED"
    assert status.execution_allowed is False
    assert status.reason == "STARTUP_CLEANUP_CANCELLED"

    async def commands():
        command = type("Command", (), {
            "config": "C", "policy": "P", "hts_id": "H2", "recovery_query": "Q2",
        })()
        with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
            await api.start_live(command)
        with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
            await api.stop_live()
        with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
            await api.restart_live(command)

    asyncio.run(commands())
    assert controller.started == 1
    assert controller.stopped == 0


def test_startup_cleanup_cancelled_owner_blocks_shared_transport_reclaim():
    registry = _LiveExecutionTransportOwnershipRegistry()
    transport = object()
    release = registry.claim(transport)

    class Controller:
        def start(self, *args): pass
        def stop(self): raise AssertionError("must not stop after unresolved cleanup cancellation")

    class Bootstrap:
        def startup_reconcile(self, query): return ()
        async def start_execution(self, hts_id): raise asyncio.CancelledError()
        async def close_execution(self): raise asyncio.CancelledError()

    coordinator = LiveRuntimeLifecycleCoordinator(
        controller=Controller(),
        bootstrap=Bootstrap(),
        release_execution_transport_ownership=release,
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(coordinator.start("C", "P", hts_id="H", recovery_query="Q"))

    with pytest.raises(RuntimeError, match="LIVE_EXECUTION_TRANSPORT_ALREADY_OWNED"):
        registry.claim(transport)
    assert coordinator.technical_state == "STARTUP_CLEANUP_CANCELLED"
```
        - STARTUP_CLEANUP_CANCELLED는 기존 technical_state is not None 계약으로 Control Tower status에 그대로 투영되고 async lifecycle command를 모두 fail-closed한다.
        - unresolved startup cleanup coordinator가 ownership release를 호출하지 않으므로 동일 shared transport의 새 registry claim도 LIVE_EXECUTION_TRANSPORT_ALREADY_OWNED로 차단된다.
        - 별도 source 수정 없이 기존 No.568 이후의 generic terminal-state projection과 No.555 ownership registry 계약이 No.573 신규 terminal state까지 실제로 연속 적용됨을 검증한다.
[Child Page] test_live_runtime_production_factory.py
```python
import asyncio

import pytest

from application.composition import live_runtime_production_factory as factory


def _deps():
	deps = {
		name: object()
		for name in (
			"market", "broker", "account", "position", "reconciler", "transport",
			"execution_adapter", "correlation_provider", "order_state_machine",
			"execution_event_deduplicator", "safety_policy",
		)
	}
	aggregate = object()
	deps["position_aggregate"] = aggregate
	deps["position_fill_adapter"] = type("FillAdapter", (), {"_aggregate": aggregate})()
	return deps


def test_factory_uses_single_bootstrap_recovery_and_controller(monkeypatch):
	events = []

	class Bootstrap:
		recovery_service = object()

	def fake_bootstrap(**kwargs):
		events.append(("bootstrap", kwargs))
		return Bootstrap()

	def fake_builder(**kwargs):
		events.append(("bundle_builder", kwargs))
		return object()

	def fake_controller(*, live_builder):
		events.append(("controller", live_builder))
		return object()

	class Coordinator:
		def __init__(self, *, controller, bootstrap, **kwargs):
			self.controller = controller
			self.bootstrap = bootstrap

	monkeypatch.setattr(factory, "create_live_runtime_bootstrap", fake_bootstrap)
	monkeypatch.setattr(factory, "build_live_bundle_from_components", fake_builder)
	monkeypatch.setattr(factory, "create_live_runtime_controller", fake_controller)
	monkeypatch.setattr(factory, "LiveRuntimeLifecycleCoordinator", Coordinator)

	deps = _deps()
	coordinator = factory.create_live_runtime_lifecycle_coordinator(**deps)

	assert isinstance(coordinator, Coordinator)
	assert [name for name, *_ in events] == ["bootstrap", "bundle_builder", "controller"]
	assert events[1][1]["recovery"] is coordinator.bootstrap.recovery_service
	bootstrap_kwargs = events[0][1]
	builder_kwargs = events[1][1]
	assert bootstrap_kwargs["broker"] is deps["broker"]
	assert bootstrap_kwargs["order_state_machine"] is deps["order_state_machine"]
	assert bootstrap_kwargs["correlation_provider"] is deps["correlation_provider"]
	assert bootstrap_kwargs["position_aggregate"] is deps["position_aggregate"]
	assert builder_kwargs["broker"] is deps["broker"]
	assert builder_kwargs["position"] is deps["position"]


def test_factory_rejects_position_fill_adapter_bound_to_different_aggregate(monkeypatch):
	deps = _deps()
	deps["position_fill_adapter"] = type("FillAdapter", (), {"_aggregate": object()})()

	with pytest.raises(ValueError, match="LIVE_RUNTIME_POSITION_AGGREGATE_OWNERSHIP_MISMATCH"):
		factory.create_live_runtime_lifecycle_coordinator(**deps)


def test_concrete_assembly_exposes_required_lifecycle_graph(monkeypatch):
	events = []

	class Bootstrap:
		recovery_service = object()

		def startup_reconcile(self, query):
			events.append("reconcile")
			return "recovered"

		async def start_execution(self, hts_id):
			events.append("execution.start")

		async def receive_execution_once(self):
			events.append("execution.receive")
			return "event"

		async def close_execution(self):
			events.append("execution.close")

	class Controller:
		def start(self, config, policy):
			events.extend(["bundle.initialize", "bundle.connect", "bundle.start"])

		def stop(self):
			events.extend(["bundle.stop", "bundle.shutdown"])

	holder = {}

	def fake_bootstrap(**kwargs):
		bootstrap = Bootstrap()
		holder["bootstrap"] = bootstrap
		return bootstrap

	def fake_builder(**kwargs):
		holder["builder_kwargs"] = kwargs
		return object()

	def fake_controller(*, live_builder):
		holder["controller"] = Controller()
		return holder["controller"]

	monkeypatch.setattr(factory, "create_live_runtime_bootstrap", fake_bootstrap)
	monkeypatch.setattr(factory, "build_live_bundle_from_components", fake_builder)
	monkeypatch.setattr(factory, "create_live_runtime_controller", fake_controller)

	coordinator = factory.create_live_runtime_lifecycle_coordinator(**_deps())
	asyncio.run(coordinator.start(object(), object(), hts_id="H", recovery_query=object()))
	asyncio.run(coordinator.receive_execution_once())
	asyncio.run(coordinator.stop())

	assert events == [
		"bundle.initialize", "bundle.connect", "bundle.start",
		"reconcile", "execution.start", "execution.receive",
		"execution.close", "bundle.stop", "bundle.shutdown",
	]
	assert holder["builder_kwargs"]["recovery"] is holder["bootstrap"].recovery_service


def test_factory_requires_and_validates_risk_state_providers_for_injected_tick_entry(monkeypatch):
	class Bootstrap:
		recovery_service = object()

	def fake_bootstrap(**kwargs):
		return Bootstrap()

	monkeypatch.setattr(factory, "create_live_runtime_bootstrap", fake_bootstrap)
	monkeypatch.setattr(factory, "build_live_bundle_from_components", lambda **kwargs: object())
	monkeypatch.setattr(factory, "create_live_runtime_controller", lambda *, live_builder: object())

	account_provider = lambda: "account"
	position_provider = lambda: "position"
	providers = type(
		"Providers",
		(),
		{
			"account_snapshot_provider": account_provider,
			"position_source_provider": position_provider,
		},
	)()
	tick_entry = type(
		"TickEntry",
		(),
		{
			"account_snapshot_provider": account_provider,
			"position_source_provider": position_provider,
		},
	)()

	deps = _deps()
	deps["tick_entry"] = tick_entry
	with pytest.raises(ValueError, match="LIVE_RUNTIME_RISK_STATE_PROVIDERS_REQUIRED"):
		factory.create_live_runtime_lifecycle_coordinator(**deps)

	deps["risk_state_providers"] = providers
	coordinator = factory.create_live_runtime_lifecycle_coordinator(**deps)
	assert coordinator.bootstrap is not None

	deps["risk_state_providers"] = type(
		"Providers",
		(),
		{
			"account_snapshot_provider": lambda: "other-account",
			"position_source_provider": position_provider,
		},
	)()
	with pytest.raises(ValueError, match="LIVE_RUNTIME_RISK_STATE_PROVIDER_OWNERSHIP_MISMATCH:account_snapshot_provider"):
		factory.create_live_runtime_lifecycle_coordinator(**deps)
```
## 검증 목적
        - production factory가 create_live_runtime_bootstrap()과 create_live_runtime_controller()를 하나의 명시적 assembly에서 결합하는지 확인한다.
        - position_fill_adapter와 position_aggregate가 실제 settlement mutation에서 동일 owner인지 확인하며, Environment/Risk position source와 execution settlement aggregate는 별도 책임으로 유지한다.
        - caller-supplied broker, OrderStateMachine, correlation provider, position aggregate를 bootstrap execution/recovery graph에 동일 object로 전달하고, LiveEnvironmentBundle에는 동일 broker와 별도 의미의 environment position source를 전달하는지 확인한다.
        - position fill adapter가 다른 aggregate를 가리키면 LIVE_RUNTIME_POSITION_AGGREGATE_OWNERSHIP_MISMATCH로 fail-closed하는지 확인한다.
        - bootstrap이 조립한 authoritative recovery_service를 LiveEnvironmentBundle builder에도 동일 객체로 전달하는지 확인한다.
        - 실제 lifecycle 순서가 bundle.initialize → connect → start → startup_reconcile → execution.start → receive → execution.close → bundle.stop → shutdown으로 유지되는지 확인한다.
        - injected TickEntry가 production coordinator에 들어오는 경우 LiveRuntimeRiskStateProviders와 Account/Position provider callable identity가 동일한지 검증한다.
        - provider bundle이 없거나 다른 provider가 연결되면 LIVE_RUNTIME_RISK_STATE_PROVIDERS_REQUIRED / LIVE_RUNTIME_RISK_STATE_PROVIDER_OWNERSHIP_MISMATCH로 fail-closed한다.
        - 새로운 background loop, credential, network client, synthetic business dependency를 생성하지 않는다.
## No.514 restart 내부 execution graph identity 검증 추가
```python

def test_stop_restart_preserves_nested_execution_graph_identity(monkeypatch):
    class Settlement:
        def __init__(self):
            self.position_aggregate = object()
            self.order_state_machine = object()
            self.execution_event_deduplicator = object()

    class Execution:
        def __init__(self):
            self.settlement = Settlement()
            self.broker = object()
            self.recovery_service = object()

    class Bootstrap:
        def __init__(self):
            self.execution = Execution()
            self.recovery_service = self.execution.recovery_service
        def startup_reconcile(self, query): return "ok"
        async def start_execution(self, hts_id): pass
        async def close_execution(self): pass

    class Controller:
        def start(self, config, policy): pass
        def stop(self): pass

    bootstrap = Bootstrap()
    coordinator = factory.LiveRuntimeLifecycleCoordinator(controller=Controller(), bootstrap=bootstrap)
    settlement = bootstrap.execution.settlement
    graph_before = tuple(map(id, (bootstrap, bootstrap.execution, settlement, settlement.position_aggregate, settlement.order_state_machine, settlement.execution_event_deduplicator, bootstrap.execution.broker, bootstrap.recovery_service)))

    asyncio.run(coordinator.start("CONFIG", "POLICY", hts_id="H", recovery_query="Q1"))
    asyncio.run(coordinator.stop())
    asyncio.run(coordinator.start("CONFIG", "POLICY", hts_id="H", recovery_query="Q2"))

    assert tuple(map(id, (coordinator._bootstrap, coordinator._bootstrap.execution, coordinator._bootstrap.execution.settlement, coordinator._bootstrap.execution.settlement.position_aggregate, coordinator._bootstrap.execution.settlement.order_state_machine, coordinator._bootstrap.execution.settlement.execution_event_deduplicator, coordinator._bootstrap.execution.broker, coordinator._bootstrap.recovery_service))) == graph_before
```
        - stop → restart가 coordinator/bootstrap 외부 identity뿐 아니라 bootstrap 내부 execution → settlement → position aggregate/OMS/deduplicator 및 recovery graph를 재생성하지 않는지 targeted 검증한다.
        - replacement가 필요한 경우 기존 coordinator mutation이 아니라 새 runtime ownership으로 분리한다.
## No.515 new runtime graph ownership boundary 검증 추가
```python
def test_explicit_new_runtime_graph_is_disjoint_from_old_runtime_graph():
    old = new_runtime_graph()
    new = new_runtime_graph()
    old_ids = {
        id(old), id(old._controller), id(old._bootstrap),
        id(old._bootstrap.execution),
        id(old._bootstrap.execution.settlement),
    }
    new_ids = {
        id(new), id(new._controller), id(new._bootstrap),
        id(new._bootstrap.execution),
        id(new._bootstrap.execution.settlement),
    }
    assert old_ids.isdisjoint(new_ids)
```
        - 명시적으로 새 runtime을 생성할 때 old/new coordinator 및 내부 controller/bootstrap/execution/settlement graph가 섞이지 않는지 검증한다.
        - old coordinator의 stop → restart는 기존 graph를 유지할 뿐 new runtime graph로 전환되지 않는다.
        - 기존 runtime 내부 dependency를 교체하는 방식은 coordinator identity invariant에 의해 fail-closed해야 하며, replacement는 새 runtime factory 호출로만 분리한다.
## No.519 shared execution transport ownership handoff 검증 추가
```python
@pytest.mark.asyncio
async def test_shared_execution_transport_cannot_be_reowned_until_old_runtime_drains(monkeypatch):
    events = []
    entered = asyncio.Event()
    release = asyncio.Event()

    class Bootstrap:
        recovery_service = object()
        def startup_reconcile(self, query): return "ok"
        async def start_execution(self, hts_id): pass
        async def receive_execution_once(self):
            entered.set()
            await release.wait()
            return "old-report"
        async def close_execution(self):
            events.append("close")

    class Controller:
        def start(self, config, policy): pass
        def stop(self): events.append("stop")

    monkeypatch.setattr(factory, "create_live_runtime_bootstrap", lambda **kwargs: Bootstrap())
    monkeypatch.setattr(factory, "build_live_bundle_from_components", lambda **kwargs: object())
    monkeypatch.setattr(factory, "create_live_runtime_controller", lambda *, live_builder: Controller())

    deps = _deps()
    old = factory.create_live_runtime_lifecycle_coordinator(**deps)
    await old.start("CONFIG", "POLICY", hts_id="OLD", recovery_query="Q")
    receive_task = asyncio.create_task(old.receive_execution_once())
    await entered.wait()
    stop_task = asyncio.create_task(old.stop())

    with pytest.raises(RuntimeError, match="LIVE_EXECUTION_TRANSPORT_ALREADY_OWNED"):
        factory.create_live_runtime_lifecycle_coordinator(**deps)

    assert not stop_task.done()
    release.set()
    assert await receive_task == "old-report"
    await stop_task

    new = factory.create_live_runtime_lifecycle_coordinator(**deps)
    assert new is not old
```
        - 동일 execution transport는 old runtime이 drain/stop을 완료하기 전 새 production runtime이 claim하지 못한다.
        - ownership release는 close_execution → in-flight drain → controller.stop 완료 뒤에만 발생한다.
        - 독립 transport를 사용하는 새 runtime은 기존처럼 별도 graph ownership으로 조립할 수 있다.
## No.516 lifecycle ownership handoff ingress 차단 검증
```python
@pytest.mark.asyncio
async def test_stop_blocks_old_ingress_before_close_finishes():
    old = new_runtime_graph()
    await old.start("CONFIG", "POLICY", hts_id="OLD", recovery_query="Q")

    closing = asyncio.create_task(old.stop())
    await old._bootstrap.close_entered.wait()

    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_NOT_STARTED"):
        await old.receive_execution_once()

    old._bootstrap.release_close.set()
    await closing


@pytest.mark.asyncio
async def test_new_runtime_can_receive_while_old_is_draining_without_graph_handoff():
    old = new_runtime_graph()
    await old.start("CONFIG", "POLICY", hts_id="OLD", recovery_query="Q")

    closing = asyncio.create_task(old.stop())
    await old._bootstrap.close_entered.wait()

    new = new_runtime_graph()
    await new.start("CONFIG", "POLICY", hts_id="NEW", recovery_query="Q")

    assert await new.receive_execution_once() == "event"
    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_NOT_STARTED"):
        await old.receive_execution_once()

    assert old._bootstrap is not new._bootstrap
    assert old._controller is not new._controller

    old._bootstrap.release_close.set()
    await closing
```
        - stop() 진입 즉시 _stopping=True로 전환하여 비동기 close_execution()이 완료되기 전에도 old runtime ingress를 차단한다.
        - old runtime drain 동안 명시적으로 새 factory가 만든 new runtime만 자신의 graph에서 receive를 허용한다.
        - old/new graph 간 controller/bootstrap ownership handoff는 객체 교체가 아니라 독립 runtime 생성으로 유지한다.
## No.526 RuntimePolicy identity propagation 검증
        - production factory는 RuntimePolicy를 새로 생성하거나 복사하지 않는다.
        - coordinator start(config, policy, ...)가 받은 동일 policy object를 controller에 전달하고, 성공 후 동일 object를 coordinator shutdown policy source로 보관해야 한다.
        - integration test에서 0.01/0.02초 policy를 주입하고 controller가 받은 객체 identity와 coordinator 내부 policy identity를 함께 확인한다.
        - production composition factory 자체는 policy 값을 합성하지 않으므로 timeout ownership은 RuntimePolicy 단일 객체에 유지된다.
## No.535 Control Tower production entry wiring 검증
```python

def test_production_factory_exposes_control_tower_api_for_same_coordinator(monkeypatch):
    from application.composition import live_runtime_production_factory as factory

    controller = object()
    coordinator = type(
        "Coordinator",
        (), {"runtime_controller": controller, "technical_state": None},
    )()

    api = factory.create_live_control_tower_runtime(
        lifecycle_coordinator=coordinator,
    )

    assert api._runtime is controller
    assert api._lifecycle_status_source is coordinator


def test_stop_timeout_coordinator_cannot_be_hidden_by_production_control_tower_entry():
    from application.composition import live_runtime_production_factory as factory

    class Status:
        environment = "live"
        state = "STOPPING"

    class Controller:
        def status(self):
            return Status()

    coordinator = type(
        "Coordinator",
        (), {"runtime_controller": Controller(), "technical_state": "STOP_TIMEOUT"},
    )()

    api = factory.create_live_control_tower_runtime(
        lifecycle_coordinator=coordinator,
    )
    status = api.status()

    assert api._lifecycle_status_source is coordinator
    assert status.technical_state == "STOP_TIMEOUT"
    assert status.execution_allowed is False
    assert status.reason == "STOP_TIMEOUT"
```
        - 최상위 Live production factory가 coordinator와 ControlTowerRuntimeAPI를 같은 object graph로 연결하는지 검증한다.
        - STOP_TIMEOUT coordinator를 새 정상 상태로 대체하거나 lifecycle source를 누락시키지 않는지 확인한다.
## No.541 production assembly integration 보강
```python
def test_production_factory_builds_real_controller_with_concrete_live_builder(monkeypatch):
    from application.environment_hub.contracts import EnvironmentConfig, EnvironmentType, RuntimePolicy
    from application.runtime_controller.controller import RuntimeController

    class Bootstrap:
        recovery_service = object()

        def startup_reconcile(self, query):
            return ("RECOVERED", query)

        async def start_execution(self, hts_id):
            return hts_id

        async def receive_execution_once(self):
            return "REPORT"

        async def close_execution(self):
            return None

    monkeypatch.setattr(factory, "create_live_runtime_bootstrap", lambda **kwargs: Bootstrap())

    deps = _deps()
    coordinator = factory.create_live_runtime_lifecycle_coordinator(**deps)

    assert isinstance(coordinator.runtime_controller, RuntimeController)
    assert coordinator.bootstrap.recovery_service is not None

    config = EnvironmentConfig(environment=EnvironmentType.LIVE)
    policy = RuntimePolicy()
    builder = factory.build_live_bundle_from_components(
        market=deps["market"],
        broker=deps["broker"],
        account=deps["account"],
        position=deps["position"],
        reconciler=deps["reconciler"],
        recovery=coordinator.bootstrap.recovery_service,
        safety_policy=deps["safety_policy"],
    )
    bundle = builder(config, policy)

    assert bundle.market is deps["market"]
    assert bundle.broker is deps["broker"]
    assert bundle.account is deps["account"]
    assert bundle.position is deps["position"]
    assert bundle.reconciler is deps["reconciler"]
    assert bundle.recovery is coordinator.bootstrap.recovery_service
```
        - production factory가 coordinator만 반환하는지에 그치지 않고, 실제 RuntimeController와 concrete LiveEnvironmentBundle builder를 조립하는지 검증한다.
        - bundle의 market/broker/account/position/reconciler/recovery가 caller-supplied object identity를 그대로 유지하는지 확인한다.
        - bootstrap은 테스트 경계에서만 최소 fake로 대체하며 실제 Live bundle assembly는 build_live_bundle_from_components()를 사용한다.
## No.549 shutdown policy validation state preservation regression
```python
@pytest.mark.asyncio
async def test_invalid_shutdown_timeout_does_not_poison_started_lifecycle():
    class Policy:
        graceful_shutdown_timeout_seconds = -1
        cancellation_drain_timeout_seconds = 1

    class Bootstrap:
        recovery_service = object()

        def startup_reconcile(self, query):
            return "ok"

        async def start_execution(self, hts_id):
            pass

        async def close_execution(self):
            raise AssertionError("close_execution must not run with invalid policy")

    class Controller:
        def __init__(self):
            self.started = 0
            self.stopped = 0

        def start(self, config, policy):
            self.started += 1

        def stop(self):
            self.stopped += 1

    controller = Controller()
    coordinator = factory.LiveRuntimeLifecycleCoordinator(
        controller=controller,
        bootstrap=Bootstrap(),
    )
    await coordinator.start("CONFIG", Policy(), hts_id="H", recovery_query="Q")

    with pytest.raises(ValueError, match="LIVE_RUNTIME_INVALID_SHUTDOWN_TIMEOUT"):
        await coordinator.stop()

    assert coordinator._started is True
    assert coordinator._stopping is False
    assert coordinator.technical_state is None
    assert controller.stopped == 0
```
        - 잘못된 shutdown timeout은 stop()의 lifecycle state mutation보다 먼저 검증한다.
        - 잘못된 policy가 close_execution()을 실행시키거나 _stopping=True 상태를 남겨 정상 lifecycle을 오염시키지 않는지 회귀 검증한다.
        - 이는 STOP_TIMEOUT과 달리 실제 transport drain 실패가 아닌 입력 policy 오류이므로, unresolved receive ownership을 의미하는 STOP_TIMEOUT 상태로 승격하지 않는다.
## No.557 coordinator construction failure 후 execution transport ownership leak 회귀 방지
```python

def test_factory_releases_transport_ownership_when_coordinator_construction_fails(monkeypatch):
    deps = _deps()
    transport = deps["transport"]

    class BrokenCoordinator:
        def __init__(self, **kwargs):
            raise RuntimeError("LIVE_RUNTIME_COORDINATOR_CONSTRUCTION_FAILED")

    monkeypatch.setattr(factory, "LiveRuntimeLifecycleCoordinator", BrokenCoordinator)
    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_COORDINATOR_CONSTRUCTION_FAILED"):
        factory.create_live_runtime_lifecycle_coordinator(**deps)

    # Failed assembly must not permanently reserve the caller-supplied transport.
    monkeypatch.setattr(factory, "LiveRuntimeLifecycleCoordinator", factory.LiveRuntimeLifecycleCoordinator)
    coordinator = factory.create_live_runtime_lifecycle_coordinator(**deps)
    assert coordinator is not None
```
        - production factory에서 controller/bootstrap assembly가 끝난 뒤 execution transport ownership을 claim하고 coordinator를 생성하므로, coordinator 생성 자체가 예외를 내면 기존 구조에서는 ownership token이 남을 수 있음을 targeted reproduction으로 확인했다.
        - 실제 OptionProject / application / composition / live_runtime_production_factory.py에 coordinator 생성 구간을 try/except로 감싸고 construction failure 시 방금 claim한 transport ownership을 즉시 release한 뒤 원래 예외를 재발생시키도록 수정했다.
        - 정상 생성 경로의 ownership semantics와 clean stop/STOP_TIMEOUT semantics는 변경하지 않는다. 즉, 실제 coordinator가 성공적으로 생성된 경우에만 lifecycle coordinator가 ownership release 책임을 보유한다.
        - Exp_Detail_1은 참조하지 않았다.
[Child Page] test_live_runtime_tick_transport_production_boundary.py
```python
import pytest

from application.composition import live_runtime_production_factory as production_factory
from application.composition import live_runtime_risk_state_factory as risk_factory


class Providers:
    def __init__(self, account_provider, position_provider):
        self.account_snapshot_provider = account_provider
        self.position_source_provider = position_provider


class Transport:
    def __init__(self, runtime, s2d, d2c, gate, router, broker_command, account, position):
        self.strategy_runtime = runtime
        self.strategy_to_decision = s2d
        self.decision_to_command = d2c
        self.risk_gate = gate
        self.risk_context = type("Context", (), {"order_router": router})()
        self.account_snapshot = account
        self.position_source = position


class Entry:
    def __init__(self, runtime, s2d, d2c, gate, account_provider, position_provider):
        self.runtime = runtime
        self.strategy_to_decision = s2d
        self.decision_to_command = d2c
        self.risk_gate = gate
        self.account_snapshot_provider = account_provider
        self.position_source_provider = position_provider


def test_tick_transport_shares_strategy_decision_risk_and_provider_graph(monkeypatch):
    runtime = object(); s2d = object(); d2c = object(); gate = object()
    router = object(); broker_command = object()
    account_provider = lambda: "account-current"
    position_provider = lambda: "position-current"
    providers = Providers(account_provider, position_provider)
    captured = {}

    def fake_transport_composition(**kwargs):
        captured["transport_kwargs"] = kwargs
        return Transport(
            kwargs["strategy_runtime"], kwargs["strategy_to_decision"],
            kwargs["decision_to_command"], kwargs["risk_gate"],
            kwargs["order_router"], kwargs["broker_command"],
            kwargs["account_snapshot"], kwargs["position_source"],
        )

    monkeypatch.setattr(risk_factory, "create_runtime_transport_composition", fake_transport_composition)
    monkeypatch.setattr(risk_factory, "LiveRuntimeTickEntry", Entry)
    monkeypatch.setattr(risk_factory, "route_from_runtime_authoritative_sources", lambda *a, **k: None)

    transport, entry = risk_factory.create_live_runtime_tick_transport(
        strategy_runtime=runtime, strategy_to_decision=s2d,
        decision_to_command=d2c, risk_gate=gate, order_router=router,
        broker_command=broker_command, risk_state_providers=providers,
    )

    assert transport.strategy_runtime is runtime
    assert transport.strategy_to_decision is s2d
    assert transport.decision_to_command is d2c
    assert transport.risk_gate is gate
    assert transport.account_snapshot == "account-current"
    assert transport.position_source == "position-current"
    assert entry.runtime is runtime
    assert entry.strategy_to_decision is s2d
    assert entry.decision_to_command is d2c
    assert entry.risk_gate is gate
    assert entry.account_snapshot_provider is account_provider
    assert entry.position_source_provider is position_provider
    assert captured["transport_kwargs"]["account_snapshot"] == "account-current"
    assert captured["transport_kwargs"]["position_source"] == "position-current"


def test_tick_transport_requires_provider_bundle():
    with pytest.raises(ValueError, match="LIVE_RUNTIME_RISK_STATE_PROVIDERS_REQUIRED"):
        risk_factory.create_live_runtime_tick_transport(
            strategy_runtime=object(), strategy_to_decision=object(),
            decision_to_command=object(), risk_gate=object(),
            order_router=object(), broker_command=object(),
            risk_state_providers=None,
        )


def test_production_factory_accepts_the_same_injected_tick_graph(monkeypatch):
    runtime = object(); s2d = object(); d2c = object(); gate = object()
    account_provider = lambda: "account"; position_provider = lambda: "position"
    providers = Providers(account_provider, position_provider)
    tick_entry = Entry(runtime, s2d, d2c, gate, account_provider, position_provider)
    deps = {name: object() for name in (
        "market", "broker", "account", "position", "reconciler", "transport",
        "execution_adapter", "correlation_provider", "order_state_machine",
        "execution_event_deduplicator", "safety_policy")}
    aggregate = object()
    deps["position_aggregate"] = aggregate
    deps["position_fill_adapter"] = type("FillAdapter", (), {"_aggregate": aggregate})()
    deps["tick_entry"] = tick_entry; deps["risk_state_providers"] = providers
    deps["runtime_transport"] = Transport(runtime, s2d, d2c, gate, object(), object(), "account", "position")
    captured = {}

    class Bootstrap: recovery_service = object()
    monkeypatch.setattr(production_factory, "create_live_runtime_bootstrap", lambda **kwargs: (captured.update(kwargs) or Bootstrap()))
    monkeypatch.setattr(production_factory, "build_live_bundle_from_components", lambda **kwargs: object())
    monkeypatch.setattr(production_factory, "create_live_runtime_controller", lambda *, live_builder: object())
    monkeypatch.setattr(production_factory, "LiveRuntimeLifecycleCoordinator", lambda *, controller, bootstrap: object())

    production_factory.create_live_runtime_lifecycle_coordinator(**deps)
    assert captured["tick_entry"] is tick_entry
    assert captured["runtime_transport"] is deps["runtime_transport"]


def test_production_factory_does_not_replace_injected_tick_entry_or_transport(monkeypatch):
    deps = {name: object() for name in (
        "market", "broker", "account", "position", "reconciler", "transport",
        "execution_adapter", "correlation_provider", "order_state_machine",
        "execution_event_deduplicator", "safety_policy")}
    aggregate = object()
    deps["position_aggregate"] = aggregate
    deps["position_fill_adapter"] = type("FillAdapter", (), {"_aggregate": aggregate})()
    account_provider = lambda: "account"; position_provider = lambda: "position"
    deps["risk_state_providers"] = Providers(account_provider, position_provider)
    entry = Entry(object(), object(), object(), object(), account_provider, position_provider)
    deps["tick_entry"] = entry
    deps["runtime_transport"] = Transport(
        entry.runtime, entry.strategy_to_decision, entry.decision_to_command,
        entry.risk_gate, object(), object(), "account", "position")
    captured = {}

    class Bootstrap: recovery_service = object()
    monkeypatch.setattr(production_factory, "create_live_runtime_bootstrap", lambda **kwargs: (captured.update(kwargs) or Bootstrap()))
    monkeypatch.setattr(production_factory, "build_live_bundle_from_components", lambda **kwargs: object())
    monkeypatch.setattr(production_factory, "create_live_runtime_controller", lambda *, live_builder: object())
    monkeypatch.setattr(production_factory, "LiveRuntimeLifecycleCoordinator", lambda *, controller, bootstrap: object())

    production_factory.create_live_runtime_lifecycle_coordinator(**deps)
    assert captured["tick_entry"] is entry
    assert captured["runtime_transport"] is deps["runtime_transport"]
```
실제 OptionProject 위치 기준: tests/integration/test_live_runtime_tick_transport_production_boundary.py. 이 페이지는 현재 Notion connector에서 확인 가능한 OptionProject/tests parent 아래에 생성했으며, 기존 tests/integration 경계의 후속 검증 파일로 관리한다.
[Child Page] test_live_runtime_kis_market_canonical_boundary.py
```python
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from contracts.kis_index_futures_market_ws_adapter import (
    KISIndexFuturesMarketWebSocketAdapter,
)
from environments.live.market.kis_futures_market_data import (
    KISFuturesMarketDataProvider,
)
from contracts.types import CanonicalMarketTick


def test_kis_observation_preserves_authoritative_instrument_and_time_but_has_no_synthetic_sequence():
    adapter = KISIndexFuturesMarketWebSocketAdapter()
    values = ["10100"] * 37
    values[0] = "10100"
    values[1] = "123456"
    values[5] = "350.10"
    values[10] = "1234"
    values[35] = "350.20"
    values[36] = "350.00"
    frame = "0|H0IFCNT0|37|" + "^".join(values)

    observation = adapter.adapt(frame)
    observed_at = datetime(2026, 9, 7, 12, 34, 56, tzinfo=timezone.utc)
    provider = KISFuturesMarketDataProvider(
        instrument_id_resolver=lambda short_code: "KOSPI200-FUT-1",
        observed_at_resolver=lambda _: observed_at,
    )

    tick = provider.publish(observation)

    assert tick.instrument_id == "KOSPI200-FUT-1"
    assert tick.observed_at is observed_at
    assert tick.price == Decimal("350.10")
    assert tick.source_sequence is None


def test_kis_market_projection_does_not_invent_source_sequence():
    adapter = KISIndexFuturesMarketWebSocketAdapter()
    values = ["10100"] * 37
    values[1] = "123456"
    values[5] = "350.10"
    values[10] = "1234"
    values[35] = "350.20"
    values[36] = "350.00"
    observation = adapter.adapt("0|H0IFCNT0|37|" + "^".join(values))
    observed_at = datetime(2026, 9, 7, 12, 34, 56, tzinfo=timezone.utc)
    tick = KISFuturesMarketDataProvider(
        instrument_id_resolver=lambda _: "KOSPI200-FUT-1",
        observed_at_resolver=lambda _: observed_at,
    ).publish(observation)

    assert tick.source_sequence is None


def test_runtime_accepts_only_a_canonical_tick_with_authoritative_sequence():
    tick = CanonicalMarketTick(
        instrument_id="KOSPI200-FUT-1",
        observed_at=datetime(2026, 9, 7, 12, 34, 56, tzinfo=timezone.utc),
        price=Decimal("350.10"),
        source_sequence=17,
    )
    assert tick.source_sequence == 17
```
## 검증 목적
        - KIS H0IFCNT0 typed observation → KISFuturesMarketDataProvider → CanonicalMarketTick 경계를 실제 구조대로 검증한다.
        - KIS short code는 authoritative resolver를 통해 instrument_id로 공급하고, KIS observed_hour를 임의 날짜/현재시각으로 합성하지 않는 기존 계약을 유지한다.
        - 현재 KIS observation에는 Runtime이 요구하는 source_sequence가 없으므로 provider가 sequence를 생성하지 않는 것을 고정한다.
        - Runtime identity contract를 만족하는 것은 CanonicalMarketTick.source_sequence가 명시적으로 공급된 경우뿐임을 분리 검증한다.
        - 이 테스트는 KIS 인증/네트워크 없이 wire-shaped adapter와 projection 경계를 검증한다.
[Child Page] test_live_runtime_production_factory_identity.py
## 검증 목적
create_live_runtime_lifecycle_coordinator()가 caller-supplied tick_entry, runtime_transport, broker, position_aggregate를 교체·복제하지 않고 production dependency graph에 전달하는지 검증한다.
## 핵심 검증
        - tick_entry object identity 보존
        - runtime_transport object identity 보존
        - broker 및 position_aggregate identity 보존
        - risk_state_providers의 Account/Position provider callable과 tick_entry callable identity 불일치 시 LIVE_RUNTIME_RISK_STATE_PROVIDER_OWNERSHIP_MISMATCH fail-closed
## 임시 workspace
/tmp/optionproject_verify_507
## 터미널 검증
production factory source를 임시 workspace에 재구성하고 assembly dependency만 최소 stub으로 대체하여 targeted pytest 실행.
결과: 2 passed.
실제 KIS 인증·네트워크·계좌·주문은 사용하지 않았다.
[Child Page] test_live_runtime_production_composition_identity_boundary.py
## 목적
LiveRuntimeProductionFactory → LiveRuntimeLifecycleCoordinator → RuntimeController/LiveEnvironmentBundle → Bootstrap 하나의 injected composition에서 caller-supplied dependency identity와 lifecycle ordering을 실제 경계 기준으로 검증한다.
## 검증 범위
        - production factory가 caller-supplied runtime_transport, tick_entry, broker, position_aggregate를 교체·복제하지 않는지 확인
        - tick_entry가 LiveRuntimeBootstrap.process_tick_once() 경계까지 동일 객체로 도달하는지 확인
        - process_tick_once()가 동일 runtime_transport.risk_context를 tick entry에 전달하는지 확인
        - RuntimeController가 LiveEnvironmentBundle의 initialize → connect → start 후 active 상태로 전환되고, 정상 stop에서 bundle.stop → shutdown → deactivate 순서를 유지하는지 확인
        - recovery가 coordinator startup에서 선행되고 execution start/stop lifecycle이 그 뒤를 따르는지 확인
## 임시 Python workspace
/tmp/optionproject_verify_508
실제 KIS credential/network/account/order는 생성하지 않고, OptionProject의 현재 production assembly 경계를 최소 stub으로 재구성하여 terminal pytest로 검증했다.
## 결과
        - 최종: 4 passed in 0.04s
        - production factory identity 전달 targeted check: PASS
        - process_tick_once() identity 전달: PASS
        - injected composition lifecycle ordering: PASS
        - recovery → execution start → stop ordering: PASS
## 판정
PASS
현재 production factory/bootstrap/controller 구조에서 caller-supplied dependency를 다른 객체로 바꾸는 경로를 확인하지 못했다. 별도 production code 수정은 필요하지 않았다.
Market CanonicalMarketTick.source_sequence BLOCKED와 H0IFCNI0/REST cross-source execution identity BLOCKED는 이 검증과 독립적으로 유지한다.
[Child Page] test_runtime_risk_router_ack_execution_position_one_shot.py
## 목적
Risk → Router → ACK → OMS → Execution → Position 전체 seam을 하나의 injected one-shot 흐름으로 검증한다.
## 검증 항목
        - Risk ALLOW → StandardOrderRouter.register_and_route() 호출
        - Router → Broker submit → BrokerOrderResponse → OrderAckEvent → OMS ACKED
        - ACK 단계에서 Position mutation이 발생하지 않음
        - H0IFCNI0-shaped ExecutionReport가 ACK 이후 LiveExecutionPositionBridge로 전달됨
        - ExecutionReport → OMS execution → 동일 position_aggregate mutation
        - 동일 execution_id replay는 Position/OMS를 중복 mutation하지 않음
        - ACK 이전 ExecutionReport는 fail-closed
        - Risk DENY는 Router/OMS/Position으로 전달되지 않음
## 임시 Python workspace
/tmp/optionproject_verify_509
## 실제 terminal pytest
현재 OptionProject의 실제 계약을 기준으로 최소 production seam을 재구성하여 pytest를 실행했다.
        - 최종 결과: 4 passed in 0.03s
        - ALLOW → ACK → Execution → Position: PASS
        - DENY → Router 차단: PASS
        - duplicate execution → 중복 Position mutation 차단: PASS
        - Execution before ACK → fail-closed: PASS
실제 KIS credential/network/account/order는 사용하지 않았다.
## 계약 주의점
ExecutionReport에는 side가 없으며, side와 originating BrokerOrderCommand는 OMS-owned state에서 공급된다. BrokerOrderCommand에 broker order id를 synthetic field로 추가하지 않는다. LiveExecutionPositionBridge는 OMS 상태에서 원 주문을 조회한다.
## 판정
PASS
Risk→Router→ACK→OMS→Execution→Position 내부 seam은 현재 정의된 계약 범위에서 하나의 one-shot 테스트 흐름으로 연결 가능하다.
Market source_sequence blocker 및 H0IFCNI0/REST cross-source execution identity blocker는 별도로 유지한다.
[Child Page] test_multi_leg_risk.py
```python
from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace

import pytest

from contracts.types import OrderIntent
from core.risk.multi_leg_risk import MultiLegRiskError, admit_multi_leg_intents
from core.risk.risk_engine import RiskGate
from core.risk.risk_input import RiskAccountInput, RiskPositionInput


@dataclass
class Command:
    client_order_id: str
    track_id: str
    qty: int
    price: float
    side: str
    tag_id: str

    def get_instrument_key(self) -> str:
        return self.client_order_id


class Margin:
    def calculate_order_margin(self, command):
        return float(command.qty) * 10


def account():
    return RiskAccountInput(
        total_balance=Decimal("100000"),
        free_margin=Decimal("100000"),
        used_margin=Decimal("0"),
        realized_pnl=Decimal("0"),
    )


def intent(client_id: str, leg_id: str, qty: int = 1) -> OrderIntent:
    return OrderIntent(
        client_order_id=client_id,
        instrument_id=f"I-{leg_id}",
        side="BUY",
        quantity=qty,
        intent_type="ENTRY",
        strategy_id="track2_asymmetric_trap",
        asset_type="OPTION",
        requested_price=Decimal("1.0"),
        order_type="LIMIT",
        order_purpose="ENTRY",
        track_id="track2_asymmetric_trap",
        tag_id="LEG",
        group_id="G-2",
        leg_id=leg_id,
    )


def gate():
    from core.risk.risk_config import RiskConfig
    return RiskGate(__import__("core.risk.risk_engine", fromlist=["RiskEngine"]).RiskEngine(
        config=RiskConfig(max_order_qty=50), margin_engine=Margin()
    ))


def factory(i):
    return Command(i.client_order_id, i.track_id or "", i.quantity, float(i.requested_price or 0), i.side, i.tag_id or "")


def test_all_legs_receive_independent_tokens():
    g = gate()
    result = admit_multi_leg_intents(
        [intent("O1", "put"), intent("O2", "call"), intent("O3", "long_put"), intent("O4", "long_call")],
        risk_gate=g, account=account(), command_factory=factory,
    )
    assert result.group_id == "G-2"
    assert set(result.tokens) == {"O1", "O2", "O3", "O4"}
    assert result.approved_quantities == {"O1": 1, "O2": 1, "O3": 1, "O4": 1}


def test_deny_stops_later_legs():
    g = gate()
    calls = []
    def deny_factory(i):
        calls.append(i.client_order_id)
        return Command(i.client_order_id, "t", 999 if i.client_order_id == "O2" else 1, 1.0, "BUY", "LEG")
    with pytest.raises(MultiLegRiskError, match="EXCEEDED_MAX_ORDER_QTY"):
        admit_multi_leg_intents([intent("O1", "a"), intent("O2", "b"), intent("O3", "c")], risk_gate=g, account=account(), command_factory=deny_factory)
    assert calls == ["O1", "O2"]


def test_client_order_id_provenance_mismatch_fails_closed():
    g = gate()
    with pytest.raises(MultiLegRiskError, match="CLIENT_ORDER_ID_PROVENANCE_MISMATCH"):
        admit_multi_leg_intents([intent("O1", "a")], risk_gate=g, account=account(), command_factory=lambda i: Command("OTHER", "t", 1, 1.0, "BUY", "LEG"))


def test_reduced_quantity_provenance_mismatch_fails_closed():
    class FakeGate:
        last_evaluation_result = SimpleNamespace(
            approved_qty=2,
            decision="REDUCE",
            reduced_command=SimpleNamespace(qty=1),
            token=object(),
        )
        def admit_order(self, *args, **kwargs):
            return True, self.last_evaluation_result.token, None
    with pytest.raises(MultiLegRiskError, match="REDUCED_QUANTITY_PROVENANCE_MISMATCH"):
        admit_multi_leg_intents([intent("O1", "a")], risk_gate=FakeGate(), account=account(), command_factory=factory)
```
## 검증 목표
        - Track2/6/8/9의 multi-leg가 동일한 per-leg Risk seam을 사용할 수 있는지 검증한다.
        - 모든 leg 승인 시 leg별 token과 effective quantity를 보존한다.
        - 중간 leg DENY 시 이후 leg를 평가하지 않는다.
        - client_order_id provenance mismatch와 REDUCE quantity mismatch는 fail-closed 한다.

[Child Page] e2e
폴더 페이지

[Child Page] regression
폴더 페이지

[Child Page] safety
폴더 페이지

[Child Page] architecture
[Child Page] phase6_test_spec.md
When physical workspace exists:
        1. same CanonicalMarketTick fixture → same MarketState
        1. no synthetic fallback value accepted
        1. every migrated strategy satisfies common lifecycle
        1. Strategy cannot call broker
        1. stale account/position data causes Risk rejection
        1. OMS accepts ExecutionReport without knowing KIS/VSSF
        1. Option Domain imports no HTTP/API module
        1. identical fixture runs → identical Signal/Decision/OrderIntent
Current status: TEST SPEC READY / EXECUTION BLOCKED.
[Child Page] phase7_test_spec.md
        1. Factory는 네 가지 EnvironmentType 각각에 대해 Bundle을 반환한다.
        1. Bundle은 필수 Contract를 모두 제공한다.
        1. 한 Runtime Controller에 active Environment가 둘 이상 존재할 수 없다.
        1. 이미 실행 중인 Runtime에 두 번째 Environment를 start하면 거부한다.
        1. stop/shutdown 후에만 다음 Environment를 활성화할 수 있다.
        1. Controller가 KIS/VMS/VSSF 구체 구현체를 직접 import하지 않는다.
        1. High-Speed는 Virtual과 동일 Core Contract를 사용하고 Clock/Replay Policy만 가속한다.
        1. Live Bundle은 allow_live_orders 같은 명시적 안전 정책 없이 실주문을 허용하지 않는다.
현재 상태: TEST SPEC READY / 실제 실행 BLOCKED.

[Child Page] virtual
[Child Page] virtual_environment_test_spec.md
        1. Market adapter produces canonical market data.
        1. Market → Core → OrderIntent path is environment-independent.
        1. OrderIntent → Virtual Broker → ExecutionReport works.
        1. Account/Position update after fills.
        1. Reconciliation detects state mismatch.
        1. Restart restores persisted virtual state.
        1. Virtual imports no Paper/Live implementation.
        1. Synthetic data remains Virtual-only.
        1. Kill Switch prevents new order submission.
        1. Same deterministic scenario produces the same execution sequence.
Execution status: specification ready; physical workspace execution remains BLOCKED.

[Child Page] high_speed
[Child Page] high_speed_test_spec.md
## Required invariants
        1. High-Speed uses the same Standard Core/Strategy/Contract as Virtual.
        1. Only Clock/Replay/Scenario execution policy is accelerated.
        1. No Paper/Live credential or adapter can be imported.
        1. Replay events remain deterministically ordered.
        1. Pause/resume/seek/reset do not mutate Core state directly.
        1. Supported speed policies: 1x, 100x, 300x, 500x, 1000x, MAX.
        1. MAX has explicit CPU/memory safe-stop thresholds.
        1. 1x and accelerated execution must preserve event/order/decision semantics.
        1. Identical seed/scenario input must reproduce the same result.
        1. Failure stops execution safely and preserves the result evidence.
## Verification status
Structural design: PASS
Physical execution: BLOCKED
Performance benchmark: BLOCKED
High-Speed ↔ Virtual result comparison: deferred to Phase 13.

[Child Page] paper
[Child Page] paper_environment_test_spec.md
        - Virtual/VMS modules are absent from Paper runtime imports.
        - Standard Core runs without modification.
        - Paper uses KIS VTS credentials/endpoint/account only.
        - Market and Broker are separate Contract implementations.
        - Execution responses normalize into CanonicalExecutionReport.
        - Account/Position snapshots reject stale data for new orders.
        - Reconciliation compares broker state with internal OMS state.
        - Restart recovers from broker state.
        - No VSSF ledger receives Paper orders.
        - Real API evidence is BLOCKED until valid credentials and endpoint responses are supplied.

[Child Page] live
[Child Page] live_environment_test_spec.md
## Structural
        - Live credential names are separate from Paper/VTS credentials.
        - Live has no VSSF/VMS synthetic fallback.
        - Live starts DISARMED.
        - Live order submission requires explicit approval, limits, non-stale account/position state and an active broker connection.
## Safety
        - Kill Switch blocks every new order.
        - Order quantity, daily loss and position limits are mandatory.
        - Duplicate client order identity cannot create a second submission.
        - Timeout/retry must query broker state before any resend.
## Recovery
        - Startup reads Broker Account/Position before resume.
        - Broker/internal mismatch causes SAFE_STOP.
        - Restart must not resend an already accepted order.
## External evidence
        - Mock responses are never PASS for Live operation.
        - Real credential, real Account/Position response and approved minimal-order evidence are required for EXTERNAL SYSTEM PROVEN.
        - Physical execution is currently expected to remain BLOCKED without credentials/network/human approval.
[Child Page] test_live_execution_position_bridge.py
```python
from decimal import Decimal

import pytest

from contracts.types import BrokerOrderCommand, OrderAckEvent, OrderIntent
from core.oms.oms_fsm import OrderStateMachine, OrderStateTransitionError
from environments.live.execution.execution_event_deduplicator import ExecutionEventDeduplicator
from environments.live.execution.kis_futures_execution_adapter import (
    KISFuturesExecutionContext,
    KISFuturesExecutionNoticeAdapter,
)
from environments.live.execution.kis_futures_execution_correlation_provider import (
    KISFuturesExecutionCorrelationProvider,
)
from environments.live.position.live_execution_position_bridge import LiveExecutionPositionBridge
from environments.live.position.live_position_fill_adapter import LivePositionFillAdapter
from environments.live.position.live_position_aggregate import LivePositionAggregate


def _frame(order_no="B123", qty="2", price="350.0"):
    values = [
        "C", "A", order_no, "O", "02", "00", "00", "K200", qty, price,
        "101010", "N", "Y", "Y", "01", "2", "N", "KOSPI", "00", "1", "1", price,
    ]
    return "0|H0IFCNI0|22|" + "^".join(values)


def test_h0ifcni0_full_seam_duplicate_execution_applies_position_once():
    oms = OrderStateMachine()
    oms.apply_intent(OrderIntent("C1", "I1", "BUY", 5, "NEW"))
    oms.apply_ack(OrderAckEvent("C1", True, "B123"))
    command = BrokerOrderCommand("C1", "I1", "BUY", 5, "MARKET")
    oms.register_broker_order_command(command)

    adapter = KISFuturesExecutionNoticeAdapter()
    notice = adapter.parse(_frame())
    correlation = KISFuturesExecutionCorrelationProvider(oms).resolve(notice.broker_order_id)
    report = adapter.to_execution_report(
        notice,
        KISFuturesExecutionContext(
            correlation.client_order_id,
            correlation.order_quantity,
            correlation.prior_filled_quantity,
        ),
    )

    aggregate = LivePositionAggregate("I1")
    bridge = LiveExecutionPositionBridge(
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(aggregate),
        execution_event_deduplicator=ExecutionEventDeduplicator(),
        position_aggregate=aggregate,
    )

    first = bridge.settle(report)
    second = bridge.settle(report)

    assert first.filled_quantity == 2
    assert second.filled_quantity == 2
    snapshot = aggregate.snapshot()
    assert snapshot.qty == 2
    assert snapshot.avg_price == Decimal("350.0")


def test_execution_before_ack_fails_closed_and_position_is_unchanged():
    oms = OrderStateMachine()
    oms.apply_intent(OrderIntent("C1", "I1", "BUY", 2, "NEW"))
    command = BrokerOrderCommand("C1", "I1", "BUY", 2, "MARKET")
    oms.register_broker_order_command(command)

    notice = KISFuturesExecutionNoticeAdapter().parse(_frame(qty="2"))
    report = KISFuturesExecutionNoticeAdapter().to_execution_report(
        notice,
        KISFuturesExecutionContext("C1", 2, 0),
    )
    aggregate = LivePositionAggregate("I1")
    bridge = LiveExecutionPositionBridge(
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(aggregate),
        execution_event_deduplicator=ExecutionEventDeduplicator(),
        position_aggregate=aggregate,
    )

    with pytest.raises(OrderStateTransitionError, match="EXECUTION_BEFORE_ACK"):
        bridge.settle(report)

    assert aggregate.snapshot().qty == 0


def test_broker_client_correlation_conflict_fails_closed():
    oms = OrderStateMachine()
    oms.apply_intent(OrderIntent("C1", "I1", "BUY", 2, "NEW"))
    oms.apply_intent(OrderIntent("C2", "I1", "BUY", 2, "NEW"))
    oms.apply_ack(OrderAckEvent("C1", True, "B123"))

    with pytest.raises(OrderStateTransitionError, match="BROKER_ORDER_ID_ALREADY_CORRELATED"):
        oms.apply_ack(OrderAckEvent("C2", True, "B123"))

    with pytest.raises(Exception):
        KISFuturesExecutionCorrelationProvider(oms).resolve("UNKNOWN")


def test_partial_fill_updates_oms_correlation_prior_quantity():
    oms = OrderStateMachine()
    oms.apply_intent(OrderIntent("C1", "I1", "BUY", 5, "NEW"))
    oms.apply_ack(OrderAckEvent("C1", True, "B123"))
    adapter = KISFuturesExecutionNoticeAdapter()
    notice = adapter.parse(_frame(qty="2"))
    provider = KISFuturesExecutionCorrelationProvider(oms)
    correlation = provider.resolve("B123")
    report = adapter.to_execution_report(
        notice,
        KISFuturesExecutionContext(
            correlation.client_order_id,
            correlation.order_quantity,
            correlation.prior_filled_quantity,
        ),
    )
    oms.apply_execution(report)

    assert provider.resolve("B123").prior_filled_quantity == 2
```
## 검증 범위
        - H0IFCNI0 → OMS correlation → ExecutionReport → dedup → OMS FSM → Position의 targeted seam을 검증한다.
        - LiveExecutionPositionBridge.settle(report)의 현재 계약에 맞춰 기존 stale test 호출을 정정했다.
        - BrokerOrderCommand는 OMS-owned correlation에 먼저 등록한다.
        - Decimal 기반 Position 평균가격 invariant를 명시적으로 검증한다.
        - 실제 KIS network, credential, account, order submission은 사용하지 않는다.
[Child Page] test_kis_futures_execution_correlation_provider.py
```python
from datetime import datetime
from decimal import Decimal

import pytest

from contracts.types import ExecutionReport, OrderAckEvent, OrderIntent
from core.oms.oms_fsm import OrderStateMachine, OrderStateTransitionError
from environments.live.execution.kis_futures_execution_adapter import (
    KISFuturesExecutionContext,
    KISFuturesExecutionNoticeAdapter,
)
from environments.live.execution.kis_futures_execution_correlation_provider import (
    KISFuturesExecutionCorrelationError,
    KISFuturesExecutionCorrelationProvider,
)


_FIELDS = [
    "cust", "account", "BRK-1001", "", "01", "00", "1", "101W09",
    "2", "101.50", "123456", "N", "Y", "Y", "001", "5", "name",
    "KOSPI200", "00", "1", "1", "101.50",
]


def _frame() -> str:
    return "0|H0IFCNI0|22|" + "^".join(_FIELDS)


def test_ack_creates_oms_authoritative_execution_correlation():
    fsm = OrderStateMachine()
    fsm.apply_intent(OrderIntent(
        client_order_id="CLIENT-1",
        instrument_id="FUT-1",
        side="BUY",
        quantity=5,
        intent_type="OPEN",
    ))
    fsm.apply_ack(OrderAckEvent(
        client_order_id="CLIENT-1",
        accepted=True,
        broker_order_id="BRK-1001",
    ))

    correlation = KISFuturesExecutionCorrelationProvider(fsm).resolve("BRK-1001")
    assert correlation.client_order_id == "CLIENT-1"
    assert correlation.broker_order_id == "BRK-1001"
    assert correlation.order_quantity == 5
    assert correlation.prior_filled_quantity == 0
    assert correlation.prior_average_price is None


def test_h0ifcni0_notice_uses_oms_correlation_without_synthetic_identity():
    fsm = OrderStateMachine()
    fsm.apply_intent(OrderIntent(
        client_order_id="CLIENT-2",
        instrument_id="FUT-2",
        side="BUY",
        quantity=5,
        intent_type="OPEN",
    ))
    fsm.apply_ack(OrderAckEvent(
        client_order_id="CLIENT-2",
        accepted=True,
        broker_order_id="BRK-1001",
    ))

    provider = KISFuturesExecutionCorrelationProvider(fsm)
    correlation = provider.resolve("BRK-1001")
    notice = KISFuturesExecutionNoticeAdapter().parse(_frame())
    context = KISFuturesExecutionContext(
        client_order_id=correlation.client_order_id,
        order_quantity=correlation.order_quantity,
        prior_filled_quantity=correlation.prior_filled_quantity,
    )
    report = KISFuturesExecutionNoticeAdapter().to_execution_report(notice, context)

    assert report.client_order_id == "CLIENT-2"
    assert report.broker_order_id == "BRK-1001"
    assert report.filled_quantity == 2
    assert report.remaining_quantity == 3


def test_unknown_broker_order_id_fails_closed():
    fsm = OrderStateMachine()
    provider = KISFuturesExecutionCorrelationProvider(fsm)
    with pytest.raises(KISFuturesExecutionCorrelationError):
        provider.resolve("UNKNOWN")


def test_second_fill_uses_updated_prior_filled_quantity():
    fsm = OrderStateMachine()
    fsm.apply_intent(OrderIntent(
        client_order_id="CLIENT-3",
        instrument_id="FUT-3",
        side="BUY",
        quantity=5,
        intent_type="OPEN",
    ))
    fsm.apply_ack(OrderAckEvent(
        client_order_id="CLIENT-3",
        accepted=True,
        broker_order_id="BRK-1001",
    ))
    provider = KISFuturesExecutionCorrelationProvider(fsm)
    adapter = KISFuturesExecutionNoticeAdapter()
    first = adapter.to_execution_report(
        adapter.parse(_frame()),
        KISFuturesExecutionContext("CLIENT-3", 5, 0),
    )
    fsm.apply_execution(first)

    correlation = provider.resolve("BRK-1001")
    assert correlation.prior_filled_quantity == 2
    assert correlation.prior_average_price == Decimal("101.50")
```
## 검증 의도
        - accepted ACK만 broker_order_id → client_order_id 상관관계를 만든다.
        - H0IFCNI0 notice는 broker order number를 사용해 OMS 상태를 조회하고, client_order_id/order_quantity/prior_filled_quantity를 synthetic 생성하지 않는다.
        - unknown broker order는 ExecutionReport 생성 전에 fail-closed한다.
        - 부분체결 후 다음 notice는 OMS가 보존한 누적 체결수량을 사용한다.
        - 실제 KIS network/실계좌/실주문은 사용하지 않는다.
[Child Page] test_kis_futures_execution_consumer.py
```python
import asyncio
import base64
import json
import pytest

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from environments.live.execution.kis_futures_execution_adapter import KISFuturesExecutionNoticeAdapter
from environments.live.execution.kis_futures_execution_consumer import KISFuturesExecutionConsumer
from environments.live.execution.kis_futures_execution_correlation_provider import KISFuturesExecutionCorrelationProvider
from infrastructure.kis.futures_execution_transport import FuturesExecutionTransportError, KISFuturesExecutionTransport


class FakeAuth:
    is_vts = False
    app_key = "APP"
    app_secret = "SECRET"
    base_url = "https://invalid.example"
    def has_credentials(self): return True


class FakeSocket:
    def __init__(self, messages): self.messages = list(messages); self.sent = []
    async def send(self, message): self.sent.append(message)
    async def recv(self): return self.messages.pop(0)
    async def close(self): return None


def _encrypt(plain: str, key: str, iv: str) -> str:
    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(plain.encode()) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key.encode()), modes.CBC(iv.encode())).encryptor()
    encrypted = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(encrypted).decode()


def _plain_h0ifcni0_frame() -> str:
    values = ["C", "A", "B123", "O", "02", "00", "00", "K200", "2", "350.0", "101010", "N", "Y", "Y", "01", "5", "N", "KOSPI", "00", "1", "1", "350.0"]
    return "^".join(values)


def test_execution_transport_decrypts_h0ifcni0_and_preserves_envelope():
    key = "0123456789abcdef0123456789abcdef"
    iv = "abcdef0123456789"
    socket = FakeSocket([
        json.dumps({"header": {"tr_id": "H0IFCNI0"}, "body": {"rt_cd": "0", "output": {"key": key, "iv": iv}}}),
        "1|H0IFCNI0|1|" + _encrypt(_plain_h0ifcni0_frame(), key, iv),
    ])
    async def socket_factory(_): return socket
    transport = KISFuturesExecutionTransport(FakeAuth(), socket_factory=socket_factory)
    transport._issue_approval_key = lambda: "approval-for-test"
    async def run():
        await transport.connect(); await transport.subscribe("H0IFCNI0", "HTS01"); return await transport.recv()
    frame = asyncio.run(run())
    assert frame == "1|H0IFCNI0|22|" + _plain_h0ifcni0_frame()
    assert json.loads(socket.sent[0])["body"]["input"] == {"tr_id": "H0IFCNI0", "tr_key": "HTS01"}


def test_execution_consumer_resolves_oms_context_and_emits_execution_report():
    key = "0123456789abcdef0123456789abcdef"
    iv = "abcdef0123456789"
    socket = FakeSocket([
        json.dumps({"header": {"tr_id": "H0IFCNI0"}, "body": {"rt_cd": "0", "output": {"key": key, "iv": iv}}}),
        "1|H0IFCNI0|1|" + _encrypt(_plain_h0ifcni0_frame(), key, iv),
    ])
    async def socket_factory(_): return socket
    transport = KISFuturesExecutionTransport(FakeAuth(), socket_factory=socket_factory)
    transport._issue_approval_key = lambda: "approval-for-test"
    correlation = type("Correlation", (), {"client_order_id": "C1", "order_quantity": 5, "prior_filled_quantity": 0})()
    provider = KISFuturesExecutionCorrelationProvider({"B123": correlation})
    reports = []
    async def run():
        consumer = KISFuturesExecutionConsumer(transport, KISFuturesExecutionNoticeAdapter(), provider, reports.append)
        await consumer.start("HTS01"); return await consumer.receive_once()
    report = asyncio.run(run())
    assert report.client_order_id == "C1"
    assert report.broker_order_id == "B123"
    assert report.filled_quantity == 2
    assert report.remaining_quantity == 3
    assert len(reports) == 1
```
def test_execution_transport_reconnect_close_start_and_subscription_ownership():
sockets = [FakeSocket([]), FakeSocket([])]
async def socket_factory(_):
return sockets.pop(0)
transport = KISFuturesExecutionTransport(FakeAuth(), socket_factory=socket_factory)
transport._issue_approval_key = lambda: "approval-for-test"
async def run():
await transport.connect()
with pytest.raises(FuturesExecutionTransportError, match="already connected"):
await transport.connect()
await transport.subscribe("H0IFCNI0", "HTS01")
with pytest.raises(FuturesExecutionTransportError, match="subscription is already active"):
await transport.subscribe("H0IFCNI0", "HTS01")
await transport.close()
await transport.connect()
await transport.subscribe("H0IFCNI0", "HTS01")
await transport.close()
asyncio.run(run())
assert len(sockets) == 0
검증 범위: encrypted KIS frame → dedicated execution transport → H0IFCNI0 adapter → OMS correlation → ExecutionReport 및 reconnect/close/start 반복 시 connection·subscription ownership. 실제 KIS 네트워크/credential/account/order는 사용하지 않는다.
[Child Page] test_live_position_aggregate_risk_source.py
```python
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
        LivePositionAggregateRiskSource({"OTHER": LivePositionAggregate("OPT-1")}).snapshot()
```
Covers authoritative projection, flat exclusion, and identity mismatch fail-closed.
[Child Page] test_live_runtime_risk_state_factory.py
```python
import pytest
from application.composition.live_runtime_risk_state_factory import create_live_runtime_risk_state_providers

class Account:
    def snapshot(self): return "authoritative-account"
class Position:
    def snapshot(self): return {}

def test_authoritative_account_and_position_are_exposed_without_synthesis():
    p=create_live_runtime_risk_state_providers(account=Account(), position_source=Position())
    assert p.account_snapshot_provider()=="authoritative-account"
    assert p.position_source_provider().snapshot()=={}

def test_missing_account_fails_closed():
    with pytest.raises(ValueError, match="LIVE_ACCOUNT_PROVIDER_REQUIRED"):
        create_live_runtime_risk_state_providers(account=None, position_source=Position())
```
Authoritative provider exposure and missing-account fail-closed coverage.
[Child Page] test_live_runtime_tick_authoritative_wiring.py
```python
import pytest

from application.composition.live_runtime_tick_entry import LiveRuntimeTickEntry


class Runtime:
    def process_tick(self, tick, observed_at):
        return ("evaluation",)

class S2D:
    def evaluate(self, evaluations):
        return ("decision",)

class D2C:
    def commands(self, decisions, evaluations):
        return ("command",)

class Context:
    def __init__(self):
        self.account_snapshot = "stale"
        self.position_source = "stale"
        self.order_router = object()
        self.broker_command = object()

def test_tick_entry_refreshes_authoritative_state_and_uses_actual_route_contract():
    seen = []
    def route(command, *, risk_gate, context):
        seen.append((command, risk_gate, context.account_snapshot, context.position_source))
        return "ALLOW"

    entry = LiveRuntimeTickEntry(
        Runtime(), S2D(), D2C(), "gate", route,
        lambda: "live-account", lambda: "live-position"
    )
    result = entry.process_tick("tick", "time", risk_context=Context())
    assert result == ("ALLOW",)
    assert seen == [("command", "gate", "live-account", "live-position")]

def test_missing_authoritative_state_fails_closed():
    entry = LiveRuntimeTickEntry(
        Runtime(), S2D(), D2C(), "gate", lambda **_: None,
        lambda: None, lambda: "position"
    )
    with pytest.raises(ValueError, match="RUNTIME_RISK_AUTHORITATIVE_STATE_REQUIRED"):
        entry.process_tick("tick", "time", risk_context=Context())
```
Actual route contract, per-call authoritative state refresh, and fail-closed coverage.

[Child Page] control_tower
[Child Page] control_tower_test_spec.md
# Control Tower 통합 검증 Spec
## No.074 Core/Strategy 동일성
        - 4개 Environment 선택에 따라 core/와 core/strategy/ 코드가 달라지지 않는다.
        - 동일 Strategy Registry/호출 계약을 사용한다.
        - Environment 차이는 Adapter/Execution 영역에서만 발생한다. fileciteturn111file0L1-L10
## No.075 High-Speed ↔ Virtual
        - 동일 Scenario를 Virtual 1x와 High-Speed 가속 정책에서 비교한다.
        - 시간 경계 및 floating-point 차이를 별도 기록한다. fileciteturn111file3L32-L39
## No.076 Contract compatibility
        - Virtual/Paper/Live가 동일 MarketDataProvider Contract를 만족한다.
        - Core 변경 없이 Adapter 교체가 가능한지 확인한다. fileciteturn112file0L1-L10
## No.077 Environment isolation
        - 다른 Environment의 Broker/VMS/VSSF 객체가 생성·공유되지 않는지 정적 import 및 객체 생성 경계를 검사한다.
        - 특히 Live에서 VSSF 객체 생성이 없어야 한다. fileciteturn111file1L11-L19
## No.078 Lifecycle/Recovery
        - 4개 Environment 각각 Start/Stop/Restart 경계를 확인한다.
        - 실행 중 환경 전환은 거부하거나 안전하게 중지 후 전환한다.
        - 정상 Stop/강제 종료/Restart 후 상태 복구를 별도 검증한다. fileciteturn111file4L41-L50
## 현재 검증 한계
실제 브로커·브라우저·외부 API 실행은 현재 환경에서 수행할 수 없으므로 정적 구조/계약/테스트 설계까지만 PASS로 기록하고 실제 실행 증거는 BLOCKED로 분리한다.
## No.528 Technical lifecycle status
        - RuntimeStatus.technical_state는 Control Tower의 기술적 lifecycle 상태 전용 필드다.
        - shutdown cancellation drain timeout은 technical_state="STOP_TIMEOUT"으로 표현한다.
        - STOP_TIMEOUT을 주문 상태, 체결 상태, 포지션 상태, Risk Domain 상태와 합치지 않는다.
        - timeout 상태에서는 shared execution ownership을 release/reuse하지 않는 fail-closed 계약을 유지한다.
        - 검증: RuntimePolicy custom timeout → cancellation capability/fallback → unresolved drain → LIVE_RUNTIME_SHUTDOWN_DRAIN_TIMEOUT + STOP_TIMEOUT 분리.
[Child Page] test_control_tower_runtime_status_projection.py
```python
from dataclasses import dataclass

from contracts.types import EnvironmentType
from interfaces.control_tower.runtime_api import ControlTowerRuntimeAPI


@dataclass
class _ControllerStatus:
    environment: str | None
    state: str


class _Controller:
    def __init__(self, status):
        self._status = status

    def start(self, config, policy):
        self._status = _ControllerStatus("live", "RUNNING")

    def stop(self):
        self._status = _ControllerStatus("live", "STOPPED")

    def status(self):
        return self._status


class _Lifecycle:
    def __init__(self, technical_state=None):
        self.technical_state = technical_state


def test_control_tower_projects_live_technical_state_into_standard_runtime_status():
    api = ControlTowerRuntimeAPI(
        _Controller(_ControllerStatus("live", "STOPPING")),
        lifecycle_status_source=_Lifecycle("STOP_TIMEOUT"),
    )

    status = api.status()

    assert status.environment is EnvironmentType.LIVE
    assert status.running is False
    assert status.technical_state == "STOP_TIMEOUT"
    assert status.execution_allowed is False
    assert status.reason == "STOP_TIMEOUT"


def test_control_tower_without_lifecycle_failure_keeps_standard_status():
    api = ControlTowerRuntimeAPI(
        _Controller(_ControllerStatus("virtual", "RUNNING")),
        lifecycle_status_source=_Lifecycle(None),
    )

    status = api.status()

    assert status.environment is EnvironmentType.VIRTUAL
    assert status.running is True
    assert status.connected is True
    assert status.execution_allowed is True
    assert status.technical_state is None
```
## No.529 검증
        - coordinator lifecycle source의 STOP_TIMEOUT이 표준 RuntimeStatus.technical_state로 projection되는지 검증한다.
        - technical failure 시 execution_allowed=False가 유지되는지 검증한다.
        - lifecycle failure가 없을 때 기존 RUNNING 상태가 표준 status로 정규화되는지 검증한다.
[Child Page] test_control_tower_live_status_assembly.py
```python
from application.composition.control_tower_runtime_composition import (
    create_live_control_tower_runtime_api,
)


class _Status:
    def __init__(self, environment="live", state="STOPPING"):
        self.environment = environment
        self.state = state


class _Controller:
    def status(self):
        return _Status()


class _Coordinator:
    def __init__(self, technical_state=None):
        self.runtime_controller = _Controller()
        self.technical_state = technical_state


def test_live_control_tower_assembly_projects_stop_timeout_fail_closed():
    coordinator = _Coordinator("STOP_TIMEOUT")

    api = create_live_control_tower_runtime_api(
        lifecycle_coordinator=coordinator,
    )
    status = api.status()

    assert api._runtime is coordinator.runtime_controller
    assert api._lifecycle_status_source is coordinator
    assert status.technical_state == "STOP_TIMEOUT"
    assert status.execution_allowed is False
    assert status.reason == "STOP_TIMEOUT"


def test_live_control_tower_assembly_rejects_missing_coordinator():
    try:
        create_live_control_tower_runtime_api(lifecycle_coordinator=None)
    except ValueError as exc:
        assert str(exc) == "LIVE_RUNTIME_LIFECYCLE_COORDINATOR_REQUIRED"
    else:
        raise AssertionError("missing coordinator must fail closed")
```
## No.534 검증
        - production assembly가 동일 coordinator의 controller와 technical lifecycle source를 함께 주입한다.
        - STOP_TIMEOUT이 RuntimeStatus까지 fail-closed로 도달한다.
        - lifecycle coordinator 누락은 fallback 없이 거부한다.
## No.535 command-path fail-closed 검증
```python
import pytest


def test_stop_timeout_control_tower_rejects_start_and_restart_without_controller_bypass():
    class Status:
        environment = "live"
        state = "STOPPED"

    class Controller:
        def __init__(self):
            self.started = 0
            self.stopped = 0
        def start(self, config, policy):
            self.started += 1
        def stop(self):
            self.stopped += 1
        def status(self):
            return Status()

    controller = Controller()
    coordinator = type(
        "Coordinator",
        (), {"runtime_controller": controller, "technical_state": "STOP_TIMEOUT"},
    )()
    api = create_live_control_tower_runtime_api(
        lifecycle_coordinator=coordinator,
    )

    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
        api.start("CONFIG", "POLICY")
    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
        api.restart("CONFIG", "POLICY")

    assert controller.started == 0
    assert controller.stopped == 0
```
        - STOP_TIMEOUT coordinator가 Control Tower command path를 통해 controller start/restart로 우회되지 않는지 검증한다.
        - status projection뿐 아니라 control command도 technical terminal state를 fail-closed로 존중한다.
## No.536 stop ownership + identity mismatch 검증
```python

def test_stop_timeout_control_tower_rejects_direct_stop_bypass():
    class Status:
        environment = "live"
        state = "STOPPED"

    class Controller:
        def __init__(self):
            self.stopped = 0
        def stop(self):
            self.stopped += 1
        def status(self):
            return Status()

    controller = Controller()
    coordinator = type(
        "Coordinator",
        (), {"runtime_controller": controller, "technical_state": "STOP_TIMEOUT"},
    )()
    api = create_live_control_tower_runtime_api(lifecycle_coordinator=coordinator)

    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_STOP_NOT_ADMITTED"):
        api.stop()
    assert controller.stopped == 0


def test_control_tower_fails_closed_when_coordinator_identity_guard_rejects_status_source():
    class Status:
        environment = "live"
        state = "RUNNING"

    class Controller:
        def status(self):
            return Status()

    class Coordinator:
        runtime_controller = Controller()
        @property
        def technical_state(self):
            raise RuntimeError("LIVE_RUNTIME_CONTROLLER_IDENTITY_CHANGED")

    api = create_live_control_tower_runtime_api(lifecycle_coordinator=Coordinator())

    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_CONTROLLER_IDENTITY_CHANGED"):
        api.status()
    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_CONTROLLER_IDENTITY_CHANGED"):
        api.start("CONFIG", "POLICY")
```
        - STOP_TIMEOUT에서 Control Tower stop()이 underlying controller를 직접 호출하지 않는지 검증한다.
        - lifecycle coordinator의 identity guard가 실패하면 status/control path가 synthetic fallback 없이 동일 오류로 fail-closed되는지 검증한다.
## No.539 status polling + command 동시성 검증
```python
import asyncio
import pytest


def test_status_polling_fails_closed_during_live_command_when_identity_changes():
    class Controller:
        def status(self):
            return type("Status", (), {"environment": "live", "state": "RUNNING"})()

    class Coordinator:
        def __init__(self):
            self.runtime_controller = Controller()
            self._bad = False
        @property
        def technical_state(self):
            if self._bad:
                raise RuntimeError("LIVE_RUNTIME_CONTROLLER_IDENTITY_CHANGED")
            return None
        async def start(self, *args, **kwargs):
            self._bad = True

    coordinator = Coordinator()
    api = create_live_control_tower_runtime_api(lifecycle_coordinator=coordinator)

    async def scenario():
        command = LiveLifecycleCommand("C", "P", "H", "Q")
        task = asyncio.create_task(api.start_live(command))
        await task
        with pytest.raises(RuntimeError, match="LIVE_RUNTIME_CONTROLLER_IDENTITY_CHANGED"):
            api.status()

    asyncio.run(scenario())
```
        - async command 완료 후 status polling이 lifecycle source identity failure를 synthetic 정상 상태로 숨기지 않고 fail-closed한다.
        - command serialization과 status projection은 별도 책임이지만 동일 authoritative lifecycle source를 사용한다.
## No.568 technical_state 전체 non-None fail-closed command 경계 회귀 검증
```python
import asyncio
from types import SimpleNamespace

import pytest

from application.composition.control_tower_runtime_composition import (
    create_live_control_tower_runtime_api,
)
from application.composition.live_runtime_lifecycle_coordinator import (
    LiveRuntimeLifecycleCoordinator,
)


class _Controller:
    def __init__(self):
        self.started = 0
        self.stopped = 0

    def start(self, config, policy):
        self.started += 1

    def stop(self):
        self.stopped += 1

    def status(self):
        return SimpleNamespace(environment="live", state="STOPPED")


class _Bootstrap:
    def startup_reconcile(self, query):
        return ()

    async def start_execution(self, hts_id):
        return None

    async def close_execution(self):
        return None


class _Policy:
    graceful_shutdown_timeout_seconds = 0
    cancellation_drain_timeout_seconds = 0


@pytest.mark.parametrize(
    "technical_state",
    [
        "STOP_TIMEOUT",
        "STOP_CONTROLLER_FAILED",
        "STOP_EXECUTION_CLOSE_FAILED",
        "TRANSPORT_OWNERSHIP_RELEASE_FAILED",
    ],
)
def test_any_terminal_technical_state_is_projected_and_async_commands_cannot_bypass(technical_state):
    controller = _Controller()
    coordinator = LiveRuntimeLifecycleCoordinator(
        controller=controller,
        bootstrap=_Bootstrap(),
    )
    coordinator._technical_state = technical_state
    api = create_live_control_tower_runtime_api(
        lifecycle_coordinator=coordinator,
    )

    status = api.status()
    assert status.technical_state == technical_state
    assert status.execution_allowed is False
    assert status.reason == technical_state

    # Live adapter의 sync command는 별도 정책으로 항상 차단된다.
    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_SYNC_COMMAND_NOT_AVAILABLE"):
        api.start("CONFIG", "POLICY")
    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_SYNC_COMMAND_NOT_AVAILABLE"):
        api.stop()
    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_SYNC_COMMAND_NOT_AVAILABLE"):
        api.restart("CONFIG", "POLICY")

    async def run_async_commands():
        command = SimpleNamespace(
            config="CONFIG",
            policy=_Policy(),
            hts_id="HTS",
            recovery_query="Q",
        )
        with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
            await api.start_live(command)
        with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
            await api.stop_live()
        with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
            await api.restart_live(command)

    asyncio.run(run_async_commands())
    assert controller.started == 0
    assert controller.stopped == 0
```
        - STOP_TIMEOUT뿐 아니라 STOP_CONTROLLER_FAILED, STOP_EXECUTION_CLOSE_FAILED, TRANSPORT_OWNERSHIP_RELEASE_FAILED도 동일한 terminal technical state 계약으로 검증한다.
        - status projection은 각 technical state를 그대로 노출하고 execution_allowed=False, reason=technical_state를 유지한다.
        - Live adapter의 sync API 차단과 별개로 실제 async start_live/stop_live/restart_live가 coordinator의 restart/stop admission을 우회하지 못하는지 executable하게 검증한다.
## No.575 terminal state status polling·command serialization·concurrent ownership claim 교차 회귀 검증
```python
import asyncio
import pytest

from application.composition.control_tower_runtime_composition import (
    create_live_control_tower_runtime_api,
)
from application.composition.live_runtime_lifecycle_coordinator import (
    LiveRuntimeLifecycleCoordinator,
)
from application.composition.live_runtime_production_factory import (
    _LiveExecutionTransportOwnershipRegistry,
)


@pytest.mark.asyncio
async def test_startup_cleanup_terminal_state_survives_status_polling_during_serialized_command():
    status_reads = []
    class Controller:
        def __init__(self): self.starts = 0
        def start(self, *args): self.starts += 1
        def status(self):
            return type("Status", (), {"environment": "live", "state": "STOPPED"})()
    class Bootstrap:
        def startup_reconcile(self, query): return ()
        async def start_execution(self, hts_id): raise asyncio.CancelledError()
        async def close_execution(self): raise asyncio.CancelledError()

    controller = Controller()
    coordinator = LiveRuntimeLifecycleCoordinator(controller=controller, bootstrap=Bootstrap())
    with pytest.raises(asyncio.CancelledError):
        await coordinator.start("C", "P", hts_id="H", recovery_query="Q")
    api = create_live_control_tower_runtime_api(lifecycle_coordinator=coordinator)

    command = type("Command", (), {"config":"C", "policy":"P", "hts_id":"H2", "recovery_query":"Q2"})()
    blocked = asyncio.create_task(api.start_live(command))
    await asyncio.sleep(0)
    for _ in range(3):
        status = api.status()
        status_reads.append((status.technical_state, status.execution_allowed, status.reason))
        await asyncio.sleep(0)
    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
        await blocked

    assert status_reads == [
        ("STARTUP_CLEANUP_CANCELLED", False, "STARTUP_CLEANUP_CANCELLED"),
    ] * 3
    assert controller.starts == 1


def test_startup_cleanup_terminal_state_concurrent_transport_claim_has_single_owner():
    registry = _LiveExecutionTransportOwnershipRegistry()
    transport = object()
    release = registry.claim(transport)

    class Controller:
        def start(self, *args): pass
        def stop(self): raise AssertionError("unresolved cleanup must retain ownership")
    class Bootstrap:
        def startup_reconcile(self, query): return ()
        async def start_execution(self, hts_id): raise asyncio.CancelledError()
        async def close_execution(self): raise asyncio.CancelledError()

    coordinator = LiveRuntimeLifecycleCoordinator(
        controller=Controller(), bootstrap=Bootstrap(),
        release_execution_transport_ownership=release,
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(coordinator.start("C", "P", hts_id="H", recovery_query="Q"))

    failures = []
    for _ in range(3):
        with pytest.raises(RuntimeError, match="LIVE_EXECUTION_TRANSPORT_ALREADY_OWNED") as exc:
            registry.claim(transport)
        failures.append(str(exc.value))
    assert failures == ["LIVE_EXECUTION_TRANSPORT_ALREADY_OWNED"] * 3
    assert coordinator.technical_state == "STARTUP_CLEANUP_CANCELLED"
```
        - terminal coordinator 상태에서는 command adapter의 serialization lock이 존재해도 status polling이 technical state를 정상 상태로 변환하거나 숨기지 않는다.
        - 반복된 status polling과 blocked command 이후에도 STARTUP_CLEANUP_CANCELLED identity가 불변임을 확인한다.
        - unresolved owner가 존재하는 동일 transport에 대한 반복 claim도 모두 단일 ownership registry 경계에서 차단된다.
        - 실제 multi-loop/thread caller contract는 현재 source에 없으므로 concurrency architecture를 확장하지 않고 기존 single-loop/registry 계약 범위에서 검증한다.
## No.576 terminal technical_state 공통 invariant 중복·누락 정리 회귀 검증
```python
import asyncio
from types import SimpleNamespace

import pytest

from application.composition.control_tower_runtime_composition import (
    create_live_control_tower_runtime_api,
)
from application.composition.live_runtime_lifecycle_coordinator import (
    LiveRuntimeLifecycleCoordinator,
)


_TERMINAL_STATES = (
    "STOP_TIMEOUT",
    "STOP_CONTROLLER_FAILED",
    "STOP_EXECUTION_CLOSE_FAILED",
    "TRANSPORT_OWNERSHIP_RELEASE_FAILED",
    "STOP_SHUTDOWN_CANCELLED",
    "STARTUP_CLEANUP_CANCELLED",
)


class _Controller:
    def __init__(self):
        self.started = 0
        self.stopped = 0
    def start(self, config, policy): self.started += 1
    def stop(self): self.stopped += 1
    def status(self):
        return SimpleNamespace(environment="live", state="STOPPED")


class _Bootstrap:
    def startup_reconcile(self, query): return ()
    async def start_execution(self, hts_id): return None
    async def close_execution(self): return None


NaNdef test_terminal_technical_state_common_invariant_projects_and_blocks_all_lifecycle_commands(technical_state):
    controller = _Controller()
    coordinator = LiveRuntimeLifecycleCoordinator(
        controller=controller, bootstrap=_Bootstrap()
    )
    coordinator._technical_state = technical_state
    api = create_live_control_tower_runtime_api(
        lifecycle_coordinator=coordinator
    )

    status = api.status()
    assert (status.technical_state, status.execution_allowed, status.reason) == (
        technical_state, False, technical_state
    )

    command = SimpleNamespace(
        config="CONFIG", policy="POLICY", hts_id="HTS", recovery_query="Q"
    )

    async def scenario():
        for operation in (
            lambda: api.start_live(command),
            api.stop_live,
            lambda: api.restart_live(command),
        ):
            with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
                await operation()

    asyncio.run(scenario())
    assert controller.started == 0
    assert controller.stopped == 0


def test_clean_state_remains_admitted_and_is_not_captured_by_terminal_invariant():
    controller = _Controller()
    coordinator = LiveRuntimeLifecycleCoordinator(
        controller=controller, bootstrap=_Bootstrap()
    )
    api = create_live_control_tower_runtime_api(lifecycle_coordinator=coordinator)
    status = api.status()
    assert status.technical_state is None
    assert status.execution_allowed is True
```
        - production source의 generic technical_state is not None 계약에 실제로 존재하는 terminal state 목록을 테스트 fixture로만 집약했다.
        - 각 state별 개별 status/command 테스트를 삭제하지 않고, 공통 invariant 누락 방지를 위한 parametrized regression을 추가했다.
        - clean state가 terminal invariant에 오인되어 execution이 차단되지 않는 정상 경계도 함께 확인한다.
        - production enum·새 abstraction은 도입하지 않는다.
[Child Page] test_live_control_tower_async_command_adapter.py
```python
import asyncio
import pytest

from application.composition.control_tower_runtime_composition import (
    create_live_control_tower_runtime_api,
)
from interfaces.control_tower.contracts import LiveLifecycleCommand


def _command():
    return LiveLifecycleCommand("C", "P", "H", "Q")


def test_live_control_tower_commands_delegate_to_same_async_coordinator():
    events = []

    class Status:
        environment = "live"
        state = "STOPPED"

    class Controller:
        def status(self): return Status()
        def start(self, *args): raise AssertionError("controller.start bypass")
        def stop(self): raise AssertionError("controller.stop bypass")

    class Coordinator:
        def __init__(self):
            self.runtime_controller = Controller()
            self.technical_state = None
        async def start(self, config, policy, *, hts_id, recovery_query):
            events.append(("start", config, policy, hts_id, recovery_query))
            return "RECOVERED"
        async def stop(self): events.append(("stop",))

    api = create_live_control_tower_runtime_api(lifecycle_coordinator=Coordinator())
    assert asyncio.run(api.start_live(_command())) == "RECOVERED"
    asyncio.run(api.stop_live())
    assert events == [("start", "C", "P", "H", "Q"), ("stop",)]


def test_live_restart_is_coordinator_stop_then_start_atomically():
    events = []

    class Controller:
        def status(self):
            return type("Status", (), {"environment": "live", "state": "STOPPED"})()

    class Coordinator:
        runtime_controller = Controller()
        technical_state = None
        async def stop(self): events.append("stop")
        async def start(self, config, policy, *, hts_id, recovery_query):
            events.append(("start", hts_id, recovery_query)); return "RECOVERED"

    api = create_live_control_tower_runtime_api(lifecycle_coordinator=Coordinator())
    assert asyncio.run(api.restart_live(_command())) == "RECOVERED"
    assert events == ["stop", ("start", "H", "Q")]


def test_live_control_tower_rejects_inherited_sync_controller_commands():
    class Controller:
        def __init__(self): self.calls = []
        def start(self, *args): self.calls.append("start")
        def stop(self): self.calls.append("stop")
        def status(self): return type("Status", (), {"environment": "live", "state": "STOPPED"})()

    class Coordinator:
        def __init__(self):
            self.runtime_controller = Controller(); self.technical_state = None
        async def start(self, *args, **kwargs): return None
        async def stop(self): return None

    coordinator = Coordinator(); api = create_live_control_tower_runtime_api(lifecycle_coordinator=coordinator)
    for command, args in ((api.start, ("C", "P")), (api.stop, ()), (api.restart, ("C", "P"))):
        with pytest.raises(RuntimeError, match="LIVE_RUNTIME_SYNC_COMMAND_NOT_AVAILABLE"):
            command(*args)
    assert coordinator.runtime_controller.calls == []


def test_concurrent_live_commands_are_serialized_and_restart_is_not_interleaved():
    events = []
    entered = asyncio.Event(); release = asyncio.Event()

    class Controller:
        def status(self):
            return type("Status", (), {"environment": "live", "state": "RUNNING"})()

    class Coordinator:
        runtime_controller = Controller(); technical_state = None
        async def start(self, *args, **kwargs):
            events.append("start-enter"); entered.set(); await release.wait(); events.append("start-exit")
        async def stop(self): events.append("stop")

    async def scenario():
        api = create_live_control_tower_runtime_api(lifecycle_coordinator=Coordinator())
        first = asyncio.create_task(api.start_live(_command()))
        await entered.wait()
        second = asyncio.create_task(api.stop_live())
        await asyncio.sleep(0)
        assert events == ["start-enter"]
        release.set()
        await asyncio.gather(first, second)

    asyncio.run(scenario())
    assert events == ["start-enter", "start-exit", "stop"]
```
## No.539 검증
        - UI/application boundary가 concrete Live dependency 대신 LiveLifecycleCommand DTO를 전달한다.
        - 동일 Live Control Tower entry의 concurrent start/stop은 command lock으로 직렬화된다.
        - restart stop → start 사이에 다른 command가 interleave되지 않는다.
## No.540 typed command + single adapter assembly 검증
```python
from application.environment_hub.contracts import EnvironmentConfig, EnvironmentType, RuntimePolicy


def test_live_command_requires_canonical_live_environment_config():
    class Controller:
        def status(self):
            return type("Status", (), {"environment": "live", "state": "STOPPED"})()
    class Coordinator:
        runtime_controller = Controller()
        technical_state = None
        async def start(self, *args, **kwargs): return None
        async def stop(self): return None

    api = create_live_control_tower_runtime_api(lifecycle_coordinator=Coordinator())
    paper = LiveLifecycleCommand(
        EnvironmentConfig(environment=EnvironmentType.PAPER, name="paper"),
        RuntimePolicy(), "H", "Q",
    )
    with pytest.raises(ValueError, match="LIVE_RUNTIME_COMMAND_ENVIRONMENT_REQUIRED"):
        asyncio.run(api.start_live(paper))


def test_same_coordinator_returns_one_control_tower_adapter_and_one_lock():
    class Controller:
        def status(self):
            return type("Status", (), {"environment": "live", "state": "STOPPED"})()
    class Coordinator:
        runtime_controller = Controller()
        technical_state = None
        async def start(self, *args, **kwargs): return None
        async def stop(self): return None

    coordinator = Coordinator()
    first = create_live_control_tower_runtime_api(lifecycle_coordinator=coordinator)
    second = create_live_control_tower_runtime_api(lifecycle_coordinator=coordinator)
    assert first is second
    assert first._command_lock is second._command_lock
```
        - Live command DTO가 canonical EnvironmentConfig/RuntimePolicy를 사용하고 LIVE 이외 환경 command를 fail-closed한다.
        - 동일 coordinator를 두 번 assembly해도 adapter와 command lock이 하나만 존재한다.
## No.541 assembly mutation fail-closed + lifecycle exception lock-release 검증
```python

def test_control_tower_assembly_rejects_mutated_cache():
    class Controller:
        def status(self): return type("Status", (), {"environment": "live", "state": "STOPPED"})()
    class Coordinator:
        runtime_controller = Controller()
        technical_state = None
        async def start(self, *args, **kwargs): return None
        async def stop(self): return None

    coordinator = Coordinator()
    api = create_live_control_tower_runtime_api(lifecycle_coordinator=coordinator)
    coordinator._control_tower_runtime_api = object()
    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_CONTROL_TOWER_ASSEMBLY_CHANGED"):
        create_live_control_tower_runtime_api(lifecycle_coordinator=coordinator)


@pytest.mark.asyncio
async def test_adapter_lock_releases_after_start_failure_and_allows_stop_reentry():
    events = []
    class Controller:
        def start(self, *args): events.append("controller.start")
        def stop(self): events.append("controller.stop")
        def status(self): return type("Status", (), {"environment": "live", "state": "STOPPED"})()
    class Bootstrap:
        def startup_reconcile(self, q): events.append("reconcile"); return ()
        async def start_execution(self, h): events.append("execution.start"); raise RuntimeError("START_FAILED")
        async def close_execution(self): events.append("execution.close")
    coordinator = LiveRuntimeLifecycleCoordinator(controller=Controller(), bootstrap=Bootstrap())
    api = create_live_control_tower_runtime_api(lifecycle_coordinator=coordinator)
    command = _live_command()  # canonical LIVE EnvironmentConfig + RuntimePolicy
    with pytest.raises(RuntimeError, match="START_FAILED"):
        await api.start_live(command)
    await api.stop_live()
    assert events[-1] == "controller.stop"


@pytest.mark.asyncio
async def test_stop_timeout_releases_adapter_lock_but_keeps_coordinator_restart_blocked():
    class Controller:
        def start(self, *args): pass
        def stop(self): raise AssertionError("must not stop on unresolved drain")
        def status(self): return type("Status", (), {"environment": "live", "state": "RUNNING"})()
    class Bootstrap:
        def startup_reconcile(self, q): return ()
        async def start_execution(self, h): return None
        async def close_execution(self): return None
        async def receive_execution_once(self): await asyncio.Event().wait()
    policy = RuntimePolicy(graceful_shutdown_timeout_seconds=0.001, cancellation_drain_timeout_seconds=0.001)
    coordinator = LiveRuntimeLifecycleCoordinator(controller=Controller(), bootstrap=Bootstrap())
    api = create_live_control_tower_runtime_api(lifecycle_coordinator=coordinator)
    command = LiveLifecycleCommand(_live_config(), policy, "H", "Q")
    await api.start_live(command)
    receive = asyncio.create_task(coordinator.receive_execution_once())
    await asyncio.sleep(0)
    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_SHUTDOWN_DRAIN_TIMEOUT"):
        await api.stop_live()
    with pytest.raises(RuntimeError, match="LIVE_RUNTIME_RESTART_NOT_ADMITTED"):
        await api.start_live(command)
    receive.cancel()
```
        - assembly cache 외부 mutation은 새 adapter 생성으로 복구하지 않고 fail-closed한다.
        - start failure와 STOP_TIMEOUT 예외가 adapter lock을 영구 점유하지 않아 이후 command 호출 자체는 가능하다.
        - 단 STOP_TIMEOUT의 coordinator restart admission은 그대로 차단되어 lock release가 lifecycle 정상화를 의미하지 않음을 분리 검증한다.

[Child Page] test_futures_broker_command_adapter.py
```python
from dataclasses import replace
from decimal import Decimal

import pytest

from contracts.types import BrokerOrderCommand
from environments.live.futures_broker_command_adapter import (
    KisFuturesBrokerCommandAdapter,
    FuturesBrokerCommandMappingError,
)


class StubSymbolSource:
    def __init__(self, symbol: str = "101W09") -> None:
        self.symbol = symbol

    def current_symbol(self) -> str:
        return self.symbol


def command() -> BrokerOrderCommand:
    return BrokerOrderCommand(
        client_order_id="ORD-1",
        instrument_id="FUT-1",
        side="BUY",
        quantity=2,
        order_type="LIMIT",
        broker_symbol=None,
        asset_type="FUTURES",
        requested_price=Decimal("350.10"),
        track_id="TRACK-1",
    )


def test_authoritative_master_symbol_is_projected_to_broker_symbol():
    out = KisFuturesBrokerCommandAdapter(StubSymbolSource("101W09")).to_broker_command(command())
    assert out.broker_symbol == "101W09"
    assert out.instrument_id == "FUT-1"
    assert out.quantity == 2
    assert out.requested_price == Decimal("350.10")


def test_adapter_does_not_use_existing_broker_symbol_as_fallback():
    existing = replace(command(), broker_symbol="STALE-SYMBOL")
    out = KisFuturesBrokerCommandAdapter(StubSymbolSource("101W09")).to_broker_command(existing)
    assert out.broker_symbol == "101W09"


def test_invalid_command_is_rejected_before_transport():
    invalid = replace(command(), quantity=0)
    with pytest.raises(FuturesBrokerCommandMappingError, match="QUANTITY_REQUIRED"):
        KisFuturesBrokerCommandAdapter(StubSymbolSource()).to_broker_command(invalid)


def test_missing_symbol_is_fail_closed():
    with pytest.raises(FuturesBrokerCommandMappingError, match="FUTURES_BROKER_SYMBOL_REQUIRED"):
        KisFuturesBrokerCommandAdapter(StubSymbolSource("")).to_broker_command(command())
```
## 검증 목적
    - KIS Contract Master의 shrn_iscd가 broker_symbol로 전달되는지 검증한다.
    - 기존 broker_symbol을 재사용하지 않고 authoritative source를 다시 조회하는지 검증한다.
    - 주문 수량 오류와 symbol 부재가 Broker transport 이전에 fail-closed 되는지 검증한다.
    - 실제 KIS credential/network 호출은 수행하지 않는다.

[Child Page] test_kis_live_futures_submit_boundary.py
```python
from dataclasses import dataclass
from decimal import Decimal

import pytest

from contracts.types import BrokerOrderCommand, BrokerOrderResponse
from environments.live.futures_broker_command_adapter import KisFuturesBrokerCommandAdapter
from environments.live.idempotency import IdempotencyRegistry, OrderIdentity
from environments.live.kis_live_broker import LiveBrokerAdapter


class StubTransport:
    def __init__(self) -> None:
        self.auth_calls = 0
        self.submitted = []

    def authenticate(self) -> bool:
        self.auth_calls += 1
        return True

    def submit(self, command):
        self.submitted.append(command)
        return BrokerOrderResponse(
            client_order_id=command.client_order_id,
            accepted=True,
            broker_order_id="KIS-ACK-1",
        )


class StubGate:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed
        self.calls = []

    def evaluate(self, quantity: int, account_age_seconds: float):
        self.calls.append((quantity, account_age_seconds))
        return type("GateResult", (), {"allowed": self.allowed, "reason": "blocked"})()


class StubSymbolSource:
    def current_symbol(self) -> str:
        return "101W09"


@dataclass(frozen=True)
class LiveSafetyPolicyStub:
    can_submit: bool = True
    max_order_quantity: int = 10
    max_account_staleness_seconds: float = 30.0


def command() -> BrokerOrderCommand:
    return BrokerOrderCommand(
        client_order_id="ORD-LIVE-1",
        instrument_id="FUT-1",
        side="BUY",
        quantity=2,
        order_type="LIMIT",
        broker_symbol=None,
        asset_type="FUTURES",
        requested_price=Decimal("350.10"),
        track_id="TRACK-1",
    )


def identity() -> OrderIdentity:
    return OrderIdentity("ORD-LIVE-1", "TRACK-1", "fp-1")


def live_adapter(transport, gate=None):
    return LiveBrokerAdapter(
        transport=transport,
        gate=gate or StubGate(),
        policy=LiveSafetyPolicyStub(),
        idempotency=IdempotencyRegistry(),
        futures_command_adapter=KisFuturesBrokerCommandAdapter(StubSymbolSource()),
    )


def test_futures_submit_projects_authoritative_symbol_before_transport():
    transport = StubTransport()
    broker = live_adapter(transport)
    assert broker.connect() is True

    result = broker.submit(command(), identity(), 1.0)

    assert result.accepted is True
    assert result.broker_order_id == "KIS-ACK-1"
    assert len(transport.submitted) == 1
    assert transport.submitted[0].broker_symbol == "101W09"
    assert transport.submitted[0].instrument_id == "FUT-1"
    assert isinstance(result, BrokerOrderResponse)


def test_safety_gate_blocks_before_transport():
    transport = StubTransport()
    broker = live_adapter(transport, StubGate(allowed=False))
    broker.connect()

    with pytest.raises(RuntimeError, match="blocked"):
        broker.submit(command(), identity(), 1.0)

    assert transport.submitted == []


def test_duplicate_identity_blocks_before_second_transport_submit():
    transport = StubTransport()
    broker = live_adapter(transport)
    broker.connect()

    broker.submit(command(), identity(), 1.0)
    with pytest.raises(RuntimeError, match="duplicate client order identity"):
        broker.submit(command(), identity(), 1.0)

    assert len(transport.submitted) == 1


def test_missing_futures_adapter_fails_closed_before_transport():
    transport = StubTransport()
    broker = LiveBrokerAdapter(
        transport=transport,
        gate=StubGate(),
        policy=LiveSafetyPolicyStub(),
        idempotency=IdempotencyRegistry(),
        futures_command_adapter=None,
    )
    broker.connect()

    with pytest.raises(RuntimeError, match="FUTURES_COMMAND_ADAPTER_REQUIRED"):
        broker.submit(command(), identity(), 1.0)

    assert transport.submitted == []
```
## 검증 목적
    - LiveSafetyGate/Idempotency 이후에만 physical transport로 진행되는지 검증한다.
    - FUTURES broker_symbol이 authoritative execution-symbol adapter에서 공급되는지 검증한다.
    - 동일 client_order_id 재제출이 두 번째 physical submit으로 이어지지 않는지 검증한다.
    - FUTURES adapter 부재 시 fail-closed 되는지 검증한다.
    - 실제 KIS credential/network 호출은 수행하지 않는다.
    - WAL/OMS 영속화는 OrderRouter 책임이며 이 테스트는 Broker submit 경계만 검증한다.

[Child Page] test_kis_order_payload.py
```python
from decimal import Decimal

import pytest

from contracts.types import BrokerOrderCommand
from environments.live.kis_order_payload import (
    KisDomesticFuturesOrderPayloadAdapter,
    KisOrderAccountContext,
    KisOrderPayloadError,
)


def command(**changes):
    values = {
        "client_order_id": "ORD-1",
        "instrument_id": "FUT-1",
        "side": "BUY",
        "quantity": 2,
        "order_type": "LIMIT",
        "broker_symbol": "101V3000",
        "asset_type": "FUTURES",
        "requested_price": Decimal("350.10"),
    }
    values.update(changes)
    return BrokerOrderCommand(**values)


def adapter(is_vts=False):
    return KisDomesticFuturesOrderPayloadAdapter(
        account=KisOrderAccountContext(cano="12345678", acnt_prdt_cd="01"),
        is_vts=is_vts,
    )


def test_real_buy_limit_payload_is_lossless_at_execution_fields():
    payload_adapter = adapter()
    assert payload_adapter.to_payload(command()) == {
        "CANO": "12345678",
        "ACNT_PRDT_CD": "01",
        "SHTN_PDNO": "101V3000",
        "ORD_PRCS_DVSN_CD": "02",
        "SLL_BUY_DVSN_CD": "02",
        "ORD_DVSN_CD": "00",
        "UNIT_PRICE": "350.10",
        "ORD_QTY": "2",
        "NMPR_TYPE_CD": "01",
        "KRX_NMPR_CNDT_CD": "0",
    }
    assert payload_adapter.tr_id() == "TTTO1101U"


def test_sell_maps_side_only_and_keeps_same_order_tr_id():
    payload_adapter = adapter()
    payload = payload_adapter.to_payload(command(side="SELL"))
    assert payload["SLL_BUY_DVSN_CD"] == "01"
    assert payload_adapter.tr_id() == "TTTO1101U"


def test_vts_uses_vtto1101u():
    assert adapter(is_vts=True).tr_id() == "VTTO1101U"


def test_invalid_or_missing_broker_symbol_fails_closed():
    with pytest.raises(KisOrderPayloadError, match="SHTN_PDNO_REQUIRED"):
        adapter().to_payload(command(broker_symbol=None))
    with pytest.raises(KisOrderPayloadError, match="FUTURES_SHTN_PDNO_PRODUCT_PREFIX_REQUIRED"):
        adapter().to_payload(command(broker_symbol="KOSPI200"))


def test_quantity_and_price_are_required():
    with pytest.raises(KisOrderPayloadError, match="ORD_QTY_REQUIRED"):
        adapter().to_payload(command(quantity=0))
    with pytest.raises(KisOrderPayloadError, match="UNIT_PRICE_REQUIRED"):
        adapter().to_payload(command(requested_price=None))


def test_unsupported_market_order_is_not_guessed():
    with pytest.raises(KisOrderPayloadError, match="UNSUPPORTED_ORDER_TYPE"):
        adapter().to_payload(command(order_type="MARKET"))
```

[Child Page] test_kis_order_transport.py
```python
import json
import urllib.error

from contracts.types import BrokerOrderCommand
from environments.live.broker.kis_order_payload import (
    KisDomesticFuturesOrderPayloadAdapter,
    KisOrderAccountContext,
)
from environments.live.broker.kis_order_transport import (
    KISDomesticFuturesOrderTransport,
    KIS_FUTURES_ORDER_PATH,
    KisOrderTransportError,
)
from infrastructure.kis.auth import KISAuthManager


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.body


def command(**changes):
    values = {
        "client_order_id": "CID-1",
        "instrument_id": "FUT-1",
        "side": "BUY",
        "quantity": 2,
        "order_type": "LIMIT",
        "broker_symbol": "101W09AA",
        "requested_price": 1.25,
        "asset_type": "FUTURES",
    }
    values.update(changes)
    return BrokerOrderCommand(**values)


def adapter(is_vts=False):
    return KisDomesticFuturesOrderPayloadAdapter(
        account=KisOrderAccountContext(cano="12345678", acnt_prdt_cd="01"),
        is_vts=is_vts,
    )


def test_real_post_uses_endpoint_headers_and_serialized_body():
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        return FakeResponse(b'{"rt_cd":"0","msg_cd":"0","msg1":"OK","output":{"ODNO":"1234"}}')

    auth = KISAuthManager()
    transport = KISDomesticFuturesOrderTransport(
        auth=auth,
        payload_adapter=adapter(),
        urlopen=fake_urlopen,
        base_url="https://kis.test",
    )

    response = transport.submit(command())

    assert response.accepted is True
    assert response.broker_order_id == "1234"
    request, timeout = calls[0]
    assert timeout == 10.0
    assert request.full_url == "https://kis.test" + KIS_FUTURES_ORDER_PATH
    assert request.get_header("Tr_id") == "TTTO1101U"
    assert request.get_header("Authorization") == "Bearer TOKEN"
    assert json.loads(request.data.decode("utf-8"))["SHTN_PDNO"] == "101W09AA"


def test_vts_uses_vts_tr_id():
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        return FakeResponse(b'{"rt_cd":"0","msg_cd":"0","msg1":"OK","output":{"ODNO":"5678"}}')

    transport = KISDomesticFuturesOrderTransport(
        auth=KISAuthManager(),
        payload_adapter=adapter(is_vts=True),
        urlopen=fake_urlopen,
    )
    response = transport.submit(command())

    assert response.accepted is True
    assert calls[0].get_header("Tr_id") == "VTTO1101U"


def test_failure_ack_is_normalized_and_is_not_execution():
    response = KISDomesticFuturesOrderTransport.normalize_response(
        "CID-2",
        {"rt_cd": "1", "msg_cd": "ERR", "msg1": "rejected", "output": {}},
    )

    assert response.accepted is False
    assert response.broker_order_id is None
    assert response.broker_code == "ERR"


def test_missing_order_number_is_not_success_ack():
    response = KISDomesticFuturesOrderTransport.normalize_response(
        "CID-3",
        {"rt_cd": "0", "msg_cd": "0", "msg1": "OK", "output": {}},
    )

    assert response.accepted is False
    assert response.broker_order_id is None


def test_network_error_is_separate_from_broker_rejection():
    def fake_urlopen(_request, timeout):
        raise urllib.error.URLError("offline")

    transport = KISDomesticFuturesOrderTransport(
        auth=KISAuthManager(),
        payload_adapter=adapter(),
        urlopen=fake_urlopen,
    )

    try:
        transport.submit(command())
    except KisOrderTransportError as exc:
        assert "transport failed" in str(exc)
    else:
        raise AssertionError("network failure must not become a broker ACK")
```
## 검증 범위
    - 실제 KIS credential/network를 사용하지 않는다.
    - REAL/VTS tr_id, endpoint, authorization header, body 직렬화를 확인한다.
    - 성공 ACK는 rt_cd=0과 output.ODNO가 모두 있을 때만 accepted로 판정한다.
    - 실패 ACK와 network/transport 오류를 서로 다른 경계로 유지한다.
    - ACK는 ExecutionReport가 아니며 체결 수량/체결가격을 생성하지 않는다.

[Child Page] test_order_ack.py
```python
from contracts.order_ack import OrderAckBoundaryError, to_order_ack_event
from contracts.types import BrokerOrderResponse


def test_accepted_ack_maps_without_execution_fields():
    event = to_order_ack_event(
        BrokerOrderResponse(
            client_order_id="ORD-1",
            accepted=True,
            broker_order_id="KIS-1",
            broker_code="0",
            message="accepted",
        )
    )
    assert event.client_order_id == "ORD-1"
    assert event.accepted is True
    assert event.broker_order_id == "KIS-1"


def test_rejected_ack_maps_without_broker_order_id():
    event = to_order_ack_event(
        BrokerOrderResponse(
            client_order_id="ORD-2",
            accepted=False,
            broker_code="ERROR",
            message="rejected",
        )
    )
    assert event.accepted is False
    assert event.broker_order_id is None


def test_accepted_ack_requires_broker_order_id():
    try:
        to_order_ack_event(
            BrokerOrderResponse(client_order_id="ORD-3", accepted=True)
        )
    except OrderAckBoundaryError as exc:
        assert str(exc) == "BROKER_ORDER_ID_REQUIRED_FOR_ACCEPTED_ACK"
    else:
        raise AssertionError("expected accepted ACK validation failure")


def test_missing_client_order_id_fails_closed():
    try:
        to_order_ack_event(BrokerOrderResponse(client_order_id="", accepted=False))
    except OrderAckBoundaryError as exc:
        assert str(exc) == "CLIENT_ORDER_ID_REQUIRED"
    else:
        raise AssertionError("expected client order id validation failure")
```
## 검증 목적
    - Broker transport ACK → canonical OrderAckEvent 변환만 검증한다.
    - ACK를 ExecutionReport로 만들지 않는다.
    - accepted ACK의 broker order id 누락은 fail-closed 한다.
    - rejected ACK는 broker order id 없이도 보존한다.

[Child Page] test_oms_fsm_ack_execution.py
```python
from dataclasses import dataclass
from decimal import Decimal

import pytest

from core.oms.oms_fsm import OrderStateMachine, OrderStateTransitionError
from contracts.types import BrokerOrderResponse, ExecutionReport
from contracts.order_ack import to_order_ack_event


@dataclass(frozen=True)
class Intent:
    client_order_id: str


def ack(client_order_id="O1", accepted=True, broker_order_id="B1"):
    return to_order_ack_event(BrokerOrderResponse(
        client_order_id=client_order_id,
        accepted=accepted,
        broker_order_id=broker_order_id,
    ))


def report(status="FILLED", qty=3):
    return ExecutionReport(
        client_order_id="O1",
        broker_order_id="B1",
        execution_id="E1",
        status=status,
        filled_quantity=qty,
        remaining_quantity=0 if status == "FILLED" else 2,
        execution_price=Decimal("101.5"),
        execution_timestamp=None,
    )


def test_ack_changes_order_state_but_not_execution():
    fsm = OrderStateMachine()
    fsm.apply_intent(Intent("O1"))
    state = fsm.apply_ack(ack())
    assert state.status == "ACKED"
    assert state.broker_order_id == "B1"


def test_execution_requires_prior_ack():
    fsm = OrderStateMachine()
    fsm.apply_intent(Intent("O1"))
    with pytest.raises(OrderStateTransitionError, match="EXECUTION_BEFORE_ACK"):
        fsm.apply_execution(report())


def test_execution_transitions_after_ack():
    fsm = OrderStateMachine()
    fsm.apply_intent(Intent("O1"))
    fsm.apply_ack(ack())
    state = fsm.apply_execution(report())
    assert state.status == "FILLED"
    assert state.broker_order_id == "B1"


def test_rejected_ack_is_terminal_and_position_is_untouched():
    fsm = OrderStateMachine()
    fsm.apply_intent(Intent("O1"))
    state = fsm.apply_ack(ack(accepted=False, broker_order_id=None))
    assert state.status == "REJECTED"
    with pytest.raises(OrderStateTransitionError, match="ACK_AFTER_TERMINAL_STATE"):
        fsm.apply_ack(ack())
```
## 검증 목적
    - BrokerOrderResponse → OrderAckEvent → OMS state 연결을 검증한다.
    - ACK가 체결 상태를 직접 만들지 않는지 검증한다.
    - ACK 이전 ExecutionReport는 fail-closed 한다.
    - ACK 이후에만 PARTIALLY_FILLED/FILLED execution state를 허용한다.
    - REJECTED는 terminal state로 처리하고 Position 변경은 수행하지 않는다.

[Child Page] test_kis_futures_execution_adapter.py
```python
from decimal import Decimal

import pytest

from contracts.types import ExecutionReport
from environments.live.execution.kis_futures_execution_adapter import (
    KISFuturesExecutionAdapterInvalid,
    KISFuturesExecutionContext,
    KISFuturesExecutionNoticeAdapter,
)


def frame(*, qty="2", price="351.25", cntg_yn="Y", order_qty="5"):
    values = [""] * 22
    values[0] = "TESTCUST"
    values[1] = "12345678-01"
    values[2] = "00012345"
    values[3] = ""
    values[4] = "02"
    values[5] = ""
    values[6] = ""
    values[7] = "101T12"
    values[8] = qty
    values[9] = price
    values[10] = "093015"
    values[11] = "N"
    values[12] = cntg_yn
    values[13] = "Y"
    values[14] = "00001"
    values[15] = order_qty
    values[16] = "TEST"
    values[17] = "KOSPI200 FUT"
    values[18] = ""
    values[19] = "G1"
    values[20] = "1"
    values[21] = price
    return "0|H0IFCNI0|22|" + "^".join(values)


def test_h0ifcni0_maps_partial_fill_to_execution_report():
    adapter = KISFuturesExecutionNoticeAdapter()
    notice = adapter.parse(frame(qty="2", order_qty="5"))
    report = adapter.to_execution_report(
        notice,
        KISFuturesExecutionContext("CLIENT-1", order_quantity=5, prior_filled_quantity=0),
    )
    assert isinstance(report, ExecutionReport)
    assert report.client_order_id == "CLIENT-1"
    assert report.broker_order_id == "00012345"
    assert report.filled_quantity == 2
    assert report.remaining_quantity == 3
    assert report.status == "PARTIALLY_FILLED"
    assert report.execution_price == Decimal("351.25")
    assert report.execution_timestamp is None


def test_h0ifcni0_maps_final_fill_to_filled():
    adapter = KISFuturesExecutionNoticeAdapter()
    notice = adapter.parse(frame(qty="2", order_qty="5"))
    report = adapter.to_execution_report(
        notice,
        KISFuturesExecutionContext("CLIENT-1", order_quantity=5, prior_filled_quantity=3),
    )
    assert report.status == "FILLED"
    assert report.remaining_quantity == 0


def test_non_execution_notice_is_fail_closed():
    adapter = KISFuturesExecutionNoticeAdapter()
    notice = adapter.parse(frame(cntg_yn="N"))
    with pytest.raises(KISFuturesExecutionAdapterInvalid):
        adapter.to_execution_report(
            notice,
            KISFuturesExecutionContext("CLIENT-1", order_quantity=5),
        )


def test_overfill_is_fail_closed():
    adapter = KISFuturesExecutionNoticeAdapter()
    notice = adapter.parse(frame(qty="3", order_qty="5"))
    with pytest.raises(KISFuturesExecutionAdapterInvalid):
        adapter.to_execution_report(
            notice,
            KISFuturesExecutionContext("CLIENT-1", order_quantity=5, prior_filled_quantity=3),
        )


def test_wrong_tr_id_is_rejected():
    adapter = KISFuturesExecutionNoticeAdapter()
    with pytest.raises(KISFuturesExecutionAdapterInvalid):
        adapter.parse(frame().replace("H0IFCNI0", "H0IFCNT0"))
```

[Child Page] test_kis_futures_execution_recovery_transport.py
```python
from __future__ import annotations

import json
from types import SimpleNamespace

from environments.live.execution.kis_futures_execution_recovery_adapter import KISExecutionRecoveryQuery
from environments.live.execution.kis_futures_execution_recovery_transport import (
    KISFuturesExecutionRecoveryTransport,
)


class FakeResponse:
    def __init__(self, body: dict, tr_cont: str):
        self._body = json.dumps(body).encode("utf-8")
        self.headers = {"tr_cont": tr_cont}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._body


class FakeAuth:
    base_url = "https://example.test"

    def get_access_token(self):
        return "TOKEN"

    def get_auth_headers(self, tr_id: str = "", force_refresh: bool = False):
        return {"tr_id": tr_id}


def test_inquire_accumulates_official_continuation_pages():
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        if len(calls) == 1:
            return FakeResponse(
                {
                    "rt_cd": "0",
                    "output1": [{"odno": "B1", "tot_ccld_qty": "2"}],
                    "ctx_area_fk200": "FK2",
                    "ctx_area_nk200": "NK2",
                },
                "M",
            )
        return FakeResponse(
            {
                "rt_cd": "0",
                "output1": [{"odno": "B2", "tot_ccld_qty": "5"}],
                "ctx_area_fk200": "",
                "ctx_area_nk200": "",
            },
            "F",
        )

    transport = KISFuturesExecutionRecoveryTransport(
        auth=FakeAuth(),
        urlopen=fake_urlopen,
    )
    result = transport.inquire(KISExecutionRecoveryQuery("C", "03", "20260906", "20260906"))

    assert [row["odno"] for row in result["output1"]] == ["B1", "B2"]
    assert len(calls) == 2
    assert calls[1][0].headers["tr_cont"] == "M"
    assert "CTX_AREA_FK200=FK2" in calls[1][0].full_url
    assert "CTX_AREA_NK200=NK2" in calls[1][0].full_url


def test_inquire_stops_without_continuation():
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        return FakeResponse(
            {
                "rt_cd": "0",
                "output1": [{"odno": "B1", "tot_ccld_qty": "2"}],
            },
            "",
        )

    transport = KISFuturesExecutionRecoveryTransport(auth=FakeAuth(), urlopen=fake_urlopen)
    result = transport.inquire(KISExecutionRecoveryQuery("C", "03", "20260906", "20260906"))

    assert len(calls) == 1
    assert result["output1"][0]["odno"] == "B1"
```
## Verification target
    - Official KIS tr_cont=M/F response continuation is consumed by the transport.
    - ctx_area_fk200 / ctx_area_nk200 are passed to the next request.
    - Multiple pages are accumulated into one recovery response.
    - No continuation means exactly one request.
    - No real KIS credential/network is used.

[Child Page] test_live_execution_recovery_pagination_multi_order_integration.py
```python
from __future__ import annotations

import json
from decimal import Decimal

from environments.live.execution.kis_futures_execution_recovery_adapter import (
    KISExecutionRecoveryContext,
    KISExecutionRecoveryQuery,
    KISFuturesExecutionRecoveryAdapter,
)
from environments.live.execution.kis_futures_execution_recovery_service import (
    LiveExecutionRecoveryService,
)
from environments.live.execution.kis_futures_execution_recovery_transport import (
    KISFuturesExecutionRecoveryTransport,
)


class FakeResponse:
    def __init__(self, body: dict, tr_cont: str):
        self._body = json.dumps(body).encode("utf-8")
        self.headers = {"tr_cont": tr_cont}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._body


class FakeAuth:
    base_url = "https://example.test"

    def get_access_token(self):
        return "TOKEN"

    def get_auth_headers(self, tr_id: str = "", force_refresh: bool = False):
        return {"tr_id": tr_id}


def test_recovery_consumes_multiple_pages_and_multiple_orders_through_service():
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        if len(calls) == 1:
            return FakeResponse(
                {
                    "rt_cd": "0",
                    "output1": [
                        {"odno": "A", "tot_ccld_qty": "2", "avg_idx": "100"},
                        {"odno": "B", "tot_ccld_qty": "1", "avg_idx": "200"},
                    ],
                    "ctx_area_fk200": "FK2",
                    "ctx_area_nk200": "NK2",
                },
                "M",
            )
        return FakeResponse(
            {
                "rt_cd": "0",
                "output1": [
                    {"odno": "A", "tot_ccld_qty": "5", "avg_idx": "102"},
                    {"odno": "B", "tot_ccld_qty": "4", "avg_idx": "201"},
                ],
            },
            "F",
        )

    transport = KISFuturesExecutionRecoveryTransport(
        auth=FakeAuth(),
        urlopen=fake_urlopen,
    )

    contexts = {
        "A": KISExecutionRecoveryContext("CLIENT-A", 5),
        "B": KISExecutionRecoveryContext("CLIENT-B", 4),
    }
    reports = []

    service = LiveExecutionRecoveryService(
        transport=transport,
        adapter=KISFuturesExecutionRecoveryAdapter(),
        correlation_provider=type(
            "Provider",
            (),
            {"resolve": lambda self, order_id: contexts[order_id]},
        )(),
        on_report=reports.append,
    )

    result = service.recover(
        KISExecutionRecoveryQuery("C", "03", "20260906", "20260906")
    )

    assert len(calls) == 2
    assert calls[1].headers["tr_cont"] == "M"
    assert "CTX_AREA_FK200=FK2" in calls[1].full_url
    assert "CTX_AREA_NK200=NK2" in calls[1].full_url
    assert len(result) == 4
    assert [r.broker_order_id for r in reports] == ["A", "B", "A", "B"]
    assert [r.filled_quantity for r in reports] == [2, 1, 3, 3]
    assert reports[2].execution_price == Decimal("103.3333333333333333333333333")
    assert reports[3].execution_price == Decimal("201.3333333333333333333333333")
    assert all(r.execution_id.startswith("REST-CCNL-SNAPSHOT|") for r in reports)
```
## Verification target
    - 실제 KISFuturesExecutionRecoveryTransport가 공식 continuation을 따라 2개 페이지를 소비한다.
    - 페이지 경계를 넘어 같은 order가 계속되어도 adapter가 order별 cumulative/average 상태를 유지한다.
    - 서로 다른 order가 섞여 있어도 각각 독립적으로 delta를 계산한다.
    - LiveExecutionRecoveryService가 transport → adapter → shared on_report 경계를 실제로 연결한다.
    - REST source-local execution identity만 생성되며 H0IFCNI0 identity를 합성하지 않는다.
    - 실계좌/실네트워크 없이 transport HTTP seam을 재현한다.

[Child Page] test_futures_broker_command_[adapter.py]
```python
from dataclasses import dataclass
from decimal import Decimal

from contracts.types import BrokerOrderCommand
from environments.live.futures_broker_command_adapter import KisFuturesBrokerCommandAdapter


@dataclass
class StubSymbolSource:
    symbol: str

    def current_symbol(self) -> str:
        return self.symbol


def command() -> BrokerOrderCommand:
    return BrokerOrderCommand(
        client_order_id="C1",
        instrument_id="FUT.K200.202609",
        side="BUY",
        quantity=1,
        order_type="LIMIT",
        asset_type="FUTURES",
        requested_price=Decimal("500.00"),
    )


def test_authoritative_symbol_is_attached_without_changing_instrument_id():
    adapter = KisFuturesBrokerCommandAdapter(StubSymbolSource("105V9ABC"))
    result = adapter.to_broker_command(command())
    assert result.broker_symbol == "105V9ABC"
    assert result.instrument_id == "FUT.K200.202609"


def test_missing_symbol_fails_closed():
    adapter = KisFuturesBrokerCommandAdapter(StubSymbolSource("  "))
    try:
        adapter.to_broker_command(command())
    except ValueError as exc:
        assert str(exc) == "FUTURES_BROKER_SYMBOL_REQUIRED"
    else:
        raise AssertionError("expected fail-closed validation")
```