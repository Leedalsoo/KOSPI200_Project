폴더: Core와 Environment를 연결하는 표준 Contract.

[Child Page] market_data.py
```python
from typing import Callable, Iterable, Protocol

from contracts.types import MarketState, ProviderHealth


MarketDataSubscriber = Callable[[MarketState], None]


class MarketDataProvider(Protocol):
    """Environment-side market data boundary."""

    def snapshot(self) -> MarketState: ...

    def subscribe(self, callback: MarketDataSubscriber) -> None: ...

    def health(self) -> ProviderHealth: ...
```
## Contract boundary
    - Environment adapters translate external/synthetic feeds into canonical MarketState.
    - Freshness and data quality are explicit in the canonical market model.
    - Synthetic Virtual data must never be presented as Paper/Live external-data evidence.

[Child Page] clock.py
```python
from datetime import datetime
from typing import Protocol


class ClockProvider(Protocol):
    """Environment-neutral time source injected into Runtime/Environment."""

    def now(self) -> datetime: ...

    def monotonic(self) -> float: ...

    def sleep_policy(self, seconds: float) -> None: ...
```
## Contract boundary
    - Real, Virtual and accelerated time implementations are injected implementations.
    - Core must not call datetime.now() or sleep against a concrete environment clock directly.
    - High-Speed changes time/replay policy, not Core strategy logic.

[Child Page] broker.py
```python
from typing import Protocol

from contracts.types import BrokerOrderCommand, ExecutionReport


class BrokerAdapter(Protocol):
    """Environment-side broker boundary."""

    def submit(self, command: BrokerOrderCommand) -> ExecutionReport: ...

    def cancel(self, order_id: str) -> ExecutionReport: ...

    def query(self, order_id: str) -> ExecutionReport | None: ...
```
## Contract boundary
    - Core emits OrderIntent.
    - Environment-specific adapter code translates OrderIntent to BrokerOrderCommand.
    - Broker returns canonical ExecutionReport.
    - Generic contract code does not invent an order type or broker execution policy.
    - Broker-specific endpoint/session/symbol details do not enter Core.

[Child Page] account.py
```python
from typing import Protocol

from contracts.types import AccountSnapshot


class AccountProvider(Protocol):
    """Environment-neutral account state provider."""

    def snapshot(self) -> AccountSnapshot: ...
```
## Contract boundary
    - Account state is read-only from the Core contract perspective.
    - AccountSnapshot.as_of and AccountSnapshot.freshness are mandatory freshness boundaries.
    - Provider-specific account objects must be translated before crossing this contract.

[Child Page] execution.py
```python
from typing import Iterable, Protocol

from contracts.types import ExecutionReport


class ExecutionProvider(Protocol):
    """Environment-neutral execution result provider."""

    def reports(self) -> Iterable[ExecutionReport]: ...

    def query_execution(self, execution_id: str) -> ExecutionReport | None: ...
```
## Contract boundary
    - Execution results are exposed only as canonical ExecutionReport values.
    - Broker-specific response objects do not cross this boundary.
    - Idempotency/reconciliation policy remains an Environment responsibility.

[Child Page] environment.py
```python
from typing import Protocol


class EnvironmentLifecycle(Protocol):
    """Common lifecycle contract implemented by every Environment Bundle."""

    def initialize(self) -> None: ...
    def connect(self) -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def restart(self) -> None: ...
    def shutdown(self) -> None: ...
```
## Contract boundary
    - High-Speed / Virtual / Paper / Live expose the same lifecycle shape.
    - Environment-specific setup remains inside the bundle implementation.
    - Runtime Controller orchestrates lifecycle; it does not own broker or market implementations.

[Child Page] runtime.py
```python
from dataclasses import dataclass
from typing import Protocol

from contracts.types import EnvironmentType


@dataclass(frozen=True)
class RuntimeCommand:
    action: str
    environment: EnvironmentType | None = None


@dataclass(frozen=True)
class RuntimeStatus:
    running: bool
    environment: EnvironmentType | None
    connected: bool
    execution_allowed: bool
    reason: str | None = None
    # Control-plane lifecycle state. Never reuse Domain order/position status values.
    technical_state: str | None = None


class RuntimeControl(Protocol):
    """UI-facing runtime control boundary."""

    def execute(self, command: RuntimeCommand) -> RuntimeStatus: ...

    def status(self) -> RuntimeStatus: ...
```
## Contract boundary
    - UI communicates through RuntimeCommand / RuntimeStatus rather than environment implementations.
    - Runtime Controller remains the lifecycle orchestrator.
    - Live execution permission is represented explicitly in status and is not implied by running=True.
    - technical_state is reserved for runtime lifecycle failures such as STOP_TIMEOUT; it must not encode Domain order, fill, position, or risk states.

[Child Page] types.py
```python
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Mapping, Sequence

@dataclass(frozen=True)
class CanonicalMarketTick:
    instrument_id: str
    observed_at: datetime
    price: Decimal
    volume: Decimal | None = None
    source_sequence: int | None = None


@dataclass(frozen=True)
class DataQuality:
    is_fresh: bool
    is_complete: bool
    source_available: bool
    reason: str | None = None


@dataclass(frozen=True)
class MarketState:
    as_of: datetime
    ticks: Mapping[str, CanonicalMarketTick]
    quality: Mapping[str, DataQuality]


class EnvironmentType(str, Enum):
    HIGH_SPEED = "high_speed"
    VIRTUAL = "virtual"
    PAPER = "paper"
    LIVE = "live"


@dataclass(frozen=True)
class OptionInstrumentIdentity:
    """Environment-neutral authoritative identity for an option instrument."""

    instrument_id: str
    symbol: str
    expiry: str | None = None
    option_type: str | None = None
    strike: Decimal | None = None


@dataclass(frozen=True)
class ExecutionLeg:
    """One typed leg of a strategy-owned multi-leg execution plan.

    Instrument identity resolution remains outside Strategy; strike/option_type are
    explicit strategy outputs and submission policy is intentionally not owned here.
    """

    leg_id: str
    side: str
    quantity: int
    option_type: str | None = None
    strike: Decimal | None = None
    requested_price: Decimal | None = None


@dataclass(frozen=True)
class MultiLegExecutionPlan:
    """Lossless strategy plan for one logical multi-leg intent.

    This is additive to OrderIntent. It describes legs only; atomicity, ordering,
    partial-fill compensation and broker submission policy belong to OMS/Execution.
    """

    group_id: str
    strategy_id: str
    legs: Sequence[ExecutionLeg]
    purpose: str | None = None

    def __post_init__(self) -> None:
        if not self.group_id:
            raise ValueError("group_id must be non-empty")
        if not self.legs:
            raise ValueError("MultiLegExecutionPlan requires at least one leg")
        leg_ids = [leg.leg_id for leg in self.legs]
        if len(set(leg_ids)) != len(leg_ids):
            raise ValueError("leg_id values must be unique within a plan")
        if any(leg.quantity <= 0 for leg in self.legs):
            raise ValueError("leg quantity must be positive")


@dataclass(frozen=True)
class OrderIntent:
    """Environment-neutral instruction emitted by Core/OMS.

    instrument_identity preserves domain identity without introducing broker-specific fields.
    The additive execution/provenance fields preserve existing program semantics
    without moving broker-specific details into Core.
    """

    client_order_id: str
    instrument_id: str
    side: str
    quantity: int
    intent_type: str
    strategy_id: str | None = None
    risk_context: str | None = None
    instrument_identity: OptionInstrumentIdentity | None = None
    asset_type: str | None = None
    requested_price: Decimal | None = None
    order_type: str | None = None
    order_purpose: str | None = None
    track_id: str | None = None
    tag_id: str | None = None
    group_id: str | None = None
    leg_id: str | None = None


@dataclass(frozen=True)
class BrokerOrderCommand:
    """Environment-specific translation of an OrderIntent."""

    client_order_id: str
    instrument_id: str
    side: str
    quantity: int
    order_type: str
    broker_symbol: str | None = None
    session_id: str | None = None
    instrument_identity: OptionInstrumentIdentity | None = None
    asset_type: str | None = None
    requested_price: Decimal | None = None
    strategy_id: str | None = None
    order_purpose: str | None = None
    track_id: str | None = None
    tag_id: str | None = None
    group_id: str | None = None
    leg_id: str | None = None


@dataclass(frozen=True)
class BrokerOrderResponse:
    """Transport-level broker ACK/result; not an execution or fill report."""

    client_order_id: str
    accepted: bool
    broker_order_id: str | None = None
    broker_code: str | None = None
    message: str | None = None
    raw_response: Mapping[str, object] | None = None


@dataclass(frozen=True)
class OrderAckEvent:\n    """Canonical order acknowledgement event; never an execution/fill."""\n\n    client_order_id: str\n    accepted: bool\n    broker_order_id: str | None = None\n    broker_code: str | None = None\n    message: str | None = None\n\n\n@dataclass(frozen=True)\nclass ExecutionReport:
    """Canonical execution result returned by an Environment adapter."""

    client_order_id: str
    broker_order_id: str | None
    execution_id: str | None
    status: str
    filled_quantity: int
    remaining_quantity: int
    execution_price: Decimal | None
    execution_timestamp: datetime | None
    source_freshness: DataQuality | None = None
    rejected_reason: str | None = None
    group_id: str | None = None
    leg_id: str | None = None


@dataclass(frozen=True)
class AccountSnapshot:
    """Environment-neutral account read model."""

    as_of: datetime
    balances: Mapping[str, Decimal]
    freshness: DataQuality


@dataclass(frozen=True)
class PositionSnapshot:
    """Environment-neutral position read model."""

    as_of: datetime
    positions: Mapping[str, Decimal]
    freshness: DataQuality


@dataclass(frozen=True)
class ProviderHealth:
    """Environment-neutral provider health result."""

    available: bool
    as_of: datetime | None = None
    reason: str | None = None


__all__: Sequence[str] = (
    "AccountSnapshot",
    "BrokerOrderCommand",
    "BrokerOrderResponse",
    "CanonicalMarketTick",
    "DataQuality",
    "EnvironmentType",
    "ExecutionReport",\n    "ExecutionLeg",\n    "MultiLegExecutionPlan",\n    "OrderAckEvent",
    "MarketState",
    "OrderIntent",
    "OptionInstrumentIdentity",
    "PositionSnapshot",
    "ProviderHealth",
)
```
## Ownership
    - Canonical Market DTO의 단일 정의는 contracts/types.py가 소유한다.
    - OrderIntent / BrokerOrderCommand / ExecutionReport / AccountSnapshot / PositionSnapshot은 contracts/types.py가 표준 DTO 소유권을 가진다.
    - OptionInstrumentIdentity는 symbol / expiry / option_type / strike를 환경 중립적인 도메인 identity로 보존한다.
    - Environment adapter는 BrokerOrderCommand를 만들고 ExecutionReport를 반환한다.
    - Core는 Broker-specific field를 사용하지 않는다.
    - Option identity는 authoritative Market/Option Master source에서 공급하며 중간 경계에서 기본값으로 재생성하지 않는다.
    - 누락된 실제 데이터는 None/명시적 freshness로 표현하며 synthetic fallback을 사용하지 않는다.
## Identity Resolver 경계 (No.083 확정)
    - CanonicalMarketTick와 Option Contract Master에서 확보한 권위 정보를 하나의 OptionInstrumentIdentity로 정규화하는 책임은 Core 진입 직후의 Domain Resolver에 둔다.
    - Resolver 입력: symbol, expiry, option_type, strike 및 asset_type.
    - Resolver 출력은 immutable identity이며 Signal/Decision/Risk/OMS 경계에서 동일 객체 또는 동등 값으로 전달한다.
    - Strategy가 명시한 option_type/strike는 주문 의도 override로 적용하되, symbol/expiry는 Market/Master authority를 유지한다.
    - 신규 표준 경로에서는 CanonicalOrderCommand의 legacy default 값으로 identity를 보완하지 않는다.
    - Resolver는 특정 VSSF/KIS API를 참조하지 않는 순수 Domain Logic으로 유지한다.
## OrderIntent Identity Finalization 규칙 (No.086)
OrderIntent 생성 직전 Core/OMS Resolver는 다음 입력을 받는다.
    1. authoritative Signal.instrument_identity
    1. explicit option_type_override
    1. explicit strike_override
결과 규칙:
    - identity가 없으면 option order를 synthetic default로 생성하지 않고 명시적 validation failure로 처리한다.
    - symbol / expiry / instrument_id는 authoritative identity에서 그대로 유지한다.
    - option_type / strike는 override가 None이 아닐 때만 해당 값으로 교체한다.
    - Resolver 결과는 새 immutable OptionInstrumentIdentity이며 이후 OrderIntent.instrument_identity에 첨부한다.
    - OrderIntent.instrument_id는 instrument_identity.instrument_id와 불일치할 수 없다.
    - OMS/Risk/Router는 확정 후 identity 필드를 재작성하지 않는다.
## Environment Adapter → CanonicalOrderCommand Mapping (No.087)
Environment Adapter는 확정된 OrderIntent.instrument_identity를 다음과 같이 1:1 전달한다.
    - asset_type ← identity.asset_type
    - symbol ← identity.symbol (default 재사용 금지)
    - expiry ← identity.expiry
    - option_type ← identity.option_type
    - strike ← identity.strike
    - side / qty / price / client_order_id / track_id / tag_id ← OrderIntent execution fields
Mapping 직전 validation:
    1. OPTION 주문은 symbol과 expiry가 비어 있지 않아야 한다.
    1. OPTION 주문은 option_type과 strike가 identity와 동일해야 한다.
    1. CanonicalOrderCommand.get_instrument_key() 재계산 결과는 OrderIntent.instrument_identity.instrument_id와 동등해야 한다.
불일치 시 Adapter는 broker command를 생성하지 않고 mapping validation failure를 반환한다. Adapter는 identity를 추론하거나 legacy default(KOSPI200, empty expiry, CALL, 0.0)로 보완하지 않는다.
## No.110 정정 규칙
기존 No.086의 override 설명 중 실제 contract 변경을 허용하는 것으로 읽힐 수 있는 부분은 No.110에서 정정한다. 현재 Resolver가 authoritative Contract Master/selector를 직접 조회하지 않는 상태에서는 기존 instrument_id를 유지한 채 다른 option_type/strike를 적용하면 identity가 오염될 수 있으므로, 변경 override는 fail-closed 한다. 동일 값 override만 보존한다.
또한 No.087의 asset_type ← identity.asset_type 표현은 현재 OptionInstrumentIdentity에 asset_type 필드가 없으므로 asset_type ← OrderIntent.asset_type으로 해석·적용한다.
[Child Page] risk_decision_adapter.py
```python
from dataclasses import replace
from typing import Protocol

from .position_execution_policy import (
    PositionExecutionDecision,
    PositionExecutionRequest,
    PositionExecutionPolicyError,
)


class RiskDecisionLike(Protocol):
    decision: str
    is_approved: bool
    approved_qty: int
    reduced_command: object | None
    rejection_reason: str | None


class RiskDecisionMappingError(PositionExecutionPolicyError):
    pass


def apply_risk_decision(
    decision: PositionExecutionDecision,
    risk_result: RiskDecisionLike,
) -> PositionExecutionDecision:
    """Apply authoritative Risk result without inventing execution semantics."""
    status = str(risk_result.decision).upper()

    if status == "DENY" or not risk_result.is_approved:
        raise RiskDecisionMappingError(
            risk_result.rejection_reason or "ORDER_DENIED_BY_RISK"
        )

    if status == "ALLOW":
        qty = int(risk_result.approved_qty)
    elif status == "REDUCE":
        reduced = getattr(risk_result, "reduced_command", None)
        reduced_qty = getattr(reduced, "qty", None) if reduced is not None else None
        if reduced_qty is None:
            raise RiskDecisionMappingError("REDUCED_QUANTITY_REQUIRED")
        if int(risk_result.approved_qty) != int(reduced_qty):
            raise RiskDecisionMappingError("RISK_QUANTITY_PROVENANCE_MISMATCH")
        qty = int(reduced_qty)
    else:
        raise RiskDecisionMappingError(f"UNKNOWN_RISK_DECISION: {status}")

    if qty <= 0:
        raise RiskDecisionMappingError("APPROVED_QUANTITY_REQUIRED")

    return replace(decision, approved_quantity=qty)
```
## 경계 규칙
        - Risk는 quantity의 승인 결과만 authoritative하게 제공한다.
        - order_type, order_purpose는 Position/Order Policy가 공급한 기존 Decision 값을 그대로 유지한다.
        - DENY는 예외로 종료하여 OrderIntent 생성으로 진행하지 않는다.
        - REDUCE에서는 approved_qty와 reduced_command.qty가 일치하지 않으면 provenance 오류로 거부한다.
        - 이 Adapter는 기본값, 전략 판단, 가격 fallback을 생성하지 않는다.
## No.298 연결 검증 보완
OptionInstrumentIdentity는 authoritative instrument_id / symbol / expiry / option_type / strike를 보존하는 immutable domain identity로 확인했다. 따라서 Adapter에서 이 값을 조합하거나 새 instrument_id를 만들지 않는다.

[Child Page] README.md
Core와 실행환경 사이의 유일한 기술적 경계다.
작성 순서:
    1. types.py
    1. market_data.py
    1. clock.py
    1. account.py
    1. broker.py
    1. execution.py
    1. environment.py
    1. runtime.py
규칙:
    - 특정 증권사 이름을 Contract에 넣지 않는다.
    - Virtual 구현체 이름을 Contract에 넣지 않는다.
    - DTO는 Canonical Model을 사용한다.
    - Contract 변경은 4개 환경 영향 분석 후에만 허용한다.

[Child Page] position.py
```python
from typing import Protocol

from contracts.types import PositionSnapshot


class PositionProvider(Protocol):
    """Environment-neutral position state provider."""

    def snapshot(self) -> PositionSnapshot: ...
```
## Contract boundary
    - Position state is read-only from the Core contract perspective.
    - PositionSnapshot.as_of and PositionSnapshot.freshness are mandatory freshness boundaries.
    - Provider-specific position objects must be translated before crossing this contract.

[Child Page] trading_calendar.py
```python
from datetime import date
from typing import Protocol


class TradingCalendar(Protocol):
    """Minimal trading-day capability required by OptionContractMaster."""

    def is_trading_day(self, value: date) -> bool: ...

    def prev_trading_day(self, value: date) -> date: ...

    def trading_days_between(self, start: date, end: date) -> int: ...
```
    - Contract only. Production source implementation is not owned by Core.
    - Unverified production calendar remains BLOCKED.
    - Tests may inject a deterministic fake calendar.

[Child Page] risk.py
```python
from dataclasses import dataclass
from decimal import Decimal
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
    required_margin: Decimal = Decimal("0")
    estimated_margin_ratio: Decimal = Decimal("0")
    token: RiskApprovalToken | None = None
    reduced_command: Any | None = None
```
## Ownership
    - Standard Risk approval/result DTO는 contracts/risk.py가 소유한다.
    - Legacy shared.core.contracts.RiskApprovalToken은 import하지 않는다.
    - RiskEvaluationResult는 Reference의 ALLOW/REDUCE/DENY 의미와 approved_qty, required_margin, estimated_margin_ratio, reduced_command 결과 계약을 보존한다.
    - reduced_command는 현재 Standard Core에 Reference CanonicalOrderCommand가 없으므로 특정 Legacy command 타입에 결합하지 않는다.
    - 실제 token 발행 알고리즘은 RiskEngine 구현 책임이며 이 파일은 데이터 계약만 소유한다.

[Child Page] virtual_contract_resolver.py
```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol


class VirtualContractResolutionError(ValueError):
    pass


@dataclass(frozen=True)
class VirtualContractMapping:
    scenario_contract_key: str
    shrn_iscd: str


class OptionContractIdentityRegistry(Protocol):
    def get_contract_identity(self, shrn_iscd: str): ...


class VirtualContractResolver:
    """Resolve Scenario keys only through explicit mapping and authoritative registry."""

    def __init__(
        self,
        mappings: Mapping[str, VirtualContractMapping],
        registry: OptionContractIdentityRegistry,
    ) -> None:
        self._mappings = dict(mappings)
        self._registry = registry
        self._validate_mappings()

    def resolve(self, scenario_contract_key: str):
        key = scenario_contract_key.strip()
        if not key:
            raise VirtualContractResolutionError("SCENARIO_CONTRACT_KEY_REQUIRED")

        mapping = self._mappings.get(key)
        if mapping is None:
            raise VirtualContractResolutionError("SCENARIO_CONTRACT_MAPPING_NOT_FOUND")

        shrn_iscd = mapping.shrn_iscd.strip()
        if not shrn_iscd:
            raise VirtualContractResolutionError("SHRN_ISCD_REQUIRED")

        identity = self._registry.get_contract_identity(shrn_iscd)
        if identity is None:
            raise VirtualContractResolutionError("AUTHORITATIVE_CONTRACT_IDENTITY_NOT_FOUND")
        return identity

    def _validate_mappings(self) -> None:
        for key, mapping in self._mappings.items():
            if not key.strip() or mapping.scenario_contract_key != key:
                raise VirtualContractResolutionError("INVALID_SCENARIO_CONTRACT_MAPPING")
            if not mapping.shrn_iscd.strip():
                raise VirtualContractResolutionError("SHRN_ISCD_REQUIRED")
```
## 책임
    - scenario_contract_key → explicit shrn_iscd → OptionContractMaster registry 단방향 해석만 허용한다.
    - symbol/expiry/strike/option_type 역추론은 하지 않는다.
    - registry 조회 실패는 fallback 없이 예외로 중단한다.
    - 실제 mapping 값 source와 registry lifecycle은 composition이 공급한다.

[Child Page] OPTION_IDENTITY_SUPPLY_CONTRACT.md
## 목적
외부 authoritative source가 제공한 옵션 계약 identity를 Standard Core의 OptionInstrumentIdentity로 주입하는 최소 경계를 고정한다.
## 최소 입력
외부 공급자는 다음 5개 값을 모두 포함한 OptionInstrumentIdentity를 공급해야 한다.
    - instrument_id
    - symbol
    - expiry
    - option_type
    - strike
실제 Core 입력 인터페이스는 core/oms/option_identity_resolver.py의 OptionIdentityResolutionInput.instrument_identity이다.
## 책임 경계
    - 외부 source/selector가 authoritative identity의 조회·선택 책임을 가진다.
    - Core Resolver는 공급된 identity를 검증하고 immutable identity로 확정한다.
    - Core는 외부 source의 식별자 형식을 알지 않는다.
    - KIS shrn_iscd, stnd_iscd 등 broker/master-specific key를 Standard instrument_id로 변환하지 않는다.
    - symbol + expiry + option_type + strike로 instrument_id를 합성하지 않는다.
    - identity가 없거나 필수 값이 비어 있으면 fail-closed 한다.
    - 실제 계약을 변경하는 option_type/strike override는 authoritative Contract Master/selector가 없으면 fail-closed 한다.
## 공급 형태
현재 production source가 확정되지 않았으므로 source adapter/selector를 구현하거나 Runtime에 연결하지 않는다. 향후 실제 공급원이 확보되면 그 source 전용 adapter가 완전한 OptionInstrumentIdentity를 만들어 OptionIdentityResolutionInput으로 전달한다.
## 보존 규칙
instrument_id / symbol / expiry는 공급 identity를 그대로 보존한다. Resolver 이후 OMS/Risk/Router가 identity를 재작성하지 않는다.
## 금지
    - shrn_iscd -> instrument_id
    - stnd_iscd -> instrument_id
    - strike/type 역산
    - composite key의 authoritative ID 승격
    - legacy default 또는 synthetic fallback

[Child Page] authoritative_option_identity_source.py
```python
from __future__ import annotations

from typing import Protocol

from contracts.types import OptionInstrumentIdentity


class AuthoritativeOptionIdentitySource(Protocol):
    """Supplies an already-authoritative Standard option identity.

    The implementation owns external lookup/selection. Core must not infer or
    synthesize instrument_id from KIS/source-specific identifiers.
    """

    def get_identity(self, selector: object) -> OptionInstrumentIdentity | None:
        """Return a complete authoritative identity or None when unresolved."""
        ...
```
## Contract
    - Source/selector owns lookup and selection.
    - Return value is either a complete OptionInstrumentIdentity or None.
    - The source boundary may interpret KIS shrn_iscd/stnd_iscd, but the Standard instrument_id must already be authoritative at the returned identity boundary.
    - No synthetic ID generation, composite-key promotion, strike/type inference, or legacy fallback.
    - Core Resolver remains responsible for final validation and fail-closed behavior.
    - This interface is a contract seam only; no production source or Runtime connection is implemented here.

[Child Page] external_authoritative_option_identity_record.py
```python
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from contracts.types import OptionInstrumentIdentity


class AuthoritativeOptionIdentityRecordError(ValueError):
    """Raised when an external authoritative identity record is incomplete or invalid."""


@dataclass(frozen=True)
class ExternalAuthoritativeOptionIdentityRecord:
    """Minimum externally owned record required to enter Standard Identity resolution.

    `instrument_id`, `symbol`, `expiry`, `option_type`, and `strike` are authoritative
    values owned by the external source. KIS-specific identifiers are optional
    provenance fields and are never promoted to `instrument_id`.
    """

    instrument_id: str
    symbol: str
    expiry: str
    option_type: str
    strike: Decimal
    shrn_iscd: str | None = None
    stnd_iscd: str | None = None

    def to_identity(self) -> OptionInstrumentIdentity:
        if not self.instrument_id:
            raise AuthoritativeOptionIdentityRecordError("INSTRUMENT_ID_REQUIRED")
        if not self.symbol:
            raise AuthoritativeOptionIdentityRecordError("SYMBOL_REQUIRED")
        if not self.expiry:
            raise AuthoritativeOptionIdentityRecordError("EXPIRY_REQUIRED")
        if not self.option_type:
            raise AuthoritativeOptionIdentityRecordError("OPTION_TYPE_REQUIRED")
        if self.strike <= 0:
            raise AuthoritativeOptionIdentityRecordError("STRIKE_REQUIRED")

        return OptionInstrumentIdentity(
            instrument_id=self.instrument_id,
            symbol=self.symbol,
            expiry=self.expiry,
            option_type=self.option_type,
            strike=self.strike,
        )
```
## Contract
    - 외부 authoritative owner가 instrument_id, symbol, expiry, option_type, strike를 모두 제공해야 한다.
    - shrn_iscd, stnd_iscd는 provenance/보조 식별자로만 보존할 수 있다.
    - KIS 식별자를 instrument_id로 변환하거나 승격하지 않는다.
    - 누락/무효 record는 fail-closed 한다.
    - 이 record는 source owner가 실제 값을 공급하기 전까지 fixture/검증 계약 용도로만 사용하며 production source를 가장하지 않는다.

[Child Page] option_identity_source_port.py
```python
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from contracts.external_authoritative_option_identity_record import (
    ExternalAuthoritativeOptionIdentityRecord,
)


class OptionIdentitySourceError(ValueError):
    """Raised when an external identity source cannot prove the selected contract."""


@dataclass(frozen=True)
class OptionIdentitySelection:
    """Contract attributes used to query an external authoritative owner.

    This object is a lookup request only. It never generates or derives an
    instrument_id.
    """

    symbol: str
    expiry: str
    option_type: str
    strike: Decimal

    def __post_init__(self) -> None:
        if not self.symbol:
            raise OptionIdentitySourceError("SYMBOL_REQUIRED")
        if not self.expiry:
            raise OptionIdentitySourceError("EXPIRY_REQUIRED")
        if not self.option_type:
            raise OptionIdentitySourceError("OPTION_TYPE_REQUIRED")
        if self.strike <= 0:
            raise OptionIdentitySourceError("STRIKE_REQUIRED")


class OptionIdentitySource(Protocol):
    """External authoritative Product/Instrument Master boundary."""

    def resolve(
        self,
        selection: OptionIdentitySelection,
    ) -> ExternalAuthoritativeOptionIdentityRecord | None:
        ...


def resolve_authoritative_option_identity(
    source: OptionIdentitySource,
    selection: OptionIdentitySelection,
) -> ExternalAuthoritativeOptionIdentityRecord:
    """Accept only a complete source-owned record matching the requested contract."""

    record = source.resolve(selection)
    if record is None:
        raise OptionIdentitySourceError("AUTHORITATIVE_IDENTITY_NOT_FOUND")

    identity = record.to_identity()
    if identity.symbol != selection.symbol:
        raise OptionIdentitySourceError("AUTHORITATIVE_SYMBOL_MISMATCH")
    if identity.expiry != selection.expiry:
        raise OptionIdentitySourceError("AUTHORITATIVE_EXPIRY_MISMATCH")
    if identity.option_type != selection.option_type:
        raise OptionIdentitySourceError("AUTHORITATIVE_OPTION_TYPE_MISMATCH")
    if identity.strike != selection.strike:
        raise OptionIdentitySourceError("AUTHORITATIVE_STRIKE_MISMATCH")

    return record
```
## 경계
    - 실제 Production source를 구현하지 않는다.
    - KIS 코드, composite key, fixture를 instrument_id로 승격하지 않는다.
    - 새 source가 연결되면 이 Port의 구현체만 Infrastructure/Application composition에서 추가한다.
    - Core Resolver는 계속 OptionInstrumentIdentity만 입력받는다.

[Child Page] authoritative_option_identity_source.py
```python
from __future__ import annotations

from typing import Protocol

from contracts.external_authoritative_option_identity_record import (
    ExternalAuthoritativeOptionIdentityRecord,
)
from contracts.option_identity_source_port import (
    OptionIdentitySelection,
    OptionIdentitySource,
)
from contracts.types import OptionInstrumentIdentity


class AuthoritativeOptionIdentitySource(OptionIdentitySource, Protocol):
    """Compatibility view of the single external authoritative identity seam.

    New lookup paths use ``resolve(selection)`` and return the source-owned
    record. ``get_identity`` is retained only for callers that already hold a
    complete authoritative identity.
    """

    def get_identity(self, selector: object) -> OptionInstrumentIdentity | None:
        ...


class AuthoritativeOptionIdentityRecordSource(OptionIdentitySource, Protocol):
    """Explicit alias for implementations returning the external record."""

    def resolve(
        self,
        selection: OptionIdentitySelection,
    ) -> ExternalAuthoritativeOptionIdentityRecord | None:
        ...
```
## 단일 seam 규칙
    - 신규 external lookup은 OptionIdentitySource.resolve(selection)을 표준 경로로 사용한다.
    - 반환값은 외부 owner가 공급한 complete record이며 to_identity()로만 Standard identity에 진입한다.
    - 기존 get_identity(selector)는 이미 authoritative identity를 보유한 legacy caller의 호환 경계로만 유지한다.
    - 두 경로 모두 synthetic instrument_id 생성을 금지한다.

[Child Page] track4_runtime_input_provider.py
```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, Sequence


class Track4InputSourceUnavailable(RuntimeError):
    pass


class Track4InputTimestampMismatch(Track4InputSourceUnavailable):
    pass


@dataclass(frozen=True)
class Track4RuntimeInputReadiness:
    market: bool
    history: bool
    account_pnl: bool
    greeks: bool
    attribution: bool

    @property
    def is_complete(self) -> bool:
        return all((self.market, self.history, self.account_pnl, self.greeks, self.attribution))


class Track4RuntimeInputProvider(Protocol):
    def readiness(self) -> Track4RuntimeInputReadiness: ...
    def observed_at(self) -> datetime: ...
    def current_price(self) -> Decimal: ...
    def active_vol(self) -> Decimal: ...
    def base_vol(self) -> Decimal: ...
    def current_pnl(self) -> Decimal: ...
    def current_equity(self) -> Decimal: ...
    def price_history(self) -> Sequence[Decimal]: ...
    def current_delta(self) -> Decimal: ...
    def current_gamma(self) -> Decimal: ...
    def premium_spent(self) -> Decimal: ...
    def accumulated_gamma_profit(self) -> Decimal: ...
    def theta_decay_cost(self) -> Decimal: ...
```
## 계약 보완
    - 모든 production Track4 input source는 observed_at()을 제공해야 한다.
    - Runtime tick의 observed_at과 source observation timestamp가 일치하지 않으면 materialization을 거부한다.
    - timestamp 불일치를 현재시간 또는 다른 tick 값으로 보정하지 않는다.
    - Market/Account/KIS source completeness가 부족하면 원 Provider의 fail-closed 예외를 유지한다.
    - OHLC high/low/close를 합성하지 않는다.

[Child Page] track4_vssf_account_projection_provider.py
```python
from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from contracts.account import AccountProvider
from contracts.track4_runtime_input_provider import (
    Track4InputSourceUnavailable,
    Track4RuntimeInputProvider,
    Track4RuntimeInputReadiness,
)


class Track4VSSFAccountProjectionProvider(Track4RuntimeInputProvider):
    """Partial read-only Track4 provider backed by authoritative AccountSnapshot."""

    def __init__(self, account: AccountProvider):
        self._account = account

    def readiness(self) -> Track4RuntimeInputReadiness:
        return Track4RuntimeInputReadiness(False, False, True, False, False)

    def _snapshot(self):
        snapshot = self._account.snapshot()
        required = ("cash", "realized_pnl", "unrealized_pnl")
        missing = [name for name in required if name not in snapshot.balances]
        if missing:
            raise Track4InputSourceUnavailable(
                f"TRACK4_ACCOUNT_FIELDS_REQUIRED: {','.join(missing)}"
            )
        return snapshot

    def observed_at(self):
        return self._snapshot().as_of

    def current_equity(self) -> Decimal:
        return Decimal(self._snapshot().balances["cash"])

    def current_pnl(self) -> Decimal:
        balances = self._snapshot().balances
        return Decimal(balances["realized_pnl"]) + Decimal(balances["unrealized_pnl"])

    def current_price(self) -> Decimal:
        raise Track4InputSourceUnavailable("TRACK4_MARKET_SOURCE_UNAVAILABLE")
    def active_vol(self) -> Decimal:
        raise Track4InputSourceUnavailable("TRACK4_MARKET_SOURCE_UNAVAILABLE")
    def base_vol(self) -> Decimal:
        raise Track4InputSourceUnavailable("TRACK4_MARKET_SOURCE_UNAVAILABLE")
    def price_high(self) -> Sequence[Decimal]:
        raise Track4InputSourceUnavailable("TRACK4_HISTORY_SOURCE_UNAVAILABLE")
    def price_low(self) -> Sequence[Decimal]:
        raise Track4InputSourceUnavailable("TRACK4_HISTORY_SOURCE_UNAVAILABLE")
    def price_close(self) -> Sequence[Decimal]:
        raise Track4InputSourceUnavailable("TRACK4_HISTORY_SOURCE_UNAVAILABLE")
    def current_delta(self) -> Decimal:
        raise Track4InputSourceUnavailable("TRACK4_GREEKS_SOURCE_UNAVAILABLE")
    def current_gamma(self) -> Decimal:
        raise Track4InputSourceUnavailable("TRACK4_GREEKS_SOURCE_UNAVAILABLE")
    def premium_spent(self) -> Decimal:
        raise Track4InputSourceUnavailable("TRACK4_ATTRIBUTION_SOURCE_UNAVAILABLE")
    def accumulated_gamma_profit(self) -> Decimal:
        raise Track4InputSourceUnavailable("TRACK4_ATTRIBUTION_SOURCE_UNAVAILABLE")
    def theta_decay_cost(self) -> Decimal:
        raise Track4InputSourceUnavailable("TRACK4_ATTRIBUTION_SOURCE_UNAVAILABLE")
```
Partial read-only Track4 provider: Account/PnL is connected from existing authoritative AccountSnapshot only; all unresolved sources remain explicit fail-closed boundaries.

[Child Page] track4_market_projection_provider.py
```python
from __future__ import annotations

from decimal import Decimal
from typing import Callable, Sequence

from .track4_kis_greeks_provider import Track4KisGreeksProvider

from core.sensor.market_condition_sensor import MarketConditionSnapshot

from .track4_runtime_input_provider import (
    Track4InputSourceUnavailable,
    Track4RuntimeInputProvider,
    Track4RuntimeInputReadiness,
)


class Track4MarketProjectionProvider(Track4RuntimeInputProvider):
    """Read-only Track4 market provider backed by authoritative Sensor projections."""

    def __init__(
        self,
        snapshot_supplier: Callable[[], MarketConditionSnapshot | None],
        price_history_supplier: Callable[[str], Sequence[float]] | None = None,
        greeks_provider: Track4KisGreeksProvider | None = None,
    ) -> None:
        self._snapshot_supplier = snapshot_supplier
        self._price_history_supplier = price_history_supplier
        self._greeks_provider = greeks_provider

    def _snapshot(self) -> MarketConditionSnapshot:
        snapshot = self._snapshot_supplier()
        if snapshot is None:
            raise Track4InputSourceUnavailable("market condition snapshot is unavailable")
        return snapshot

    def readiness(self) -> Track4RuntimeInputReadiness:
        snapshot = self._snapshot_supplier()
        history_ready = False
        if snapshot is not None and self._price_history_supplier is not None:
            history_ready = bool(self._price_history_supplier(snapshot.instrument_id))
        return Track4RuntimeInputReadiness(
            market=snapshot is not None,
            history=history_ready,
            account_pnl=False,
            greeks=self._greeks_provider is not None,
            attribution=False,
        )

    def observed_at(self):
        return self._snapshot().as_of

    def current_price(self) -> Decimal:
        return Decimal(str(self._snapshot().current_price))

    def active_vol(self) -> Decimal:
        if self._greeks_provider is not None:
            return self._greeks_provider.active_vol()
        return Decimal(str(self._snapshot().volatility))

    def base_vol(self) -> Decimal:
        return Decimal(str(self._snapshot().baseline_volatility))

    def current_pnl(self) -> Decimal:
        raise Track4InputSourceUnavailable("account/pnl source is unavailable")

    def current_equity(self) -> Decimal:
        raise Track4InputSourceUnavailable("account/equity source is unavailable")

    def price_history(self) -> Sequence[Decimal]:
        snapshot = self._snapshot()
        if self._price_history_supplier is None:
            raise Track4InputSourceUnavailable("observed price history source is unavailable")
        return tuple(Decimal(str(value)) for value in self._price_history_supplier(snapshot.instrument_id))

    def current_delta(self) -> Decimal:
        if self._greeks_provider is None:
            raise Track4InputSourceUnavailable("greeks source is unavailable")
        return self._greeks_provider.current_delta()

    def current_gamma(self) -> Decimal:
        if self._greeks_provider is None:
            raise Track4InputSourceUnavailable("greeks source is unavailable")
        return self._greeks_provider.current_gamma()

    def premium_spent(self) -> Decimal:
        raise Track4InputSourceUnavailable("attribution source is unavailable")

    def accumulated_gamma_profit(self) -> Decimal:
        raise Track4InputSourceUnavailable("attribution source is unavailable")

    def theta_decay_cost(self) -> Decimal:
        raise Track4InputSourceUnavailable("attribution source is unavailable")
```
## 경계
    - MarketConditionSensor의 private state를 직접 읽지 않는다.
    - MarketConditionSnapshot과 공개 price_history() projection만 사용한다.
    - current_price → snapshot.current_price
    - active_vol → snapshot.volatility
    - base_vol → snapshot.baseline_volatility
    - price_history → 공개 Sensor price history supplier
    - Market 외 입력은 임의값으로 채우지 않고 fail-closed한다.
    - OHLC high/low/close를 합성하지 않는다.

[Child Page] track4_composite_runtime_input_[provider.py]
```python
from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from .track4_runtime_input_provider import (
    Track4InputSourceUnavailable,
    Track4InputTimestampMismatch,
    Track4RuntimeInputProvider,
    Track4RuntimeInputReadiness,
)


class Track4CompositeRuntimeInputProvider(Track4RuntimeInputProvider):
    """Compose independent authoritative partial Track4 providers without synthesizing data."""

    def __init__(self, market_provider: Track4RuntimeInputProvider, account_provider: Track4RuntimeInputProvider) -> None:
        self._market_provider = market_provider
        self._account_provider = account_provider

    def readiness(self) -> Track4RuntimeInputReadiness:
        market = self._market_provider.readiness()
        account = self._account_provider.readiness()
        return Track4RuntimeInputReadiness(
            market=market.market or account.market,
            history=market.history or account.history,
            account_pnl=market.account_pnl or account.account_pnl,
            greeks=market.greeks or account.greeks,
            attribution=market.attribution or account.attribution,
        )

    def observed_at(self):
        market_at = self._market_provider.observed_at()
        account_at = self._account_provider.observed_at()
        if market_at != account_at:
            raise Track4InputTimestampMismatch(
                f"TRACK4_SOURCE_TIMESTAMP_MISMATCH: market={market_at!s} account={account_at!s}"
            )
        return market_at

    def current_price(self) -> Decimal: return self._market_provider.current_price()
    def active_vol(self) -> Decimal: return self._market_provider.active_vol()
    def base_vol(self) -> Decimal: return self._market_provider.base_vol()
    def current_pnl(self) -> Decimal: return self._account_provider.current_pnl()
    def current_equity(self) -> Decimal: return self._account_provider.current_equity()
    def price_history(self) -> Sequence[Decimal]: return self._market_provider.price_history()
    def current_delta(self) -> Decimal: return self._market_provider.current_delta()
    def current_gamma(self) -> Decimal: return self._market_provider.current_gamma()
    def premium_spent(self) -> Decimal: return self._market_provider.premium_spent()
    def accumulated_gamma_profit(self) -> Decimal: return self._market_provider.accumulated_gamma_profit()
    def theta_decay_cost(self) -> Decimal: return self._market_provider.theta_decay_cost()
```
## 경계
    - Market과 Account/PnL 두 partial Provider의 authoritative source만 조합한다.
    - Composite에서 값의 계산·추정·합성을 하지 않는다.
    - price_history는 Market provider의 공개 관측 history projection을 그대로 전달한다.
    - 각 source가 공급하지 않는 값은 원 Provider의 Track4InputSourceUnavailable를 그대로 전파한다.
    - 전체 source completeness 확보 전에는 Runtime process_tick production 연결을 수행하지 않는다.

[Child Page] track4_market_history_projection.py
```python
from __future__ import annotations

from decimal import Decimal
from typing import Protocol, Sequence


class Track4MarketHistoryProjection(Protocol):
    """Read-only projection of observed market price history."""

    def price_history(self) -> Sequence[Decimal]: ...
```
## 목적
    - MarketConditionSensor의 내부 price buffer를 Track4가 직접 읽지 않도록 최소 public projection seam을 정의한다.
    - 반환값은 실제 관측 price의 순서와 값을 그대로 보존한다.
    - projection 과정에서 OHLC를 합성하지 않는다.
## 중요 경계
    - 이 계약은 관측 price history 계약이다.
    - price_high/price_low/price_close를 tick price에서 임의 생성하지 않는다.
    - 이 계약은 No.349에서 확정한 observed tick-price deadband의 authoritative history 입력 경계로 사용한다.
    - 이 계약의 존재 자체가 OHLC를 의미하지 않으며, OHLC readiness와 혼동하지 않는다.

[Child Page] track4_option_valuation_input.py
```python
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

class OptionValuationInputInvalid(ValueError):
    """Authoritative valuation input is missing or invalid."""

@dataclass(frozen=True)
class Track4OptionValuationInput:
    """Minimal environment-neutral input contract for option valuation."""
    instrument_id: str
    observed_at: datetime
    underlying_price: Decimal
    option_price: Decimal
    strike: Decimal
    expiry: date
    time_to_expiry_years: Decimal
    implied_volatility: Decimal
    risk_free_rate: Decimal
    price_source: str
    iv_source: str
    risk_free_rate_source: str
    time_to_expiry_source: str

    def __post_init__(self) -> None:
        if not self.instrument_id:
            raise OptionValuationInputInvalid("instrument_id is required")
        if self.underlying_price <= 0:
            raise OptionValuationInputInvalid("underlying_price must be positive")
        if self.option_price < 0:
            raise OptionValuationInputInvalid("option_price must be non-negative")
        if self.strike <= 0:
            raise OptionValuationInputInvalid("strike must be positive")
        if self.time_to_expiry_years <= 0:
            raise OptionValuationInputInvalid("time_to_expiry_years must be positive")
        if self.implied_volatility <= 0:
            raise OptionValuationInputInvalid("implied_volatility must be positive")
        if not self.price_source:
            raise OptionValuationInputInvalid("price_source is required")
        if not self.iv_source:
            raise OptionValuationInputInvalid("iv_source is required")
        if not self.risk_free_rate_source:
            raise OptionValuationInputInvalid("risk_free_rate_source is required")
        if not self.time_to_expiry_source:
            raise OptionValuationInputInvalid("time_to_expiry_source is required")
```
## Ownership / boundary
    - Read-only, environment-neutral valuation input DTO.
    - Does not calculate Delta/Gamma/Theta, IV, DTE, or risk-free rate.
    - Does not choose bid/ask/last as valuation reference price.
    - Every valuation-sensitive input carries a non-empty provenance field.
    - Existing OptionContract/TradingCalendar remains the identity and trading-day DTE owner; this DTO only accepts an already-established valuation time convention.
    - Until real runtime owners exist, no production Greeks provider may construct this DTO from synthetic/default values.

[Child Page] track4_kis_greeks_provider.py
```python
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Any, Mapping, Protocol


class Track4KisGreeksSourceInvalid(ValueError):
    """Raised when a KIS option Greeks snapshot is missing or invalid."""


@dataclass(frozen=True)
class Track4KisGreeksSnapshot:
    instrument_id: str
    observed_at: str
    delta: Decimal
    gamma: Decimal
    theta: Decimal
    implied_volatility: Decimal
    source: str = "KIS:H0IOCNT0"

    def __post_init__(self) -> None:
        if not self.instrument_id.strip():
            raise Track4KisGreeksSourceInvalid("instrument_id is required")
        if not self.observed_at.strip():
            raise Track4KisGreeksSourceInvalid("observed_at is required")
        if not self.source.strip():
            raise Track4KisGreeksSourceInvalid("source is required")
        for name, value in (
            ("delta", self.delta),
            ("gamma", self.gamma),
            ("theta", self.theta),
            ("implied_volatility", self.implied_volatility),
        ):
            if not value.is_finite():
                raise Track4KisGreeksSourceInvalid(f"{name} must be finite")
        if self.implied_volatility <= 0:
            raise Track4KisGreeksSourceInvalid("implied_volatility must be positive")


class Track4KisGreeksProvider(Protocol):
    @property
    def snapshot(self) -> Track4KisGreeksSnapshot: ...
    def current_delta(self) -> Decimal: ...
    def current_gamma(self) -> Decimal: ...
    def current_theta(self) -> Decimal: ...
    def active_vol(self) -> Decimal: ...


class KISIndexOptionGreeksProvider:
    """Read-only projection of the KIS index-option realtime trade payload.

    KIS H0IOCNT0 supplies delta, gamma, theta and HTS implied volatility directly.
    This adapter does not calculate Greeks, infer IV, or introduce a risk-free-rate
    assumption. The payload must already be the authoritative KIS option event.
    """

    def __init__(self, snapshot: Track4KisGreeksSnapshot):
        self._snapshot = snapshot

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        instrument_id: str,
        observed_at: str,
        source: str = "KIS:H0IOCNT0",
    ) -> "KISIndexOptionGreeksProvider":
        def decimal_field(name: str) -> Decimal:
            raw = payload.get(name)
            if raw is None or raw == "":
                raise Track4KisGreeksSourceInvalid(f"{name} is missing")
            try:
                value = Decimal(str(raw))
            except (InvalidOperation, ValueError) as exc:
                raise Track4KisGreeksSourceInvalid(f"{name} is invalid") from exc
            if not value.is_finite():
                raise Track4KisGreeksSourceInvalid(f"{name} must be finite")
            return value

        return cls(
            Track4KisGreeksSnapshot(
                instrument_id=instrument_id,
                observed_at=observed_at,
                delta=decimal_field("delta"),
                gamma=decimal_field("gama"),
                theta=decimal_field("theta"),
                implied_volatility=decimal_field("hts_ints_vltl"),
                source=source,
            )
        )

    def current_delta(self) -> Decimal:
        return self._snapshot.delta

    def current_gamma(self) -> Decimal:
        return self._snapshot.gamma

    def current_theta(self) -> Decimal:
        return self._snapshot.theta

    def active_vol(self) -> Decimal:
        return self._snapshot.implied_volatility

    @property
    def snapshot(self) -> Track4KisGreeksSnapshot:
        return self._snapshot
```
Authoritative source mapping
    - KIS domestic index-option realtime trade: H0IOCNT0 / 실시간-014
    - delta → Track4 current Delta
    - gama → Track4 current Gamma
    - theta → raw option Theta only; not yet promoted to monetary theta_decay_cost
    - hts_ints_vltl → KIS HTS implied volatility
The provider is intentionally read-only and performs no Black-Scholes calculation, IV solving, risk-free-rate defaulting, or price-reference inference.

[Child Page] track4_kis_greeks_ws_adapter.py
```python
from __future__ import annotations

from typing import Any, Mapping

from .track4_kis_greeks_provider import (
    KISIndexOptionGreeksProvider,
    Track4KisGreeksProvider,
    Track4KisGreeksSourceInvalid,
)


class Track4KisWebSocketAdapterInvalid(ValueError):
    """Raised when a KIS realtime wire frame cannot be adapted safely."""


# H0IOCNT0 wire payload positions documented by KIS Open Trading API.
_INSTRUMENT_INDEX = 0
_OBSERVED_HOUR_INDEX = 1
_DELTA_INDEX = 28
_GAMMA_INDEX = 29
_THETA_INDEX = 31
_IV_INDEX = 33


class KISIndexOptionGreeksWebSocketAdapter:
    """Adapt one decoded KIS H0IOCNT0 realtime frame into the authoritative Provider.

    This is deliberately a wire-to-provider boundary, not a WebSocket transport.
    The caller owns the live socket, subscription lifecycle and environment clock.
    The adapter only validates the KIS frame envelope/field positions and delegates
    the authoritative numeric fields to KISIndexOptionGreeksProvider.
    """

    TR_ID = "H0IOCNT0"

    def adapt(
        self,
        frame: str,
        *,
        observed_at: str,
        source: str = "KIS:H0IOCNT0",
    ) -> Track4KisGreeksProvider:
        parts = frame.split("|")
        if len(parts) < 4 or parts[0] not in {"0", "1"}:
            raise Track4KisWebSocketAdapterInvalid("invalid KIS realtime frame envelope")
        if parts[1] != self.TR_ID:
            raise Track4KisWebSocketAdapterInvalid("unexpected KIS TR ID")

        try:
            field_count = int(parts[2])
        except ValueError as exc:
            raise Track4KisWebSocketAdapterInvalid("invalid KIS field count") from exc

        values = parts[3].split("^")
        if field_count != len(values):
            raise Track4KisWebSocketAdapterInvalid("KIS field count mismatch")
        required_max = max(_INSTRUMENT_INDEX, _OBSERVED_HOUR_INDEX, _DELTA_INDEX, _GAMMA_INDEX, _THETA_INDEX, _IV_INDEX)
        if len(values) <= required_max:
            raise Track4KisWebSocketAdapterInvalid("KIS H0IOCNT0 payload is incomplete")

        instrument_id = values[_INSTRUMENT_INDEX].strip()
        if not instrument_id:
            raise Track4KisWebSocketAdapterInvalid("instrument id is missing")

        # observed_at is intentionally supplied by the caller; bsop_hour is retained
        # as source payload data but is not promoted to a timezone/date timestamp.
        payload: Mapping[str, Any] = {
            "delta": values[_DELTA_INDEX],
            "gama": values[_GAMMA_INDEX],
            "theta": values[_THETA_INDEX],
            "hts_ints_vltl": values[_IV_INDEX],
        }
        return KISIndexOptionGreeksProvider.from_payload(
            payload,
            instrument_id=instrument_id,
            observed_at=observed_at,
            source=source,
        )
```
## 경계 계약
    - 입력: KIS WebSocket 실시간 frame의 0|H0IOCNT0|<field_count>|<^-delimited payload> 형태.
    - optn_shrn_iscd → instrument_id.
    - delta / gama / theta / hts_ints_vltl은 KIS 공식 H0IOCNT0 field order에서 직접 추출한다.
    - observed_at은 WebSocket adapter가 임의 생성하지 않고 호출자가 주입한다.
    - 수신 frame의 field count와 TR ID를 검증하고 불일치 시 fail-closed 한다.
    - 실제 socket 연결, approval key, subscribe/unsubscribe, reconnect는 이 계약의 책임이 아니다.
    - Provider 내부의 from_payload()가 숫자 유효성 및 IV 양수 조건을 최종 검증한다.
    - theta는 raw Theta로만 전달되며 theta_decay_cost로 변환하지 않는다.
    - 이 경계는 KIS wire → Provider까지만 담당하며 MarketProjection/Composite가 다시 값을 계산하지 않는다.
KIS 공식 Open Trading API의 H0IOCNT0 명세에서 지수옵션 실시간체결가가 WebSocket으로 제공되고 delta, gama, theta, hts_ints_vltl 필드가 포함됨을 확인했다. 현재 Exp_Detail_1에는 이 wire frame을 실제로 수신하여 이 adapter를 호출하는 KIS WebSocket consumer는 없다.

[Child Page] risk_free_rate_source.py
```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

class RiskFreeRateUnavailable(RuntimeError):
    """Authoritative risk-free-rate source is unavailable."""

@dataclass(frozen=True, slots=True)
class RiskFreeRateSnapshot:
    rate: Decimal
    observed_at: datetime
    source: str

    def __post_init__(self) -> None:
        if self.rate < Decimal("-1"):
            raise ValueError("risk-free rate is invalid")
        if not self.source:
            raise ValueError("risk-free rate source is required")

class RiskFreeRateProvider(ABC):
    @abstractmethod
    def get_rate(self, observed_at: datetime) -> RiskFreeRateSnapshot:
        raise NotImplementedError
```
## Ownership
    - Option valuation의 risk-free rate 공급 경계만 정의한다.
    - 기본값, 상수, 임의 금리, fallback rate를 제공하지 않는다.
    - 실제 source가 확인되기 전에는 production 구현체를 만들지 않는다.
    - source와 observed_at을 함께 보존한다.

[Child Page] valuation_time_convention.py
```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

class ValuationTimeUnavailable(RuntimeError):
    """A complete valuation time convention is not available."""

@dataclass(frozen=True, slots=True)
class TimeToExpirySnapshot:
    expiry: date
    valuation_at: datetime
    years: Decimal
    source: str

    def __post_init__(self) -> None:
        if self.years <= 0:
            raise ValueError("time to expiry must be positive")
        if not self.source:
            raise ValueError("time-to-expiry source is required")

class ValuationTimeConvention(ABC):
    @abstractmethod
    def resolve(self, expiry: date, valuation_at: datetime) -> TimeToExpirySnapshot:
        raise NotImplementedError
```
## Ownership
    - OptionContract/TradingCalendar는 expiry와 trading-day 의미를 소유한다.
    - Clock는 valuation timestamp를 공급한다.
    - 이 port가 둘을 valuation용 time_to_expiry_years로 결합하는 경계를 정의한다.
    - day-count, timezone, cutoff, expiry-day treatment가 확정되기 전에는 계산 구현체를 추가하지 않는다.

[Child Page] futures_identity_source_port.py
from future import annotations
from dataclasses import dataclass
from typing import Protocol
class FuturesIdentitySourceError(ValueError):
pass
@dataclass(frozen=True)
class FuturesInstrumentIdentity:
instrument_id: str
symbol: str
def post_init(self) -> None:
if not str(self.instrument_id).strip():
raise FuturesIdentitySourceError('FUTURES_INSTRUMENT_ID_REQUIRED')
if not str(self.symbol).strip():
raise FuturesIdentitySourceError('FUTURES_SYMBOL_REQUIRED')
class FuturesIdentitySourcePort(Protocol):
def current_identity(self) -> FuturesInstrumentIdentity: ...
def require_futures_identity(source: FuturesIdentitySourcePort | None) -> FuturesInstrumentIdentity:
if source is None:
raise FuturesIdentitySourceError('FUTURES_IDENTITY_SOURCE_REQUIRED')
identity = source.current_identity()
if not isinstance(identity, FuturesInstrumentIdentity):
raise FuturesIdentitySourceError('FUTURES_IDENTITY_TYPE_REQUIRED')
return identity
## 책임
    - instrument_id와 Risk/Canonical용 symbol을 서로 다른 필드로 명시 보존한다.
    - CanonicalMarketTick.instrument_id를 자동으로 symbol로 해석하지 않는다.
    - legacy KOSPI200/KOSPI200F 기본값을 사용하지 않는다.
    - 실제 Market/Contract source adapter는 이 Port 구현체로 별도 주입해야 한다.

[Child Page] krx_kis_identity_reconciliation.py
"""KRX↔KIS identity reconciliation.
No implicit code conversion is permitted. A match is accepted only when the
authoritative KRX ISU_CD exactly equals a KIS stnd_iscd. Name similarity and
prefix heuristics are intentionally excluded.
"""
from future import annotations
from dataclasses import dataclass
from typing import Iterable, Literal
ProductKind = Literal["FUTURES", "OPTION"]
class IdentityReconciliationError(ValueError):
pass
@dataclass(frozen=True)
class KrxInstrumentRecord:
isu_cd: str
isu_nm: str
product_kind: ProductKind
def post_init(self) -> None:
if not self.isu_cd.strip(): raise IdentityReconciliationError("KRX_ISU_CD_REQUIRED")
if not self.isu_nm.strip(): raise IdentityReconciliationError("KRX_ISU_NM_REQUIRED")
@dataclass(frozen=True)
class KisMasterIdentityRecord:
shrn_iscd: str
stnd_iscd: str | None
def post_init(self) -> None:
if not self.shrn_iscd.strip(): raise IdentityReconciliationError("KIS_SHRN_ISCD_REQUIRED")
@dataclass(frozen=True)
class ReconciledInstrumentIdentity:
product_kind: ProductKind
krx_isu_cd: str
kis_shrn_iscd: str
kis_stnd_iscd: str
matched_by: str = "KIS_STND_ISCD_EXACT"
def reconcile_krx_to_kis(
krx_records: Iterable[KrxInstrumentRecord],
kis_records: Iterable[KisMasterIdentityRecord],
) -> tuple[ReconciledInstrumentIdentity, ...]:
by_standard: dict[str, KisMasterIdentityRecord] = {}
for record in kis_records:
if not record.stnd_iscd: continue
key = record.stnd_iscd.strip()
previous = by_standard.get(key)
if previous is not None and previous.shrn_iscd != record.shrn_iscd:
raise IdentityReconciliationError(f"AMBIGUOUS_KIS_STANDARD_CODE:{key}")
by_standard[key] = record
reconciled: list[ReconciledInstrumentIdentity] = []
seen_krx: set[str] = set()
for record in krx_records:
key = record.isu_cd.strip()
if key in seen_krx:
raise IdentityReconciliationError(f"DUPLICATE_KRX_ISU_CD:{key}")
seen_krx.add(key)
kis = by_standard.get(key)
if kis is None:
continue
reconciled.append(ReconciledInstrumentIdentity(
product_kind=record.product_kind,
krx_isu_cd=key,
kis_shrn_iscd=kis.shrn_iscd.strip(),
kis_stnd_iscd=key,
))
return tuple(reconciled)
# Ownership: KRX identifies the external universe; KIS shrn_iscd remains the
# execution code. Contract-month/current-contract policy is intentionally out
# of this module because the supplied KRX daily API spec does not define it.

[Child Page] futures_contract_master.py
"""KIS index-futures contract projection from fo_idx_code_mts.mst.
Authoritative meanings follow KIS 종목마스터정보(지수선물옵션).h.
"""
from future import annotations
from dataclasses import dataclass
from typing import Iterable, Optional
KIS_FUTURES_INFO_TYPES = frozenset({"1", "3", "7", "9", "B"})
KIS_CURRENT_MONTH_CODE = "1"
class FuturesContractMasterError(ValueError):
pass
@dataclass(frozen=True)
class KisFuturesContractIdentity:
shrn_iscd: str
stnd_iscd: Optional[str]
info_type: str
mmsc_cls_code: str
unas_shrn_iscd: Optional[str]
unas_kor_name: Optional[str]
kor_name: Optional[str] = None
def parse_kis_futures_contracts(raw_content: str) -> tuple[KisFuturesContractIdentity, ...]:
records: list[KisFuturesContractIdentity] = []
seen: dict[str, KisFuturesContractIdentity] = {}
for line in raw_content.splitlines():
if not line or "|" not in line:
continue
parts = [part.strip() for part in line.split("|")]
if len(parts) < 9:
continue
info_type, shrn_iscd, stnd_iscd, kor_name = parts[:4]
if info_type not in KIS_FUTURES_INFO_TYPES or not shrn_iscd:
continue
identity = KisFuturesContractIdentity(
shrn_iscd=shrn_iscd,
stnd_iscd=stnd_iscd or None,
info_type=info_type,
mmsc_cls_code=parts[6],
unas_shrn_iscd=parts[7] or None,
unas_kor_name=parts[8] or None,
kor_name=kor_name or None,
)
existing = seen.get(shrn_iscd)
if existing is not None and existing != identity:
raise FuturesContractMasterError(f"CONFLICTING_FUTURES_IDENTITY:{shrn_iscd}")
seen[shrn_iscd] = identity
return tuple(seen.values())
def select_current_futures_contract(
records: Iterable[KisFuturesContractIdentity],
*, underlying_short_code: Optional[str] = None,
underlying_name: Optional[str] = None,
) -> KisFuturesContractIdentity:
candidates = [r for r in records if r.mmsc_cls_code == KIS_CURRENT_MONTH_CODE]
if underlying_short_code is not None:
candidates = [r for r in candidates if r.unas_shrn_iscd == underlying_short_code]
if underlying_name is not None:
candidates = [r for r in candidates if r.unas_kor_name == underlying_name]
if len(candidates) != 1:
raise FuturesContractMasterError(f"CURRENT_FUTURES_NOT_UNIQUE:{len(candidates)}")
return candidates[0]
class KisCurrentFuturesContractSource:
def init(self, records, *, underlying_short_code=None, underlying_name=None):
self._records = tuple(records)
self._underlying_short_code = underlying_short_code
self._underlying_name = underlying_name
def current_contract(self) -> KisFuturesContractIdentity:
return select_current_futures_contract(
self._records,
underlying_short_code=self._underlying_short_code,
underlying_name=self._underlying_name,
)
def with_target(self, *, underlying_short_code: Optional[str] = None, underlying_name: Optional[str] = None) -> "KisCurrentFuturesContractSource":
"""Return a source view using an explicit Application target selector."""
return KisCurrentFuturesContractSource(
self._records,
underlying_short_code=underlying_short_code,
underlying_name=underlying_name,
)

[Child Page] virtual_contract_mapping_contract.md
## 목적
Virtual Scenario와 Replay가 실제 KIS 계약 identity를 추론 없이 명시적으로 참조할 수 있게 하는 최소 configuration/data contract를 정의한다.
이 계약은 새로운 KIS 종목 identity를 생성하지 않는다. 이미 authoritative registry에 존재하는 shrn_iscd만 참조한다.
## 최소 구조
VirtualContractMapping
    - scenario_contract_key: str
    - shrn_iscd: str
### 필드 의미
    - scenario_contract_key: Virtual Scenario 또는 Replay가 거래 대상으로 사용하는 외부 key. Scenario source가 명시적으로 공급한다.
    - shrn_iscd: KIS Option Master registry에 이미 존재하는 authoritative short code reference.
expiry, option_type, strike는 mapping 자체에 중복 저장하지 않는다. 필요 시 registry lookup 결과에서 읽는다.
## 해석 흐름
Scenario/Replay input
→ scenario_contract_key
→ exact mapping lookup
→ shrn_iscd
→ exact authoritative registry lookup
→ KisOptionContractIdentity
→ validation
→ OptionInstrumentIdentity
## Validation
    1. 빈 scenario_contract_key 금지
    1. 빈 shrn_iscd 금지
    1. 동일 scenario_contract_key의 중복 mapping 금지
    1. mapping의 shrn_iscd가 authoritative OptionContractMaster registry에 없으면 fail-closed
    1. strike/type/expiry fallback lookup 금지
    1. registry가 없거나 identity가 검증되지 않으면 Virtual Environment 구성 중단
## Scenario 입력 규칙
Scenario가 계약 단위를 표현하려면 각 거래 대상에 scenario_contract_key를 명시해야 한다.
Replay도 동일 key를 보존하거나 입력 이벤트에 직접 shrn_iscd authoritative reference를 제공할 수 있다. 두 경우 모두 Builder의 역할은 해석과 검증뿐이다.
## 배치 위치
KIS Master identity를 소유하는 core/oms와 Virtual input을 직접 결합하지 않는다.
권장 경계:
    - mapping contract: contracts
    - mapping resolver/validation: application 또는 environment composition
    - authoritative identity registry: core/oms
    - Scenario/Replay source: environments/virtual
## 금지사항
    - scenario_contract_key를 KIS 코드 형식으로 변환하거나 추측하지 않는다.
    - symbol + expiry + strike + option_type 조합으로 shrn_iscd를 찾지 않는다.
    - 임의 KOSPI200_VIRTUAL identity를 생성하지 않는다.
    - mapping에 실제 계약 속성을 복제해 별도 authoritative source로 만들지 않는다.
## 다음 구현 조건
이 계약 자체는 안전하게 구현 가능하지만 실제 mapping 데이터 source가 아직 없다. 다음 단계에서는 기존 Virtual Scenario 입력 형식에 scenario_contract_key를 명시적으로 공급할 수 있는 최소 확장 지점이 있는지 확인한다. 없으면 configuration source를 새로 만들되 실제 KIS 종목코드 값은 authoritative data가 제공될 때까지 포함하지 않는다.

[Child Page] authoritative_option_identity_owner_matrix.md
# Standard instrument_id authoritative owner 후보 대조표
## 목적
Standard OptionInstrumentIdentity.instrument_id의 실제 Production authoritative owner를 확정하기 위한 대조 경계다.
## 최소 공급 계약
    - instrument_id
    - symbol
    - expiry
    - option_type
    - strike
## 후보 대조
<!-- Notion table block -->
| 후보 | 확인 가능한 값 | Standard instrument_id 공급 | 판정 |
| KIS Option Master (fo_idx_code_mts.mst) | shrn_iscd, stnd_iscd, 상품/행사가/월물/만기 정보 | 확인되지 않음 | 사용 불가 |
| KIS Market Data | symbol/shrn_iscd, 가격, expiry 등 | 확인되지 않음 | 사용 불가 |
| KIS Real Broker | SHTN_PDNO/broker symbol 경계 | Standard ID 공급원 아님 | 사용 불가 |
| Virtual/Replay fixture | 테스트용 authoritative ID | Production source 아님 | 사용 불가 |
| 외부 Product/Instrument Master | 실제 owner/record 미확보 | 미확인 | blocker 유지 |
## 금지
    - KIS 식별자를 Standard instrument_id로 변환/승격하지 않는다.
    - synthetic/composite ID를 생성하지 않는다.
    - fixture ID를 Production ID로 사용하지 않는다.
    - Runtime/OMS에서 ID를 추측하거나 생성하지 않는다.
## 승인 조건
실제 owner가 위 5개 값을 authoritative하게 공급하고 있음을 확인한 뒤에만 source-specific adapter를 구현한다. Adapter contract test PASS 전에는 Runtime 통합을 수행하지 않는다.
## 현재 판정
실제 Standard instrument_id owner는 미확정이다. Identity blocker를 유지한다.
## 추가 검증 결과 — KIS 공식 Master 원본 구조
KIS 공식 종목마스터정보(지수선물옵션).h에서 shrn_iscd는 단축코드, stnd_iscd는 표준코드이며 kor_name, atm_cls_code, acpr, mmsc_cls_code, 기초자산 코드/명 등이 별도 필드로 정의된다.
Reference Exp_Detail_1의 shared/contracts/option_master.py도 실제 fo_idx_code_mts.mst를 상품종류 | symbol(shrn_iscd) | standard_code(stnd_iscd) | name 구조로 파싱하고 있다.
이 증거는 KIS Master가 shrn_iscd와 stnd_iscd를 별도 KIS Master 필드로 제공한다는 것은 확정하지만, 이 중 어느 값도 Standard OptionInstrumentIdentity.instrument_id라는 별도 도메인 ID임을 증명하지 않는다.
따라서 KIS Master를 Standard instrument_id owner로 승격하지 않는다.

[Child Page] canonical_order_transport.py
```python
from dataclasses import dataclass
from decimal import Decimal


class CanonicalOrderTransportError(ValueError):
    pass


@dataclass(frozen=True)
class CanonicalOrderTransportInput:
    client_order_id: str
    asset_type: str
    side: str
    quantity: int
    price: Decimal
    option_type: str | None
    strike: Decimal | None
    symbol: str | None
    expiry: str | None
    track_id: str | None
    tag_id: str | None
    instrument_id: str | None


def validate_lossless_transport(request: CanonicalOrderTransportInput) -> None:
    if not request.client_order_id:
        raise CanonicalOrderTransportError("CLIENT_ORDER_ID_REQUIRED")
    if request.quantity <= 0:
        raise CanonicalOrderTransportError("QUANTITY_REQUIRED")
    if request.asset_type not in {"OPTION", "FUTURES"}:
        raise CanonicalOrderTransportError("ASSET_TYPE_REQUIRED")
    if not request.instrument_id:
        raise CanonicalOrderTransportError("AUTHORITATIVE_INSTRUMENT_ID_REQUIRED")

    if request.asset_type == "OPTION":
        if not request.symbol or not request.expiry:
            raise CanonicalOrderTransportError("OPTION_SYMBOL_EXPIRY_REQUIRED")
        if request.option_type not in {"CALL", "PUT"}:
            raise CanonicalOrderTransportError("OPTION_TYPE_REQUIRED")
        if request.strike is None:
            raise CanonicalOrderTransportError("STRIKE_REQUIRED")
```
## 계약 원칙
    - Canonical 실행/추적 필드는 값 자체를 변경하지 않고 운반한다.
    - symbol/expiry/option_type/strike는 실제 upstream identity source가 공급한 값만 사용한다.
    - instrument_id는 authoritative identity에서만 공급하며 이 계층에서 생성하지 않는다.
    - OPTION identity가 불완전하면 fail-closed한다.
    - order_type/order_purpose는 이 transport 계층에서 생성하지 않는다.
    - Reference Runtime의 legacy default/fallback을 Standard identity로 승격하지 않는다.

[Child Page] kis_option_master_identity_contract.md
No.140의 후속 설계. 기존 option_master.py의 만기 조회 기능을 유지하면서 KIS 공식 Master의 상품 식별정보를 shrn_iscd(단축코드)와 stnd_iscd(표준코드)로 분리 보존하고, 이후 Broker의 SHTN_PDNO 공급까지 연결할 수 있는 최소 계약을 정의한다.
## 현재 구현의 문제
현재 parse_kis_fo_idx_mst()는 다음과 같이 Dict[str, str]만 반환한다.
```plain text
symbol -> expiry
standard_code -> expiry
```
이 구조에서는 동일 계약의 symbol/shrn_iscd와 standard_code/stnd_iscd 관계가 사라진다. 또한 두 코드가 모두 동일한 만기 lookup key가 되어 식별자 의미를 구분할 수 없다.
## 설계 원칙
    1. 기존 get_expiry(symbol) / register_contract(symbol, expiry) 의미를 유지한다.
    1. 기존 호출자가 문자열 key를 사용해도 동작하도록 compatibility lookup을 유지한다.
    1. 새로운 identity 레코드에서는 KIS 공식 필드 의미를 명시적으로 분리한다.
    1. shrn_iscd는 KIS Broker 주문상품코드 SHTN_PDNO 공급 후보로 명시한다.
    1. stnd_iscd는 별도 표준코드로 보존하며 SHTN_PDNO로 사용하지 않는다.
    1. expiry/option_type/strike도 같은 계약 레코드에 보존한다.
    1. Broker가 identity를 추측하거나 생성하지 않는다.
    1. synthetic instrument_id를 만들지 않는다.
## 최소 데이터 계약
```python
@dataclass(frozen=True)
class KisOptionContractIdentity:
    shrn_iscd: str
    stnd_iscd: str | None
    expiry: str
    option_type: str | None
    strike: Decimal | None
    info_type: str | None
```
의미:
    - shrn_iscd: KIS Master 단축코드. 주문 경계에서 SHTN_PDNO로 전달할 수 있는 authoritative 후보.
    - stnd_iscd: KIS Master 표준코드. 주문상품코드와 별도 보존.
    - expiry: 기존 만기 조회값.
    - option_type: KIS info_type의 명시적 Call/Put 매핑 결과만 보존. 파싱/매핑할 수 없으면 임의 추론하지 않고 None.
    - strike: Master acpr 원본에서 검증 후 보존. 파싱할 수 없으면 임의 추론하지 않고 None.
    - info_type: KIS Master 원본 코드를 그대로 보존하여 원본 의미를 잃지 않는다.
## Lookup 구조
기존 호환 map과 identity map을 분리한다.
```plain text
_legacy_contracts: Dict[str, str]
    └─ 기존 symbol/standard_code → expiry

_contract_identities: Dict[str, KisOptionContractIdentity]
    └─ shrn_iscd → 전체 authoritative 후보 identity
```
Master load 시 하나의 원본 레코드에서 identity를 먼저 만들고,
_legacy_contracts[shrn_iscd] = expiry를 등록한다. 필요하면 기존 호환성을 위해 stnd_iscd도 expiry alias로 등록하되, identity의 primary key는 반드시 shrn_iscd로 유지한다.
## API 최소 확장
기존 API를 제거하거나 의미를 변경하지 않고 다음을 추가하는 방향으로 설계한다.
```python
def get_contract_identity(self, shrn_iscd: str) -> KisOptionContractIdentity | None:
    ...

def register_contract_identity(
    self,
    identity: KisOptionContractIdentity,
) -> None:
    ...
```
기존:
```python
get_expiry(symbol)
register_contract(symbol, expiry)
```
은 그대로 유지한다.
register_contract()는 identity 전체를 알지 못하는 기존 호출자를 위해 legacy-only 등록으로 남기고, 새 KIS Master loader는 register_contract_identity()를 사용한다.
## info_type → CanonicalOptionType 명시적 매핑 경계
KIS 공식 info_type 의미와 현재 Canonical enum을 대조한 결과:
    - Canonical: CALL, PUT
    - KIS: 5/D/L = Call 계열, 6/E/M = Put 계열
따라서 다음과 같은 KIS Master 전용 adapter 경계에서만 변환한다.
```plain text
KIS raw info_type
    ↓ explicit mapping
CanonicalOptionType.CALL / PUT
```
허용 매핑:
```python
KIS_INFO_TYPE_TO_OPTION_TYPE = {
    "5": CanonicalOptionType.CALL,
    "D": CanonicalOptionType.CALL,
    "L": CanonicalOptionType.CALL,
    "6": CanonicalOptionType.PUT,
    "E": CanonicalOptionType.PUT,
    "M": CanonicalOptionType.PUT,
}
```
주의:
    - 이 매핑은 KIS Master adapter에서만 수행한다.
    - Canonical 자체가 KIS 코드를 알면 안 된다.
    - 미지원 info_type은 매핑하지 않고 fail-closed 또는 None으로 남긴다. 주문 identity를 위해 필요한 경우 None 상태를 허용하지 않고 검증 단계에서 차단한다.
    - info_type의 상품군 차이를 없애기 위해 Call/Put만 남기는 것이 목적이 아니라, 원본 info_type도 identity에 함께 보존한다.
    - shrn_iscd/stnd_iscd 의미는 이 매핑과 무관하며 계속 분리한다.
## Parser 경계
현재 parser의 반환형 Dict[str, str]을 즉시 깨뜨리는 변경은 피한다. 먼저 내부적으로 원본 레코드를 identity로 파싱하는 별도 함수/계층을 설계하고, 기존 parse_kis_fo_idx_mst()는 compatibility wrapper로 유지하는 것이 안전하다.
권장 흐름:
```plain text
raw MST line
  ↓
KisOptionContractIdentity parser
  ↓
identity registry
  ├─ shrn_iscd → identity
  └─ legacy expiry aliases
```
## 중요 보류
현재 remote option_master.py가 실제로 option_type과 strike를 parts[4:]에서 어떻게 안정적으로 읽을지에 대한 고정 필드 위치는 아직 이 단계에서 코드로 확정하지 않는다. KIS Master의 공식 column order와 현재 raw line parser를 추가 대조한 뒤 구현한다.
즉 이번 단계는 데이터 계약 설계 단계이며 원격 코드를 수정하지 않는다.
## 이후 Runtime 연결 조건
```plain text
KIS Master identity
  shrn_iscd
       ↓
verified Instrument Identity
       ↓
CanonicalStrategySignal / Position Logic
       ↓
CanonicalOrderCommand.symbol = verified shrn_iscd
       ↓
Real Broker SHTN_PDNO
```
CanonicalOrderCommand.symbol의 기본값 KOSPI200을 즉시 변경하지 않는다. 실제 Strategy/Position 공급경로가 identity를 전달할 때 fail-closed 검증을 추가하는 것이 다음 후속 단계다.
## No.152 실제 구현 반영
설계 계약을 OptionProject/core/oms/option_master.py에 실제 코드로 반영했다. shrn_iscd를 identity primary key로 사용하고 stnd_iscd는 별도 보존 및 legacy expiry alias로만 사용한다. Standard instrument_id 생성과 stnd_iscd → SHTN_PDNO 변환은 구현하지 않았다.

[Child Page] kis_instrument_identity_minimum_contract.md
# No.140 보강 — KIS 공식 Master 필드 정의 확인
KIS 공식 종목마스터정보(지수선물옵션).h에서 shrn_iscd는 단축코드, stnd_iscd는 표준코드로 별도 정의된다. KIS 공식 domestic_index_future_code.py 역시 fo_idx_code_mts.mst를 상품종류 / 단축코드 / 표준코드 / 한글종목명 / ATM구분 / 행사가 / 월물구분코드 / 기초자산 단축코드 / 기초자산 명으로 정제한다.
따라서 standard_code를 KIS 주문 API의 SHTN_PDNO로 사용하는 것은 금지한다. 주문 API의 SHTN_PDNO는 단축상품번호이므로 Master의 단축코드(shrn_iscd) 측과 연결하는 것이 의미상 올바른 경계다.
현재 프로젝트의 symbol이 실제로 shrn_iscd를 보장하는지는 별도 검증이 필요하다. 따라서 Runtime 코드는 아직 변경하지 않는다.
No.138의 후속으로 KIS Master / Market Data / Runtime / Real Broker 사이에서 실제로 어떤 값이 Instrument Identity 후보로 이동하는지 대조하고, 현재 구조에서 확정 가능한 최소 계약과 미확정 영역을 분리한다.
## 1. KIS Master
shared/contracts/option_master.py의 parse_kis_fo_idx_mst()는 원본 레코드에서 symbol, standard_code, name, prod_type을 읽는다.
현재 구현은 옵션의 symbol과 standard_code를 모두 {code: expiry} lookup key로 저장한다.
중요한 점은 현재 Master의 책임이 만기 조회라는 것이다. standard_code와 symbol의 상품식별 의미를 별도의 InstrumentIdentity 객체로 보존하지 않는다.
## 2. Market Data
option_program/market_data/market_data_adapter.py는 외부 패킷의 symbol / stck_shrn_iscd / shrn_iscd 중 하나를 CanonicalMarketTick.symbol로 전달하고, expiry도 별도로 전달한다.
그러나 이 symbol은 현재 Market Data Adapter에서 KIS Master와의 authoritative identity 일치 검증을 거치지 않는다.
따라서 CanonicalMarketTick.symbol을 자동으로 SHTN_PDNO 또는 Standard instrument_id로 승격할 수 없다.
## 3. Runtime
option_program/runtime/program_runtime.py에서 Strategy signal을 CanonicalStrategySignal로 만들 때 symbol과 expiry를 CanonicalStrategySignal에 보존하지 않는다.
이후 CanonicalOrderCommand 생성에서도 symbol을 명시하지 않는다.
결과적으로 CanonicalOrderCommand.symbol의 기본값 KOSPI200이 유지될 수 있다.
이는 No.137에서 확인한 실제 주문 경계와 연결되어, Real Broker의 SHTN_PDNO가 KOSPI200으로 전달될 수 있는 구조적 단절이다.
## 4. Real Broker
option_program/broker/real_broker_adapter.py의 _map_instrument_code()는 상품코드를 조합하지 않고 CanonicalOrderCommand.symbol을 그대로 KIS SHTN_PDNO에 전달한다.
따라서 Broker는 identity를 해결하는 계층이 아니다. 상위 계층에서 검증된 주문상품코드를 받아야 한다.
또한 현재 execution/open-order/status 조회에는 101V3000 같은 fallback symbol이 존재한다. 이는 authoritative Instrument Identity로 사용할 수 없는 호환/방어값이다.
## 5. KIS 공식 API 대조
KIS 공식 Open Trading API의 국내선물옵션 주문 계약은 SHTN_PDNO를 필수 단축상품번호로 정의하며 선물 6자리, 옵션 9자리 예시를 제공한다.
공식 예제의 주문 payload도 SHTN_PDNO를 직접 사용한다.
따라서 현재 프로젝트에서 CanonicalOrderCommand.symbol은 단순 내부 symbol이 아니라 실제 Broker 경계에서는 검증된 KIS 단축상품번호 역할을 해야 한다.
다만 KIS MST의 standard_code와 주문 API SHTN_PDNO가 동일 필드라는 직접적인 공식 매핑은 여전히 확보되지 않았다.
## 최소 계약
현재 단계에서 확정할 수 있는 최소 계약은 다음과 같다.
```plain text
Authoritative Contract/Product Master
    ↓
Instrument Identity Candidate
    ├─ broker_product_code (KIS SHTN_PDNO 후보)
    ├─ symbol
    ├─ expiry
    ├─ option_type
    └─ strike
    ↓
Identity validation / verified mapping
    ↓
Canonical Signal / Position Logic
    ↓
Canonical Order Command
    ↓
Real Broker passthrough → SHTN_PDNO
```
## 금지사항
    - KOSPI200을 실제 KIS SHTN_PDNO로 사용하지 않는다.
    - 101V3000 등의 fallback을 authoritative identity로 사용하지 않는다.
    - standard_code를 확인 없이 instrument_id 또는 SHTN_PDNO라고 이름만 바꾸지 않는다.
    - symbol + expiry + strike + option_type을 조합해 synthetic instrument_id를 만들지 않는다.
    - Broker Adapter에서 identity를 추측하거나 생성하지 않는다.
    - Market Data의 symbol을 검증 없이 주문상품코드로 승격하지 않는다.
## 다음 단계
KIS Master 원본의 실제 레코드 필드 정의를 확인할 수 있는 공식 자료 또는 프로젝트에 이미 저장된 원본/샘플을 확보하여 symbol, standard_code, SHTN_PDNO의 1:1 관계를 증명한다. 그 증거가 확보되기 전에는 Runtime Canonical 계약을 변경하지 않는다.

[Child Page] kis_instrument_identity_supply.md
## 목적
KIS 실전 브로커 주문 계층에서 사용하는 종목 식별자 공급 경계를 정리한다.
## 실제 Exp_Detail_1 대조 결과
    - shared/contracts/option_master.py는 KIS 공식 fo_idx_code_mts.mst.zip을 다운로드하고 파싱한다.
    - 원본 MST 파싱 단계에서 symbol과 standard_code를 모두 읽는다.
    - 그러나 현재 Master 구현은 최종적으로 {symbol: expiry}와 {standard_code: expiry} 형태의 만기 조회 정보만 보존한다.
    - 따라서 현재 OptionContractMaster는 만기일 공급원이지, instrument_id를 포함한 완전한 Standard Instrument Identity 공급원으로 사용할 수 없다.
    - option_program/broker/real_broker_adapter.py의 _map_instrument_code()는 CanonicalOrderCommand.symbol을 KIS SHTN_PDNO로 그대로 전달한다.
    - 현재 program_runtime.py에서 CanonicalOrderCommand를 만들 때 symbol을 명시하지 않으므로 Canonical 기본값 KOSPI200이 그대로 남을 수 있다.
    - 결과적으로 현재 경로는 실제 KIS 상품코드가 명시적으로 공급되지 않은 주문이 SHTN_PDNO=KOSPI200으로 전달될 위험이 있다.
## 안전한 Standard 연결 기준
```plain text
KIS 공식 Contract/Product Master
        ↓
검증된 Instrument Identity
        ↓
Strategy Signal / Position Logic
        ↓
OptionIdentityResolver
        ↓
OrderIntentFactory
        ↓
Environment / Broker
```
## 금지
    - symbol + expiry + strike + option_type 임의 조합으로 상품코드 생성 금지
    - KOSPI200을 실제 KIS 상품코드로 간주 금지
    - Market Tick의 symbol을 검증 없이 Contract Master ID로 승격 금지
    - standard_code의 의미를 공식 계약 확인 없이 instrument_id로 단정 금지
## 다음 연결 조건
KIS MST의 standard_code가 실제 주문용 SHTN_PDNO인지 공식 계약/실제 데이터 구조로 확인한 뒤, 그 값과 symbol, expiry, option_type, strike의 관계를 완전한 Instrument Identity 공급계약으로 확정한다.
그 전까지 OrderIntentFactory의 instrument identity 연결은 보류한다.

[Child Page] futures_execution_symbol_source.py
```python
"""Authoritative KIS FUTURES execution/Risk symbol projection."""
from __future__ import annotations

from contracts.futures_contract_master import KisCurrentFuturesContractSource
from application.composition.futures_contract_target_resolver import resolve_current_futures_contract
from application.composition.futures_target_configuration import FuturesTargetConfiguration


class FuturesExecutionSymbolSourceError(ValueError):
    pass


class KisFuturesExecutionSymbolSource:
    """Expose the selected KIS short product code without creating Standard identity."""

    def __init__(
        self,
        source: KisCurrentFuturesContractSource,
        target: FuturesTargetConfiguration,
    ) -> None:
        self._source = source
        self._target = target

    def current_symbol(self) -> str:
        contract = resolve_current_futures_contract(
            source=self._source,
            target=self._target,
        )
        symbol = contract.shrn_iscd.strip()
        if not symbol:
            raise FuturesExecutionSymbolSourceError("FUTURES_EXECUTION_SYMBOL_REQUIRED")
        return symbol
```
## 책임 경계
    - 입력은 검증된 KIS KisFuturesContractIdentity 공급원과 Application target configuration이다.
    - current_symbol()은 선택된 record의 shrn_iscd를 그대로 반환한다.
    - shrn_iscd를 instrument_id로 승격하지 않는다.
    - stnd_iscd를 주문/실행 코드로 사용하지 않는다.
    - KOSPI200/U200 또는 기타 broker code 상수를 생성하지 않는다.
    - 주문을 직접 제출하지 않고 Market subscription / Risk / Broker execution routing이 소비할 authoritative execution symbol만 제공한다.
## 연결 경로
KIS Master → KisFuturesContractIdentity → FuturesTargetConfiguration → resolve_current_futures_contract() → KisFuturesExecutionSymbolSource.current_symbol()
Standard instrument_id 공급 owner가 확보되기 전까지 FuturesIdentitySourcePort의 instrument_id는 임의 생성하지 않는다.

[Child Page] kis_index_futures_market_ws_adapter.py
```python
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


class KISIndexFuturesWebSocketAdapterInvalid(ValueError):
    """Raised when a KIS index-futures realtime frame cannot be adapted safely."""


@dataclass(frozen=True)
class KisIndexFuturesMarketObservation:
    shrn_iscd: str
    observed_hour: str
    price: Decimal | None
    volume: Decimal | None
    ask_price: Decimal | None
    bid_price: Decimal | None
    source: str


_H0IFCNT0 = "H0IFCNT0"
_H0IFASP0 = "H0IFASP0"

# H0IFCNT0: symbol, time, current price, accumulated volume, ask1, bid1
_TRADE_SYMBOL = 0
_TRADE_TIME = 1
_TRADE_PRICE = 5
_TRADE_VOLUME = 10
_TRADE_ASK1 = 35
_TRADE_BID1 = 36

# H0IFASP0: symbol, time, ask1, bid1
_QUOTE_SYMBOL = 0
_QUOTE_TIME = 1
_QUOTE_ASK1 = 2
_QUOTE_BID1 = 7


def _decode_fields(frame: str, expected_tr_id: str) -> list[str]:
    parts = frame.split("|")
    if len(parts) < 4 or parts[0] not in {"0", "1"}:
        raise KISIndexFuturesWebSocketAdapterInvalid("invalid KIS realtime frame envelope")
    if parts[1] != expected_tr_id:
        raise KISIndexFuturesWebSocketAdapterInvalid("unexpected KIS TR ID")
    try:
        field_count = int(parts[2])
    except ValueError as exc:
        raise KISIndexFuturesWebSocketAdapterInvalid("invalid KIS field count") from exc
    values = parts[3].split("^")
    if field_count != len(values):
        raise KISIndexFuturesWebSocketAdapterInvalid("KIS field count mismatch")
    return values


class KISIndexFuturesMarketWebSocketAdapter:
    """Adapt official KIS index-futures trade/quote frames into typed observations."""

    TRADE_TR_ID = _H0IFCNT0
    QUOTE_TR_ID = _H0IFASP0

    def adapt(self, frame: str, *, source: str | None = None) -> KisIndexFuturesMarketObservation:
        parts = frame.split("|")
        if len(parts) < 2:
            raise KISIndexFuturesWebSocketAdapterInvalid("invalid KIS realtime frame")
        if parts[1] == self.TRADE_TR_ID:
            return self._adapt_trade(frame, source=source or "KIS:H0IFCNT0")
        if parts[1] == self.QUOTE_TR_ID:
            return self._adapt_quote(frame, source=source or "KIS:H0IFASP0")
        raise KISIndexFuturesWebSocketAdapterInvalid("unsupported KIS index-futures TR ID")

    def _adapt_trade(self, frame: str, *, source: str) -> KisIndexFuturesMarketObservation:
        values = _decode_fields(frame, self.TRADE_TR_ID)
        required_max = max(_TRADE_SYMBOL, _TRADE_TIME, _TRADE_PRICE, _TRADE_VOLUME, _TRADE_ASK1, _TRADE_BID1)
        if len(values) <= required_max:
            raise KISIndexFuturesWebSocketAdapterInvalid("KIS H0IFCNT0 payload is incomplete")
        symbol = values[_TRADE_SYMBOL].strip()
        if not symbol:
            raise KISIndexFuturesWebSocketAdapterInvalid("KIS futures short code is missing")
        try:
            return KisIndexFuturesMarketObservation(
                shrn_iscd=symbol,
                observed_hour=values[_TRADE_TIME].strip(),
                price=Decimal(values[_TRADE_PRICE]),
                volume=Decimal(values[_TRADE_VOLUME]),
                ask_price=Decimal(values[_TRADE_ASK1]),
                bid_price=Decimal(values[_TRADE_BID1]),
                source=source,
            )
        except Exception as exc:
            raise KISIndexFuturesWebSocketAdapterInvalid("invalid H0IFCNT0 numeric field") from exc

    def _adapt_quote(self, frame: str, *, source: str) -> KisIndexFuturesMarketObservation:
        values = _decode_fields(frame, self.QUOTE_TR_ID)
        required_max = max(_QUOTE_SYMBOL, _QUOTE_TIME, _QUOTE_ASK1, _QUOTE_BID1)
        if len(values) <= required_max:
            raise KISIndexFuturesWebSocketAdapterInvalid("KIS H0IFASP0 payload is incomplete")
        symbol = values[_QUOTE_SYMBOL].strip()
        if not symbol:
            raise KISIndexFuturesWebSocketAdapterInvalid("KIS futures short code is missing")
        try:
            return KisIndexFuturesMarketObservation(
                shrn_iscd=symbol,
                observed_hour=values[_QUOTE_TIME].strip(),
                price=None,
                volume=None,
                ask_price=Decimal(values[_QUOTE_ASK1]),
                bid_price=Decimal(values[_QUOTE_BID1]),
                source=source,
            )
        except Exception as exc:
            raise KISIndexFuturesWebSocketAdapterInvalid("invalid H0IFASP0 numeric field") from exc
```
## 책임 경계
    - KIS 공식 H0IFCNT0 지수선물 실시간체결과 H0IFASP0 실시간호가 wire frame을 처리한다.
    - futs_shrn_iscd는 KIS shrn_iscd 원문을 보존한다.
    - 체결 frame은 현재가/누적거래량/1호가를, 호가 frame은 1호가를 원문 위치에서 직접 추출한다.
    - shrn_iscd를 Standard instrument_id로 승격하지 않는다.
    - 실제 socket/approval key/subscription/reconnect는 별도 transport owner가 담당한다.
    - VTS/Paper가 지수선물 실시간을 지원한다고 가정하지 않는다.

[Child Page] order_ack.py
```python
from contracts.types import BrokerOrderResponse, OrderAckEvent


class OrderAckBoundaryError(ValueError):
    """Raised when a broker ACK cannot be converted safely."""


def to_order_ack_event(response: BrokerOrderResponse) -> OrderAckEvent:
    """Convert transport ACK into a canonical ACK event without inventing execution data."""
    if not response.client_order_id:
        raise OrderAckBoundaryError("CLIENT_ORDER_ID_REQUIRED")
    if response.accepted and not response.broker_order_id:
        raise OrderAckBoundaryError("BROKER_ORDER_ID_REQUIRED_FOR_ACCEPTED_ACK")

    return OrderAckEvent(
        client_order_id=response.client_order_id,
        accepted=response.accepted,
        broker_order_id=response.broker_order_id,
        broker_code=response.broker_code,
        message=response.message,
    )


__all__ = ("OrderAckBoundaryError", "to_order_ack_event")
```
## Boundary contract
    - BrokerOrderResponse는 broker transport가 반환하는 ACK/result다.
    - OrderAckEvent는 OMS가 주문 접수 결과를 기록하기 위한 canonical ACK event다.
    - accepted=True이면 broker order id가 반드시 있어야 한다.
    - accepted=False는 reject/failure ACK로 전달하며 broker order id는 선택 사항이다.
    - ACK에는 체결수량, 체결가격, execution id를 추가하지 않는다.
    - ACK는 ExecutionReport로 변환되지 않는다.
    - 실제 체결은 별도 ExecutionProvider의 execution inquiry/realtime fill source에서 ExecutionReport로 생성한다.
    - client_order_id는 transport 응답과 ACK event 사이에서 변경하지 않는다.