폴더 페이지

[Child Page] RISK_GATE_REFERENCE_CONTRACT.md
## 목적
Reference option_program/risk_control/risk_engine.py의 RiskSensor → RiskEngine → RiskGate 경계를 OptionProject Standard Core에 이식하기 전에 실제 입력/출력 계약을 고정한다.
## Reference 계약
    - RiskConfig: max_order_qty=50, max_daily_loss_krw=10,000,000, max_margin_utilization_ratio=0.85, max_position_per_instrument=100, vol_spike_threshold_multiplier=1.30, account/position stale timeout=30s.
    - RiskSensor.scan_risk(active_vol, base_vol, current_regime, account_margin_ratio, is_account_stale, is_position_stale) → RiskSensorSnapshot.
    - RiskEngine.evaluate_order(command, account, positions, sensor_snapshot, allow_reduction=False) → RiskEvaluationResult.
    - RiskGate.admit_order(command, account, positions, sensor_snapshot, allow_reduction=False) → (approved, token, rejection_reason)이며 last_evaluation_result를 보관한다.
    - Risk 판정 순서: kill switch → qty validity/max → daily loss → instrument position limit → required/free margin → margin utilization → margin diet → approval token.
    - ALLOW/REDUCE에서 최종 수량은 Risk가 결정한다. DENY는 주문 실행 객체를 만들지 않는다.
    - REDUCE는 reduced_command.qty 및 approved_qty를 최종 실행 수량으로 사용한다.
## OptionProject 현재 계약과의 차이
현재 contracts/types.py의 AccountSnapshot은 balances: Mapping[str, Decimal> 중심의 환경중립 read model이고, Reference RiskEngine이 직접 요구하는 total_balance, realized_pnl, used_margin, free_margin 필드가 없다. 현재 PositionSnapshot도 Reference가 사용하는 instrument별 {side, qty} 구조와 동일하지 않다.
따라서 RiskEngine을 현재 Account/Position 계약에 맞춰 임의 변환하거나 balance key 이름을 추측하지 않는다.
## 구현 경계
    1. CanonicalOrderCommand의 qty/price/side/asset/option identity/track_id/tag_id는 그대로 Risk 입력으로 전달한다.
    1. Account/Position은 authoritative Standard Snapshot에서 Risk 전용 입력으로 명시적으로 변환되는 계약이 확보된 후 연결한다.
    1. order_type/order_purpose를 Risk에서 추론하지 않는다. 해당 책임은 Position Execution Policy에 둔다.
    1. Reference의 RiskApprovalToken은 Standard Core가 외부 Legacy contract를 직접 import하지 않도록 별도 표준 계약 확인 후 연결한다.
    1. Risk 결과 이후의 OrderIntent/OMS Runtime 연결은 이번 단계에서 하지 않는다.
## 검증 기준
Reference Exp_Detail_1은 읽기 전용으로 유지한다. 독립 테스트는 OptionProject 구현을 임시 Python workspace로 materialize한 뒤 실행하며, 원격 브랜치에서 테스트/수정하지 않는다.
## RiskConfig Validation Contract
### 목적
RiskConfig는 Runtime Risk 판단 이전의 authoritative configuration boundary다. 외부 raw configuration은 이 경계에서 한 번만 normalization·validation되며, RiskEngine/RiskSensor는 검증 완료된 immutable RiskConfig를 직접 소비한다.
### Validation owner
    - Owner: RiskConfig
    - Consumer: RiskEngine, RiskSensor
    - Consumer-side 동일 validation 재구현: 금지
    - Invalid configuration: constructor 단계 fail-fast
### Field policy
<!-- Notion table block -->
| Field | Accepted input | Normalized contract | Domain rule | Error code |
| max_order_qty | int (bool 제외) | int | > 0 | MAX_ORDER_QTY_POSITIVE_INT_REQUIRED |
| max_daily_loss_krw | Decimal/int/float/string | Decimal | > 0, finite | RISK_CONFIG_DECIMAL_VALUE_* / MAX_DAILY_LOSS_KRW_POSITIVE_REQUIRED |
| max_margin_utilization_ratio | Decimal/int/float/string | Decimal | 0 < value <= 1 | RISK_CONFIG_DECIMAL_VALUE_* / MAX_MARGIN_UTILIZATION_RATIO_RANGE_REQUIRED |
| max_position_per_instrument | int (bool 제외) | int | > 0 | MAX_POSITION_PER_INSTRUMENT_POSITIVE_INT_REQUIRED |
| vol_spike_threshold_multiplier | Decimal/int/float/string | Decimal | > 0, finite | RISK_CONFIG_DECIMAL_VALUE_* / VOL_SPIKE_THRESHOLD_MULTIPLIER_POSITIVE_REQUIRED |
| margin_diet_active | bool | bool | bool only | MARGIN_DIET_ACTIVE_BOOL_REQUIRED |
| account_stale_timeout_sec | finite numeric | float | >= 0 | ACCOUNT_STALE_TIMEOUT_SEC_NONNEGATIVE_FINITE_REQUIRED |
| position_stale_timeout_sec | finite numeric | float | >= 0 | POSITION_STALE_TIMEOUT_SEC_NONNEGATIVE_FINITE_REQUIRED |
### Common numeric rules
    1. None와 bool은 Decimal numeric threshold 입력으로 허용하지 않는다.
    1. Decimal normalization은 Decimal(str(value))를 사용하여 기존 valid int/float/string constructor compatibility를 유지한다.
    1. NaN과 ±Infinity 등 non-finite 값은 허용하지 않는다.
    1. 변환 불가 값은 explicit ValueError로 정규화한다.
    1. Decision threshold의 authoritative representation은 Decimal이다.
### Error-code layering
    - Generic input-shape/normalization failure: RISK_CONFIG_DECIMAL_VALUE_REQUIRED / INVALID / FINITE_REQUIRED
    - Field semantic domain failure: 각 field별 _REQUIRED 또는 _RANGE_REQUIRED
    - 목적: 호출자는 numeric 형식 문제와 해당 Risk parameter의 업무 범위 위반을 구분할 수 있다.
### Margin ratio upper bound
max_margin_utilization_ratio의 현재 의미는 RiskEngine의 margin utilization threshold이며 0 < ratio <= 1로 계약한다. 향후 실제 leverage/margin model의 authoritative source가 ratio가 1을 초과하는 별도 업무 의미를 요구할 경우에만 해당 field의 domain policy를 재판정한다. 근거 없는 선제 확장은 하지 않는다.
### Runtime boundary
External raw config input → RiskConfig normalization/validation → valid immutable RiskConfig → RiskEngine/RiskSensor direct consumption
이 문서는 RiskSensor → RiskEngine → RiskGate 책임 경계 및 기존 RiskConfig 기본값을 정의한 RISK_GATE_REFERENCE_CONTRACT의 보완 계약이며, Risk 판정 순서나 전략 의미를 변경하지 않는다.

[Child Page] risk_input.py
```python
from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping

from contracts.types import AccountSnapshot, PositionSnapshot


@dataclass(frozen=True)
class RiskAccountInput:
    total_balance: Decimal
    realized_pnl: Decimal
    used_margin: Decimal
    free_margin: Decimal


@dataclass(frozen=True)
class RiskPosition:
    side: str
    qty: int


@dataclass(frozen=True)
class RiskPositionInput:
    positions: Mapping[str, RiskPosition]


def account_snapshot_to_risk_input(snapshot: AccountSnapshot) -> RiskAccountInput:
    required = ("cash", "realized_pnl", "margin_used", "available_cash")
    missing = [key for key in required if key not in snapshot.balances]
    if missing:
        raise ValueError(f"RISK_ACCOUNT_FIELDS_REQUIRED: {','.join(missing)}")
    return RiskAccountInput(
        total_balance=Decimal(snapshot.balances["cash"]),
        realized_pnl=Decimal(snapshot.balances["realized_pnl"]),
        used_margin=Decimal(snapshot.balances["margin_used"]),
        free_margin=Decimal(snapshot.balances["available_cash"]),
    )


def position_snapshot_to_risk_input(snapshot: PositionSnapshot) -> RiskPositionInput:
    raise ValueError("RISK_POSITION_SIDE_REQUIRED")
```
## 계약 근거
    - VirtualAccount의 canonical AccountSnapshot.balances에는 cash, margin_used, realized_pnl, available_cash가 실제 상태로 이미 존재한다.
    - 따라서 이 네 값의 의미를 새로 계산하지 않고 명시적으로 Risk 입력 DTO에 매핑한다.
    - cash → total_balance, margin_used → used_margin, available_cash → free_margin, realized_pnl → realized_pnl 매핑은 기존 VirtualAccount 상태의 명칭과 동작을 그대로 보존한다.
    - 누락된 key는 fail-closed 한다.
    - PositionSnapshot에는 수량만 있고 side가 없으므로 RiskEngine의 position-side 계약으로 임의 변환하지 않는다. side를 authoritative하게 공급하는 별도 Standard Position Risk contract가 확정될 때까지 변환을 거부한다.
    - contracts/types.py의 기존 DTO 자체는 변경하지 않는다.

[Child Page] RISK_ENGINE_STANDARD_MIGRATION_CONTRACT.md
## 목적
Reference option_program/risk_control/risk_engine.py를 OptionProject Standard Core로 이식하기 위한 최소 경계를 고정한다. Reference 코드를 그대로 복사하지 않고, 이미 확정된 Standard 입력 DTO와 책임 분리를 유지한다.
## Reference 실제 의존성 대조
    - CanonicalOrderCommand: client_order_id, track_id, asset_type, side, qty, price, option_type, strike, symbol, expiry, tag_id를 제공하며 get_instrument_key()를 가진다.
    - CanonicalAccountSummary: Reference RiskEngine이 직접 요구하는 total_balance, realized_pnl, used_margin, free_margin을 제공한다.
    - RiskApprovalToken: Reference는 shared.core.contracts.RiskApprovalToken을 사용하며 order_id(UUID), timestamp_ns, signature 필드를 가진다. Standard Core는 이 Legacy 타입을 직접 import하지 않는다.
    - MarginEngine.calculate_order_margin(command): OPTION은 price * qty * 250000, 단 price >= 50이면 2.5 fallback; FUTURES는 price * qty * 250000 * 0.10이다.
    - RiskSensorSnapshot: is_margin_diet_required 및 reason 등을 RiskEngine에 전달한다.
## Standard 연결 경계
### 입력
    1. 주문: Standard CanonicalOrderCommand를 그대로 전달한다.
    1. 계좌: AccountSnapshot -> RiskAccountInput 명시적 adapter를 사용한다.
        - cash -> total_balance
        - realized_pnl -> realized_pnl
        - margin_used -> used_margin
        - available_cash -> free_margin
    1. 포지션: authoritative PositionManager.positions의 symbol -> {qty, avg_price, side}를 PositionManager -> RiskPositionInput adapter로 전달한다. PositionSnapshot에서 side를 추론하지 않는다.
    1. 센서: RiskSensorSnapshot을 RiskEngine 입력으로 유지한다.
## 최소 이식 대상
    1. RiskConfig
    1. RiskSensor의 scan_risk() 순수 판정 로직
    1. RiskEvaluationResult
    1. RiskEngine의 kill switch / daily loss / instrument limit / margin / margin diet / approval-token 판정 로직
    1. RiskGate의 admit_order() 단일 진입점과 last_evaluation_result
## 의도적으로 이식하지 않는 것
    - OrderType, OrderPurpose 등 Risk가 책임지지 않는 intent 정보
    - Legacy shared.core.contracts 직접 import
    - Legacy CanonicalAccountSummary 직접 의존
    - PositionSnapshot에 side를 추가하는 변경
    - Runtime/OMS 연결
    - Reference PositionManager의 내부 FIFO 구현 복사
## 중요한 정합성 확인
Reference RiskEngine은 calculate_expected_position()에서 반대 방향 주문을 단순 수량 차감/반전으로 계산한다. 실제 PositionManager는 FIFO attribution이 있으면 lot 기준으로 처리한다. 따라서 RiskEngine은 PositionManager의 FIFO를 재구현하지 않고, pre-trade capacity 계산에 필요한 authoritative aggregate side/qty만 사용한다.
## 현재 보류 경계
RiskEngine 판정 로직 자체는 Standard 입력 계약으로 이식 가능하다. 다만 승인 토큰은 Standard 전용 RiskApprovalToken 계약이 아직 별도로 확정되지 않았으므로 Legacy 타입을 직접 가져오지 않는다. 다음 구현 단계에서 Standard token DTO를 최소 계약으로 확정한 뒤 RiskEngine/RiskGate를 구현한다.
## 검증 기준
    - Reference Exp_Detail_1은 읽기 전용.
    - Reference 소스 대조 결과만으로 pytest PASS를 주장하지 않는다.
    - 구현 후 ALLOW, REDUCE, DENY, kill switch, daily loss, position limit, free margin, margin ratio, margin diet, token 발행 경로를 독립 테스트한다.

[Child Page] risk.py
```python
from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RiskApprovalToken:
    """Standard Core risk approval proof.

    The contract intentionally does not depend on Legacy shared contracts.
    """

    order_id: UUID
    timestamp_ns: int
    signature: str


@dataclass(frozen=True, slots=True)
class RiskEvaluationResult:
    """Authoritative result of a pre-trade risk evaluation."""

    is_approved: bool
    decision: str = "ALLOW"
    original_qty: int = 0
    approved_qty: int = 0
    rejection_reason: str | None = None
    required_margin: float = 0.0
    estimated_margin_ratio: float = 0.0
    token: RiskApprovalToken | None = None
    reduced_command: Any | None = None
```
## Ownership
    - Standard Risk approval/result DTO는 contracts/risk.py가 소유한다.
    - Legacy shared.core.contracts.RiskApprovalToken은 import하지 않는다.
    - RiskEvaluationResult는 Reference의 ALLOW/REDUCE/DENY 의미와 approved_qty, required_margin, estimated_margin_ratio, reduced_command 결과 계약을 보존한다.
    - reduced_command는 현재 Standard Core에 Reference CanonicalOrderCommand가 없으므로 특정 Legacy command 타입에 결합하지 않는다.
    - 실제 token 발행 알고리즘은 RiskEngine 구현 책임이며 이 파일은 데이터 계약만 소유한다.

[Child Page] risk_config.py
```python
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import math
from typing import Any


@dataclass(frozen=True)
class RiskConfig:
    """Standard risk threshold configuration.

    Decision thresholds use Decimal as the authoritative configuration
    contract. Constructor compatibility is preserved for valid int/float/string
    inputs by normalizing them once at the configuration boundary.

    Invalid numeric configuration is rejected at construction time so it cannot
    reach runtime risk decisions.
    """

    max_order_qty: int = 50
    max_daily_loss_krw: Decimal = Decimal("10000000")
    max_margin_utilization_ratio: Decimal = Decimal("0.85")
    max_position_per_instrument: int = 100
    vol_spike_threshold_multiplier: Decimal = Decimal("1.30")
    margin_diet_active: bool = False
    account_stale_timeout_sec: float = 30.0
    position_stale_timeout_sec: float = 30.0

    @staticmethod
    def _decimal(value: Any) -> Decimal:
        if value is None or isinstance(value, bool):
            raise ValueError("RISK_CONFIG_DECIMAL_VALUE_REQUIRED")
        try:
            normalized = value if isinstance(value, Decimal) else Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError("RISK_CONFIG_DECIMAL_VALUE_INVALID") from exc
        if not normalized.is_finite():
            raise ValueError("RISK_CONFIG_DECIMAL_VALUE_FINITE_REQUIRED")
        return normalized

    @staticmethod
    def _positive_int(value: Any, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field}_POSITIVE_INT_REQUIRED")
        return value

    @staticmethod
    def _nonnegative_timeout(value: Any, field: str) -> float:
        if value is None or isinstance(value, bool):
            raise ValueError(f"{field}_NONNEGATIVE_FINITE_REQUIRED")
        try:
            normalized = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field}_NONNEGATIVE_FINITE_REQUIRED") from exc
        if not math.isfinite(normalized) or normalized < 0:
            raise ValueError(f"{field}_NONNEGATIVE_FINITE_REQUIRED")
        return normalized

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_order_qty",
            self._positive_int(self.max_order_qty, "MAX_ORDER_QTY"),
        )
        object.__setattr__(
            self,
            "max_position_per_instrument",
            self._positive_int(
                self.max_position_per_instrument,
                "MAX_POSITION_PER_INSTRUMENT",
            ),
        )

        daily_loss = self._decimal(self.max_daily_loss_krw)
        margin_ratio = self._decimal(self.max_margin_utilization_ratio)
        vol_multiplier = self._decimal(self.vol_spike_threshold_multiplier)

        if daily_loss <= 0:
            raise ValueError("MAX_DAILY_LOSS_KRW_POSITIVE_REQUIRED")
        if not Decimal("0") < margin_ratio <= Decimal("1"):
            raise ValueError("MAX_MARGIN_UTILIZATION_RATIO_RANGE_REQUIRED")
        if vol_multiplier <= 0:
            raise ValueError("VOL_SPIKE_THRESHOLD_MULTIPLIER_POSITIVE_REQUIRED")
        if not isinstance(self.margin_diet_active, bool):
            raise ValueError("MARGIN_DIET_ACTIVE_BOOL_REQUIRED")

        object.__setattr__(self, "max_daily_loss_krw", daily_loss)
        object.__setattr__(
            self,
            "max_margin_utilization_ratio",
            margin_ratio,
        )
        object.__setattr__(
            self,
            "vol_spike_threshold_multiplier",
            vol_multiplier,
        )
        object.__setattr__(
            self,
            "account_stale_timeout_sec",
            self._nonnegative_timeout(
                self.account_stale_timeout_sec,
                "ACCOUNT_STALE_TIMEOUT_SEC",
            ),
        )
        object.__setattr__(
            self,
            "position_stale_timeout_sec",
            self._nonnegative_timeout(
                self.position_stale_timeout_sec,
                "POSITION_STALE_TIMEOUT_SEC",
            ),
        )
```

[Child Page] risk_sensor.py
```python
import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from core.risk.risk_config import RiskConfig


@dataclass(frozen=True)
class RiskSensorSnapshot:
    """Standard, environment-neutral result of one risk sensor scan."""

    is_vol_spike: bool = False
    is_crisis_regime: bool = False
    is_margin_diet_required: bool = False
    is_account_stale: bool = False
    is_position_stale: bool = False
    active_vol_ratio: Decimal = Decimal("1")
    reason: str = "NORMAL"


class RiskSensor:
    """Reference RiskSensor rules without Legacy/VSSF dependencies."""

    def __init__(self, config: RiskConfig | None = None):
        self.config = config or RiskConfig()

    @staticmethod
    def _decimal(value: Any) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))

    def scan_risk(
        self,
        active_vol: float | Decimal,
        base_vol: float | Decimal,
        current_regime: str = "NORMAL",
        account_margin_ratio: float | Decimal = Decimal("0"),
        is_account_stale: bool = False,
        is_position_stale: bool = False,
    ) -> RiskSensorSnapshot:
        """Scan volatility, regime, margin and freshness state."""
        if any(
            v is None or (isinstance(v, float) and math.isnan(v))
            for v in (active_vol, base_vol)
        ):
            return RiskSensorSnapshot(reason="INVALID_OR_NAN_SENSOR_INPUT")

        active_vol_decimal = self._decimal(active_vol)
        base_vol_decimal = self._decimal(base_vol)
        margin_ratio_decimal = self._decimal(account_margin_ratio)
        vol_ratio = (
            active_vol_decimal / base_vol_decimal
            if base_vol_decimal > 0
            else Decimal("1")
        )
        is_vol_spike = vol_ratio >= self.config.vol_spike_threshold_multiplier
        is_crisis = current_regime in {"CRISIS", "HIGH_VOLATILITY", "EXTREME_MOVE"}
        is_margin_diet = margin_ratio_decimal > self.config.max_margin_utilization_ratio

        reason = "NORMAL"
        if is_margin_diet:
            reason = f"MARGIN_DIET_TRIGGERED (Ratio={margin_ratio_decimal:.2%})"
        elif is_vol_spike:
            reason = f"VOLATILITY_SPIKE_DETECTED (Ratio={vol_ratio:.2f})"
        elif is_crisis:
            reason = f"CRISIS_REGIME_ACTIVE ({current_regime})"
        elif is_account_stale or is_position_stale:
            reason = (
                "STALE_STATE_DETECTED "
                f"(AccountStale={is_account_stale}, PosStale={is_position_stale})"
            )

        return RiskSensorSnapshot(
            is_vol_spike=is_vol_spike,
            is_crisis_regime=is_crisis,
            is_margin_diet_required=is_margin_diet,
            is_account_stale=is_account_stale,
            is_position_stale=is_position_stale,
            active_vol_ratio=vol_ratio,
            reason=reason,
        )
```

[Child Page] risk_engine.py
```python
"""Standard Core pre-trade RiskEngine and RiskGate."""
import dataclasses
import logging
import time
import uuid
from decimal import Decimal
from typing import Any, Mapping, Optional, Protocol

from contracts.risk import RiskApprovalToken, RiskEvaluationResult
from core.risk.risk_config import RiskConfig
from core.risk.risk_input import RiskAccountInput, RiskPositionInput
from core.risk.risk_sensor import RiskSensor, RiskSensorSnapshot

logger = logging.getLogger(__name__)

class RiskOrderCommand(Protocol):
    client_order_id: str
    track_id: str
    qty: int
    price: float
    side: Any
    tag_id: str
    def get_instrument_key(self) -> str: ...

class MarginCalculator(Protocol):
    def calculate_order_margin(self, command: RiskOrderCommand) -> float: ...

class RiskEngine:
    def __init__(self, config: Optional[RiskConfig] = None, margin_engine: Optional[MarginCalculator] = None, risk_sensor: Optional[RiskSensor] = None):
        self.config = config or RiskConfig()
        if margin_engine is None:
            raise ValueError("RISK_MARGIN_DEPENDENCY_REQUIRED")
        self.margin_engine = margin_engine
        self.sensor = risk_sensor or RiskSensor(self.config)
        self._is_kill_switch_active = False
        self._daily_realized_loss = Decimal("0")

    def trigger_kill_switch(self, reason: str = "MANUAL_PANIC_STOP") -> None:
        self._is_kill_switch_active = True
        logger.critical("[RiskEngine] KILL SWITCH: %s", reason)

    def reset_kill_switch(self) -> None:
        self._is_kill_switch_active = False

    def is_kill_switch_active(self) -> bool:
        return self._is_kill_switch_active

    @staticmethod
    def _decimal(value: Any) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))

    def record_realized_loss(self, loss_amount: float | Decimal) -> None:
        amount = self._decimal(loss_amount)
        if amount < 0:
            self._daily_realized_loss += abs(amount)

    @staticmethod
    def _order_side(command: RiskOrderCommand) -> str:
        return command.side.value if hasattr(command.side, "value") else str(command.side)

    def calculate_expected_position(self, command: RiskOrderCommand, positions: Optional[RiskPositionInput] = None) -> dict[str, Any]:
        positions_map: Mapping[str, Any] = positions.positions if positions is not None else {}
        instrument_key = command.get_instrument_key()
        current = positions_map.get(instrument_key)
        if current is None and len(positions_map) == 1:
            current = next(iter(positions_map.values()))
        curr_qty = int(getattr(current, "qty", 0)) if current is not None else 0
        curr_side = getattr(current, "side", None) if current is not None else None
        order_side = self._order_side(command)
        if curr_qty == 0 or not curr_side:
            return {"instrument_key": instrument_key, "side": order_side, "qty": command.qty}
        if curr_side == order_side:
            return {"instrument_key": instrument_key, "side": curr_side, "qty": curr_qty + command.qty}
        if command.qty < curr_qty:
            return {"instrument_key": instrument_key, "side": curr_side, "qty": curr_qty - command.qty}
        if command.qty == curr_qty:
            return {"instrument_key": instrument_key, "side": "FLAT", "qty": 0}
        return {"instrument_key": instrument_key, "side": order_side, "qty": command.qty - curr_qty}

    def evaluate_order(self, command: RiskOrderCommand, account: RiskAccountInput, positions: Optional[RiskPositionInput] = None, sensor_snapshot: Optional[RiskSensorSnapshot] = None, allow_reduction: bool = False) -> RiskEvaluationResult:
        original_qty = command.qty
        if self._is_kill_switch_active:
            return RiskEvaluationResult(False, "DENY", original_qty, 0, "REJECTED_BY_KILL_SWITCH")
        if command.qty <= 0:
            return RiskEvaluationResult(False, "DENY", original_qty, 0, f"INVALID_ORDER_QTY: {command.qty}")
        if command.qty > self.config.max_order_qty:
            return RiskEvaluationResult(False, "DENY", original_qty, 0, f"EXCEEDED_MAX_ORDER_QTY: {command.qty} > {self.config.max_order_qty}")
        realized_pnl = self._decimal(account.realized_pnl)
        total_loss = self._daily_realized_loss + abs(min(Decimal("0"), realized_pnl))
        max_daily_loss = self.config.max_daily_loss_krw
        if total_loss >= max_daily_loss:
            return RiskEvaluationResult(False, "DENY", original_qty, 0, f"EXCEEDED_MAX_DAILY_LOSS: {total_loss:,.0f} >= {self.config.max_daily_loss_krw:,.0f} KRW")
        effective_cmd = command
        expected = self.calculate_expected_position(effective_cmd, positions)
        if expected["qty"] > self.config.max_position_per_instrument:
            current = positions.positions.get(expected["instrument_key"]) if positions is not None else None
            current_qty = int(getattr(current, "qty", 0)) if current is not None else 0
            if current is None and positions is not None and len(positions.positions) == 1:
                current = next(iter(positions.positions.values())); current_qty = int(getattr(current, "qty", 0))
            remaining_capacity = self.config.max_position_per_instrument - current_qty
            if allow_reduction and 0 < remaining_capacity < effective_cmd.qty:
                effective_cmd = dataclasses.replace(effective_cmd, qty=remaining_capacity)
            else:
                return RiskEvaluationResult(False, "DENY", original_qty, 0, f"EXCEEDED_INSTRUMENT_LIMIT: {expected['qty']} > {self.config.max_position_per_instrument}")
        required_margin = self._decimal(self.margin_engine.calculate_order_margin(effective_cmd))
        used_margin = self._decimal(account.used_margin)
        total_balance = self._decimal(account.total_balance)
        free_margin = self._decimal(account.free_margin)
        estimated_ratio = (used_margin + required_margin) / total_balance if total_balance > 0 else Decimal("1")
        if required_margin > free_margin:
            unit_margin = required_margin / effective_cmd.qty if effective_cmd.qty > 0 else Decimal("0")
            max_affordable_qty = int(free_margin / unit_margin) if unit_margin > 0 else 0
            if allow_reduction and 0 < max_affordable_qty < effective_cmd.qty:
                effective_cmd = dataclasses.replace(effective_cmd, qty=max_affordable_qty)
                required_margin = self._decimal(self.margin_engine.calculate_order_margin(effective_cmd))
                estimated_ratio = (used_margin + required_margin) / total_balance if total_balance > 0 else Decimal("1")
            else:
                return RiskEvaluationResult(False, "DENY", original_qty, 0, f"INSUFFICIENT_FREE_MARGIN: req={required_margin:,.0f} > free={float(account.free_margin):,.0f} KRW", required_margin, estimated_ratio)
        if estimated_ratio > self.config.max_margin_utilization_ratio:
            return RiskEvaluationResult(False, "DENY", original_qty, 0, f"EXCEEDED_MAX_MARGIN_RATIO: {estimated_ratio:.2%} > {self.config.max_margin_utilization_ratio:.2%}", required_margin, estimated_ratio)
        if sensor_snapshot and sensor_snapshot.is_margin_diet_required and effective_cmd.tag_id != "RISK_HEDGE":
            return RiskEvaluationResult(False, "DENY", original_qty, 0, f"MARGIN_DIET_ACTIVE: Blocked new entry under {sensor_snapshot.reason}", required_margin, estimated_ratio)
        is_reduced = effective_cmd.qty < original_qty
        decision = "REDUCE" if is_reduced else "ALLOW"
        token = RiskApprovalToken(uuid.uuid4(), time.time_ns(), f"SIG-RISK-APPROVED-{effective_cmd.track_id}-{effective_cmd.client_order_id}")
        return RiskEvaluationResult(True, decision, original_qty, effective_cmd.qty, None, required_margin, estimated_ratio, token, effective_cmd if is_reduced else None)

class RiskGate:
    def __init__(self, risk_engine: RiskEngine):
        self.engine = risk_engine
        self.last_evaluation_result: Optional[RiskEvaluationResult] = None
    def admit_order(self, command: RiskOrderCommand, account: RiskAccountInput, positions: Optional[RiskPositionInput] = None, sensor_snapshot: Optional[RiskSensorSnapshot] = None, allow_reduction: bool = False) -> tuple[bool, Optional[RiskApprovalToken], Optional[str]]:
        result = self.engine.evaluate_order(command, account, positions, sensor_snapshot, allow_reduction=allow_reduction)
        self.last_evaluation_result = result
        if result.is_approved and result.token is not None:
            return True, result.token, None
        return False, None, result.rejection_reason
```

[Child Page] risk_runtime_adapter.py
```python
"""Non-invasive Standard Risk input boundary for Runtime integration."""
from dataclasses import dataclass
from typing import Any, Protocol

from contracts.types import AccountSnapshot
from core.risk.risk_input import (
    RiskAccountInput,
    RiskPositionInput,
    account_snapshot_to_risk_input,
)
from core.risk.risk_position import position_manager_to_risk_input


class RiskCompatibleOrderCommand(Protocol):
    """Structural contract required by Standard RiskEngine.

    The adapter does not construct or rewrite a command. It only verifies that
    the already-authoritative execution command exposes the fields Risk needs.
    """

    client_order_id: str
    track_id: str
    qty: int
    price: float
    side: Any
    tag_id: str

    def get_instrument_key(self) -> str: ...


@dataclass(frozen=True)
class RiskRuntimeInputs:
    command: RiskCompatibleOrderCommand
    account: RiskAccountInput
    positions: RiskPositionInput


def validate_risk_order_command(command: Any) -> RiskCompatibleOrderCommand:
    """Validate structural compatibility without changing the command."""
    required = ("client_order_id", "track_id", "qty", "price", "side", "tag_id")
    missing = [name for name in required if not hasattr(command, name)]
    if missing or not callable(getattr(command, "get_instrument_key", None)):
        raise TypeError(
            "RISK_ORDER_COMMAND_FIELDS_REQUIRED: "
            + ",".join(missing or ["get_instrument_key"])
        )
    return command


def build_risk_runtime_inputs(
    command: Any,
    account_snapshot: AccountSnapshot,
    position_manager: Any,
) -> RiskRuntimeInputs:
    """Build only the Standard Risk inputs from authoritative sources.

    No order_type/order_purpose is generated here. No quantity, side, price,
    track_id, tag_id, or instrument identity is rewritten.
    """
    validated_command = validate_risk_order_command(command)
    account = account_snapshot_to_risk_input(account_snapshot)
    positions = position_manager_to_risk_input(position_manager)
    return RiskRuntimeInputs(
        command=validated_command,
        account=account,
        positions=positions,
    )
```
## 계약
    - Runtime command는 새 객체로 변환하지 않고 structural validation 후 동일 객체를 Risk에 전달한다.
    - client_order_id, track_id, tag_id, side, qty, price, get_instrument_key()를 보존한다.
    - Account는 기존 account_snapshot_to_risk_input()을 재사용한다.
    - Position은 PositionManager.positions의 authoritative side/qty를 기존 position_manager_to_risk_input()으로 전달한다.
    - PositionSnapshot에서 side를 추론하지 않는다.
    - order_type / order_purpose를 생성·추론하지 않는다.
    - OPTION identity를 생성하거나 보완하지 않는다.
    - Reference Runtime 자체와 Legacy DTO를 import하지 않는다.
    - 실제 CanonicalOrderCommand가 Standard contracts/types.py에 존재하지 않는 현재 상태에서는 이를 임의 생성하지 않는다. 이후 canonical command가 확정되면 동일 structural boundary를 그대로 검증한다.

[Child Page] multi_leg_risk.py
```python
"""Per-leg Standard RiskGate composition for MultiLegExecutionPlan."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from contracts.risk import RiskApprovalToken
from contracts.types import OrderIntent
from core.risk.risk_engine import RiskGate, RiskOrderCommand
from core.risk.risk_input import RiskAccountInput, RiskPositionInput
from core.risk.risk_sensor import RiskSensorSnapshot


class MultiLegRiskError(ValueError):
    """Fail-closed multi-leg Risk composition error."""


@dataclass(frozen=True)
class MultiLegRiskApproval:
    """Authoritative per-leg Risk approval collection."""

    group_id: str
    approved_quantities: Mapping[str, int]
    tokens: Mapping[str, RiskApprovalToken]
    reduced_commands: Mapping[str, object]



def admit_multi_leg_intents(
    intents: tuple[OrderIntent, ...] | list[OrderIntent],
    *,
    risk_gate: RiskGate,
    account: RiskAccountInput,
    positions: RiskPositionInput | None = None,
    sensor_snapshot: RiskSensorSnapshot | None = None,
    allow_reduction: bool = False,
    command_factory: Callable[[OrderIntent], RiskOrderCommand],
) -> MultiLegRiskApproval:
    """Evaluate each materialized leg independently through the Standard RiskGate.

    `command_factory` is an explicit composition boundary: this function does not
    invent qty/price/side/tag/identity values that are absent from OrderIntent.
    Every approved token and effective quantity remains keyed by the original
    `client_order_id`; any DENY or provenance mismatch aborts the whole submission.
    """
    if not intents:
        raise MultiLegRiskError("MULTI_LEG_INTENTS_REQUIRED")

    group_ids = {intent.group_id for intent in intents}
    if len(group_ids) != 1 or None in group_ids:
        raise MultiLegRiskError("SINGLE_GROUP_ID_REQUIRED")

    group_id = next(iter(group_ids))
    approved_quantities: dict[str, int] = {}
    tokens: dict[str, RiskApprovalToken] = {}
    reduced_commands: dict[str, object] = {}

    for intent in intents:
        if not intent.client_order_id:
            raise MultiLegRiskError("CLIENT_ORDER_ID_REQUIRED")
        command = command_factory(intent)
        if str(command.client_order_id) != str(intent.client_order_id):
            raise MultiLegRiskError("CLIENT_ORDER_ID_PROVENANCE_MISMATCH")

        approved, token, reason = risk_gate.admit_order(
            command,
            account,
            positions,
            sensor_snapshot,
            allow_reduction=allow_reduction,
        )
        result = risk_gate.last_evaluation_result
        if not approved or token is None or result is None:
            raise MultiLegRiskError(reason or "ORDER_DENIED_BY_RISK")
        if result.approved_qty <= 0:
            raise MultiLegRiskError("APPROVED_QUANTITY_REQUIRED")
        if str(result.token) != str(token):
            raise MultiLegRiskError("RISK_TOKEN_PROVENANCE_MISMATCH")

        approved_quantities[intent.client_order_id] = int(result.approved_qty)
        tokens[intent.client_order_id] = token
        if result.decision == "REDUCE":
            reduced = result.reduced_command
            reduced_qty = getattr(reduced, "qty", None) if reduced is not None else None
            if reduced_qty is None or int(reduced_qty) != int(result.approved_qty):
                raise MultiLegRiskError("REDUCED_QUANTITY_PROVENANCE_MISMATCH")
            reduced_commands[intent.client_order_id] = reduced

    if len(tokens) != len(intents):
        raise MultiLegRiskError("ALL_LEG_RISK_TOKENS_REQUIRED")

    return MultiLegRiskApproval(
        group_id=group_id,
        approved_quantities=approved_quantities,
        tokens=tokens,
        reduced_commands=reduced_commands,
    )
```
## 계약
    - MultiLegExecutionPlan → OrderIntent[] materializer의 결과만 입력으로 받는다.
    - 각 leg는 기존 RiskGate.admit_order()에 독립적으로 평가한다.
    - client_order_id를 leg별 token/approved quantity의 provenance key로 유지한다.
    - ALLOW는 RiskEvaluationResult.approved_qty를 authoritative quantity로 사용한다.
    - REDUCE는 reduced_command.qty와 approved_qty가 일치하는지 검증한다.
    - DENY, token 누락, identity/provenance 불일치는 즉시 fail-closed 한다.
    - command_factory는 이미 확정된 OrderIntent → RiskOrderCommand 변환을 외부에서 공급한다. 이 계층에서 synthetic default를 생성하지 않는다.
    - group-level margin/net exposure, spread offset, atomic basket limit은 계산하지 않는다.