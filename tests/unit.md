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