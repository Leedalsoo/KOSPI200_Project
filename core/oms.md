폴더 페이지

[Child Page] option_identity_resolver.py
```python
from dataclasses import dataclass
from decimal import Decimal

from contracts.types import OptionInstrumentIdentity


class IdentityResolutionError(ValueError):
    """Raised when an authoritative option identity cannot be finalized."""


@dataclass(frozen=True)
class OptionIdentityResolutionInput:
    """Authoritative identity plus explicit strategy selection overrides."""

    instrument_identity: OptionInstrumentIdentity | None
    option_type_override: str | None = None
    strike_override: Decimal | None = None


class OptionIdentityResolver:
    """Finalizes immutable option identity immediately before OrderIntent creation.

    The resolver never invents symbol, expiry, instrument_id, option type, or strike.
    Overrides may change only option_type and strike when explicitly supplied.
    """

    def resolve(self, request: OptionIdentityResolutionInput) -> OptionInstrumentIdentity:
        identity = request.instrument_identity
        if identity is None:
            raise IdentityResolutionError("OPTION_IDENTITY_REQUIRED")

        option_type = request.option_type_override if request.option_type_override is not None else identity.option_type
        strike = request.strike_override if request.strike_override is not None else identity.strike

        # An override that changes contract identity requires an authoritative
        # contract-master lookup. This resolver has no such source, so it must
        # fail closed rather than attach a new option_type/strike to the old id.
        if request.option_type_override is not None and request.option_type_override != identity.option_type:
            raise IdentityResolutionError("AUTHORITATIVE_IDENTITY_REQUIRED_FOR_OPTION_TYPE_OVERRIDE")
        if request.strike_override is not None and request.strike_override != identity.strike:
            raise IdentityResolutionError("AUTHORITATIVE_IDENTITY_REQUIRED_FOR_STRIKE_OVERRIDE")

        if not identity.instrument_id:
            raise IdentityResolutionError("INSTRUMENT_ID_REQUIRED")
        if not identity.symbol:
            raise IdentityResolutionError("SYMBOL_REQUIRED")
        if not identity.expiry:
            raise IdentityResolutionError("EXPIRY_REQUIRED")
        if option_type is None:
            raise IdentityResolutionError("OPTION_TYPE_REQUIRED")
        if strike is None or strike <= 0:
            raise IdentityResolutionError("STRIKE_REQUIRED")

        return OptionInstrumentIdentity(
            instrument_id=identity.instrument_id,
            symbol=identity.symbol,
            expiry=identity.expiry,
            option_type=option_type,
            strike=strike,
        )
```
## Contract
    - 책임 위치: Core/OMS → OrderIntent 생성 직전.
    - 입력: 외부에서 authoritative하게 공급된 OptionInstrumentIdentity + option_type_override + strike_override.
    - 실제 입력 인터페이스: OptionIdentityResolutionInput.instrument_identity.
    - 출력: 새 immutable OptionInstrumentIdentity.
    - 외부 Identity 공급자의 최소 책임은 instrument_id / symbol / expiry / option_type / strike가 채워진 authoritative OptionInstrumentIdentity를 제공하는 것이다.
    - 공급자 조회 방식이나 외부 식별자 형식은 Core 계약에 포함하지 않는다. KIS shrn_iscd 등 source-specific key는 공급자 경계에서 해석한다.
    - symbol, expiry, instrument_id는 authoritative identity에서만 가져온다.
    - option_type/strike override가 authoritative identity와 동일하면 그대로 보존한다.
    - override가 실제 option contract identity를 변경하면 authoritative Contract Master/selector가 필요하다. 현재 Resolver는 그 source를 가지지 않으므로 fail-closed 한다.
    - identity가 없거나 필수 option identity가 비어 있으면 실패한다.
    - KOSPI200, 빈 expiry, CALL, 0.0 등의 legacy default를 보완값으로 사용하지 않는다.
    - Broker/VMS/VSSF/KIS/API를 참조하지 않는다.
    - Resolver 이후 OMS/Risk/Router는 identity를 재작성하지 않는다.
## Legacy compatibility boundary
원격 Exp_Detail_1의 CanonicalStrategySignal.symbol/expiry additive 확장은 legacy 전달·보존용으로 취급한다. Standard Core의 최종 identity는 이 Resolver를 통해 OptionInstrumentIdentity로 확정한다.

[Child Page] contracts.py
```python
from contracts.types import ExecutionReport, OrderAckEvent
from core.oms.oms_fsm import OrderState, OrderStateMachine, OrderStateTransitionError


__all__ = (
    "ExecutionReport",
    "OrderAckEvent",
    "OrderState",
    "OrderStateMachine",
    "OrderStateTransitionError",
)
```
## Ownership correction
ExecutionReport is a canonical environment/Core boundary DTO and is therefore owned by contracts/types.py.
core/oms/contracts.py retains the public import/re-export for compatibility while OrderStateMachine remains the OMS responsibility.
Environment adapters translate OrderIntent to BrokerOrderCommand and return canonical ExecutionReport values.
## ACK state boundary note
OrderAckEvent는 Broker transport ACK를 OMS 주문 접수 상태에 반영하기 위한 canonical event다. ACK는 ExecutionReport가 아니며 체결수량·체결가격·execution id를 생성하지 않는다. 실제 체결은 ExecutionProvider에서 ExecutionReport로 공급하고 OrderStateMachine.apply_execution()을 통해 OMS 상태를 전이한다.
## No.423 상태전이 구현 판단
현재 OrderStateMachine은 apply_intent() 및 apply_execution() 중심으로 존재하며 ACK 전용 상태전이 API는 확인되지 않았다. 따라서 ACK를 execution으로 오인하지 않는 최소 경계로 apply_ack()를 추가하는 것이 필요하다. 상태명은 기존 코드에 없는 새로운 업무 상태를 임의 확장하지 않고, 우선 ACKED를 canonical 접수 상태로 사용한다. Reject는 REJECTED로 기록한다. Position 변경은 수행하지 않는다.
### ACK 적용 계약
```python
from contracts.types import OrderAckEvent


def apply_ack(self, event: OrderAckEvent):
    """Record broker acceptance/rejection only; never mutate execution/position state."""
    if event.accepted:
        self._states[event.client_order_id] = "ACKED"
    else:
        self._states[event.client_order_id] = "REJECTED"
```
apply_ack()는 주문 상태만 변경하며 filled_quantity, remaining_quantity, execution_price, Position 등을 변경하지 않는다. 실제 구현 시 기존 OrderStateMachine의 상태 저장 구조와 transition validation을 그대로 사용해야 한다.
[Child Page] multi_leg_plan.py
```python
from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from contracts.types import ExecutionLeg, MultiLegExecutionPlan


def build_pair_plan(
    *,
    group_id: str,
    strategy_id: str,
    purpose: str,
    put_strike: Decimal,
    call_strike: Decimal,
    put_quantity: int,
    call_quantity: int,
    side: str = "BUY",
) -> MultiLegExecutionPlan:
    """Build a typed CALL/PUT pair without encoding submission policy."""
    return MultiLegExecutionPlan(
        group_id=group_id,
        strategy_id=strategy_id,
        purpose=purpose,
        legs=(
            ExecutionLeg("put", side, put_quantity, "PUT", put_strike),
            ExecutionLeg("call", side, call_quantity, "CALL", call_strike),
        ),
    )


def build_trap_plan(
    *,
    group_id: str,
    strategy_id: str,
    purpose: str,
    short_put: Decimal,
    short_call: Decimal,
    long_put: Decimal,
    long_call: Decimal,
    quantity: int = 1,
) -> MultiLegExecutionPlan:
    """Build Track2's four-leg trap while preserving side and strike per leg."""
    return MultiLegExecutionPlan(
        group_id=group_id,
        strategy_id=strategy_id,
        purpose=purpose,
        legs=(
            ExecutionLeg("short_put", "SELL", quantity, "PUT", short_put),
            ExecutionLeg("short_call", "SELL", quantity, "CALL", short_call),
            ExecutionLeg("long_put", "BUY", quantity, "PUT", long_put),
            ExecutionLeg("long_call", "BUY", quantity, "CALL", long_call),
        ),
    )
```
## Ownership
        - Strategy layer computes side/quantity/option_type/strike and returns a typed plan.
        - group_id identifies one logical strategy intent; each leg_id is stable only within that group.
        - Instrument master resolution and concrete OrderIntent creation remain downstream.
        - This module does not define atomicity, submission order, compensation, or partial-fill policy.

[Child Page] position_group.py
```python
from dataclasses import dataclass
from enum import Enum
from typing import Mapping

class LegStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"

@dataclass(frozen=True)
class PositionGroupLeg:
    leg_id: str
    group_id: str
    instrument_id: str
    side: str
    quantity: int
    status: LegStatus = LegStatus.PENDING

@dataclass(frozen=True)
class PositionGroup:
    group_id: str
    strategy_id: str
    direction: str
    legs: tuple[PositionGroupLeg, ...]

    @property
    def is_complete(self) -> bool:
        return bool(self.legs) and all(leg.status == LegStatus.FILLED for leg in self.legs)

    @property
    def is_integral(self) -> bool:
        if not self.legs:
            return False
        return all(leg.group_id == self.group_id and leg.quantity > 0 for leg in self.legs)

class PositionGroupRegistry:
    def __init__(self) -> None:
        self._groups: dict[str, PositionGroup] = {}

    def register(self, group: PositionGroup) -> None:
        if group.group_id in self._groups:
            raise ValueError(f"duplicate position group: {group.group_id}")
        if not group.is_integral:
            raise ValueError(f"invalid position group: {group.group_id}")
        self._groups[group.group_id] = group

    def get(self, group_id: str) -> PositionGroup:
        return self._groups[group_id]

    def replace(self, group: PositionGroup) -> None:
        if group.group_id not in self._groups:
            raise KeyError(group.group_id)
        if not group.is_integral:
            raise ValueError(f"invalid position group: {group.group_id}")
        self._groups[group.group_id] = group

    def all(self) -> Mapping[str, PositionGroup]:
        return dict(self._groups)
```
Track3 asymmetric legging은 이 계약을 통해 group/leg identity를 보존한다. Strategy는 이 Registry를 직접 호출하지 않고, Decision/OMS가 생성·갱신한다.

[Child Page] track3_legging.py
```python
from dataclasses import dataclass
from contracts.types import OrderIntent
from core.oms.position_group import PositionGroupLeg, LegStatus

@dataclass(frozen=True)
class LeggingPlan:
    group_id: str
    first_leg: PositionGroupLeg
    second_leg: PositionGroupLeg

class Track3LeggingCoordinator:
    """Turns a two-leg Track3 plan into sequential OrderIntent objects.

    No broker, clock, VMS/VSSF or UI dependency is allowed here.
    """
    def start(self, plan: LeggingPlan, *, price: object, purpose: str) -> OrderIntent:
        leg = plan.first_leg
        return OrderIntent(
            client_order_id=leg.leg_id,
            instrument_id=leg.instrument_id,
            side=leg.side,
            quantity=leg.quantity,
            intent_type=f"{purpose}:{plan.group_id}:{leg.leg_id}",
            group_id=plan.group_id,
            leg_id=leg.leg_id,
        )

    def next_after_fill(self, plan: LeggingPlan, filled_leg_id: str) -> OrderIntent | None:
        if filled_leg_id != plan.first_leg.leg_id:
            return None
        leg = plan.second_leg
        return OrderIntent(
            client_order_id=leg.leg_id,
            instrument_id=leg.instrument_id,
            side=leg.side,
            quantity=leg.quantity,
            intent_type=f"TRACK3_LEG2:{plan.group_id}:{leg.leg_id}",
            group_id=plan.group_id,
            leg_id=leg.leg_id,
        )
```
price는 현재 OrderIntent가 가격 필드를 갖지 않기 때문에 의도적으로 사용하지 않는다. 실제 지정가/시장가 및 timeout/fallback은 Environment Execution Contract에서 결정해야 한다.
원격 Track3의 _execute_asymmetric_legging()이 첫 번째 OTM leg를 제출하고 pending 상태에 ATM leg를 보관한 뒤, on_leg_filled()에서 두 번째 주문을 생성하는 구조를 그대로 개념적으로 보존한다. fileciteturn271file0L2-L2

[Child Page] order_intent_factory.py
```python
from dataclasses import dataclass
from decimal import Decimal
from contracts.types import OptionInstrumentIdentity, OrderIntent
from core.strategy.contracts import Signal
from core.oms.option_identity_resolver import (
    OptionIdentityResolutionInput,
    OptionIdentityResolver,
)


class OrderIntentValidationError(ValueError):
    """Raised when a Signal cannot be converted into an executable intent."""


@dataclass(frozen=True)
class OrderIntentExecutionInput:
    """Execution semantics supplied by Risk/Position Logic, not Strategy."""

    client_order_id: str
    quantity: int
    requested_price: Decimal | None
    order_type: str
    order_purpose: str
    asset_type: str
    track_id: str | None = None
    tag_id: str | None = None


@dataclass(frozen=True)
class OrderIntentFactory:
    """Builds an immutable OrderIntent after identity resolution.

    Strategy supplies direction and optional option-selection overrides.
    Risk/Position Logic supplies executable quantity and price semantics.
    The factory never invents missing identity or execution values.
    """

    resolver: OptionIdentityResolver

    def create(
        self,
        signal: Signal,
        execution: OrderIntentExecutionInput,
    ) -> OrderIntent:
        if execution.quantity <= 0:
            raise OrderIntentValidationError("QUANTITY_REQUIRED")
        if not execution.order_type:
            raise OrderIntentValidationError("ORDER_TYPE_REQUIRED")
        if not execution.order_purpose:
            raise OrderIntentValidationError("ORDER_PURPOSE_REQUIRED")
        if not execution.asset_type:
            raise OrderIntentValidationError("ASSET_TYPE_REQUIRED")

        side = {"LONG": "BUY", "SHORT": "SELL"}.get(signal.direction)
        if side is None:
            raise OrderIntentValidationError("ORDER_SIDE_REQUIRED")

        identity = None
        instrument_id = ""
        if execution.asset_type == "OPTION":
            identity = self.resolver.resolve(
                OptionIdentityResolutionInput(
                    instrument_identity=signal.instrument_identity,
                    option_type_override=signal.option_type_override,
                    strike_override=signal.strike_override,
                )
            )
            instrument_id = identity.instrument_id
        elif signal.instrument_identity is not None:
            identity = signal.instrument_identity
            instrument_id = identity.instrument_id

        if not instrument_id:
            raise OrderIntentValidationError("INSTRUMENT_ID_REQUIRED")

        return OrderIntent(
            client_order_id=execution.client_order_id,
            instrument_id=instrument_id,
            side=side,
            quantity=execution.quantity,
            intent_type=execution.order_purpose,
            strategy_id=signal.strategy_id,
            risk_context=None,
            instrument_identity=identity,
            asset_type=execution.asset_type,
            requested_price=execution.requested_price,
            order_type=execution.order_type,
            order_purpose=execution.order_purpose,
            track_id=execution.track_id,
            tag_id=execution.tag_id,
        )
```
## 책임 경계
    - Strategy Signal은 direction/confidence/reason과 identity/option override만 제공한다.
    - quantity, requested_price, order_type, order_purpose는 Risk/Position Logic 또는 상위 주문 정책이 공급한다.
    - OPTION은 OptionIdentityResolver를 반드시 거쳐 immutable identity를 확정한다.
    - identity가 없거나 필수 값이 없으면 synthetic fallback 없이 실패한다.
    - 기존 Track 전략의 계산/주문 실행 로직을 이 Factory에 복제하지 않는다.
    - FUTURES 등 non-option도 임의 instrument_id를 만들지 않고 authoritative identity가 제공될 때만 사용한다.
## Contract reference
This page is the Standard OrderIntentExecutionInput factory contract used in the Phase 15 comparison. Its execution input requires client_order_id, quantity, requested_price, order_type, order_purpose, asset_type, track_id, and tag_id.

[Child Page] POSITION_ORDER_INTENT_SUPPLY_TRACE.md
## 목적
No.110 다음 단계로 Reference Baseline의 실제 주문 생성 경로를 재대조하여 Standard OrderIntentExecutionInput의 각 필드가 어디에서 authoritative하게 공급되는지 확정한다.
## Reference Baseline 추적 결과
기준 브랜치: Exp_Detail_1
실제 경로:
Track 1~9 → CanonicalStrategySignal → DecisionArbiter → CanonicalOrderCommand → RiskGate → OrderRouter → Environment
### quantity
    - 초기 공급원: 각 Strategy 결과의 sig["qty"]
    - CanonicalStrategySignal.qty → CanonicalOrderCommand.qty로 전달
    - RiskEngine은 승인 단계에서 한도/증거금 조건에 따라 qty를 감소시킬 수 있음
    - 따라서 Standard 경계에서는 전략 제안 수량과 Risk/Position 승인 후 실행 수량을 동일한 authoritative source로 취급하면 안 됨
### requested_price
    - 초기 공급원: Strategy 결과의 sig["price"]
    - 누락 시 Reference Runtime은 tick.last_price fallback을 사용
    - 최종 CanonicalOrderCommand.price는 주문 요청가격 의미
    - 실제 체결가격은 별도 ExecutionReport에서 생성됨
    - Standard 구조에서는 synthetic fallback을 새로 만들지 않고, 실제 가격 공급원이 명시되지 않으면 validation failure 또는 upstream contract gap으로 처리
### asset_type
    - Reference Runtime이 Strategy signal의 asset/type에서 OPTION/FUTURES를 분류하여 공급
    - Standard OrderIntentExecutionInput.asset_type의 실제 upstream source는 Strategy/Signal domain 분류임
### track_id / tag_id
    - track_id: Strategy identity에서 공급
    - tag_id: Strategy signal에서 공급하며 RiskEngine의 특수 정책 식별에도 사용
    - provenance로 보존 가능
### order_type
    - Reference CanonicalOrderCommand에는 독립 필드가 없음
    - 따라서 현재 Baseline에서 authoritative 공급원을 확인할 수 없음
### order_purpose
    - Reference CanonicalOrderCommand에는 독립 필드가 없음
    - 일부 track_id/tag_id가 목적을 암시하지만 표준 order_purpose의 authoritative source로 승격할 근거는 없음
## 핵심 판정
Reference Baseline에는 No.006의 표준 흐름에 명시된 독립적인 Position Logic → Order Intent 실행 의미 공급 단계가 아직 존재하지 않는다.
따라서 다음을 금지한다.
    - Baseline에 없는 order_type/order_purpose 기본값 생성
    - track_id/tag_id를 임의로 order_purpose로 변환
    - Strategy qty를 Risk 승인 후 실행 qty로 무조건 간주
    - requested_price와 execution price 혼합
## Standard 구현에 대한 영향
현재 OrderIntentFactory의 OrderIntentExecutionInput은 계약상 필요한 실행 의미를 명시하지만, 모든 필드가 Reference Baseline의 기존 공급원으로 이미 충족되는 것은 아니다.
현재 확인된 authoritative 공급 상태:
    - quantity: 부분 확인 — Strategy 제안값 존재, Risk 최종값은 별도 승인 결과
    - requested_price: 부분 확인 — Strategy price 존재, legacy fallback은 Standard로 이식하지 않음
    - asset_type: 확인
    - track_id/tag_id: 확인
    - order_type: 공급원 없음
    - order_purpose: 공급원 없음
## 다음 구현 기준
다음 단계에서는 새로운 synthetic Position Logic을 임의 생성하지 않는다.
먼저 Standard Core에서 Position/Execution Policy Contract가 실제로 어떤 계층의 책임이어야 하는지 확정하고, order_type/order_purpose 및 Risk 승인 후 quantity를 공급하는 최소 계약을 설계한다.

[Child Page] position_execution_policy.py
```python
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


class PositionExecutionPolicyError(ValueError):
    pass


@dataclass(frozen=True)
class PositionExecutionRequest:
    """Authoritative inputs already produced upstream; no synthetic defaults."""
    client_order_id: str
    proposed_quantity: int
    requested_price: Decimal | None
    asset_type: str
    track_id: str | None = None
    tag_id: str | None = None


@dataclass(frozen=True)
class PositionExecutionDecision:
    """Execution semantics owned by Position/Risk/Order Policy boundary."""
    client_order_id: str
    approved_quantity: int
    requested_price: Decimal | None
    order_type: str
    order_purpose: str
    asset_type: str
    track_id: str | None = None
    tag_id: str | None = None


class PositionExecutionPolicy(Protocol):
    def decide(
        self,
        request: PositionExecutionRequest,
    ) -> PositionExecutionDecision:
        ...
```
## 책임 경계
    - Strategy는 proposed quantity와 방향/identity를 제안한다.
    - Position/Risk/Order Policy는 실행 가능 quantity와 주문 실행 의미를 결정한다.
    - approved_quantity는 Strategy 제안값과 구분된다.
    - requested_price는 요청 가격이며 체결 가격이 아니다.
    - order_type, order_purpose는 반드시 실제 상위 정책이 공급한다.
    - Contract 자체는 LIMIT/ENTRY 같은 기본값을 만들지 않는다.
    - RiskEngine의 REDUCE/DENY 결과를 이 계약으로 억지 변환하지 않는다. 실제 Standard 연결 시 승인 결과의 authoritative mapping을 별도로 확정한다.
## OrderIntentFactory 연결 규칙
PositionExecutionDecision의
    - approved_quantity → quantity
    - requested_price → requested_price
    - order_type → order_type
    - order_purpose → order_purpose
    - asset_type / track_id / tag_id → provenance
로 1:1 전달한다.
## Risk 결과 연결 원칙
Reference RiskEngine의 실제 결과는 ALLOW / REDUCE / DENY 세 상태를 가진다.
    - DENY: OrderIntent를 생성하지 않는다. rejection_reason을 보존하고 상위 흐름에서 종료한다.
    - ALLOW: approved_quantity를 실행 수량으로 사용한다.
    - REDUCE: RiskEngine의 reduced_command.qty 또는 동등하게 명시된 승인 수량을 실행 수량으로 사용한다. proposed_quantity를 다시 사용하지 않는다.
order_type과 order_purpose는 RiskEvaluationResult에 존재하지 않으므로 Risk 결과에서 추론하지 않는다. 이 값은 PositionExecutionDecision의 authoritative 공급값만 사용한다.
## 현재 상태
이 페이지는 최소 책임 계약 정의다. 새로운 Position 전략이나 주문 정책 구현이 아니다. 기존 Exp_Detail_1에 없는 execution semantics를 임의 생성하지 않고, 누락된 공급 책임을 명시적으로 분리한다.
## Phase 15 후속 확인
CanonicalOrderCommand와 실제 Exp_Detail_1 Runtime을 다시 대조한 결과, 이 계약이 요구하는 order_type / order_purpose는 현재 Reference Runtime에서 공급되지 않는다. 따라서 이 Protocol을 구현하는 구체 정책은 아직 생성하지 않는다. LIMIT, MARKET, ENTRY, EXIT, RISK_HEDGE 등의 값은 실제 상위 정책의 명시적 입력이 확보된 이후에만 공급한다.

[Child Page] risk_order_intent_adapter.py
```python
from dataclasses import replace
from typing import Protocol

from .position_execution_policy import PositionExecutionDecision, PositionExecutionPolicyError
from .order_intent_factory import OrderIntentExecutionInput


class RiskResultLike(Protocol):
    decision: str
    is_approved: bool
    approved_qty: int
    reduced_command: object | None
    rejection_reason: str | None


class RiskOrderIntentMappingError(PositionExecutionPolicyError):
    pass


def build_order_intent_execution_input(
    decision: PositionExecutionDecision,
    risk_result: RiskResultLike,
) -> OrderIntentExecutionInput:
    """Combine Position execution semantics with authoritative Risk quantity.

    This adapter does not infer order_type/order_purpose and does not create
    an input for DENY. Strategy proposed quantity is never used as a fallback.
    """
    status = str(risk_result.decision).upper()

    if status == "DENY" or not risk_result.is_approved:
        raise RiskOrderIntentMappingError(
            risk_result.rejection_reason or "ORDER_DENIED_BY_RISK"
        )

    if status == "ALLOW":
        quantity = int(risk_result.approved_qty)
    elif status == "REDUCE":
        reduced = getattr(risk_result, "reduced_command", None)
        reduced_qty = getattr(reduced, "qty", None) if reduced is not None else None
        if reduced_qty is None:
            raise RiskOrderIntentMappingError("REDUCED_QUANTITY_REQUIRED")
        if int(risk_result.approved_qty) != int(reduced_qty):
            raise RiskOrderIntentMappingError("RISK_QUANTITY_PROVENANCE_MISMATCH")
        quantity = int(reduced_qty)
    else:
        raise RiskOrderIntentMappingError(f"UNKNOWN_RISK_DECISION: {status}")

    if quantity <= 0:
        raise RiskOrderIntentMappingError("APPROVED_QUANTITY_REQUIRED")

    return OrderIntentExecutionInput(
        client_order_id=decision.client_order_id,
        quantity=quantity,
        requested_price=decision.requested_price,
        order_type=decision.order_type,
        order_purpose=decision.order_purpose,
        asset_type=decision.asset_type,
        track_id=decision.track_id,
        tag_id=decision.tag_id,
    )
```
## 계약 목적
PositionExecutionDecision의 실행 의미와 Reference Risk 결과를 기존 OrderIntentFactory가 요구하는 OrderIntentExecutionInput으로 1회 변환한다.
## 보존 규칙
    - ALLOW: approved_qty → quantity
    - REDUCE: reduced_command.qty → quantity; approved_qty와 불일치하면 실패
    - DENY: OrderIntentExecutionInput 자체를 생성하지 않고 거부 사유를 전달
    - requested_price, order_type, order_purpose, asset_type, track_id, tag_id는 PositionExecutionDecision에서 그대로 전달
    - proposed_quantity는 fallback으로 사용하지 않음
    - Risk 결과로 order_type/order_purpose를 추론하지 않음
    - 현재 Reference Runtime의 allow_reduction 동작을 이 Adapter가 변경하지 않음

[Child Page] canonical_order_command_order_intent_contract_comparison.md
## Baseline
Reference Runtime: CanonicalStrategySignal → CanonicalOrderCommand → RiskGate → OrderRouter → Environment.
## Comparison
<!-- Notion table block -->
| Field | CanonicalOrderCommand | Standard OrderIntentExecutionInput / OrderIntent | Decision |
| client_order_id | str | str | Direct 1:1 |
| quantity | qty: int | quantity: int | Use authoritative post-Risk quantity; never Strategy qty as fallback |
| requested_price | price: float | `requested_price: Decimal | None` |
| side | CanonicalOrderSide BUY/SELL | OrderIntent side: str; Factory currently derives from Signal.direction | Preserve Canonical BUY/SELL; do not reverse-map through LONG/SHORT |
| asset_type | CanonicalAssetType | execution asset_type / OrderIntent asset_type | Direct semantic mapping |
| track_id | str | `str | None` |
| tag_id | str | `str | None` |
| option_type | optional CanonicalOptionType | OptionInstrumentIdentity.option_type | Identity mapping + equality validation |
| strike | float | OptionInstrumentIdentity.strike | Identity mapping + equality validation |
| symbol | str | OptionInstrumentIdentity.symbol | Preserve authoritative identity value; no default supplementation |
| expiry | str | OptionInstrumentIdentity.expiry | Preserve authoritative value; no inference |
| instrument_id | absent as stored field; command exposes get_instrument_key() | required by OrderIntent | Requires explicit identity equivalence validation; no synthetic ID |
| order_type | absent | required by execution input / optional on OrderIntent | No safe source in current Canonical Runtime |
| order_purpose | absent | required by execution input / optional on OrderIntent | No safe source in current Canonical Runtime |
| broker-specific fields | absent | absent from Core; BrokerOrderCommand owns them | Environment-only |
## Non-negotiable mapping rules
    - No order_type default such as LIMIT may be introduced from legacy OrderRequest.
    - No order_purpose may be inferred from track/tag/action/side.
    - No new instrument_id may be generated when authoritative identity is absent.
    - OPTION identity must remain internally consistent with symbol/expiry/option_type/strike and its instrument_id.
    - Risk ALLOW/REDUCE determines executable quantity; DENY creates no execution intent.
## Current implementation decision
Do not replace the Reference Runtime's CanonicalOrderCommand path yet. A non-invasive adapter may be introduced only after an authoritative supplier for order_type and order_purpose is defined and identity equivalence is validated.

canonical_order_command_order_intent_contract_comparison.md

[Child Page] order_position_execution_policy.py
## 목적
No.006의 표준 흐름 Market State → Strategy → Signal → Decision → Risk Validation → Position Logic → Order Intent를 기준으로, 현재 Exp_Detail_1의 기존 주문 동작을 유지하면서 order_purpose의 권위 있는 공급 경계를 분리한다.
## 핵심 원칙
    - Position Logic은 Strategy action을 단순 문자열 변환하는 계층이 아니라 실제 포지션 상태와 명시된 실행 의도를 근거로 Order Intent에 필요한 실행 의미를 공급하는 책임 경계다.
    - 현재 Exp_Detail_1에는 이 책임을 수행하는 authoritative Position Logic의 order_purpose 공급 필드/구현이 확인되지 않았다.
    - 따라서 지금 단계에서 실제 purpose 값을 만들거나 action→purpose 매핑을 추가하지 않는다.
    - order_type과 order_purpose는 분리한다.
    - 기존 VSSF 실행 동작이 LIMIT이므로 order_type=LIMIT은 compatibility policy로 보존할 수 있다. 이것은 CanonicalOrderCommand에 독립적인 order_type이 존재한다는 의미가 아니다.
    - Risk 결과는 최종 수량에 대한 authoritative source이며 Policy가 수량을 임의 결정하지 않는다.
    - track_id, tag_id, side, Strategy action 이름으로 order_purpose를 추론하지 않는다.
## 최소 책임 계약
```python
from dataclasses import dataclass
from typing import Optional, Protocol

class OrderPurposeResolutionError(ValueError):
    pass

@dataclass(frozen=True)
class ExplicitPositionExecutionIntent:
    """Position Logic 경계에서 명시적으로 공급되는 실행 의미."""
    order_purpose: str
    order_type: Optional[str] = None

@dataclass(frozen=True)
class OrderPositionExecutionPolicyInput:
    client_order_id: str
    asset_type: str
    side: str
    position_execution_intent: Optional[ExplicitPositionExecutionIntent]
    track_id: Optional[str] = None
    tag_id: Optional[str] = None

@dataclass(frozen=True)
class OrderPositionExecutionPolicyDecision:
    client_order_id: str
    order_type: str
    order_purpose: str

class OrderPositionExecutionPolicy(Protocol):
    def decide(
        self,
        request: OrderPositionExecutionPolicyInput,
    ) -> OrderPositionExecutionPolicyDecision:
        ...
```
## 의미 결정 규칙
### order_purpose
    1. Position Logic이 명시적 ExplicitPositionExecutionIntent.order_purpose를 공급해야 한다.
    1. 공급되지 않으면 성공 Decision을 반환하지 않는다.
    1. track_id, tag_id, side, FENCE_BUILD, FENCE_CLEAR, FUTURES_ORDER, FUTURES_UNWIND, TAIL_DEFENSE_BUILD, FLATTEN_ALL 등으로 추론하지 않는다.
    1. 기존 legacy OrderRequest.order_purpose 기본값을 현재 Canonical Runtime에 승격하지 않는다.
### order_type
    1. 명시적 intent에 값이 있으면 compatibility policy가 허용하는지 검증한다.
    1. 값이 없으면 현재 기존 실행 동작 보존을 위해 LIMIT을 사용할 수 있다.
    1. 지원되지 않는 유형은 실패 처리한다.
    1. order_type compatibility fallback은 order_purpose의 필수 명시 공급을 완화하지 않는다.
## 최소 구현 골격
```python
class ExplicitOrderPositionExecutionPolicy:
    def decide(self, request: OrderPositionExecutionPolicyInput):
        intent = request.position_execution_intent
        if intent is None or not str(intent.order_purpose).strip():
            raise OrderPurposeResolutionError(
                "ORDER_PURPOSE_POSITION_LOGIC_INTENT_REQUIRED"
            )

        order_type = str(intent.order_type).strip() if intent.order_type else "LIMIT"
        if order_type != "LIMIT":
            raise OrderPurposeResolutionError(
                f"UNSUPPORTED_ORDER_TYPE_COMPATIBILITY_POLICY: {order_type}"
            )

        return OrderPositionExecutionPolicyDecision(
            client_order_id=request.client_order_id,
            order_type=order_type,
            order_purpose=str(intent.order_purpose).strip(),
        )
```
## Adapter 연결 경계
향후 연결은 다음과 같이 제한한다.
CanonicalOrderCommand + authoritative Risk result + Position Logic explicit execution intent/policy decision → Standard OrderIntentExecutionInput
Adapter 금지사항:
    - order_type 임의 추론
    - order_purpose 임의 추론
    - Risk 결과로 purpose/type 생성
    - track/tag/action을 purpose로 승격
    - 새로운 instrument_id 생성
    - Strategy 제안 수량을 Risk 승인 수량 대신 사용
## 현재 Runtime 적용 판단
현재 Reference Runtime은 Strategy → CanonicalOrderCommand → RiskGate → OrderRouter → VSSF/Environment → Broker다. 따라서 이 정책을 즉시 삽입하지 않는다.
No.006의 목표 구조에 맞추어 향후 연결 위치는 Risk Validation → Position Logic → Order Intent 사이로 정의하되, 기존 프로그램에 없는 Position Logic의 구체적인 purpose 결정 규칙은 별도 근거가 확인될 때까지 구현하지 않는다.
## 검증 기준
    - Position Logic explicit purpose 없음 → 실패
    - explicit purpose 있음 + order_type 없음 → LIMIT
    - explicit LIMIT → LIMIT
    - 지원하지 않는 order_type → 실패
    - Policy는 quantity를 결정하지 않음; 최종 quantity는 Risk 결과가 authoritative source
    - Policy는 instrument identity를 새로 생성하지 않음
    - 현재 Canonical Runtime은 변경하지 않음

[Child Page] track_execution_intent_provenance.md
# 목적
No.123에서 확인된 Track 1~9의 실행 provenance와 현재 Canonical Runtime 사이의 전달 단절을 보존 관점에서 정리한다.
## 정정된 핵심 사실
Track9를 포함한 전략 코드에는 일부 signal에 명시적인 order_purpose/order_type 정보가 존재할 수 있으나, 이것이 모든 Track에 공통된 것은 아니다. 따라서 존재하는 명시값은 보존하고, 존재하지 않는 값은 추론하지 않는다.
## 보존 원칙
    - strategy action은 원문 provenance로 보존한다.
    - strategy가 명시한 order_purpose가 있으면 별도 declared 값으로 보존한다.
    - strategy가 명시한 order_type이 있으면 별도 declared 값으로 보존한다.
    - action/track/tag/side/position 방향만으로 purpose를 생성하지 않는다.
    - legacy DTO 기본값을 현재 의미로 승격하지 않는다.
    - Position Logic에서 explicit execution intent가 공급될 때만 Standard OrderPurpose로 확정한다.
## 다음 전달계약
Strategy → Execution Provenance → Canonical/Intermediate → Risk → Position Logic → Explicit Execution Intent → OrderIntent
여기서 provenance는 관찰·보존 데이터, execution intent는 실행을 위해 명시적으로 결정된 데이터로 분리한다. 이 둘을 하나의 enum으로 합치지 않는다.
## 보호 범위
원격 Exp_Detail_1은 변경하지 않는다. 기존 전략 규칙을 재작성하거나 action을 임의의 ENTRY/EXIT/HEDGE로 변환하지 않는다.
## 다음 단계
실제 DecisionArbiter → CanonicalOrderCommand 생성 지점을 추적하여 provenance가 어느 경계에서 소실되는지 확인하고, 기존 Runtime을 변경하지 않는 최소 전달 지점을 결정한다.

[Child Page] track_execution_intent_provenance_process_notes.md
## 작업 목적
No.122의 다음 단계 지시에 따라 Exp_Detail_1의 Track 1~9 및 실제 Position 상태를 대조하여 기존 코드에 이미 존재하는 명시적 execution intent/order_purpose가 있는지 확인하고, 새 전략 규칙을 만들지 않는 범위에서 Standard Position Logic으로 보존 가능한 provenance를 판정했다.
## 대조 결과
    - Track 1~8의 확인된 전략 신호 구조에는 독립적인 order_purpose 필드가 없다. action, type, qty, price, pricing_mode, tag_id 및 전략별 상태값이 중심이다.
    - Track 9의 raw legacy signal에는 명시적인 order_purpose가 실제 존재한다.
        - ADD_INSURANCE: ENTRY
        - REDUCE_INSURANCE: EXIT
        - EARLY_PROFIT_TAKE: EXIT
        - REHEDGE_ENTRY: ENTRY
    - 따라서 Track9의 값은 action 이름에서 추론한 값이 아니라 기존 코드가 직접 공급한 명시값이다.
    - 그러나 Standard Core Track9에서는 이 purpose가 Signal 객체의 독립 필드로 보존되지 않고 action/reason payload 형태로 전환되어 있으며, CanonicalStrategySignal/CanonicalOrderCommand에도 order_purpose가 없다.
    - 실제 PositionManager의 aggregate/order attribution 데이터에는 client_order_id, symbol, side, qty, avg_price 등이 있으나 order_purpose를 저장·결정하지 않는다.
## No.006 기준 판정
No.006의 Market State → Strategy → Signal → Decision → Risk Validation → Position Logic → Order Intent 경계를 유지해야 한다. 따라서 Track9의 기존 명시 purpose를 Position Logic이 새로 추론하는 것이 아니라, 명시적 provenance로 보존하여 Risk 이후 Position Logic에서 검증·최종 공급할 수 있는 전달 계약이 필요하다.
Track1~8은 현재 명시 purpose 공급원이 확인되지 않았으므로 STRATEGY_ENTRY 등의 기본값을 넣거나 action/track/tag/side를 purpose로 변환하지 않는다. purpose가 필요한 실행 Intent에서 근거가 없으면 fail-closed한다.
order_type은 별도 문제이며 기존 VSSF의 LIMIT 실행 호환 정책으로 관리한다. purpose provenance와 혼합하지 않는다.
## 구현 판단
이번 단계에서는 실제 Canonical DTO나 Runtime을 변경하지 않는다. 먼저 다음 최소 계약을 설계한다.
    1. 기존 raw signal에 명시 purpose가 있는 경우 그 provenance를 잃지 않는 전달 객체/필드.
    1. Risk Validation 이후 Position Logic에서 해당 명시값을 검증하고 ExplicitPositionExecutionIntent로 공급하는 경계.
    1. purpose가 없는 Track은 임의 보정하지 않고 OrderIntent 단계에서 실패시키는 조건.
    1. 기존 LIMIT 호환 정책은 계속 독립 유지.
## 원격 Git 및 테스트 경계
    - 원격 Exp_Detail_1 수정·생성·삭제 없음.
    - 원격 브랜치 대상 터미널 테스트 실행 없음.
    - GitHub 정적 대조와 Notion 기준 대조만 수행.
## 다음 작업
Track9의 명시 ENTRY/EXIT를 보존할 수 있는 최소 provenance 전달 계약을 Standard Core/Canonical 경계에 설계하고, Track1~8의 미공급 상태를 fail-closed로 유지할 수 있는지 검토한다.

[Child Page] execution_provenance.py
# 역할
Strategy가 이미 알고 있는 실행 provenance를 손실 없이 보존하기 위한 중간 계약이다. 이 객체는 OrderPurpose를 결정하지 않는다.
## 계약
```python
from dataclasses import dataclass
from typing import Any, Mapping, Optional

@dataclass(frozen=True)
class ExecutionProvenance:
    strategy_id: Optional[str] = None
    track_id: Optional[str] = None
    tag_id: Optional[str] = None
    action: Optional[str] = None
    reason: Optional[str] = None
    entry_reason: Optional[str] = None
    exit_reason: Optional[str] = None
    declared_order_purpose: Optional[str] = None
    declared_order_type: Optional[str] = None
    metadata: Mapping[str, Any] | None = None
```
## 의미
    - action: 전략이 생성한 원문 실행 provenance. 해석하지 않는다.
    - declared_order_purpose: 전략/상위 정책이 실제로 명시한 경우에만 저장한다.
    - declared_order_type: 실제 명시된 경우에만 저장한다.
    - metadata: 기존 전략별 추가 provenance를 잃지 않기 위한 보조 영역이다.
## 금지 규칙
```plain text
action            ─X→ order_purpose
track_id/tag_id   ─X→ order_purpose
side              ─X→ order_purpose
position direction─X→ order_purpose
missing value     ─X→ synthetic default
```
## Position Logic과의 경계
```plain text
ExecutionProvenance
       │
       │ 보존 데이터
       ▼
Position Logic
       │
       │ explicit execution intent가 실제로 존재할 때만 결정
       ▼
ExplicitPositionExecutionIntent
       │
       ▼
OrderIntent
```
declared_order_purpose가 존재하더라도 그것을 자동으로 Standard OrderPurpose로 승격하는 것은 Position Logic의 검증·정책 책임으로 남긴다. 즉 provenance와 실행 의사결정은 동일 객체/동일 책임으로 취급하지 않는다.
## order_type
order_type=LIMIT compatibility는 이 provenance 계약과 독립적이다. 현재 Runtime의 LIMIT 동작을 보존하는 정책에서 별도로 처리한다.
## 현재 적용 상태
이 페이지는 OptionProject 설계 계약이며 원격 Exp_Detail_1에 직접 적용하지 않는다. 실제 Runtime 연결은 DecisionArbiter → CanonicalOrderCommand의 provenance 소실 지점을 확인한 후 결정한다.

[Child Page] strategy_provenance_transport_design.md
No.125에서 확인한 실제 provenance 소실 지점을 기준으로, 기존 Exp_Detail_1 Runtime의 의미와 기능을 변경하지 않으면서 Strategy provenance를 다음 계층까지 보존하는 방법을 비교한다.
## 실제 소실 지점
program_runtime.py에서 전략 결과 sig 딕셔너리를 CanonicalStrategySignal로 직접 생성한다.
보존되는 값:
    - qty
    - price
    - asset
    - type / option_type
    - side
    - strike
    - tag_id
현재 Canonical DTO로 전달되지 않는 값:
    - action
    - reason
    - 명시된 order_purpose
    - 명시된 order_type
    - 전략별 기타 metadata
따라서 DecisionArbiter는 이미 provenance가 제거된 CanonicalStrategySignal만 받으며, Arbiter 이후에서 복구하는 것은 불가능하다.
## 전달 방식 비교
### A. CanonicalStrategySignal 자체 확장
CanonicalStrategySignal에 provenance 필드를 추가한다.
장점:
    - 현재 Runtime의 Strategy → Arbiter → 이후 흐름을 가장 적게 변경할 수 있다.
    - Arbiter가 signal 객체를 그대로 반환하므로 provenance 보존이 단순하다.
단점:
    - shared/contracts/canonical.py가 전략별 선택적 metadata까지 알게 된다.
    - Standard Contract가 전략 provenance와 실행 의미를 함께 가지게 될 위험이 있다.
    - 기존 Canonical Contract의 책임 범위가 넓어진다.
### B. 별도 Intermediate Wrapper 사용
CanonicalStrategySignal은 현재 그대로 유지하고, 별도의 wrapper가 signal과 ExecutionProvenance를 함께 보유한다.
예:
StrategySignalEnvelope(signal=CanonicalStrategySignal, provenance=ExecutionProvenance)
장점:
    - 기존 Canonical DTO를 변경하지 않는다.
    - provenance와 canonical execution signal의 책임을 명확히 분리할 수 있다.
    - Strategy별 추가 정보가 Standard Canonical Contract를 오염시키지 않는다.
단점:
    - DecisionArbiter의 입력/출력 타입을 wrapper 기준으로 확장해야 한다.
    - 현재 Arbiter의 정렬·충돌 로직이 wrapper 내부 signal을 참조하도록 변경해야 한다.
### C. Provenance Store/ID 별도 보관
Canonical signal에는 provenance ID만 연결하고 실제 provenance를 별도 저장한다.
장점:
    - Canonical Contract 영향이 가장 작을 수 있다.
단점:
    - 단일 tick 처리에서 별도 저장소가 필요해진다.
    - ID 매핑 실패 가능성이 생긴다.
    - 결정론성과 추적성이 오히려 복잡해진다.
    - 현재 Runtime 목적에 비해 과도하다.
## 결정
현재 단계에서는 B안의 별도 Intermediate Wrapper 방식을 우선 설계안으로 채택한다.
이유:
    1. No.006의 Standard Contracts와 Strategy Framework 책임을 분리한다.
    1. 기존 CanonicalStrategySignal의 의미를 변경하지 않는다.
    1. Strategy가 명시한 provenance를 보존할 수 있다.
    1. order_purpose를 provenance에서 자동으로 실행 의미로 승격하지 않는다.
    1. 기존 Runtime 기능을 보존하면서 향후 Position Logic에서 명시적인 execution intent를 결정할 수 있다.
## 필수 규칙
    - declared_order_purpose가 없으면 None으로 보존한다.
    - declared_order_type가 없으면 None으로 보존한다.
    - action으로 purpose를 추론하지 않는다.
    - track_id, tag_id, side, Position 방향으로 purpose를 추론하지 않는다.
    - legacy OrderRequest의 기본값을 사용하지 않는다.
    - wrapper는 provenance를 보존할 뿐 실행 의미를 결정하지 않는다.
    - Risk 결과의 최종 수량은 별도의 Risk adapter에서 권위 있게 반영한다.
## 향후 최소 연결 후보
Strategy dict → CanonicalStrategySignal + ExecutionProvenance → StrategySignalEnvelope → DecisionArbiter → Risk → Position Logic
단, 현재 Exp_Detail_1 Runtime을 즉시 변경하지 않는다. 먼저 Track 1~9의 provenance 실제 발생 형태를 모두 대조하고 wrapper가 모든 전략의 기존 신호를 손실 없이 감쌀 수 있는지 확인한 후 연결한다.
## 보호 범위
    - 원격 Git Exp_Detail_1 변경 없음
    - 원격 브랜치 터미널 테스트 없음
    - 기존 전략 action의 의미 재해석 없음
    - order_purpose 및 order_type synthetic default 없음

[Child Page] strategy_provenance_transport_design.md
No.125에서 확인한 실제 Runtime의 provenance 소실 지점을 기준으로, 기존 CanonicalStrategySignal의 의미와 현재 주문 경로를 변경하지 않으면서 Strategy의 추가 실행 provenance를 보존하는 최소 전달 구조를 정의한다.
## 실제 확인 결과
program_runtime.py에서 각 Track의 전략 결과 sig를 CanonicalStrategySignal로 field-by-field 변환한다. 현재 변환되는 값은 signal_id, track_id, asset_type, side, qty, price, option_type, strike, tag_id이며, 전략 dictionary에 존재할 수 있는 action, reason, entry_reason, exit_reason, order_purpose, order_type은 Canonical DTO에 전달되지 않는다.
따라서 provenance의 최초 명시적 소실 경계는 다음과 같다.
```plain text
Strategy signal dict
        ↓
program_runtime.py CanonicalStrategySignal 변환
        ↓
CanonicalStrategySignal
```
DecisionArbiter는 이미 생성된 CanonicalStrategySignal을 중재하므로 이 이전 단계에서 사라진 값을 복원할 책임이 없다.
## 최소 보존 구조
기존 Canonical DTO를 즉시 확장하지 않고 별도의 provenance wrapper/intermediate를 사용한다.
```plain text
Strategy
  ↓
CanonicalStrategySignal + ExecutionProvenance
  ↓
StrategySignalEnvelope
  ↓
DecisionArbiter
  ↓
Risk
  ↓
Position Logic
  ↓
ExplicitPositionExecutionIntent
  ↓
OrderIntent
```
## 보존 규칙
    - 기존 Canonical field의 의미를 변경하지 않는다.
    - Strategy가 실제 명시한 order_purpose만 declared_order_purpose로 보존한다.
    - Strategy가 실제 명시한 order_type만 declared_order_type로 보존한다.
    - 값이 없으면 None으로 보존한다.
    - action, track_id, tag_id, side, Position 방향으로 order_purpose를 추론하지 않는다.
    - provenance와 최종 execution intent를 동일 객체/enum으로 취급하지 않는다.
    - 기존 LIMIT 실행 호환성 정책은 purpose 결정과 분리한다.
## Wrapper 설계 원칙
StrategySignalEnvelope는 최소한 다음 두 영역을 보존해야 한다.
    1. signal: 기존 CanonicalStrategySignal
    1. provenance: ExecutionProvenance
Provenance에는 전략별 추가 정보가 존재할 수 있으므로 전략별 metadata를 보존할 수 있어야 한다. 다만 현재 Runtime에서 실제 사용되지 않는 값을 새 의미로 변환해서는 안 된다.
## Runtime 연결 원칙
현재 DecisionArbiter와 CanonicalOrderCommand → RiskGate → OrderRouter 경로는 그대로 유지한다. Wrapper를 실제 Runtime에 연결할 때도 기존 주문 수량, 가격, side, asset 및 주문 ID 생성 규칙을 변경하지 않는다.
특히 order_purpose가 없는 Track의 신호에 대해 ENTRY/EXIT/HEDGE 등의 값을 자동 생성하지 않는다.
## 다음 검증 대상
Track 1~9 각각의 실제 signal dictionary가 제공하는 provenance key를 전수 대조하여 Wrapper가 필요한 최소 필드를 확정한다. 그 결과에 따라 실제 Runtime 변경 여부와 변경 범위를 결정한다.
## 보호 범위
    - 원격 Git Exp_Detail_1 변경 없음
    - 원격 브랜치 터미널 테스트 없음
    - 기존 Strategy action 의미 변경 없음
    - legacy OrderRequest 기본값을 승격하지 않음

[Child Page] strategy_signal_envelope.py
## 목적
Track 1~9의 기존 Strategy signal dictionary에서 CanonicalStrategySignal이 담당하는 표준 필드와 전략 고유 provenance를 분리하여 함께 운반하는 최소 Intermediate Wrapper 계약을 정의한다.
## 설계 원칙
    - CanonicalStrategySignal은 변경하지 않는다.
    - ExecutionProvenance는 관찰·보존 데이터이며 실행 의미를 결정하지 않는다.
    - declared_order_purpose와 declared_order_type은 원본 signal에 실제 명시된 경우에만 보존한다.
    - 누락된 값은 None으로 유지한다.
    - action, track_id, tag_id, side, Position 방향으로 order_purpose를 추론하지 않는다.
    - pricing_mode, limit_offset_ticks, fallback_market_timeout_sec, strike/leg 구조 등 전략별 데이터는 metadata에 보존할 수 있다.
    - Risk 승인 수량은 이 wrapper에서 변경하지 않는다.
## 코드
```python
from dataclasses import dataclass
from typing import Mapping, Any

from .execution_provenance import ExecutionProvenance


@dataclass(frozen=True)
class StrategySignalEnvelope:
    """Canonical signal과 원본 strategy provenance를 함께 운반한다.

    이 객체는 실행 의미를 결정하거나 Canonical 값을 재작성하지 않는다.
    """

    signal: Any
    provenance: ExecutionProvenance

    @property
    def signal_id(self) -> str:
        return str(self.signal.signal_id)

    @property
    def track_id(self) -> str:
        return str(self.signal.track_id)


def build_strategy_signal_envelope(
    signal: Any,
    raw_signal: Mapping[str, Any],
    *,
    strategy_id: str | None = None,
) -> StrategySignalEnvelope:
    """기존 raw signal에서 provenance만 추출하여 envelope를 만든다.

    Canonical signal의 값은 이 함수에서 변환하지 않는다.
    """
    provenance = ExecutionProvenance(
        strategy_id=strategy_id or raw_signal.get("strategy_id"),
        track_id=str(raw_signal["track_id"]) if raw_signal.get("track_id") is not None else getattr(signal, "track_id", None),
        tag_id=str(raw_signal["tag_id"]) if raw_signal.get("tag_id") is not None else getattr(signal, "tag_id", None),
        action=str(raw_signal["action"]) if raw_signal.get("action") is not None else None,
        reason=str(raw_signal["reason"]) if raw_signal.get("reason") is not None else None,
        entry_reason=str(raw_signal["entry_reason"]) if raw_signal.get("entry_reason") is not None else None,
        exit_reason=str(raw_signal["exit_reason"]) if raw_signal.get("exit_reason") is not None else None,
        declared_order_purpose=(
            str(raw_signal["order_purpose"])
            if raw_signal.get("order_purpose") is not None
            else None
        ),
        declared_order_type=(
            str(raw_signal["order_type"])
            if raw_signal.get("order_type") is not None
            else None
        ),
        metadata={
            str(key): value
            for key, value in raw_signal.items()
            if key not in {
                "strategy_id",
                "track_id",
                "tag_id",
                "action",
                "reason",
                "entry_reason",
                "exit_reason",
                "order_purpose",
                "order_type",
            }
        },
    )
    return StrategySignalEnvelope(signal=signal, provenance=provenance)
```
## Track 1~9 호환 판정
현재 program_runtime.py의 Strategy dictionary → Canonical 변환에서 Canonical로 직접 전달되는 핵심값은 qty, price, asset/type, side, option_type, strike, tag_id 등이다. 반면 action/reason 및 일부 전략별 추가 필드는 Canonical에 들어가지 않는다. 따라서 raw signal을 만드는 지점에서 이 함수로 provenance를 별도 추출하면 Canonical Contract를 확장하지 않고 손실을 방지할 수 있다.
확인된 실제 사례:
    - Track1: action, type, reason, pricing_mode, tag_id 등의 전략 고유 값이 존재하며 공통 order_purpose는 관찰된 범위에서 없음.
    - Track2: action, pricing_mode, reason, trap/strike 구조 등 전략 고유 값이 존재하며 공통 order_purpose는 관찰된 범위에서 없음.
    - Track3: action, reason, pricing/leg/group 관련 전략 고유 값이 존재하며 공통 order_purpose는 관찰된 범위에서 없음.
    - Track4: action, reason, pricing_mode, delta/strike 등 전략 고유 값이 존재하며 공통 order_purpose는 관찰된 범위에서 없음.
    - Track5: action, reason, pricing_mode, gap/target/stop 관련 값이 존재하며 공통 order_purpose는 관찰된 범위에서 없음.
    - Track6: action, reason, pricing_mode, 보험 strike/cost/queue 관련 값이 존재하며 공통 order_purpose는 관찰된 범위에서 없음.
    - Track7: action, reason, pricing_mode, skew/insurance/cutoff 관련 값이 존재하며 공통 order_purpose는 관찰된 범위에서 없음.
    - Track8: action, reason, pricing_mode, monthly strangle/expiry 관련 값이 존재하며 공통 order_purpose는 관찰된 범위에서 없음.
    - Track9: 일부 signal에는 실제 명시적인 order_purpose가 존재한다. 확인 사례: ADD_INSURANCE=ENTRY, REDUCE_INSURANCE=EXIT, EARLY_PROFIT_TAKE=EXIT, REHEDGE_ENTRY=ENTRY. 이 값은 반드시 declared provenance로 보존해야 한다. 반대로 ENTER_EVENT_STRANGLE, CLOSE_EVENT_STRANGLE 등 모든 signal이 purpose를 명시하는 것은 아니므로 누락값을 추론하지 않는다.
## 중요 정정
Track9는 order_purpose가 전혀 없는 전략이 아니다. 일부 signal에 명시값이 실제 존재한다. 따라서 전체 Track을 order_purpose 없음으로 단순화하면 원본 의미를 훼손한다.
## 연결 보류 기준
이 wrapper는 설계 및 작업대 코드이며 현재 원격 Runtime에 연결하지 않는다. 실제 연결 시에는 DecisionArbiter의 입력/출력 계약과 정렬·중재 로직을 wrapper에 맞게 별도 검토하고, 기존 Runtime의 주문 생성/리스크/OMS 기능을 동일하게 유지하는 회귀 검증을 먼저 확보한다.

[Child Page] decision_arbiter_envelope_compatibility.md
# 목적
No.128에서 확정한 DecisionArbiter 호출 직전 Envelope 경계를 실제 program_runtime.py의 데이터 흐름에 대입하여, 기존 List[CanonicalStrategySignal] 기반 Risk/Order 경로를 변경하지 않고 provenance를 보존할 수 있는 최소 transport insertion point를 정의한다.
## 현재 Runtime 기준
원격 Exp_Detail_1의 현재 흐름은 다음과 같다.
Track 1~9 raw signal dict → CanonicalStrategySignal → SignalGenerator validation → raw_signals_collected → DecisionArbiter → RiskGate → OrderRouter
Canonical 생성 시 CanonicalStrategySignal에는 signal_id, track_id, asset_type, side, qty, price, option_type, strike, tag_id 등이 들어가지만 raw dictionary의 action, reason, 전략별 metadata 및 일부 명시적인 order_purpose/order_type은 별도 보존되지 않는다.
## 최소 삽입 지점
가장 작은 의미 보존 지점은 각 raw signal이 유효한 CanonicalStrategySignal로 변환·검증된 직후다.
권장 논리:
raw sig dict
→ CanonicalStrategySignal 생성
→ SignalGenerator validation
→ StrategySignalEnvelope(signal=c_sig, provenance=raw sig에서 추출)
→ 기존 Canonical 리스트에는 envelope.signal만 공급
→ 기존 DecisionArbiter/Risk/Order 경로 유지
즉, Envelope는 Canonical 리스트를 대체하지 않고 provenance 보존용 병렬 운반 객체로 사용한다.
## Adapter 책임
Adapter는 다음 두 가지 역할만 가진다.
    1. raw signal과 Canonical signal 사이의 provenance를 연결한다.
    1. 기존 Arbiter 입력이 요구하는 CanonicalStrategySignal만 추출한다.
Adapter가 해서는 안 되는 것:
    - qty 변경
    - price 변경
    - side 변경
    - asset_type/strike/option_type 변경
    - priority 재계산
    - clash 재판정
    - signal 정렬 변경
    - order_purpose 추론
    - order_type 추론
    - Risk 승인 수량 적용
## 중복·식별 안전성
Envelope를 다시 연결할 때 signal_id를 식별자로 사용한다. 동일 tick 내에서 동일 signal_id가 둘 이상이면 provenance 재연결이 모호하므로 fail-closed 해야 한다.
기존 Runtime이 생성하는 SIG-{seq}-{Track}-{local_seq} 규칙은 현재 각 strategy의 local sequence와 track을 포함하므로, Adapter는 값을 새로 만들지 않고 기존 signal_id를 그대로 사용한다.
## 권장 최소 API
```python
from typing import Iterable, List, Tuple


def unwrap_strategy_signal_envelopes(
    envelopes: Iterable[StrategySignalEnvelope],
) -> List[CanonicalStrategySignal]:
    return [envelope.signal for envelope in envelopes]


def index_strategy_signal_envelopes(
    envelopes: Iterable[StrategySignalEnvelope],
) -> dict[str, StrategySignalEnvelope]:
    indexed: dict[str, StrategySignalEnvelope] = {}
    for envelope in envelopes:
        signal_id = envelope.signal_id
        if signal_id in indexed:
            raise ValueError(f"DUPLICATE_SIGNAL_ID: {signal_id}")
        indexed[signal_id] = envelope
    return indexed
```
위 API는 Arbiter의 알고리즘을 복제하지 않는다. unwrap은 기존 입력 형태를 제공하고 index는 결과 provenance 재연결을 위한 식별자 검증만 수행한다.
## 중요: Runtime에 즉시 삽입하지 않는 이유
현재 Runtime은 raw_signals_collected 자체를 Risk 및 이후 주문 생성 경로의 입력으로 사용한다. 따라서 이 리스트를 Envelope 리스트로 직접 변경하면 downstream 계약을 동시에 변경해야 한다.
따라서 1차 구현에서는 다음 구조가 안전하다.
CanonicalStrategySignal[] = 기존 실행 경로의 authoritative runtime list
StrategySignalEnvelope[] = provenance 보존용 parallel list/index
이렇게 하면 기존 Strategy → SignalGenerator → Arbiter → RiskGate → OrderRouter의 실행 의미를 유지하면서 향후 Position Logic에서 provenance를 참조할 수 있다.
## order_purpose 전달 원칙
Envelope에 보존된 declared_order_purpose는 즉시 Standard OrderPurpose로 승격하지 않는다.
    - 명시값이 있으면 provenance로 보존
    - 없으면 None
    - action/track/tag/side/position 방향으로 추론 금지
    - Position Logic에서 explicit execution intent를 결정할 때 검증된 명시값을 입력 후보로 사용
Track9의 일부 명시 purpose도 이 원칙에 따라 보존한다.
## 결론
CanonicalStrategySignal을 변경하지 않고, 기존 Runtime의 Canonical 리스트를 그대로 유지하면서 별도의 StrategySignalEnvelope parallel transport를 두는 것이 현재 시점의 최소·안전한 삽입 방식이다.
실제 Runtime 수정 전에는 Envelope가 Risk 결과와 연결되는 이후 경계에서 signal_id/수량 provenance/order purpose provenance가 정확히 유지되는지를 별도 설계해야 한다.
## 보호 범위
    - 원격 Exp_Detail_1 수정 없음
    - 터미널 테스트 없음
    - 기존 Arbiter 알고리즘 복제·재구현 없음
    - Legacy OrderRequest 기본값 승격 없음
    - order_purpose 및 order_type 추론 없음

[Child Page] risk_provenance_transport.md
## 목적
No.129에서 확정한 StrategySignalEnvelope parallel transport를 실제 Risk 결과와 Position Logic / Order Intent 경계까지 연결하기 위한 최소 전달계약을 정의한다. 기존 CanonicalStrategySignal[] → DecisionArbiter → RiskGate → OrderRouter 실행 의미는 변경하지 않는다.
## 원격 Exp_Detail_1 실제 흐름
현재 program_runtime.py의 실제 주문 경로는 다음과 같다.
CanonicalStrategySignal → DecisionArbiter → approved_sig → CanonicalOrderCommand → RiskGate.admit_order() → RiskEvaluationResult → effective_cmd → OrderRouter.register_and_route()
RiskGate는 RiskEvaluationResult를 last_evaluation_result에 보관한다. 결과에는 decision, is_approved, original_qty, approved_qty, reduced_command, rejection_reason, token이 있다.
현재 Runtime은 allow_reduction을 명시하지 않으므로 기본값 False로 동작한다. 따라서 현재 실행에서는 REDUCE를 새로 활성화하지 않는다.
## provenance가 실제로 연결될 수 있는 안정 지점
### 1. Signal identity
CanonicalStrategySignal.signal_id가 Arbiter 입력과 결과 신호에 그대로 유지된다. Arbiter는 이 값을 우선순위/정렬의 최종 tie-break 및 결과 재연결 key로 사용할 수 있다.
### 2. Command identity
Runtime은 승인된 signal을 CanonicalOrderCommand로 만들면서 client_order_id를 생성한다. 이 시점에 client_order_id → signal_id 매핑을 별도로 기록하는 것이 가장 안전하다.
문자열의 일부를 다시 파싱하여 signal_id를 복원하지 않는다. 현재 문자열 형식은 호환성상 보존하되 provenance 식별의 권위값으로 승격하지 않는다.
### 3. Risk quantity
Risk 통과 후 실제 실행 대상은 effective_cmd다.
    - ALLOW: approved_qty를 사용하며 effective_cmd is cmd.
    - REDUCE: reduced_command.qty가 최종 수량이며 client_order_id는 유지된다.
    - DENY: OrderIntent를 생성하지 않는다.
따라서 Position Logic / Order Intent로 전달할 quantity의 권위값은 strategy signal의 원래 qty가 아니라 Risk 결과를 반영한 effective_cmd.qty다.
## 최소 provenance index
권장되는 parallel transport 상태는 다음 두 인덱스다.
```python
signal_provenance_by_id: dict[str, StrategySignalEnvelope]
order_provenance_by_client_id: dict[str, StrategySignalEnvelope]
```
연결 순서는 다음과 같다.
StrategySignalEnvelope.signal_id
→ Arbiter approved signal의 signal_id
→ 생성된 CanonicalOrderCommand.client_order_id와 envelope 연결
→ RiskGate
→ effective_cmd.client_order_id로 동일 envelope 재조회
→ Risk 승인 수량을 적용한 Position Logic / Order Intent 입력 생성
REDUCE에서도 client_order_id가 유지되므로 동일 연결을 유지할 수 있다.
## Adapter 책임
Adapter는 다음만 수행한다.
    1. Envelope를 signal_id로 index한다.
    1. 승인된 signal과 provenance를 signal_id로 연결한다.
    1. CanonicalOrderCommand 생성 시 client_order_id → envelope 연결을 만든다.
    1. Risk 결과가 승인된 경우 effective_cmd.client_order_id로 provenance를 재조회한다.
    1. Risk의 최종 실행 수량을 effective_cmd.qty에서 확인한다.
    1. explicit declared_order_purpose / declared_order_type만 Position Logic의 입력 후보로 전달한다.
    1. DENY 또는 provenance 불일치 시 fail-closed한다.
## Adapter가 하지 않는 것
    - Arbiter priority / sorting / clash 재계산
    - signal qty와 Risk qty의 재계산
    - action → order_purpose 추론
    - track_id / tag_id → order_purpose 추론
    - side / position direction → order_purpose 추론
    - missing purpose/type의 기본값 생성
    - Risk REDUCE 활성화
    - CanonicalOrderCommand 구조 변경
    - client_order_id 문자열 parsing으로 signal_id 복원
## 권장 최소 API 형태
```python
from dataclasses import dataclass

@dataclass(frozen=True)
class RiskProvenanceLink:
    signal_id: str
    client_order_id: str
    envelope: StrategySignalEnvelope


def link_approved_signal_to_order(
    envelope: StrategySignalEnvelope,
    client_order_id: str,
) -> RiskProvenanceLink:
    if envelope.signal_id == "":
        raise ValueError("SIGNAL_ID_REQUIRED")
    if not client_order_id:
        raise ValueError("CLIENT_ORDER_ID_REQUIRED")
    return RiskProvenanceLink(
        signal_id=envelope.signal_id,
        client_order_id=client_order_id,
        envelope=envelope,
    )
```
실제 Risk 결과를 OrderIntent로 변환할 때는 기존 risk_order_intent_adapter.py의 원칙을 그대로 적용한다. 즉 ALLOW는 approved_qty, REDUCE는 reduced_command.qty를 사용하고, DENY는 실패시킨다. 이 문서는 그 수량 결정 로직을 복제하지 않고 provenance 연결만 담당한다.
## Position Logic 경계
No.006 및 No.043의 표준 흐름에 따라 Position Logic은 Risk 이후의 명시적 실행 의미를 다룬다. Strategy provenance의 declared_order_purpose/type는 관찰·보존된 원본 값이지 자동 확정된 표준 OrderPurpose/OrderType가 아니다.
따라서 다음 조건을 모두 만족할 때만 ExplicitPositionExecutionIntent 후보로 전달한다.
    - provenance가 해당 signal_id에 정확히 연결됨
    - 승인된 client_order_id와 연결됨
    - 명시적 order_purpose가 존재함
    - order_type이 존재한다면 명시값 그대로 전달
purpose가 없는 Track1~8 또는 purpose가 없는 Track9 신호는 빈 값을 유지한다. action 이름만으로 purpose를 만들어내지 않는다.
## 현재 Runtime을 변경하지 않는 단계적 적용
    1. 현재 raw_signals_collected: List[CanonicalStrategySignal]는 그대로 유지한다.
    1. Envelope는 parallel list/index로만 보존한다.
    1. Arbiter는 기존 Canonical list를 그대로 받는다.
    1. approved signal이 생긴 후 signal_id → envelope를 조회한다.
    1. CanonicalOrderCommand 생성 직후 client_order_id → envelope를 연결한다.
    1. RiskGate는 현재 그대로 호출한다.
    1. Risk 승인 후 effective_cmd.client_order_id로 동일 provenance를 조회한다.
    1. 이후 Position Logic / OrderIntent 단계에서만 explicit execution intent를 해석한다.
## Fail-closed 조건
다음은 주문 Intent로 진행시키지 않는다.
    - 동일 signal_id에 여러 envelope가 존재
    - approved signal의 signal_id가 provenance index에 없음
    - client_order_id가 provenance link에 없음
    - Risk가 DENY
    - Risk REDUCE인데 reduced_command가 없거나 수량이 approved_qty와 불일치
    - Risk 승인 수량이 0 이하
    - explicit purpose가 필요한 Position Logic 단계에서 purpose가 없음
## 결론
현재 Runtime에서 provenance를 Risk 이후까지 보존하는 가장 작은 변경 단위는 signal_id를 1차 연결키로 하고, 주문 생성 시점에 client_order_id를 2차 실행 추적키로 고정하는 parallel provenance index다. Risk는 수량의 권위자로 유지하고, effective_cmd가 Position Logic / Order Intent로 넘어가는 실행 데이터의 기준이 된다. Canonical Contract, DecisionArbiter, RiskGate, OrderRouter의 현재 의미는 이 단계에서 변경하지 않는다.
## 근거
    - No.006: Market State → Strategy → Signal → Decision → Risk Validation → Position Logic → Order Intent
    - No.043: Signal은 전략 판단, Risk는 허용/거부/수량 조정, Position Logic은 포지션 차이 계산, Order Intent는 Broker 호출과 분리
    - No.129: Envelope는 기존 Canonical 실행 리스트를 대체하지 않는 parallel transport
    - 원격 Exp_Detail_1의 program_runtime.py, risk_engine.py, order_router.py 실제 코드 기준

[Child Page] canonical_order_command_adapter.py
```python
from dataclasses import dataclass
from contracts.types import OptionInstrumentIdentity
from shared.contracts.canonical import (
    CanonicalAssetType,
    CanonicalOrderCommand,
    CanonicalStrategySignal,
)
from core.runtime.runtime_execution_context import RuntimeExecutionContext


class CanonicalOrderCommandValidationError(ValueError):
    pass


@dataclass(frozen=True)
class CanonicalOrderCommandAdapter:
    """Build a Reference-compatible command without inventing execution identity."""

    def create(
        self,
        signal: CanonicalStrategySignal,
        runtime: RuntimeExecutionContext,
    ) -> CanonicalOrderCommand:
        if signal.qty <= 0:
            raise CanonicalOrderCommandValidationError("QUANTITY_REQUIRED")
        if signal.price <= 0:
            raise CanonicalOrderCommandValidationError("PRICE_REQUIRED")
        if not signal.track_id:
            raise CanonicalOrderCommandValidationError("TRACK_ID_REQUIRED")
        if not signal.instrument_id:
            raise CanonicalOrderCommandValidationError("AUTHORITATIVE_INSTRUMENT_ID_REQUIRED")

        client_order_id = runtime.client_order_id(signal.track_id)

        if signal.asset_type == CanonicalAssetType.OPTION:
            if not signal.symbol or not signal.expiry:
                raise CanonicalOrderCommandValidationError("OPTION_SYMBOL_EXPIRY_REQUIRED")
            if signal.option_type is None:
                raise CanonicalOrderCommandValidationError("OPTION_TYPE_REQUIRED")
            if signal.strike <= 0:
                raise CanonicalOrderCommandValidationError("STRIKE_REQUIRED")

        return CanonicalOrderCommand(
            client_order_id=client_order_id,
            track_id=signal.track_id,
            asset_type=signal.asset_type,
            side=signal.side,
            qty=signal.qty,
            price=signal.price,
            option_type=signal.option_type,
            strike=signal.strike,
            symbol=signal.symbol,
            expiry=signal.expiry,
            tag_id=signal.tag_id,
        )
```
## 책임
    - client_order_id는 RuntimeExecutionContext가 authoritative sequence로 파생한다.
    - adapter 자체에서 tick/local sequence를 새로 생성하지 않는다.
    - instrument_id는 CanonicalStrategySignal에 보존된 authoritative identity만 검증한다.
    - OPTION의 symbol/expiry/option_type/strike가 불완전하면 fail-closed한다.
    - Reference의 KOSPI200, empty expiry 등의 legacy default를 보완값으로 사용하지 않는다.
    - requested_price, order_type, order_purpose는 이 Command adapter의 책임이 아니다.

[Child Page] risk_to_order_intent_adapter.md
## 목적
No.131~132에서 확정한 signal_id → client_order_id → effective_cmd 연결을 Standard OrderIntentExecutionInput에 안전하게 연결하는 최소 Adapter 계약이다.
## 실제 Standard Factory 계약
OrderIntentExecutionInput은 다음을 요구한다: client_order_id, quantity, requested_price, order_type, order_purpose, asset_type, track_id, tag_id. Factory는 quantity/order_type/order_purpose/asset_type 및 instrument identity를 검증하며 누락 시 실패한다.
## Adapter 입력
    - RiskProvenanceLink: signal_id, client_order_id, StrategySignalEnvelope
    - effective_cmd: Risk 이후 실제 실행 대상 CanonicalOrderCommand
    - execution_policy_decision: Position Logic이 결정한 order_type, order_purpose
## 변환 규칙
<!-- Notion table block -->
| OrderIntentExecutionInput | 공급원 | 규칙 |
| client_order_id | effective_cmd.client_order_id | provenance link와 동일해야 함 |
| quantity | effective_cmd.qty | Risk 이후 값만 authoritative. signal qty 재사용 금지 |
| requested_price | effective_cmd.price | 현재 Canonical price를 Decimal로 보존. 별도 fallback 금지 |
| order_type | Position Execution Policy | 정책 결정값만 사용. 누락 시 Factory 전에 실패 |
| order_purpose | Position Execution Policy / explicit provenance | 명시된 값만 사용. action/track/tag/side로 추론 금지 |
| asset_type | effective_cmd.asset_type.value | Canonical 값 보존 |
| track_id | effective_cmd.track_id | Canonical provenance 보존 |
| tag_id | effective_cmd.tag_id | Canonical provenance 보존 |
## Explicit purpose 연결
Track9 등 원본 신호에 명시된 order_purpose/order_type는 StrategySignalEnvelope.provenance에 보존한다. 그러나 provenance 값 자체를 무조건 Standard 의미로 승격하지 않는다. Position Logic의 OrderPositionExecutionPolicyDecision을 통해 OrderIntent 실행 의미로 확정한 경우에만 Factory 입력으로 전달한다.
purpose가 없으면 OrderIntentExecutionInput을 생성하지 않는다. 특히 BUY=ENTRY, SELL=EXIT, Track9=HEDGE 등의 추론을 금지한다.
## order_type 호환 정책
현재 Reference 실행은 LIMIT 기반이지만 Canonical DTO의 독립 필드가 아니다. 따라서 Adapter가 임의로 Canonical에 order_type을 추가하지 않는다. Position Execution Policy가 현재 호환 정책으로 LIMIT을 명시적으로 결정한 경우에만 Factory 입력으로 전달한다. 이는 Canonical 의미 변경이 아니다.
## fail-closed 조건
    - provenance link의 signal_id와 envelope signal_id 불일치
    - provenance link의 client_order_id와 effective command client_order_id 불일치
    - effective_cmd.qty <= 0
    - order_type 없음
    - order_purpose 없음
    - asset_type 없음
## Adapter 책임 범위
Adapter는 의미를 새로 결정하지 않고, 이미 결정된 Risk 결과와 Position Execution Policy 결과를 Factory 계약으로 정확히 운반한다. DecisionArbiter 재실행, Risk 재계산, quantity 재계산, instrument identity 생성, purpose 추론을 하지 않는다.
## Runtime 연결 시점
현재 Runtime은 effective_cmd를 바로 OrderRouter에 전달한다. 따라서 이 Adapter를 즉시 Runtime에 삽입하면 기존 실행 경로가 바뀐다. 본 단계에서는 계약을 확정하고 실제 Runtime 삽입은 별도 단계에서 진행한다. Runtime 변경 시에도 기존 raw_signals_collected: List[CanonicalStrategySignal], Arbiter, RiskGate semantics를 유지해야 한다.
## No.133 실제 계약 대조 결과
### 1. Standard OrderIntentExecutionInput 필수 계약
    - client_order_id
    - quantity
    - requested_price
    - order_type
    - order_purpose
    - asset_type
    - track_id
    - tag_id
OrderIntentFactory는 execution input의 quantity/order_type/order_purpose/asset_type를 필수 검증하며, OPTION인 경우 OptionIdentityResolver를 통해 instrument_id를 확정한다. identity 또는 필수 execution 값이 없으면 synthetic fallback 없이 실패한다.
### 2. Risk 이후 authoritative 값
현재 Reference Runtime의 Risk 이후 실행 객체는 effective_cmd이며, 실행 수량은 effective_cmd.qty를 authoritative source로 사용한다. 따라서 Strategy signal의 qty를 다시 사용하거나 Adapter에서 Risk 결과를 재계산하지 않는다.
### 3. 안전한 필드 매핑
<!-- Notion table block -->
| OrderIntentExecutionInput | 공급 경계 | 규칙 |
| client_order_id | effective_cmd.client_order_id  • RiskProvenanceLink | 두 값이 정확히 일치해야 함 |
| quantity | effective_cmd.qty | Risk 이후 최종값만 사용, <=0 fail-closed |
| requested_price | effective_cmd.price 후보 | 실제 계약상 price 의미를 추가 확인한 뒤 연결 |
| asset_type | effective_cmd.asset_type | Canonical 값 보존 |
| track_id | effective_cmd.track_id | provenance 재작성 금지 |
| tag_id | effective_cmd.tag_id | provenance 재작성 금지 |
| order_purpose | explicit execution provenance / Position Logic | 누락 시 추론·기본값 금지 |
| order_type | explicit execution provenance / Position Execution Policy | 명시값만 전달; compatibility LIMIT은 별도 정책 경계 |
### 4. Identity 경계
현재 원격 CanonicalOrderCommand에는 별도 instrument_id가 없으며 OPTION identity를 Standard Factory가 요구한다. 따라서 지금 즉시 Factory를 Runtime에 삽입하지 않는다.
다음 단계는 실제 Track 신호의 option_type/strike/symbol/expiry 및 Futures 식별정보가 어떤 authoritative identity로 연결될 수 있는지 추적하고, OptionIdentityResolver 직전의 변환 계약을 확정하는 것이다.
### 5. 기존 프로그램 보호
    - Canonical DTO 변경 없음
    - DecisionArbiter 변경 없음
    - RiskGate 변경 없음
    - OrderRouter 변경 없음
    - 기존 전략 계산/주문 실행 로직 복제 없음
    - 원격 Exp_Detail_1 변경 없음

[Child Page] oms_fsm.py
```python
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from contracts.types import BrokerOrderCommand, ExecutionReport, OrderAckEvent


class OrderStateTransitionError(ValueError):
    """Raised when an order state transition is unsafe or invalid."""


@dataclass(frozen=True)
class OrderState:
    client_order_id: str
    status: str
    broker_order_id: str | None = None
    order_quantity: int = 0
    filled_quantity: int = 0
    broker_order_command: BrokerOrderCommand | None = None
    average_execution_price: Decimal | None = None


@dataclass(frozen=True)
class ExecutionCorrelation:
    """OMS-owned state required to correlate a broker execution notice."""

    client_order_id: str
    broker_order_id: str
    order_quantity: int
    prior_filled_quantity: int
    prior_average_price: Decimal | None = None


class OrderStateMachine:
    """OMS-owned order state and broker/client correlation boundary."""

    def __init__(self) -> None:
        self._states: dict[str, OrderState] = {}
        self._broker_to_client: dict[str, str] = {}

    def apply_intent(self, intent) -> OrderState:
        client_order_id = str(intent.client_order_id).strip()
        if not client_order_id:
            raise OrderStateTransitionError("CLIENT_ORDER_ID_REQUIRED")
        quantity = int(intent.quantity)
        if quantity <= 0:
            raise OrderStateTransitionError("ORDER_QUANTITY_INVALID")
        if client_order_id in self._states:
            raise OrderStateTransitionError("ORDER_INTENT_ALREADY_REGISTERED")
        state = OrderState(client_order_id, "SUBMITTED", order_quantity=quantity)
        self._states[client_order_id] = state
        return state

    def register_broker_order_command(self, command: BrokerOrderCommand) -> OrderState:
        client_order_id = str(command.client_order_id).strip()
        if not client_order_id:
            raise OrderStateTransitionError("CLIENT_ORDER_ID_REQUIRED")
        current = self._states.get(client_order_id)
        if current is None:
            raise OrderStateTransitionError("ORDER_NOT_REGISTERED")
        if current.status not in {"SUBMITTED", "ACKED"}:
            raise OrderStateTransitionError("BROKER_COMMAND_AFTER_INVALID_STATE")
        if command.quantity != current.order_quantity:
            raise OrderStateTransitionError("BROKER_COMMAND_QUANTITY_MISMATCH")
        if command.instrument_identity is not None and command.instrument_id != command.instrument_identity.instrument_id:
            raise OrderStateTransitionError("BROKER_COMMAND_INSTRUMENT_ID_MISMATCH")
        state = OrderState(
            client_order_id=current.client_order_id,
            status=current.status,
            broker_order_id=current.broker_order_id,
            order_quantity=current.order_quantity,
            filled_quantity=current.filled_quantity,
            broker_order_command=command,
            average_execution_price=current.average_execution_price,
        )
        self._states[client_order_id] = state
        return state

    def apply_ack(self, event: OrderAckEvent) -> OrderState:
        client_order_id = str(event.client_order_id).strip()
        if not client_order_id:
            raise OrderStateTransitionError("CLIENT_ORDER_ID_REQUIRED")
        current = self._states.get(client_order_id)
        if current is None:
            raise OrderStateTransitionError("ORDER_NOT_REGISTERED")
        if current.status not in {"SUBMITTED", "ACKED"}:
            raise OrderStateTransitionError("ACK_AFTER_TERMINAL_STATE")
        if event.accepted and not event.broker_order_id:
            raise OrderStateTransitionError("BROKER_ORDER_ID_REQUIRED_FOR_ACCEPTED_ACK")
        if event.accepted:
            broker_order_id = str(event.broker_order_id).strip()
            previous_client = self._broker_to_client.get(broker_order_id)
            if previous_client is not None and previous_client != client_order_id:
                raise OrderStateTransitionError("BROKER_ORDER_ID_ALREADY_CORRELATED")
            self._broker_to_client[broker_order_id] = client_order_id
        state = OrderState(
            client_order_id,
            "ACKED" if event.accepted else "REJECTED",
            event.broker_order_id,
            current.order_quantity,
            current.filled_quantity,
            current.broker_order_command,
            current.average_execution_price,
        )
        self._states[client_order_id] = state
        return state

    def resolve_execution_correlation(self, broker_order_id: str) -> ExecutionCorrelation:
        broker_id = str(broker_order_id).strip()
        if not broker_id:
            raise OrderStateTransitionError("BROKER_ORDER_ID_REQUIRED")
        client_order_id = self._broker_to_client.get(broker_id)
        if client_order_id is None:
            raise OrderStateTransitionError("BROKER_ORDER_ID_NOT_CORRELATED")
        state = self._states.get(client_order_id)
        if state is None:
            raise OrderStateTransitionError("CORRELATED_ORDER_STATE_MISSING")
        if state.status not in {"ACKED", "PARTIALLY_FILLED"}:
            raise OrderStateTransitionError("EXECUTION_CORRELATION_STATE_INVALID")
        return ExecutionCorrelation(
            client_order_id=state.client_order_id,
            broker_order_id=broker_id,
            order_quantity=state.order_quantity,
            prior_filled_quantity=state.filled_quantity,
            prior_average_price=state.average_execution_price,
        )

    def get_broker_order_command(self, broker_order_id: str | None) -> BrokerOrderCommand:
        broker_id = str(broker_order_id or "").strip()
        if not broker_id:
            raise OrderStateTransitionError("BROKER_ORDER_ID_REQUIRED")
        client_order_id = self._broker_to_client.get(broker_id)
        if client_order_id is None:
            raise OrderStateTransitionError("BROKER_ORDER_ID_NOT_CORRELATED")
        state = self._states.get(client_order_id)
        if state is None or state.broker_order_command is None:
            raise OrderStateTransitionError("BROKER_ORDER_COMMAND_NOT_REGISTERED")
        if state.broker_order_id != broker_id:
            raise OrderStateTransitionError("BROKER_ORDER_ID_MISMATCH")
        return state.broker_order_command

    def apply_execution(self, report: ExecutionReport) -> OrderState:
        client_order_id = str(report.client_order_id).strip()
        current = self._states.get(client_order_id)
        if current is None:
            raise OrderStateTransitionError("ORDER_NOT_REGISTERED")
        if current.status not in {"ACKED", "PARTIALLY_FILLED"}:
            raise OrderStateTransitionError("EXECUTION_BEFORE_ACK")
        if report.status not in {"PARTIALLY_FILLED", "FILLED"}:
            raise OrderStateTransitionError("UNSUPPORTED_EXECUTION_STATUS")
        if report.filled_quantity <= 0:
            raise OrderStateTransitionError("FILLED_QUANTITY_INVALID")
        cumulative = current.filled_quantity + report.filled_quantity
        if cumulative > current.order_quantity:
            raise OrderStateTransitionError("FILLED_QUANTITY_EXCEEDS_ORDER")
        if report.remaining_quantity != current.order_quantity - cumulative:
            raise OrderStateTransitionError("REMAINING_QUANTITY_MISMATCH")
        if report.broker_order_id and current.broker_order_id != report.broker_order_id:
            raise OrderStateTransitionError("BROKER_ORDER_ID_MISMATCH")
        average_execution_price = current.average_execution_price
        if report.execution_price is not None and report.execution_price > 0:
            if current.filled_quantity == 0 or average_execution_price is None:
                average_execution_price = report.execution_price
            else:
                average_execution_price = (
                    average_execution_price * Decimal(current.filled_quantity)
                    + report.execution_price * Decimal(report.filled_quantity)
                ) / Decimal(cumulative)
        state = OrderState(
            client_order_id,
            report.status,
            report.broker_order_id or current.broker_order_id,
            current.order_quantity,
            cumulative,
            current.broker_order_command,
            average_execution_price,
        )
        self._states[client_order_id] = state
        return state

    def get(self, client_order_id: str) -> OrderState | None:
        return self._states.get(client_order_id)


__all__ = (
    "ExecutionCorrelation",
    "OrderState",
    "OrderStateMachine",
    "OrderStateTransitionError",
)
```
## Boundary rules
    - SUBMITTED → ACKED/REJECTED is the broker acknowledgement transition.
    - The authoritative BrokerOrderCommand is registered into OMS state before/at broker submission; it is never reconstructed from an execution notice.
    - Accepted ACK creates the OMS-owned broker_order_id → client_order_id correlation mapping.
    - get_broker_order_command() exposes the original command only through the OMS correlation mapping.
    - resolve_execution_correlation() exposes only existing OMS state; it never synthesizes an order identity or quantity.
    - ACKED → PARTIALLY_FILLED/FILLED is driven only by ExecutionReport.
    - Execution before ACK, broker-order mismatch, overfill, or remaining-quantity mismatch is rejected fail-closed.
    - Existing WAL persistence remains outside this state machine; this class owns the order-state/correlation boundary.

[Child Page] order_router.py
```python
"""Standard production OrderRouter boundary."""
from __future__ import annotations

from typing import Any

from contracts.order_ack import to_order_ack_event
from contracts.types import BrokerOrderCommand, BrokerOrderResponse
from core.oms.oms_fsm import OrderStateMachine


class OrderRouterError(RuntimeError):
    pass


class StandardOrderRouter:
    def __init__(self, *, order_state_machine: OrderStateMachine, broker_adapter: Any = None) -> None:
        if order_state_machine is None: raise ValueError("ORDER_STATE_MACHINE_REQUIRED")
        self._order_state_machine = order_state_machine
        self._broker_adapter = broker_adapter

    def register_and_route(self, command: BrokerOrderCommand, token: Any, *, broker_adapter: Any = None, **kwargs: Any) -> BrokerOrderResponse:
        if command is None: raise OrderRouterError("BROKER_ORDER_COMMAND_REQUIRED")
        if token is None: raise OrderRouterError("RISK_APPROVAL_TOKEN_REQUIRED")
        broker = broker_adapter if broker_adapter is not None else self._broker_adapter
        if broker is None: raise OrderRouterError("BROKER_ADAPTER_REQUIRED")
        submit = getattr(broker, "submit", None)
        if not callable(submit): raise OrderRouterError("BROKER_SUBMIT_REQUIRED")

        if self._order_state_machine.get(command.client_order_id) is None:
            self._order_state_machine.apply_intent(command)

        response = submit(command, **kwargs)
        if not isinstance(response, BrokerOrderResponse):
            raise OrderRouterError("BROKER_ORDER_RESPONSE_REQUIRED")
        if response.client_order_id != command.client_order_id:
            raise OrderRouterError("BROKER_RESPONSE_CLIENT_ORDER_ID_MISMATCH")

        self._order_state_machine.apply_ack(to_order_ack_event(response))
        return response


__all__ = ("OrderRouterError", "StandardOrderRouter")
```
## 책임
    - BrokerOrderCommand를 재구성하지 않는다.
    - Risk 승인 token 없이는 routing하지 않는다.
    - OMS 주문 등록 → broker submit → ACK→OMS state transition을 실제 수행한다.
    - execution/fill 및 Position 정산은 별도 execution ingress가 담당한다.
    - WAL, credential, network retry를 중복 소유하지 않는다.

[Child Page] risk_approved_broker_command_adapter.py
```python
"""Lossless Risk-effective quantity projection onto an authoritative BrokerOrderCommand."""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from contracts.types import BrokerOrderCommand

class RiskApprovedBrokerCommandError(ValueError):
    pass

def project_risk_effective_quantity(*, original: BrokerOrderCommand, effective: Any) -> BrokerOrderCommand:
    if original is None:
        raise RiskApprovedBrokerCommandError("BROKER_ORDER_COMMAND_REQUIRED")
    if effective is None:
        raise RiskApprovedBrokerCommandError("RISK_EFFECTIVE_COMMAND_REQUIRED")
    if str(original.client_order_id) != str(getattr(effective, 'client_order_id', '')):
        raise RiskApprovedBrokerCommandError("CLIENT_ORDER_ID_MISMATCH")
    original_qty = int(original.quantity)
    effective_qty = int(getattr(effective, 'qty', 0))
    if original_qty <= 0 or effective_qty <= 0:
        raise RiskApprovedBrokerCommandError("QUANTITY_REQUIRED")
    if effective_qty > original_qty:
        raise RiskApprovedBrokerCommandError("RISK_QUANTITY_INCREASE_FORBIDDEN")

    # Only Risk-authoritative quantity may change. Identity and execution semantics
    # remain exactly those supplied by the authoritative BrokerOrderCommand source.
    return replace(original, quantity=effective_qty)

__all__ = ("RiskApprovedBrokerCommandError", "project_risk_effective_quantity")
```
## 책임
    - Risk ALLOW/REDUCE 결과의 최종 quantity만 authoritative BrokerOrderCommand에 반영한다.
    - instrument_id, broker_symbol, instrument_identity, side, order_type, requested_price, order_purpose, track_id, tag_id를 생성·추론·변경하지 않는다.
    - Risk가 수량을 증가시키면 fail-closed한다.
    - 이 Adapter는 CanonicalOrderCommand에서 BrokerOrderCommand를 새로 만드는 translator가 아니다.

[Child Page] multi_leg_materializer.py
```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Sequence
from contracts.types import ExecutionLeg, MultiLegExecutionPlan, OptionInstrumentIdentity, OrderIntent

class MultiLegMaterializationError(ValueError): pass
IdentityResolver = Callable[[ExecutionLeg], OptionInstrumentIdentity]

@dataclass(frozen=True)
class MultiLegExecutionSemantics:
    order_type: str
    order_purpose: str
    asset_type: str = "OPTION"

def materialize_multi_leg_plan(plan: MultiLegExecutionPlan, *, resolve_identity: IdentityResolver, semantics: MultiLegExecutionSemantics, client_order_id_for: Callable[[MultiLegExecutionPlan, ExecutionLeg], str] | None = None) -> Sequence[OrderIntent]:
    if not semantics.order_type: raise MultiLegMaterializationError("ORDER_TYPE_REQUIRED")
    if not semantics.order_purpose: raise MultiLegMaterializationError("ORDER_PURPOSE_REQUIRED")
    if semantics.asset_type != "OPTION": raise MultiLegMaterializationError("OPTION_ASSET_TYPE_REQUIRED")
    make_client_id = client_order_id_for or (lambda p, leg: f"{p.group_id}:{leg.leg_id}")
    intents = []
    for leg in plan.legs:
        identity = resolve_identity(leg)
        if not identity or not identity.instrument_id: raise MultiLegMaterializationError("AUTHORITATIVE_IDENTITY_REQUIRED")
        if leg.option_type is not None and identity.option_type != leg.option_type: raise MultiLegMaterializationError("OPTION_TYPE_IDENTITY_MISMATCH")
        if leg.strike is not None and identity.strike != leg.strike: raise MultiLegMaterializationError("STRIKE_IDENTITY_MISMATCH")
        client_order_id = make_client_id(plan, leg)
        if not client_order_id: raise MultiLegMaterializationError("CLIENT_ORDER_ID_REQUIRED")
        intents.append(OrderIntent(client_order_id=client_order_id, instrument_id=identity.instrument_id, side=leg.side, quantity=leg.quantity, intent_type=semantics.order_purpose, strategy_id=plan.strategy_id, instrument_identity=identity, asset_type=semantics.asset_type, requested_price=leg.requested_price, order_type=semantics.order_type, order_purpose=semantics.order_purpose, track_id=plan.strategy_id, group_id=plan.group_id, leg_id=leg.leg_id))
    return tuple(intents)
```
    - leg count/order/side/quantity/group_id/leg_id lossless projection.
    - authoritative resolver만 사용하며 synthetic identity 금지.
    - order_type/order_purpose는 explicit semantics 없으면 fail-closed.
    - atomicity/partial-fill/unwind policy는 포함하지 않음.

[Child Page] test_multi_leg_materializer.py
```python
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
        materialize_multi_leg_plan(plan, resolve_identity=wrong, semantics=MultiLegExecutionSemantics("LIMIT","HEDGE"))
```
    - Track2 4-leg preservation
    - Track8 asymmetric quantity preservation
    - identity mismatch fail-closed

[Child Page] multi_leg_submission.py
```python
from __future__ import annotations

from typing import Any, Callable, Sequence

from contracts.types import BrokerOrderCommand, OrderIntent


class MultiLegSubmissionError(RuntimeError):
    pass


CommandMapper = Callable[[OrderIntent], BrokerOrderCommand]
TokenSupplier = Callable[[OrderIntent, BrokerOrderCommand], Any]


def submit_multi_leg_intents(
    intents: Sequence[OrderIntent],
    *,
    to_broker_command: CommandMapper,
    approval_token_for: TokenSupplier,
    order_router: Any,
) -> tuple[Any, ...]:
    """Submit already-approved intents in declared plan order.

    This is intentionally a transport seam, not an atomic execution engine.
    It does not infer, reorder, compensate, unwind, or synthesize risk tokens.
    """
    if not intents:
        raise MultiLegSubmissionError("MULTI_LEG_INTENTS_REQUIRED")
    if order_router is None or not callable(getattr(order_router, "register_and_route", None)):
        raise MultiLegSubmissionError("ORDER_ROUTER_REQUIRED")

    group_id = intents[0].group_id
    if not group_id:
        raise MultiLegSubmissionError("GROUP_ID_REQUIRED")
    if len({intent.group_id for intent in intents}) != 1:
        raise MultiLegSubmissionError("GROUP_ID_MISMATCH")
    if len({intent.leg_id for intent in intents}) != len(intents) or any(not i.leg_id for i in intents):
        raise MultiLegSubmissionError("UNIQUE_LEG_ID_REQUIRED")

    responses = []
    for intent in intents:
        command = to_broker_command(intent)
        if command is None:
            raise MultiLegSubmissionError("BROKER_COMMAND_REQUIRED")
        if command.group_id != intent.group_id or command.leg_id != intent.leg_id:
            raise MultiLegSubmissionError("GROUP_LEG_PROVENANCE_MISMATCH")
        token = approval_token_for(intent, command)
        if token is None:
            raise MultiLegSubmissionError("RISK_APPROVAL_TOKEN_REQUIRED")
        responses.append(order_router.register_and_route(command, token))
    return tuple(responses)
```
## 책임 경계
    - 입력 sequence의 순서대로 Router에 전달하는 transport adapter.
    - 각 leg는 독립 BrokerOrderCommand와 독립 RiskApprovalToken을 요구.
    - Track3 fill-dependent legging을 호출하지 않으며 대체하지 않음.
    - atomicity, parallelism, partial-fill compensation/unwind는 정책 부재로 구현하지 않음.
    - 중간 leg 실패 시 이전 leg 취소/반대매매를 자동 수행하지 않고 즉시 예외를 전달.

[Child Page] test_multi_leg_submission.py
```python
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
        submit_multi_leg_intents(intents, to_broker_command=Command, approval_token_for=lambda i,c: None if i.leg_id=="b" else "T:a", order_router=router)
    assert [x[0] for x in router.calls] == ["a"]
```
## 검증 목적
    - Track2 declared leg order/provenance가 Router까지 보존됨
    - Track8 asymmetric quantity는 materializer에서 유지된 채 submission seam 통과
    - token 없는 leg는 fail-closed
    - 이 seam은 Track3 fill-dependent legging과 독립