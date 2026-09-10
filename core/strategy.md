## Strategy Registry 검증 기준

```python
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from core.domain.market_models import MarketState
from core.strategy.contracts import CommonStrategyInput, StrategyInput, StrategyContext
from core.strategy.registry import StrategyRegistry

@dataclass(frozen=True)
class DummyPayload:
    strategy_id: str


def context(strategy_id: str, payload_id: str | None = None) -> StrategyContext:
    payload = DummyPayload(payload_id or strategy_id) if payload_id is not None else None
    strategy_input = None
    if payload is not None:
        strategy_input = StrategyInput(
            common=CommonStrategyInput(as_of=datetime(2026, 1, 1)),
            payload=payload,
        )
    return StrategyContext(
        market_state=MarketState(as_of=datetime(2026, 1, 1), ticks={}, quality={}),
        strategy_id=strategy_id,
        input=strategy_input,
    )


def test_payload_strategy_id_must_match_context():
    registry = StrategyRegistry()
    try:
        registry.validate_context(context("track1", "track2"))
    except ValueError:
        return
    raise AssertionError("mismatched strategy payload must be rejected")


def test_missing_input_is_not_fabricated():
    registry = StrategyRegistry()
    registry.validate_context(context("track1"))


def test_duplicate_strategy_identity_is_rejected():
    class DummyStrategy:
        strategy_id = "track1"
        version = "1"

    registry = StrategyRegistry()
    registry.register(DummyStrategy())
    try:
        registry.register(DummyStrategy())
    except ValueError:
        return
    raise AssertionError("duplicate strategy identity must be rejected")
```

### 검증 항목

1. 정상 payload/context ID 일치

1. payload/context ID 불일치 → 즉시 ValueError

1. input=None → synthetic input 생성 없이 허용

1. 동일 (strategy_id, version) 재등록 → ValueError

1. Registry가 Broker/OrderRequest/VMS/VSSF/UI를 호출하지 않는지 정적 검토

이 테스트는 실제 9개 전략의 동작 테스트가 아니라 공통 Contract/Registry 경계 테스트다. 실제 원격 Git 브랜치에는 쓰지 않는다.

[Child Page] contracts.py
```python
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, Sequence

from contracts.types import OptionInstrumentIdentity
from core.domain.market_models import MarketState


@dataclass(frozen=True)
class CommonStrategyInput:
    """Only values whose meaning and unit are shared by multiple strategies."""

    as_of: datetime
    current_price: Decimal | None = None
    active_vol: Decimal | None = None
    base_vol: Decimal | None = None
    budget: Decimal | None = None
    current_pnl: Decimal | None = None
    total_fees: Decimal | None = None
    time_str: str | None = None
    date_str: str | None = None


class StrategyPayload(Protocol):
    """Marker contract for strategy-specific, typed input payloads.

    Strategy identity is authoritative in StrategyContext. Individual typed
    payloads may additionally expose strategy_id, but the field is not required
    because some strategy contracts intentionally carry no identity field.
    """


@dataclass(frozen=True)
class StrategyInput:
    common: CommonStrategyInput
    payload: StrategyPayload


@dataclass(frozen=True)
class StrategyContext:
    market_state: MarketState
    strategy_id: str
    input: StrategyInput | None = None


@dataclass(frozen=True)
class Signal:
    strategy_id: str
    direction: str  # LONG / SHORT / FLAT
    confidence: float
    reason: str
    instrument_identity: OptionInstrumentIdentity | None = None

    # Strategy may express an option selection without replacing authoritative
    # market/master symbol or expiry.
    option_type_override: str | None = None
    strike_override: Decimal | None = None
    execution_proposal: "StrategyExecutionProposal | None" = None


class Strategy(Protocol):
    strategy_id: str
    version: str

    def initialize(self, context: StrategyContext) -> None: ...
    def on_market_state(self, context: StrategyContext) -> None: ...
    def evaluate(self, context: StrategyContext) -> Sequence[Signal]: ...
    def reset(self) -> None: ...
```
### Contract rules
    - StrategyContext.input is the only standardized strategy-input entry point.
    - input=None is retained temporarily for backward compatibility while Track1~9 are migrated; new Runtime wiring must provide StrategyInput.
    - Common fields are optional unless their semantic meaning and unit are confirmed for the strategy.
    - Strategy-specific values belong in a typed payload; they are not added as arbitrary trackN_input attributes on StrategyContext.
    - Missing real input must not be replaced with synthetic defaults.
    - Strategy returns Signal; order creation, broker calls, execution pricing, IOC/fallback and tranche execution remain outside Core Strategy.
    - Signal.instrument_identity carries resolved authoritative option context when an instrument is already selected. A strategy may use option_type_override / strike_override to express order intent, but must not synthesize or replace authoritative symbol/expiry.
    - A later OMS/Order boundary resolves instrument_identity + explicit overrides into the immutable identity attached to OrderIntent.
    - The contract intentionally does not import OrderRequest, ExecutionReport, Broker, VMS, VSSF or UI.
    - If a typed payload exposes strategy_id, the Registry checks it against StrategyContext.strategy_id.
    - StrategyContext.strategy_id remains the authoritative identity boundary for payloads that do not expose strategy_id.
The nine baseline strategies must implement this contract after discovery; no production placeholder strategy is invented.

[Child Page] registry.py
```python
from typing import Dict, Tuple

from core.strategy.contracts import Strategy, StrategyContext


class StrategyRegistry:
    """Registry keyed by immutable strategy identity (id, version)."""

    def __init__(self) -> None:
        self._strategies: Dict[Tuple[str, str], Strategy] = {}

    def register(self, strategy: Strategy) -> None:
        key = (strategy.strategy_id, strategy.version)
        if key in self._strategies:
            raise ValueError(f"duplicate strategy: {key}")
        self._strategies[key] = strategy

    def get(self, strategy_id: str, version: str) -> Strategy:
        try:
            return self._strategies[(strategy_id, version)]
        except KeyError as exc:
            raise KeyError(f"strategy not registered: {(strategy_id, version)}") from exc

    def validate_context(self, context: StrategyContext) -> None:
        if context.input is None:
            return
        payload_strategy_id = getattr(context.input.payload, "strategy_id", None)
        if payload_strategy_id is not None and payload_strategy_id != context.strategy_id:
            raise ValueError(
                "strategy input payload mismatch: "
                f"context={context.strategy_id!r}, payload={payload_strategy_id!r}"
            )

    def prepare(self, strategy_id: str, version: str, context: StrategyContext) -> Strategy:
        if context.strategy_id != strategy_id:
            raise ValueError(
                "strategy context mismatch: "
                f"context={context.strategy_id!r}, requested={strategy_id!r}"
            )
        self.validate_context(context)
        return self.get(strategy_id, version)
```
### Registry boundary
    - Registry remains environment-neutral.
    - Registration identity remains (strategy_id, version).
    - When a supplied payload exposes strategy_id, its identity must match StrategyContext.strategy_id; payloads without that field use StrategyContext.strategy_id as the authoritative identity.
    - Missing input is not fabricated.
    - Registry does not create orders or call Broker/VMS/VSSF/UI.
    - Duplicate registration remains rejected.

[Child Page] standard_registry.py
```python
"""Standard Option Core registry manifest.

The manifest owns immutable strategy identities and registration order.
(strategy_id, version) is the registry identity and must not be reconstructed
by callers with a hard-coded version.
"""

from core.strategy.registry import StrategyRegistry
from core.strategy.track1_tail_defense import Track1TailDefense
from core.strategy.track2_asymmetric_trap import Track2AsymmetricTrap
from core.strategy.track3_statistical_arbitrage import Track3StatisticalArbitrage
from core.strategy.track4_gamma_scalping import Track4GammaScalping
from core.strategy.track5_gap_divergence import Track5GapDivergence
from core.strategy.track6_daily_tail_insurance import Track6DailyTailInsurance
from core.strategy.track7_volatility_skew_weekly_insurance import Track7VolatilitySkewWeeklyInsurance
from core.strategy.track8_macro_regime_monthly_strangle import Track8MacroRegimeMonthlyStrangle
from core.strategy.track9_event_overnight_insurance import Track9EventOvernightInsurance


STANDARD_STRATEGY_TYPES = (
    Track1TailDefense,
    Track2AsymmetricTrap,
    Track3StatisticalArbitrage,
    Track4GammaScalping,
    Track5GapDivergence,
    Track6DailyTailInsurance,
    Track7VolatilitySkewWeeklyInsurance,
    Track8MacroRegimeMonthlyStrangle,
    Track9EventOvernightInsurance,
)

STANDARD_STRATEGY_KEYS = tuple(
    (strategy_type.strategy_id, strategy_type.version)
    for strategy_type in STANDARD_STRATEGY_TYPES
)

STANDARD_STRATEGY_IDS = tuple(
    strategy_id for strategy_id, _ in STANDARD_STRATEGY_KEYS
)


def build_standard_strategy_registry() -> StrategyRegistry:
    registry = StrategyRegistry()
    for strategy_type in STANDARD_STRATEGY_TYPES:
        registry.register(strategy_type())
    return registry
```
## 변경 이유
기존 STANDARD_STRATEGY_IDS만으로는 Registry의 실제 immutable identity인 (strategy_id, version) 전체를 표현할 수 없다.
특히 Track1의 version이 1.1.0인 상태에서 호출자가 모든 Strategy version을 "1.0"으로 가정하면 Registry 조회 계약이 깨진다.
STANDARD_STRATEGY_KEYS를 유일한 identity manifest로 두고:
    - Registry 등록 순서
    - Orchestrator 실행 순서
    - Test 조회 key
를 동일 source에서 사용한다.
STANDARD_STRATEGY_IDS는 UI 표시나 Strategy 선택 등 ID만 필요한 하위 호환 용도로 유지한다.

[Child Page] orchestrator.py
```python
"""Environment-neutral lifecycle orchestrator for registered strategies."""

from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, Sequence, Tuple

from core.strategy.contracts import Signal, StrategyContext
from core.strategy.registry import StrategyRegistry


StrategyKey = Tuple[str, str]


@dataclass(frozen=True)
class StrategyRunFailure:
    strategy_id: str
    version: str
    stage: str
    error_type: str
    message: str


@dataclass(frozen=True)
class StrategyRunResult:
    signals: Tuple[Signal, ...]
    failures: Tuple[StrategyRunFailure, ...]


class StrategyOrchestrator:
    """Runs the standard Strategy lifecycle without Runtime/Broker/UI dependency."""

    def __init__(
        self,
        registry: StrategyRegistry,
        strategy_keys: Iterable[StrategyKey],
    ) -> None:
        self._registry = registry
        self._strategy_keys = tuple(strategy_keys)
        self._enabled: Dict[StrategyKey, bool] = {
            key: True for key in self._strategy_keys
        }
        self._initialized: set[StrategyKey] = set()

    def set_enabled(
        self,
        strategy_id: str,
        version: str,
        enabled: bool,
    ) -> None:
        key = (strategy_id, version)
        if key not in self._enabled:
            raise KeyError(f"strategy not managed: {key}")
        self._enabled[key] = enabled

    def is_enabled(self, strategy_id: str, version: str) -> bool:
        return self._enabled[(strategy_id, version)]

    def reset(self) -> None:
        for strategy_id, version in self._strategy_keys:
            strategy = self._registry.get(strategy_id, version)
            strategy.reset()
        self._initialized.clear()

    def run(
        self,
        contexts: Mapping[str, StrategyContext],
        selected: Iterable[StrategyKey] | None = None,
    ) -> StrategyRunResult:
        keys = tuple(selected) if selected is not None else self._strategy_keys
        signals: list[Signal] = []
        failures: list[StrategyRunFailure] = []

        for strategy_id, version in keys:
            key = (strategy_id, version)
            if key not in self._enabled:
                raise KeyError(f"strategy not managed: {key}")
            if not self._enabled[key]:
                continue

            context = contexts.get(strategy_id)
            if context is None:
                failures.append(
                    StrategyRunFailure(
                        strategy_id,
                        version,
                        "context",
                        "KeyError",
                        "strategy context not supplied",
                    )
                )
                continue

            try:
                strategy = self._registry.prepare(
                    strategy_id,
                    version,
                    context,
                )
            except Exception as exc:
                failures.append(
                    StrategyRunFailure(
                        strategy_id,
                        version,
                        "prepare",
                        type(exc).__name__,
                        str(exc),
                    )
                )
                continue

            if key not in self._initialized:
                try:
                    strategy.initialize(context)
                    self._initialized.add(key)
                except Exception as exc:
                    failures.append(
                        StrategyRunFailure(
                            strategy_id,
                            version,
                            "initialize",
                            type(exc).__name__,
                            str(exc),
                        )
                    )
                    continue

            try:
                strategy.on_market_state(context)
            except Exception as exc:
                failures.append(
                    StrategyRunFailure(
                        strategy_id,
                        version,
                        "on_market_state",
                        type(exc).__name__,
                        str(exc),
                    )
                )
                continue

            try:
                produced = strategy.evaluate(context)
                signals.extend(tuple(produced))
            except Exception as exc:
                failures.append(
                    StrategyRunFailure(
                        strategy_id,
                        version,
                        "evaluate",
                        type(exc).__name__,
                        str(exc),
                    )
                )

        return StrategyRunResult(
            signals=tuple(signals),
            failures=tuple(failures),
        )
```
## 책임
    - Registry에 등록된 Strategy만 실행
    - enabled filtering
    - initialize 1회 → on_market_state → evaluate 순서 보장
    - StrategyContext ID/payload 검증은 기존 Registry.prepare를 재사용
    - Signal만 수집
    - Strategy 단위 실패 격리 및 실패 정보 반환
## 비책임
    - Decision/Risk/Position/Order Intent
    - Broker/API/VMS/VSSF/UI/Runtime
    - Track별 직접 분기
    - 주문 실행
## 상태 원칙
    - Orchestrator는 Strategy 인스턴스를 생성하거나 공유하지 않는다.
    - Registry가 제공한 인스턴스의 lifecycle만 관리한다.
    - Registry를 새로 build하면 기존 Strategy 상태와 공유되지 않는다.
[Child Page] canonical_signal_adapter_draft_superseded.py
```python
from dataclasses import dataclass
from typing import Optional

from contracts.types import OptionInstrumentIdentity
from core.strategy.contracts import Signal
from shared.contracts.canonical import (
    CanonicalAssetType,
    CanonicalOrderSide,
    CanonicalOptionType,
    CanonicalStrategySignal,
)


@dataclass(frozen=True)
class RuntimeSignalContext:
    """Authoritative values supplied by Runtime/Controller, not Strategy."""

    signal_id: str
    track_id: str
    price: float
    timestamp: str


def _require_non_empty(value: str, field_name: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise ValueError(f"{field_name}_REQUIRED")
    return value


def signal_to_canonical(
    signal: Signal,
    runtime: RuntimeSignalContext,
) -> CanonicalStrategySignal:
    """Convert Standard Signal only from authoritative supplied values.

    No signal_id/track_id/default qty/side/asset/price/option identity is inferred.
    """
    signal_id = _require_non_empty(runtime.signal_id, "SIGNAL_ID")
    track_id = _require_non_empty(runtime.track_id, "TRACK_ID")
    proposal = signal.execution_proposal
    if proposal is None:
        raise ValueError("EXECUTION_PROPOSAL_REQUIRED")

    if proposal.proposed_quantity <= 0:
        raise ValueError("QTY_REQUIRED")
    if not proposal.asset_type:
        raise ValueError("ASSET_TYPE_REQUIRED")
    if not proposal.side:
        raise ValueError("SIDE_REQUIRED")

    asset_type = CanonicalAssetType(str(proposal.asset_type))
    side = CanonicalOrderSide(str(proposal.side))

    identity: Optional[OptionInstrumentIdentity] = signal.instrument_identity
    option_type: Optional[CanonicalOptionType] = None
    strike = 0.0
    symbol = ""
    expiry = ""

    if asset_type == CanonicalAssetType.OPTION:
        if identity is None:
            raise ValueError("OPTION_IDENTITY_REQUIRED")
        if not identity.instrument_id or not identity.symbol or not identity.expiry:
            raise ValueError("OPTION_IDENTITY_INCOMPLETE")
        if identity.option_type is None or identity.strike is None:
            raise ValueError("OPTION_IDENTITY_INCOMPLETE")

        if proposal.option_type is not None and str(proposal.option_type) != str(identity.option_type):
            raise ValueError("OPTION_TYPE_IDENTITY_MISMATCH")
        if proposal.strike is not None and proposal.strike != identity.strike:
            raise ValueError("STRIKE_IDENTITY_MISMATCH")

        option_type = CanonicalOptionType(str(identity.option_type))
        strike = float(identity.strike)
        symbol = identity.symbol
        expiry = identity.expiry

    return CanonicalStrategySignal(
        signal_id=signal_id,
        track_id=track_id,
        asset_type=asset_type,
        side=side,
        qty=proposal.proposed_quantity,
        price=float(runtime.price),
        option_type=option_type,
        strike=strike,
        tag_id=str(proposal.tag_id) if proposal.tag_id is not None else "",
        reason=signal.reason,
        timestamp=runtime.timestamp,
        symbol=symbol,
        expiry=expiry,
    )
```
## 계약 규칙
        - signal_id는 Runtime/Controller가 공급한다. Adapter는 생성하지 않는다.
        - track_id도 Runtime/Controller가 명시 공급한다. strategy_id로 대체하지 않는다.
        - qty, asset_type, side는 StrategyExecutionProposal의 실제 값만 사용한다.
        - price와 timestamp는 Runtime/Controller가 공급한다. Adapter가 Strategy/MarketState에서 추론하지 않는다.
        - OPTION은 Signal.instrument_identity가 없거나 불완전하면 fail-closed 한다.
        - Proposal의 option_type/strike가 존재하면 authoritative identity와 동일한 경우만 보존한다. 불일치 시 fail-closed 한다.
        - FUTURES는 OptionInstrumentIdentity를 요구하지 않으며 option_type/strike는 비적용값으로 유지한다.
        - tag_id가 없는 경우 빈 문자열은 '미지정'의 구조적 표현이며 전략명 등으로 합성하지 않는다.
        - Adapter는 입력 Signal 또는 CanonicalStrategySignal을 변경하지 않는다.
## 적용 범위
현재는 최소 계약과 범용 변환 함수만 정의한다. Track1은 authoritative OptionInstrumentIdentity가 별도로 공급되지 않는 현재 상태에서는 변환을 성공시키지 않는다. Track4는 Futures Proposal과 RuntimeSignalContext가 모두 공급되면 변환 대상이 될 수 있다.
[Child Page] runtime_strategy_to_decision_adapter.py
```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from application.composition.runtime_strategy_result_collection_adapter import (
    RuntimeStrategyEvaluation,
)
from contracts.types import OptionInstrumentIdentity
from core.decision.decision_arbiter import ArbitrationResult, DecisionArbiter
from core.strategy.canonical_signal_adapter import (
    RuntimeSignalContext,
    signal_to_canonical,
)
from shared.contracts.canonical import CanonicalStrategySignal


InstrumentIdentityProvider = Callable[[RuntimeStrategyEvaluation], OptionInstrumentIdentity | None]


@dataclass(frozen=True)
class RuntimeDecisionResult:
    canonical_signals: tuple[CanonicalStrategySignal, ...]
    arbitration: ArbitrationResult


class RuntimeStrategyToDecisionAdapter:
    """Connect Runtime-owned Strategy evaluations to existing Canonical→Decision seam.

    RuntimeExecutionContext is the authoritative source for deterministic IDs.
    This adapter does not invent price, instrument identity, quantity, side, or
    execution semantics.
    """

    def __init__(self, arbiter: DecisionArbiter) -> None:
        self._arbiter = arbiter

    def arbitrate(
        self,
        evaluations: Iterable[RuntimeStrategyEvaluation],
        *,
        price: float,
        timestamp: str,
        account: Any,
        instrument_identity_provider: InstrumentIdentityProvider | None = None,
    ) -> RuntimeDecisionResult:
        canonical_signals: list[CanonicalStrategySignal] = []
        seen_signal_ids: set[str] = set()

        for evaluation in evaluations:
            signal = evaluation.result
            track_id = str(getattr(evaluation.context, "strategy_id", "") or "").strip()
            if not track_id:
                raise ValueError("RUNTIME_TRACK_ID_REQUIRED")

            signal_id = evaluation.runtime_context.signal_id(track_id)
            if signal_id in seen_signal_ids:
                raise ValueError("RUNTIME_DUPLICATE_SIGNAL_ID")
            seen_signal_ids.add(signal_id)

            identity = (
                instrument_identity_provider(evaluation)
                if instrument_identity_provider is not None
                else None
            )
            canonical_signals.append(
                signal_to_canonical(
                    signal,
                    RuntimeSignalContext(
                        signal_id=signal_id,
                        track_id=track_id,
                        price=price,
                        timestamp=timestamp,
                    ),
                    instrument_identity=identity,
                )
            )

        arbitration = self._arbiter.arbitrate(canonical_signals, account)
        return RuntimeDecisionResult(
            canonical_signals=tuple(canonical_signals),
            arbitration=arbitration,
        )
```
## 책임
        - RuntimeStrategyEvaluation.runtime_context에서 deterministic signal_id를 파생한다.
        - 기존 signal_to_canonical()과 DecisionArbiter를 그대로 재사용한다.
        - price는 Runtime 입력으로 명시 공급하며 requested_price로 대체하지 않는다.
        - OPTION identity는 provider가 authoritative 값만 공급하며 누락 시 기존 adapter에서 fail-closed한다.
        - qty/side/asset_type는 StrategyExecutionProposal 값을 보존한다.
        - order_type/order_purpose/client_order_id는 이 단계에서 생성하지 않는다.
        - Risk/Order 실행은 별도 기존 No.335~337 seam으로 유지한다.
[Child Page] runtime_decision_command_adapter.py
```python
from __future__ import annotations

from typing import Iterable

from application.composition.runtime_strategy_result_collection_adapter import (
    RuntimeStrategyEvaluation,
)
from core.runtime.reference_execution_pipeline import (
    DecisionCommandContext,
    approved_signal_to_command,
)
from shared.contracts.canonical import CanonicalOrderCommand, CanonicalStrategySignal


class RuntimeDecisionCommandAdapter:
    """Transport approved signals to CanonicalOrderCommand using Runtime-owned IDs."""

    def build_commands(
        self,
        evaluations: Iterable[RuntimeStrategyEvaluation],
        approved_signals: Iterable[CanonicalStrategySignal],
    ) -> tuple[CanonicalOrderCommand, ...]:
        contexts: dict[str, RuntimeStrategyEvaluation] = {}
        for evaluation in evaluations:
            track_id = str(getattr(evaluation.context, "strategy_id", "") or "").strip()
            if not track_id:
                raise ValueError("RUNTIME_TRACK_ID_REQUIRED")
            signal_id = evaluation.runtime_context.signal_id(track_id)
            if signal_id in contexts:
                raise ValueError("RUNTIME_DUPLICATE_SIGNAL_ID")
            contexts[signal_id] = evaluation

        commands: list[CanonicalOrderCommand] = []
        for signal in approved_signals:
            evaluation = contexts.get(signal.signal_id)
            if evaluation is None:
                raise ValueError("RUNTIME_APPROVED_SIGNAL_CONTEXT_REQUIRED")
            track_id = str(getattr(evaluation.context, "strategy_id", "") or "").strip()
            if track_id != signal.track_id:
                raise ValueError("RUNTIME_TRACK_ID_CONTEXT_MISMATCH")

            commands.append(
                approved_signal_to_command(
                    signal,
                    context=DecisionCommandContext(
                        client_order_id=evaluation.runtime_context.client_order_id(track_id),
                    ),
                )
            )

        return tuple(commands)
```
## 책임
        - client_order_id는 RuntimeExecutionContext의 authoritative tick/local sequence 계약에서만 파생한다.
        - approved signal의 qty/price/side/track/identity를 재작성하지 않는다.
        - approved signal에 대응하는 Runtime evaluation이 없으면 fail-closed한다.
        - 이 계층은 Risk/Router dependency를 직접 소유하지 않는다.
        - 이후 route_from_authoritative_sources()에는 실제 AccountSnapshot/PositionManager/OrderRouter가 composition에서 명시 공급될 때만 연결한다.
[Child Page] runtime_authoritative_risk_router_adapter.py
```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from core.position.position_aggregate import PositionAggregateSource
from core.position.position_aggregate_risk_adapter import position_aggregate_to_risk_input
from core.risk.risk_input import account_snapshot_to_risk_input
from core.runtime.reference_execution_pipeline import CanonicalRiskCommandAdapter, ReferenceExecutionResult
from core.oms.risk_approved_broker_command_adapter import project_risk_effective_quantity
from shared.contracts.canonical import CanonicalOrderCommand

@dataclass(frozen=True)
class RiskRouterContext:
    account_snapshot: Any
    position_source: PositionAggregateSource
    order_router: Any
    broker_command: Any = None

def route_from_runtime_authoritative_sources(command: CanonicalOrderCommand, *, risk_gate: Any, context: RiskRouterContext, sensor_snapshot: Any = None, allow_reduction: bool = False) -> ReferenceExecutionResult:
    adapted = CanonicalRiskCommandAdapter.from_command(command)
    account = account_snapshot_to_risk_input(context.account_snapshot)
    positions = position_aggregate_to_risk_input(context.position_source)
    approved, token, rejection_reason = risk_gate.admit_order(adapted, account, positions, sensor_snapshot, allow_reduction)
    result = risk_gate.last_evaluation_result
    if not approved or result is None:
        return ReferenceExecutionResult(False, getattr(result, 'decision', 'DENY'), False, None, rejection_reason or getattr(result, 'rejection_reason', None))

    effective = result.reduced_command if result.decision == 'REDUCE' and result.reduced_command is not None else adapted
    if token is None:
        raise RuntimeError("RISK_APPROVAL_TOKEN_REQUIRED")

    # Production path must carry an already-authoritative BrokerOrderCommand.
    # This boundary only projects Risk-effective quantity onto it.
    routed_command = (
        project_risk_effective_quantity(original=context.broker_command, effective=effective)
        if context.broker_command is not None
        else effective
    )
    context.order_router.register_and_route(routed_command, token)
    return ReferenceExecutionResult(True, result.decision, True, effective)
```
## 책임
        - 기존 Account/Position authoritative projection과 RiskGate token 전달을 유지한다.
        - broker_command가 제공되면 실제 authoritative BrokerOrderCommand에 Risk 최종 quantity만 투영하여 StandardOrderRouter로 전달한다.
        - broker_command가 없으면 기존 structural seam 호환을 유지하지만 StandardOrderRouter production 조립에는 사용하지 않는다.
        - Broker identity/execution semantics를 CanonicalRiskCommandAdapter에서 합성하지 않는다.

[Child Page] integration_fixtures.py
```python
"""Deterministic integration fixtures for the nine Standard Core strategies."""

from datetime import datetime
from decimal import Decimal

from core.domain.market_models import CanonicalMarketTick, MarketState
from core.strategy.contracts import CommonStrategyInput, StrategyContext, StrategyInput
from core.strategy.track1_tail_defense import Track1Input
from core.strategy.track2_asymmetric_trap import Track2MarketInputs
from core.strategy.track3_statistical_arbitrage import Track3MarketInput
from core.strategy.track4_gamma_scalping import Track4MarketInput
from core.strategy.track5_gap_divergence import Track5MarketInput
from core.strategy.track6_daily_tail_insurance import Track6MarketInput
from core.strategy.track7_volatility_skew_weekly_insurance import Track7MarketInput
from core.strategy.track8_macro_regime_monthly_strangle import Track8MarketInput
from core.strategy.track9_event_overnight_insurance import Track9MarketInput

AS_OF = datetime(2026, 1, 2, 10, 0)
DATE = "2026-01-02"
PRICE = Decimal("350")


def canonical_market_state() -> MarketState:
    return MarketState(
        as_of=AS_OF,
        ticks={
            "KOSPI200": CanonicalMarketTick(
                instrument_id="KOSPI200",
                observed_at=AS_OF,
                price=PRICE,
                volume=None,
            )
        },
        quality={},
    )


def common_input() -> CommonStrategyInput:
    return CommonStrategyInput(as_of=AS_OF, current_price=PRICE)


def payloads():
    return {
        "TRACK1_TAIL_DEFENSE": Track1Input(
            strategy_id="TRACK1_TAIL_DEFENSE",
            momentum_confirmed=False,
            days_to_expiry=10.0,
            current_time=AS_OF,
            active_vol=1.0,
            base_vol=1.0,
        ),
        "track2_asymmetric_trap": Track2MarketInputs(
            strategy_id="track2_asymmetric_trap",
            bbw_window=(2.0, 1.0),
            volume_window=(1.0, 10.0),
            basis=Decimal("0.5"),
            put_iv=Decimal("1.2"),
            call_iv=Decimal("1.0"),
            poc_price=Decimal("348"),
            bid_qtys=(Decimal("10"),) * 5,
            ask_qtys=(Decimal("1"),) * 5,
            active_vol=1.0,
            base_vol=1.0,
        ),
        "track3_stat_arb": Track3MarketInput(
            strategy_id="track3_stat_arb",
            spread_history=(1.0,) * 10,
            active_vol=1.0,
            base_vol=1.0,
            time_str="10:00:00",
            date_str=DATE,
            current_pnl=0.0,
            total_fees=0.0,
        ),
        "track4_gamma_scalping": Track4MarketInput(
            observed_at=AS_OF,
            current_price=PRICE,
            active_vol=Decimal("1"),
            base_vol=Decimal("1"),
            time_str="10:00:00",
            current_delta=Decimal("0"),
            current_gamma=Decimal("0"),
            current_pnl=Decimal("0"),
            premium_spent=Decimal("200000"),
            accumulated_gamma_profit=Decimal("0"),
            theta_decay_cost=Decimal("0"),
            current_equity=Decimal("1000000"),
        ),
        "track5_gap_divergence": Track5MarketInput(
            strategy_id="track5_gap_divergence",
            open_price=PRICE,
            previous_close=PRICE,
            active_vol=Decimal("1"),
            regime="NORMAL",
            current_price=PRICE,
        ),
        "track6_daily_tail_insurance": Track6MarketInput(
            strategy_id="track6_daily_tail_insurance",
            current_price=PRICE,
            active_vol=Decimal("1"),
            base_vol=Decimal("1"),
            budget=Decimal("1000000"),
            date_str=DATE,
            time_str="10:00:00",
        ),
        "track7_volatility_skew_weekly_insurance": Track7MarketInput(
            strategy_id="track7_volatility_skew_weekly_insurance",
            current_price=PRICE,
            budget=Decimal("1000000"),
            date_str=DATE,
            is_new_week_start=False,
            active_vol=Decimal("1"),
            call_iv=Decimal("1"),
            put_iv=Decimal("1"),
            time_str="10:00:00",
            is_expiry_day=False,
            is_week_end=False,
        ),
        "track8_macro_regime_monthly_strangle": Track8MarketInput(
            strategy_id="track8_macro_regime_monthly_strangle",
            dte=Decimal("20"),
            budget=Decimal("1000000"),
            current_price=PRICE,
            current_regime="NORMAL",
            date_str=DATE,
            current_pnl=Decimal("0"),
            total_fees=Decimal("0"),
            time_str="10:00:00",
            active_vol=Decimal("1"),
            margin_ratio=Decimal("0"),
            risk_guard_active=False,
        ),
        "track9_event_overnight_insurance": Track9MarketInput(
            strategy_id="track9_event_overnight_insurance",
            current_price=PRICE,
            active_sell_qty=10,
            current_insurance_qty=5,
            date_str=DATE,
            time_str="10:00:00",
        ),
    }


def contexts() -> dict[str, StrategyContext]:
    state = canonical_market_state()
    return {
        strategy_id: StrategyContext(
            market_state=state,
            strategy_id=strategy_id,
            input=StrategyInput(common=common_input(), payload=payload),
        )
        for strategy_id, payload in payloads().items()
    }
```
## Fixture 원칙
    - 모든 값은 고정되어 deterministic
    - 실제 Track별 dataclass만 사용
    - payload를 공통 DTO로 변환하지 않음
    - 주문/Broker/Runtime fixture 없음
    - Signal 발생 자체를 성공 조건으로 강제하지 않음
    - 실제 dataclass 필드와 일치하지 않는 임의 필드는 사용하지 않음
## 이번 정정 범위
No.060 이후 추가 대조한 Track4~Track9의 실제 typed contract를 반영했다.
    - Track4: current_delta/current_gamma/current_equity 등 실제 필드 사용
    - Track6: budget/date_str/time_str를 포함한 실제 필드 사용
    - Track7: budget/is_new_week_start/date_str 및 실제 optional 입력 사용
    - Track8: dte/budget/date_str를 포함한 실제 필드 사용
    - Track9: 현재 정의된 필드만 사용
이 fixture는 production input adapter가 아니며, 실제 전략 로직을 변경하지 않는다.
[Child Page] [LEGACY_MISPLACED] test_live_runtime_execution_lifecycle_ownership_seam.py
```python
# Integration contract test for No.491.
# The harness mirrors the current OptionProject lifecycle contracts:
# RuntimeController owns Environment bundle lifecycle; LiveRuntimeBootstrap
# exposes explicit recovery/execution lifecycle and does not auto-start them.

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
## 검증 목적
        - RuntimeController.start/stop은 Environment bundle lifecycle만 수행하는지 확인한다.
        - LiveRuntimeBootstrap.startup_reconcile → start_execution → receive_execution_once → close_execution은 명시적 caller orchestration으로만 수행되는지 확인한다.
        - recovery와 realtime execution이 동일 settlement/OMS/Position state를 공유하는 graph를 가정하여 identity를 보존한다.
        - shutdown에서 execution close와 bundle stop/shutdown이 중복 settlement를 만들지 않도록 lifecycle 순서를 검증한다.
        - 실제 KIS network/credential/account/order submission은 사용하지 않는다.
## 위치
OptionProject / tests / integration
## 임시 검증
Workspace: /tmp/optionproject_verify_491
pytest -q 결과: 2 passed in 0.05s

[Child Page] track1_tail_defense.py
```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Sequence

from core.strategy.contracts import Signal, Strategy, StrategyContext, StrategyPayload
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal


@dataclass(frozen=True)
class Track1Input(StrategyPayload):
    strategy_id: str = "TRACK1_TAIL_DEFENSE"
    momentum_confirmed: bool = False
    days_to_expiry: float | None = None
    current_time: datetime | None = None
    active_vol: float | None = None
    base_vol: float | None = None
    coverage_ratio: float | None = None
    short_option_net_delta: Decimal | None = None


@dataclass
class Track1State:
    base_price: float | None = None
    fence_distance: float = 7.5
    active_fence_type: str | None = None
    active_fence_strike: float | None = None
    active_fence_tag: int = 0
    futures_hedge_count: int = 0
    hedge_count_date: date | None = None
    active_hedge: str | None = None
    hedge_entry_price: float | None = None
    profit_buffer: float = 0.0
    market_opened: bool = False


class Track1TailDefense(Strategy):
    """Track 1 Tail Defense를 Standard Strategy Contract로 이식한 상태기계."""

    strategy_id = "TRACK1_TAIL_DEFENSE"
    version = "1.1.0"

    def __init__(self, profit_target: float = 500_000.0, max_hedge_allowed: int = 20) -> None:
        self.profit_target = profit_target
        self.max_hedge_allowed = max_hedge_allowed
        self.state = Track1State()
        self._initialized = False

    def initialize(self, context: StrategyContext) -> None:
        self.reset()
        self._initialized = True

    def on_market_state(self, context: StrategyContext) -> None:
        self._initialized = True

    @staticmethod
    def _price(context: StrategyContext) -> float:
        tick = next(iter(context.market_state.ticks.values()))
        return float(tick.price)

    @staticmethod
    def _round_strike(price: float) -> float:
        return round(price / 2.5) * 2.5

    @staticmethod
    def _input(context: StrategyContext) -> Track1Input | None:
        payload = context.input.payload if context.input is not None else None
        return payload if isinstance(payload, Track1Input) else None

    def _build_fence_signal(self, fence_type: str, strike: float, tag: int, reason: str) -> Signal:
        # Legacy Track1 explicitly creates these fence legs as OPTION qty=1.
        # The side is the explicit side of this signal, not a generic direction→side conversion.
        side = "BUY" if fence_type == "CALL" else "SELL"
        proposal = StrategyExecutionProposal(
            proposed_quantity=1,
            asset_type="OPTION",
            requested_price=None,
            side=side,
            track_id=self.strategy_id,
            tag_id=str(tag),
            option_type=fence_type,
            strike=Decimal(str(strike)),
        )
        return Signal(self.strategy_id, side, 1.0,
                      f"FENCE_BUILD:{fence_type}:{strike}:#{tag}:{reason}",
                      execution_proposal=proposal)

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        if context.strategy_id != self.strategy_id:
            raise ValueError("strategy context mismatch")
        if not self._initialized:
            self.initialize(context)

        track_input = self._input(context)
        price = self._price(context)
        signals: list[Signal] = []

        if track_input is not None:
            if track_input.current_time is not None:
                current_date = track_input.current_time.date()
                if self.state.hedge_count_date != current_date:
                    self.state.futures_hedge_count = 0
                    self.state.hedge_count_date = current_date
            if track_input.days_to_expiry is not None and track_input.days_to_expiry <= 4.0:
                if self.state.active_fence_type is not None:
                    signals.append(Signal(
                        self.strategy_id,
                        "FLAT",
                        1.0,
                        f"FENCE_CLEAR:D4_CUTOFF:{self.state.active_fence_type}:{self.state.active_fence_strike}:#{self.state.active_fence_tag}",
                        execution_proposal=StrategyExecutionProposal(
                            proposed_quantity=1,
                            asset_type="OPTION",
                            requested_price=None,
                            side=None,
                            track_id=self.strategy_id,
                            tag_id=str(self.state.active_fence_tag),
                            option_type=self.state.active_fence_type,
                            strike=Decimal(str(self.state.active_fence_strike)),
                        ),
                    ))
                    self.state.active_fence_type = None
                    self.state.active_fence_strike = None
                return signals
            if track_input.active_vol is not None and track_input.base_vol is not None:
                self.state.fence_distance = 12.5 if track_input.active_vol > track_input.base_vol * 1.15 else 7.5

        if not self.state.market_opened:
            self.state.base_price = price
            self.state.market_opened = True
            call_outer = self._round_strike(price + 12.5)
            put_outer = self._round_strike(price - 12.5)
            put_inner = self._round_strike(price - 7.5)
            self.state.active_fence_type = "PUT"
            self.state.active_fence_strike = put_inner
            self.state.active_fence_tag = 1
            return (
                self._build_fence_signal("CALL", call_outer, 0, "TAIL_DEFENSE_BUILD_OUTER"),
                self._build_fence_signal("PUT", put_outer, 0, "TAIL_DEFENSE_BUILD_OUTER"),
                self._build_fence_signal("PUT", put_inner, 1, "INITIAL_INNER_FENCE"),
            )

        if self.state.active_fence_type is None or self.state.active_fence_strike is None:
            return signals

        base = self.state.base_price or price
        warning = self.state.fence_distance * 0.9
        approaching = (price <= base - warning if self.state.active_fence_type == "PUT" else price >= base + warning)

        if approaching and self.state.active_hedge is None:
            momentum_confirmed = track_input.momentum_confirmed if track_input is not None else False
            if momentum_confirmed and self.state.futures_hedge_count < self.max_hedge_allowed:
                self.state.active_hedge = "SELL" if self.state.active_fence_type == "PUT" else "BUY"
                self.state.hedge_entry_price = price
                hedge_qty = 0
                if track_input.short_option_net_delta is not None:
                    from core.risk.delta_hedge_quantity import delta_to_mini_futures_qty
                    hedge_qty = delta_to_mini_futures_qty(track_input.short_option_net_delta)
                if hedge_qty <= 0:
                    self.state.active_hedge = None
                    self.state.hedge_entry_price = None
                    return signals
                self.state.futures_hedge_count += 1
                signals.append(Signal(
                    self.strategy_id,
                    self.state.active_hedge,
                    1.0,
                    f"FUTURES_HEDGE_TRIGGER:#{self.state.futures_hedge_count}:price={price}:qty={hedge_qty}",
                    execution_proposal=StrategyExecutionProposal(
                        proposed_quantity=hedge_qty,
                        asset_type="FUTURES",
                        requested_price=None,
                        side=self.state.active_hedge,
                        track_id=self.strategy_id,
                        tag_id="FUTURES_HEDGE",
                        option_type=None,
                        strike=None,
                    ),
                ))

        if self.state.active_hedge and self.state.hedge_entry_price is not None:
            reverted = ((self.state.active_hedge == "SELL" and price - self.state.hedge_entry_price >= 1.5) or
                        (self.state.active_hedge == "BUY" and self.state.hedge_entry_price - price >= 1.5))
            if reverted:
                unwind = "BUY" if self.state.active_hedge == "SELL" else "SELL"
                signals.append(Signal(self.strategy_id, unwind, 1.0, "FUTURES_UNWIND:1.5PT_REVERSION"))
                self.state.active_hedge = None
                self.state.hedge_entry_price = None

        return signals

    def reset(self) -> None:
        self.state = Track1State()
        self._initialized = False
```
## Legacy 기능 이식 상태
원격 Track1에는 Dual-Ring(7.5/12.5pt), 변동성 기반 fence 확대, 날짜 리셋, 90% 접근 hedge, D-4 cutoff, 100% collision 방어, 1.5pt reversal unwind, Dynamic Profit Take/Rebuild가 존재한다. fileciteturn367file0L1-L2 fileciteturn368file0L1-L6
이번 단계에서는 Track1Input을 만들고 StrategyContext.input을 통해 전략 고유 입력을 공급하도록 전환했다. DTE는 MarketTick의 다른 필드로 추측하지 않고 typed input으로만 받는다.
### Domain Definition 반영
    - 선물 헷지 수량은 ceil(abs(매도 옵션 순델타 합계) × 5)로 계산한다.
    - 수량은 core.risk.delta_hedge_quantity.delta_to_mini_futures_qty() 공통 유틸을 사용한다.
    - 선물 방향(side)은 기존 Track1 fence 방향에 따른 헷지 방향을 유지하고, 수량과 방향을 별도 책임으로 취급한다.
    - 입력 short_option_net_delta가 없거나 0이면 임의 수량을 생성하지 않고 해당 헷지 intent를 만들지 않는다.
    - futures_hedge_count는 current_time.date()가 바뀌면 0으로 초기화하여 일일 최대 20회 규칙을 적용한다.
### 아직 별도 Contract가 필요한 기능
    - 100% collision의 전체 coverage/direction 판단
    - Dynamic Profit Take/Rebuild의 수수료·슬리피지 계산
    - OptionContract/TradingCalendar 기반 D-4 domain 연결
위 기능은 필요한 Standard Risk/Execution/Option domain 입력이 준비되기 전까지 임의 값으로 구현하지 않는다.

[Child Page] track2_asymmetric_trap.py
## 목적
원격 Exp_Detail_1/option_program/strategy/plugins/track2.py의 Track 2 핵심 전략을 Standard Strategy Contract에 맞춰 이식하기 위한 설계/코드 작업 파일.
## 원격 원문에서 확인된 기능
    - 자본 배분 10%
    - 저변동성 active_vol <= base_vol * 0.85: ATM ±5.0 Long / ±10.0 Short의 Zero-Cost Wide Trap
    - 고변동성: ATM ±2.5 Long / ±7.5 Short의 Gamma Narrow Trap
    - Mid-Price Offset 및 1 tick 지정가
    - 손절 -30%
    - +30%/+50%/+100% 구간별 trailing stop
    - trailing stop 이후 Short switch 및 15분 timeout guard
    - BBW 역사적 최저 + 거래량 Z-Score > 3.0 동시 trigger
    - OBI 절대값 > 0.5, basis > 0.3, IV skew 방향 검증, POC 1.0pt 이탈의 4중 whipsaw filter
    - 장 마감 15:15 신규 진입 차단
    - 손실 후 15분 cooldown
    - 일일 최대 진입 2회
    - KOSPI200 옵션 가격 tick size 0.01/0.05 기반 reversal price 보정
## Standard Core 이식 규칙
StrategyContext(MarketState)와 Signal만 사용한다. OrderRequest, Broker, TimeService, VMS/VSSF, UI를 Strategy가 직접 호출하지 않는다. 실제 spread/basis/IV/호가잔량/BBW/volume/POC가 canonical contract에 없으면 synthetic fallback을 만들지 않고 입력 부족 상태를 명시한다.
## 상태 분리
전략 내부에는 trap lifecycle과 cooldown 같은 순수 전략 상태만 둔다. 실제 주문 객체 생성, risk 승인, execution은 Decision/Risk/OMS/Environment 계층으로 넘긴다.
## 현재 상태
원격 원문 검토 및 이식 범위 확정 완료. 실제 Standard Strategy 코드 구현과 독립 테스트는 다음 단계에서 진행한다. Legacy Track2는 보존한다.
## Standard Core 실제 구현 v1
```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Sequence

from core.strategy.contracts import Signal, StrategyContext
from core.strategy.multi_leg_plan import build_trap_plan
from contracts.types import MultiLegExecutionPlan


@dataclass(frozen=True)
class Track2MarketInputs:
    strategy_id: str = "track2_asymmetric_trap"
    bbw_window: Sequence[float]
    volume_window: Sequence[float]
    basis: Decimal
    put_iv: Decimal
    call_iv: Decimal
    poc_price: Decimal
    bid_qtys: Sequence[Decimal]
    ask_qtys: Sequence[Decimal]
    active_vol: float
    base_vol: float


class Track2AsymmetricTrap:
    strategy_id = "track2_asymmetric_trap"
    version = "1.0"
    CAPITAL_ALLOCATION_RATE = Decimal("0.10")
    MAX_DAILY_ENTRIES = 2
    COOLDOWN = timedelta(minutes=15)
    MARKET_CUTOFF = time(15, 15)
    STOP_LOSS_RATIO = Decimal("-0.30")

    def __init__(self) -> None:
        self._trap_active = False
        self._entry_price: Decimal | None = None
        self._entry_instrument: str | None = None
        self._last_loss_at: datetime | None = None
        self._daily_entry_count = 0
        self._session_date: date | None = None
        self._high_pnl_ratio = Decimal("0")
        self._short_switch_at: datetime | None = None
        self._short_switched = False

    def initialize(self, context: StrategyContext) -> None:
        self.reset()
        self._session_date = context.market_state.as_of.date()

    def on_market_state(self, context: StrategyContext) -> None:
        current_date = context.market_state.as_of.date()
        if self._session_date != current_date:
            self._session_date = current_date
            self._daily_entry_count = 0

    def reset(self) -> None:
        self._trap_active = False
        self._entry_price = None
        self._entry_instrument = None
        self._last_loss_at = None
        self._daily_entry_count = 0
        self._session_date = None
        self._high_pnl_ratio = Decimal("0")
        self._short_switch_at = None
        self._short_switched = False

    def build_asymmetric_trap(self, current_atm: Decimal, active_vol: float, base_vol: float) -> dict[str, object]:
        if active_vol <= base_vol * 0.85:
            return {
                "status": "ZERO_COST_WIDE_TRAP_SUCCESS",
                "trap_type": "ZERO_COST_10PT_WIDE",
                "pricing_mode": "MID_PRICE_OFFSET",
                "limit_offset_ticks": 1,
                "signals": [
                    {"action": "EXECUTE_SHORT_LEG", "strikes": {"call": current_atm + Decimal("10.0"), "put": current_atm - Decimal("10.0")}},
                    {"action": "EXECUTE_LONG_TRAP_LEG", "strikes": {"call": current_atm + Decimal("5.0"), "put": current_atm - Decimal("5.0")}},
                ],
            }
        return {
            "status": "GAMMA_PEAK_NARROW_TRAP_SUCCESS",
            "trap_type": "GAMMA_5PT_NARROW",
            "pricing_mode": "MID_PRICE_OFFSET",
            "limit_offset_ticks": 1,
            "signals": [
                {"action": "EXECUTE_SHORT_LEG", "strikes": {"call": current_atm + Decimal("7.5"), "put": current_atm - Decimal("7.5")}},
                {"action": "EXECUTE_LONG_TRAP_LEG", "strikes": {"call": current_atm + Decimal("2.5"), "put": current_atm - Decimal("2.5")}},
            ],
        }

    def build_execution_plan(self, group_id: str, current_atm: Decimal, active_vol: float, base_vol: float) -> MultiLegExecutionPlan:
        trap = self.build_asymmetric_trap(current_atm, active_vol, base_vol)
        short = trap["signals"][0]["strikes"]
        long = trap["signals"][1]["strikes"]
        return build_trap_plan(
            group_id=group_id, strategy_id=self.strategy_id, purpose=str(trap["trap_type"]),
            short_put=short["put"], short_call=short["call"],
            long_put=long["put"], long_call=long["call"], quantity=1,
        )

    @staticmethod
    def check_market_trigger(bbw_window: Sequence[float], volume_window: Sequence[float]) -> bool:
        if len(bbw_window) < 2 or len(volume_window) < 2 or bbw_window[-1] != min(bbw_window):
            return False
        history = volume_window[:-1]
        mean = sum(history) / len(history)
        variance = sum((x - mean) ** 2 for x in history) / len(history)
        std = variance ** 0.5
        z_score = 99.0 if std == 0 and volume_window[-1] > mean else 0.0 if std == 0 else (volume_window[-1] - mean) / std
        return z_score > 3.0

    @staticmethod
    def validate_whipsaw_filters(last_price: Decimal, bid_qtys: Sequence[Decimal], ask_qtys: Sequence[Decimal], basis: Decimal, put_iv: Decimal, call_iv: Decimal, poc_price: Decimal) -> bool:
        bid_sum = sum(bid_qtys[:5], Decimal("0"))
        ask_sum = sum(ask_qtys[:5], Decimal("0"))
        total = bid_sum + ask_sum
        obi = Decimal("0") if total == 0 else (bid_sum - ask_sum) / total
        if abs(obi) <= Decimal("0.5") or basis <= Decimal("0.3"):
            return False
        is_upward = last_price > poc_price
        if is_upward and put_iv >= call_iv:
            return False
        if not is_upward and call_iv >= put_iv:
            return False
        return abs(last_price - poc_price) > Decimal("1.0")

    @staticmethod
    def reversal_price(current_bbo_price: Decimal) -> Decimal:
        tick_size = Decimal("0.01") if current_bbo_price < Decimal("3.0") else Decimal("0.05")
        price = current_bbo_price - Decimal("2") * tick_size
        price = (price / tick_size).to_integral_value(rounding=ROUND_HALF_UP) * tick_size
        return max(price, Decimal("0.01"))

    def evaluate_trap(self, current_price: Decimal, now: datetime) -> Sequence[Signal]:
        if self._short_switch_at is not None and now - self._short_switch_at >= self.COOLDOWN:
            self._short_switch_at = None
            self._short_switched = False
            return (Signal(self.strategy_id, "FLAT", 1.0, "SHORT_SWITCH_TIMEOUT_EXIT"),)
        if not self._trap_active or self._entry_price is None or self._entry_price <= 0:
            return ()
        pnl = (current_price - self._entry_price) / self._entry_price
        if pnl <= self.STOP_LOSS_RATIO:
            self._last_loss_at = now
            self._trap_active = False
            self._entry_price = None
            self._high_pnl_ratio = Decimal("0")
            return (Signal(self.strategy_id, "FLAT", 1.0, f"STOP_LOSS {pnl * 100:.1f}%"),)
        self._high_pnl_ratio = max(self._high_pnl_ratio, pnl)
        if self._high_pnl_ratio >= Decimal("0.30"):
            trailing = Decimal("0.90") if self._high_pnl_ratio >= Decimal("1.0") else Decimal("0.88") if self._high_pnl_ratio >= Decimal("0.50") else Decimal("0.85")
            if pnl <= self._high_pnl_ratio * trailing:
                self._trap_active = False
                self._entry_price = None
                self._high_pnl_ratio = Decimal("0")
                self._short_switch_at = now
                self._short_switched = True
                return (Signal(self.strategy_id, "SHORT", 1.0, "TAKE_PROFIT_TRAILING_STOP"),)
        return ()

    def evaluate_with_inputs(self, context: StrategyContext, inputs: Track2MarketInputs) -> Sequence[Signal]:
        now = context.market_state.as_of
        if now.time() >= self.MARKET_CUTOFF or self._daily_entry_count >= self.MAX_DAILY_ENTRIES:
            return ()
        if self._last_loss_at is not None and now - self._last_loss_at < self.COOLDOWN:
            return ()
        tick = next(iter(context.market_state.ticks.values()), None)
        if tick is None or not self.check_market_trigger(inputs.bbw_window, inputs.volume_window):
            return ()
        if not self.validate_whipsaw_filters(tick.price, inputs.bid_qtys, inputs.ask_qtys, inputs.basis, inputs.put_iv, inputs.call_iv, inputs.poc_price):
            return ()
        self._trap_active = True
        self._entry_price = tick.price
        self._entry_instrument = tick.instrument_id
        self._high_pnl_ratio = Decimal("0")
        self._daily_entry_count += 1
        return (Signal(self.strategy_id, "LONG", 1.0, "ASYMMETRIC_TRAP_ENTRY"),)

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        # Canonical MarketState에 없는 BBW/IV/Basis/OBI/POC를 임의 생성하지 않는다.
        # 표준 입력은 StrategyContext.input.payload에서만 받는다.
        if context.input is None:
            return ()
        payload = context.input.payload
        if not isinstance(payload, Track2MarketInputs):
            return ()
        if payload.strategy_id != context.strategy_id:
            return ()
        return self.evaluate_with_inputs(context, payload)
```
### 구현 판정
    - 원격 Track2의 핵심 수치/상태전이를 실제 코드 형태로 이식했다.
    - Track2의 실행 제안은 trap이 Call/Put 복수 leg로 구성되고, 단일 Signal에 authoritative한 asset/side/instrument/strike를 lossless하게 확정할 수 없으므로 StrategyExecutionProposal을 생성하지 않는다.
    - evaluate()는 부족한 canonical 입력을 임의 생성하지 않도록 안전하게 no-op 처리한다.
    - 추가 입력은 Track2MarketInputs로 명시하여 이후 Sensor/Contract 확장 시 연결할 수 있다.
    - Signal만 반환하며 Legacy OrderRequest를 생성하지 않는다.
    - 실제 terminal pytest 실행은 여전히 BLOCKED이다.
<page url="https://app.notion.com/p/3d15f4f6eaa1-81f3-b80a-db62ec76d610">
## ExecutionProposal 연결 판정
    - ASYMMETRIC_TRAP_ENTRY에는 StrategyExecutionProposal을 연결하지 않는다.
    - 원격 Track2의 trap은 Call/Put 복수 leg 구조이며, 현재 단일 Proposal 계약으로는 leg별 strike/option_type/side/identity를 손실 없이 표현할 수 없다.
    - qty=1, asset_type=OPTION, side=BUY를 단일 주문 의미로 확정하는 것도 원격 실행 구조에서 직접 확인되지 않으므로 추론하지 않는다.
    - 따라서 Track2는 Proposal-less Signal을 유지하고 후속 Policy/Identity Resolver 경계에서 실제 주문 단위를 확정한다.

[Child Page] track3_statistical_arbitrage.py
## No.029 Track3 옵션 Carry/Theta·Butterfly·Calendar Spread 기능 보완
원격 track3.py의 별도 순수 기능 _calculate_butterfly_legs(), _validate_calendar_spread_iv(), calculate_options_carry_and_theta()를 확인하고 Standard Core에서 환경 의존성 없이 재사용 가능한 순수 함수로 정리한다. 원문은 Butterfly를 ATM-tick BUY / ATM SELL×2 / ATM+tick BUY로 만들고, Calendar IV divergence를 동일 길이의 near/far IV series에서 마지막 spread와 과거 평균의 차이가 0.05 초과인지 검사한다. fileciteturn282file0L2-L2
```python
from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping, Sequence

@dataclass(frozen=True)
class Track3OptionLeg:
    strike: Decimal
    quantity: int
    side: str


def calculate_butterfly_legs(atm_strike: Decimal, tick_size: Decimal) -> tuple[Track3OptionLeg, ...]:
    if tick_size <= 0:
        raise ValueError("tick_size must be positive")
    return (
        Track3OptionLeg(atm_strike - tick_size, 1, "BUY"),
        Track3OptionLeg(atm_strike, 2, "SELL"),
        Track3OptionLeg(atm_strike + tick_size, 1, "BUY"),
    )


def validate_calendar_spread_iv(near_iv: Sequence[float], far_iv: Sequence[float], threshold: float = 0.05) -> bool:
    if len(near_iv) < 2 or len(far_iv) < 2 or len(near_iv) != len(far_iv):
        return False
    spreads = [n - f for n, f in zip(near_iv, far_iv)]
    return abs(spreads[-1] - sum(spreads[:-1]) / len(spreads[:-1])) > threshold


def calculate_options_carry_and_theta(options_legs: Sequence[Mapping[str, object]], current_index: float) -> float:
    """계약별 현재 시장가격과 진입가격 차이로 옵션 leg PnL을 계산한다.

    실제 시장가격이 없는 경우 값을 합성하지 않는다. `current_market_price`가 없는 leg는
    내재가치만 사용하던 Legacy 동작을 보존하되, 현재 Standard 입력에서는 caller가 명시적으로
    시장가격을 제공하는 것을 우선한다.
    """
    total = 0.0
    for leg in options_legs:
        strike = float(leg.get("strike", 0.0) or 0.0)
        entry = float(leg.get("price", 0.0) or 0.0)
        qty = int(leg.get("qty", 1) or 1)
        side = str(leg.get("side", "BUY"))
        option_type = str(leg.get("type", "CALL"))
        if strike <= 0 or qty <= 0:
            continue
        intrinsic = max(0.0, current_index - strike) if option_type == "CALL" else max(0.0, strike - current_index)
        market = float(leg.get("current_market_price", intrinsic))
        pnl_points = market - entry if side == "BUY" else entry - market
        total += pnl_points * qty * 250_000.0
    return total
```
### Architecture 판정
    - Butterfly/Calendar/Carry 계산은 Strategy 내부 순수 함수로 유지 가능하다.
    - 실제 option quote/IV/expiry/fees 공급은 MarketData/Option Contract/Environment 경계에서 담당한다.
    - OrderRequest, Broker, TimeService 직접 호출은 하지 않는다.
    - 현재 Canonical MarketState에 없는 옵션 전용 입력을 임의의 350.0 등으로 채우지 않는다.
    - Butterfly leg의 실제 주문 생성은 OrderIntent/OMS로 넘긴다.
### 원문 대조 추가 사항
calculate_options_carry_and_theta()는 CALL/PUT의 intrinsic 계산 후 current_market_price가 있으면 이를 사용하고, BUY/SELL 방향으로 250,000 multiplier를 적용한다. fileciteturn282file0L2-L2
### 구현 상태
Track3 핵심 계산·진입·청산·Legging·옵션 보조 계산까지 Standard Core 작업대에 반영했다. 다만 전체 Track3가 실제 Runtime에 연결된 것은 아니며, terminal pytest도 아직 실행하지 못했다.
## No.028 후반부 기능 이식 — 청산·Trailing·Stop·EOD·Cooldown
원격 Track3의 evaluate_arbitrage() 후반부를 다시 원문 대조하여 Standard Core용 순수 상태 전이 메서드로 분리했다. 원문은 15:15 EOD → 3단계 trailing → Z-score stop → holding timeout → convergence/profitability/integrity 순서로 평가하며, 청산마다 last_exit_z_score, position/group 초기화, cooldown을 갱신한다. fileciteturn277file0L2-L2
```python
from dataclasses import dataclass

@dataclass(frozen=True)
class Track3ExitDecision:
    action: str
    status: str
    reason: str
    cooldown_ticks: int


def evaluate_exit(
    *,
    active_position: str,
    group_id: str | None,
    z_score: float,
    z_exit_threshold: float,
    z_stop_loss_threshold: float,
    holding_ticks: int,
    max_holding_ticks: int,
    current_pnl: float,
    total_fees: float,
    estimated_exit_cost: float,
    group_integrity: bool,
    high_watermark: float,
    premium_spent: float,
    time_str: str,
    regime: str,
) -> Track3ExitDecision | None:
    # 원문 우선순위 ① 15:15 EOD
    if time_str >= "15:15:00":
        action = "CLOSE_SHORT_SPREAD" if active_position == "SHORT_SPREAD" else "CLOSE_LONG_SPREAD"
        return Track3ExitDecision(action, "MARKET_CLOSE_FLATTEN", "15:15 EOD atomic group flatten", 20)

    # ② high-watermark trailing lock
    if high_watermark > 30_000.0:
        pnl_ratio = high_watermark / max(1.0, premium_spent)
        trailing_ratio = 0.90 if pnl_ratio >= 2.0 else 0.88 if pnl_ratio >= 1.3 else 0.85
        if current_pnl <= high_watermark * trailing_ratio:
            action = "CLOSE_SHORT_SPREAD" if active_position == "SHORT_SPREAD" else "CLOSE_LONG_SPREAD"
            return Track3ExitDecision(action, "TRAILING_PROFIT_LOCK", "high-watermark trailing reversal", 20)

    # ③ extreme Z-score stop
    stop = (
        active_position == "SHORT_SPREAD" and z_score >= z_stop_loss_threshold
    ) or (
        active_position == "LONG_SPREAD" and z_score <= -z_stop_loss_threshold
    )
    if stop:
        action = "CLOSE_SHORT_SPREAD" if active_position == "SHORT_SPREAD" else "CLOSE_LONG_SPREAD"
        return Track3ExitDecision(action, "STOP_LOSS", "extreme Z-score breach", 40)

    # ④ holding timeout
    if holding_ticks >= max_holding_ticks:
        action = "CLOSE_SHORT_SPREAD" if active_position == "SHORT_SPREAD" else "CLOSE_LONG_SPREAD"
        return Track3ExitDecision(action, "TIMEOUT_EXIT", "maximum holding ticks reached", 20)

    # ⑤ convergence + economic profitability + structural integrity
    converged = (
        active_position == "SHORT_SPREAD" and z_score <= z_exit_threshold
    ) or (
        active_position == "LONG_SPREAD" and z_score >= -z_exit_threshold
    )
    expected_exit_net = current_pnl - total_fees - estimated_exit_cost
    profitable = expected_exit_net >= -5_000.0
    if regime == "HIGH_VOLATILITY" and current_pnl > 10_000.0:
        profitable = True
    if regime == "GAP" and converged and current_pnl > 5_000.0:
        profitable = True

    if converged and profitable and group_integrity:
        action = "CLOSE_SHORT_SPREAD" if active_position == "SHORT_SPREAD" else "CLOSE_LONG_SPREAD"
        return Track3ExitDecision(action, "CLOSED", "convergence + profitability + integrity", 20)

    return None
```
### 상태 적용 규칙
Track3ExitDecision이 반환되면 Strategy 상태는 공통 청산 처리로 일관되게 초기화한다.
```python
def apply_exit(self, decision: Track3ExitDecision, z_score: float) -> None:
    self.last_exit_z_score = z_score
    self.active_position = None
    self.active_group_id = None
    self.position_group_legs = []
    self.group_integrity = True
    self.cooldown_ticks = decision.cooldown_ticks
    self.holding_ticks = 0
    self._arb_high_pnl = 0.0
```
### 원문 보존 판정
    - EOD cooldown = 20 ticks
    - trailing cooldown = 20 ticks
    - stop-loss cooldown = 40 ticks
    - timeout cooldown = 20 ticks
    - convergence close cooldown = 20 ticks
    - trailing 단계 = 0.85 / 0.88 / 0.90
    - stop threshold = 3.5
    - convergence threshold = 0.2
    - economic guard = -5,000 KRW
원격 원문에서 확인된 순서를 유지하되, 실제 주문/체결은 OMS/Environment로 넘긴다. fileciteturn277file0L2-L2
## Standard Core 1차 구현
원격 Track3의 실제 수치와 진입 흐름을 보존하면서 Strategy 경계를 분리한 구현 기준을 추가했다.
```python
from dataclasses import dataclass
from typing import Sequence
from core.strategy.contracts import Signal, StrategyContext

@dataclass(frozen=True)
class Track3MarketInput:
    strategy_id: str
    spread_history: Sequence[float]
    active_vol: float
    base_vol: float
    time_str: str
    date_str: str
    bid_ask_spread: float | None = None
    gap_pct: float | None = None
    price_change_rate: float | None = None
    regime: str | None = None
    market_stable: bool | None = None
    spread_normalizing: bool | None = None
    current_pnl: float = 0.0
    total_fees: float = 0.0
    premium_spent: float | None = None

@dataclass
class Track3State:
    active_position: str | None = None
    group_id: str | None = None
    group_sequence: int = 0
    cooldown_ticks: int = 0
    holding_ticks: int = 0
    last_exit_z_score: float | None = None
    high_pnl: float = 0.0
    group_integrity: bool = True

class Track3StatisticalArbitrage:
    strategy_id = "track3_stat_arb"
    version = "1.0"

    def __init__(self, *, z_entry_threshold: float = 2.0, z_exit_threshold: float = 0.2,
                 z_stop_loss_threshold: float = 3.5, max_holding_ticks: int = 300,
                 min_required_profit: float = 15000.0, base_round_trip_cost: float = 10000.0) -> None:
        self.z_entry_threshold = z_entry_threshold
        self.z_exit_threshold = z_exit_threshold
        self.z_stop_loss_threshold = z_stop_loss_threshold
        self.max_holding_ticks = max_holding_ticks
        self.min_required_profit = min_required_profit
        self.base_round_trip_cost = base_round_trip_cost
        self.state = Track3State()

    def initialize(self, context: StrategyContext) -> None:
        self.reset()

    def on_market_state(self, context: StrategyContext) -> None:
        return None

    @staticmethod
    def calculate_z_score(spread_series: Sequence[float]) -> tuple[float, bool]:
        if len(spread_series) < 10:
            return 0.0, False
        mean = sum(spread_series) / len(spread_series)
        variance = sum((x - mean) ** 2 for x in spread_series) / len(spread_series)
        std = variance ** 0.5
        if std == 0:
            return 0.0, True
        return (spread_series[-1] - mean) / std, True

    @staticmethod
    def detect_market_regime(data: Track3MarketInput) -> str:
        if data.regime in {"HIGH_VOL", "HIGH_VOLATILITY"}: return "HIGH_VOLATILITY"
        if data.regime in {"EXTREME_MOVE", "CIRCUIT_BREAKER", "CRASH"}: return "EXTREME_MOVE"
        if data.regime in {"GAP", "GAP_OPEN"}: return "GAP"
        ratio = data.active_vol / max(0.1, data.base_vol)
        if data.time_str < "09:05:00" and abs(data.gap_pct or 0.0) >= 0.008: return "GAP"
        if abs(data.price_change_rate or 0.0) >= 0.02 or ratio >= 2.5: return "EXTREME_MOVE"
        if ratio >= 1.4 or (data.bid_ask_spread is not None and data.bid_ask_spread > 0.3): return "HIGH_VOLATILITY"
        return "NORMAL"

    def estimate_round_trip_cost(self, regime: str, qty: int, data: Track3MarketInput) -> float:
        spread = (data.bid_ask_spread if data.bid_ask_spread is not None else 0.05) * 250000.0
        slippage_ticks = 1.0 if regime == "NORMAL" else 2.0 if regime == "HIGH_VOLATILITY" else 3.0
        return 3000.0 * 2 * qty + slippage_ticks * 0.05 * 250000.0 * qty + spread * qty + self.base_round_trip_cost

    def calculate_expected_gross_profit(self, z_score: float, spread_history: Sequence[float], qty: int) -> float:
        if len(spread_history) < 10: return 0.0
        mean = sum(spread_history) / len(spread_history)
        variance = sum((x - mean) ** 2 for x in spread_history) / len(spread_history)
        return abs(z_score) * (variance ** 0.5) * 0.8 * 250000.0 * qty

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        data = context.input.payload if context.input is not None else None
        if not isinstance(data, Track3MarketInput): return ()
        z, valid = self.calculate_z_score(data.spread_history)
        if not valid: return ()
        regime = self.detect_market_regime(data)
        if self.state.cooldown_ticks > 0: self.state.cooldown_ticks -= 1
        if self.state.active_position is not None: return ()
        if data.time_str >= "15:00:00" or regime == "EXTREME_MOVE" or self.state.cooldown_ticks > 0: return ()
        if regime == "GAP" and not (data.market_stable and data.spread_normalizing): return ()
        if self.state.last_exit_z_score is not None and abs(z - self.state.last_exit_z_score) < 0.8: return ()
        ratio = data.active_vol / max(0.1, data.base_vol)
        if regime == "HIGH_VOLATILITY": threshold, min_profit, qty = max(2.2, self.z_entry_threshold * ratio * 1.2), self.min_required_profit * 1.5, 1
        elif regime == "GAP": threshold, min_profit, qty = max(2.0, self.z_entry_threshold * 1.1), self.min_required_profit * 1.3, 1
        else: threshold, min_profit, qty = max(1.5, self.z_entry_threshold * ratio), self.min_required_profit, 1
        net = self.calculate_expected_gross_profit(z, data.spread_history, qty) - self.estimate_round_trip_cost(regime, qty, data)
        if net < min_profit or abs(z) < threshold: return ()
        self.state.group_sequence += 1
        self.state.group_id = f"ARB-GROUP-{data.date_str.replace('-', '')}-TRACK3-{self.state.group_sequence:04d}"
        self.state.active_position = "SHORT_SPREAD" if z > 0 else "LONG_SPREAD"
        self.state.holding_ticks = 0
        self.state.high_pnl = 0.0
        return (Signal(self.strategy_id, "SELL" if z > 0 else "BUY", 1.0, f"STAT_ARB group={self.state.group_id} z={z:.4f} net={net:.0f}"),)

    def reset(self) -> None:
        self.state = Track3State()
```
주의: 위 구현은 현재 Standard Contract에 존재하지 않는 Track3 전용 입력을 Track3MarketInput으로 명시했다. 실제 StrategyContext가 이를 직접 보유하도록 변경하는 것은 Contract 확장 작업으로 별도 판정해야 한다.
```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite
from statistics import mean, pstdev
from typing import Mapping, Sequence

from core.strategy.contracts import Signal, StrategyContext


@dataclass(frozen=True)
class Track3MarketInput:
    """Track3가 필요로 하는 비표준 시장 입력을 명시적으로 전달한다."""
    spread_history: tuple[float, ...] = ()
    active_vol: float = 1.0
    base_vol: float = 1.0
    price_change_rate: float = 0.0
    bid_ask_spread: float = 0.0
    gap_pct: float = 0.0
    is_gap: bool = False
    time_str: str = "09:00:00"
    market_stable: bool = False
    spread_normalizing: bool = False
    allow_size_up: bool = False
    current_pnl: float = 0.0
    total_fees: float = 0.0
    premium_spent: float = 0.0
    current_price: float = 0.0
    options_legs: tuple[Mapping[str, object], ...] = ()
    regime: str | None = None
    date_str: str = ""


@dataclass(frozen=True)
class Track3Result:
    status: str
    regime: str
    z_score: float
    signals: tuple[Signal, ...] = ()


@dataclass
class Track3StatisticalArbitrage:
    strategy_id: str = "Strategy_3_StatArb"
    version: str = "1.0"
    z_entry_threshold: float = 2.0
    z_exit_threshold: float = 0.2
    z_stop_loss_threshold: float = 3.5
    max_holding_ticks: int = 300
    min_required_profit: float = 15_000.0
    base_round_trip_cost: float = 10_000.0
    active_position: str | None = None
    active_group_id: str | None = None
    group_sequence: int = 0
    cooldown_ticks: int = 0
    holding_ticks: int = 0
    last_exit_z_score: float | None = None
    group_integrity: bool = True
    position_group_legs: list[Mapping[str, object]] = field(default_factory=list)
    _arb_high_pnl: float = 0.0
    _current_date: str = ""

    def initialize(self, context: StrategyContext) -> None:
        self.reset()

    def on_market_state(self, context: StrategyContext) -> None:
        return None

    def reset(self) -> None:
        self.active_position = None
        self.active_group_id = None
        self.group_sequence = 0
        self.cooldown_ticks = 0
        self.holding_ticks = 0
        self.last_exit_z_score = None
        self.group_integrity = True
        self.position_group_legs = []
        self._arb_high_pnl = 0.0
        self._current_date = ""

    @staticmethod
    def calculate_z_score(spread_series: Sequence[float]) -> tuple[float, bool]:
        if len(spread_series) < 10:
            return 0.0, False
        values = tuple(float(v) for v in spread_series)
        if not all(isfinite(v) for v in values):
            return 0.0, False
        std = pstdev(values)
        if std == 0.0:
            return 0.0, True
        return (values[-1] - mean(values)) / std, True

    @staticmethod
    def detect_market_regime(data: Track3MarketInput) -> str:
        explicit = data.regime
        if explicit in {"HIGH_VOL", "HIGH_VOLATILITY"}:
            return "HIGH_VOLATILITY"
        if explicit in {"EXTREME_MOVE", "CIRCUIT_BREAKER", "CRASH"}:
            return "EXTREME_MOVE"
        if explicit in {"GAP", "GAP_OPEN"}:
            return "GAP"

        vol_ratio = data.active_vol / max(0.1, data.base_vol)
        gap = data.is_gap or (
            data.time_str < "09:05:00" and abs(data.gap_pct) >= 0.008
        )
        if gap:
            return "GAP"
        if abs(data.price_change_rate) >= 0.02 or vol_ratio >= 2.5:
            return "EXTREME_MOVE"
        if vol_ratio >= 1.4 or data.bid_ask_spread > 0.3:
            return "HIGH_VOLATILITY"
        return "NORMAL"

    def estimate_round_trip_cost(
        self, regime: str, qty: int, data: Track3MarketInput
    ) -> float:
        spread_cost = data.bid_ask_spread * 250_000.0
        fee_per_leg = 3_000.0
        slippage_ticks = 1.0 if regime == "NORMAL" else 2.0 if regime == "HIGH_VOLATILITY" else 3.0
        slippage = slippage_ticks * 0.05 * 250_000.0 * qty
        return (fee_per_leg * 2 * qty) + slippage + (spread_cost * qty) + self.base_round_trip_cost

    @staticmethod
    def calculate_expected_gross_profit(
        z_score: float, spread_history: Sequence[float], qty: int
    ) -> float:
        if len(spread_history) < 10:
            return 0.0
        std = pstdev(float(v) for v in spread_history)
        return abs(z_score) * std * 0.8 * 250_000.0 * qty

    @staticmethod
    def calculate_options_carry_and_theta(data: Track3MarketInput) -> float:
        total = 0.0
        for leg in data.options_legs:
            strike = float(leg.get("strike", 0.0))
            entry = float(leg.get("price", 0.0))
            qty = int(leg.get("qty", 1))
            side = str(leg.get("side", "BUY"))
            option_type = str(leg.get("type", "CALL"))
            if strike <= 0:
                continue
            intrinsic = max(0.0, data.current_price - strike) if option_type == "CALL" else max(0.0, strike - data.current_price)
            market = float(leg.get("current_market_price", intrinsic))
            total += (market - entry) * qty * 250_000.0 if side == "BUY" else (entry - market) * qty * 250_000.0
        return total

    def _signal(self, action: str, position: str, reason: str, **details: object) -> Signal:
        payload = {"action": action, "position": position, **details}
        return Signal(
            strategy_id=self.strategy_id,
            direction=position,
            confidence=1.0,
            reason=f"{reason} | {payload}",
        )

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        """MarketState 자체만으로 부족한 Track3 입력은 context 확장 입력으로 받는다."""
        data = context.input.payload if context.input is not None else None
        if not isinstance(data, Track3MarketInput):
            return ()
        result = self.evaluate_input(data)
        return result.signals

    def evaluate_input(self, data: Track3MarketInput) -> Track3Result:
        if data.date_str and data.date_str != self._current_date:
            self._current_date = data.date_str
            self.cooldown_ticks = 0
            self.holding_ticks = 0
            self.active_position = None
            self.active_group_id = None
            self.last_exit_z_score = None
            self.position_group_legs = []
            self.group_integrity = True

        z_score, valid = self.calculate_z_score(data.spread_history)
        regime = self.detect_market_regime(data)
        if self.cooldown_ticks > 0:
            self.cooldown_ticks -= 1
        if not valid:
            return Track3Result("HOLD", regime, z_score)

        vol_ratio = data.active_vol / max(0.1, data.base_vol)
        if regime == "HIGH_VOLATILITY":
            threshold = max(2.2, self.z_entry_threshold * vol_ratio * 1.2)
            min_profit = self.min_required_profit * 1.5
            qty = 1
        elif regime == "EXTREME_MOVE":
            threshold = 999.0
            min_profit = self.min_required_profit * 3.0
            qty = 0
        elif regime == "GAP":
            threshold = max(2.0, self.z_entry_threshold * 1.1)
            min_profit = self.min_required_profit * 1.3
            qty = 1
        else:
            threshold = max(1.5, self.z_entry_threshold * vol_ratio)
            min_profit = self.min_required_profit
            qty = 2 if abs(z_score) >= 2.5 and data.allow_size_up else 1

        effective_pnl = data.current_pnl + self.calculate_options_carry_and_theta(data)
        signals: list[Signal] = []

        if self.active_position is None:
            if data.time_str >= "15:00:00" or regime == "EXTREME_MOVE" or self.cooldown_ticks > 0:
                return Track3Result("ENTRY_BLOCK", regime, z_score)
            if regime == "GAP" and not (data.market_stable and data.spread_normalizing):
                return Track3Result("GAP_UNSTABLE_HOLD", regime, z_score)
            if self.last_exit_z_score is not None and abs(z_score - self.last_exit_z_score) < 0.8:
                return Track3Result("OLD_DISLOCATION_BLOCK", regime, z_score)

            cost = self.estimate_round_trip_cost(regime, qty, data)
            gross = self.calculate_expected_gross_profit(z_score, data.spread_history, qty)
            net = gross - cost
            if net < min_profit:
                return Track3Result("PROFITABILITY_BLOCK", regime, z_score)
            if z_score >= threshold:
                position = "SHORT_SPREAD"
            elif z_score <= -threshold:
                position = "LONG_SPREAD"
            else:
                return Track3Result("HOLD", regime, z_score)

            self.group_sequence += 1
            self.active_group_id = f"ARB-GROUP-{data.date_str or 'UNKNOWN'}-TRACK3-{self.group_sequence:04d}"
            self.active_position = position
            self.holding_ticks = 0
            self._arb_high_pnl = 0.0
            self.group_integrity = True
            self.position_group_legs = [
                {"group_id": self.active_group_id, "leg_type": "FUTURES_SHORT" if position == "SHORT_SPREAD" else "FUTURES_LONG", "qty": qty},
                {"group_id": self.active_group_id, "leg_type": "HEDGE_LEG", "qty": qty},
            ]
            signals.append(self._signal("EXECUTE_STAT_ARB", position, "Z-score entry and expected net profit satisfied", group_id=self.active_group_id, qty=qty, expected_net_pnl=net))
            return Track3Result("ENTER", regime, z_score, tuple(signals))

        self.holding_ticks += 1
        action_type = "CLOSE_SHORT_SPREAD" if self.active_position == "SHORT_SPREAD" else "CLOSE_LONG_SPREAD"
        if data.time_str >= "15:15:00":
            signals.append(self._signal("CLOSE_STAT_ARB", action_type, "15:15 atomic position-group close", group_id=self.active_group_id, qty=1))
            return self._close("MARKET_CLOSE_FLATTEN", z_score, tuple(signals), cooldown=20)

        self._arb_high_pnl = max(self._arb_high_pnl, effective_pnl)
        spent = max(1.0, data.premium_spent)
        if self._arb_high_pnl > 30_000.0:
            ratio = self._arb_high_pnl / spent
            trailing = 0.90 if ratio >= 2.0 else 0.88 if ratio >= 1.3 else 0.85
            if effective_pnl <= self._arb_high_pnl * trailing:
                signals.append(self._signal("CLOSE_STAT_ARB", action_type, "high-watermark trailing profit lock", group_id=self.active_group_id, qty=1))
                return self._close("TRAILING_PROFIT_LOCK", z_score, tuple(signals), cooldown=20)

        stop = (self.active_position == "SHORT_SPREAD" and z_score >= self.z_stop_loss_threshold) or (self.active_position == "LONG_SPREAD" and z_score <= -self.z_stop_loss_threshold)
        if stop:
            signals.append(self._signal("CLOSE_STAT_ARB", action_type, "extreme Z-score stop loss", group_id=self.active_group_id, qty=1))
            return self._close("STOP_LOSS", z_score, tuple(signals), cooldown=40)
        if self.holding_ticks >= self.max_holding_ticks:
            signals.append(self._signal("CLOSE_STAT_ARB", action_type, "maximum holding time reached", group_id=self.active_group_id, qty=1))
            return self._close("TIMEOUT_EXIT", z_score, tuple(signals), cooldown=20)

        converged = (self.active_position == "SHORT_SPREAD" and z_score <= self.z_exit_threshold) or (self.active_position == "LONG_SPREAD" and z_score >= -self.z_exit_threshold)
        cost = self.estimate_round_trip_cost(regime, 1, data)
        net_exit = effective_pnl - data.total_fees - cost
        profitable = net_exit >= -5_000.0
        if regime == "HIGH_VOLATILITY" and effective_pnl > 10_000.0:
            profitable = True
        if regime == "GAP" and converged and effective_pnl > 5_000.0:
            profitable = True
        if converged and profitable and self.group_integrity:
            signals.append(self._signal("CLOSE_STAT_ARB", action_type, "convergence + profitability + integrity", group_id=self.active_group_id, expected_net_pnl=net_exit, qty=1))
            return self._close("CLOSED", z_score, tuple(signals), cooldown=20)
        return Track3Result("HOLD", regime, z_score)

    def _close(self, status: str, z_score: float, signals: tuple[Signal, ...], cooldown: int) -> Track3Result:
        self.last_exit_z_score = z_score
        self.active_position = None
        self.active_group_id = None
        self.position_group_legs = []
        self.cooldown_ticks = cooldown
        self.holding_ticks = 0
        return Track3Result(status, "", z_score, signals)
```
## 이식 주의사항
    - 원격 Track3의 OrderRequest 직접 생성/비동기 leg 주문은 제거했다. 해당 책임은 Decision/OMS/Execution으로 이동한다.
    - 원격의 계산식과 상태 전이 기준은 가능한 한 유지했다.
    - 실제 spread_history, fee/PnL, options legs 등은 합성 기본값으로 만들지 않는다.
    - StrategyContext에 track3_input이 없는 현재 상태에서는 evaluate()가 빈 Signal을 반환한다. 이는 잘못된 synthetic trading을 막기 위한 의도적 안전장치다.
    - _close()의 regime 반환은 상태 결과용이며, 외부 runtime에서는 원본 입력 regime을 별도로 보존하는 것이 바람직하다.

[Child Page] track4_gamma_scalping.py
## No.349 입력계약 보완 — 실제 OHLC 부재에 따른 observed tick-price deadband
    - 원격 Legacy의 price_high/low/close는 실제 OHLC가 아니라 동일 tick.last_price를 세 버퍼에 반복 저장했다.
    - 현재 Canonical/Market 계층에도 authoritative OHLC source가 없으므로 fake OHLC를 유지하지 않는다.
    - 기존 Legacy의 실제 계산 결과를 보존하기 위해 연속 관측 tick 가격의 평균 절대 변화량을 deadband 원천으로 명시한다.
    - 기존 ×5 정규화와 0.2~0.6 clamp는 유지하여 Gamma Scalping의 동적 Delta Hedge 목적을 보존한다.
## 원격 원문 기반 Standard Core 이식 — Track 4 Gamma Scalping
원격 Exp_Detail_1/option_program/strategy/plugins/track4.py를 직접 검토했다. 핵심 기능은 10% 자본 배분, 변동성 기반 Basecamp, ATR 동적 Delta Hedge Deadband, Theta Decay Guard, 3단계 Profit Trailing이다. fileciteturn289file0L2-L6
### 보존 기능
    - Low Vol active_vol <= base_vol*0.85: ATM±2.5 Wide Basecamp
    - High Vol active_vol >= base_vol*1.30: ATM ATM Basecamp
    - 15:15 신규 Basecamp 차단
    - Mid-price / tick offset / fallback timeout은 실행 계층 책임으로 분리
    - Delta Deadband 기본 0.3, 실제 ATR 기반 0.2~0.6 clamp
    - Delta hedge는 Theta guard와 독립적으로 작동
    - hedge quantity ±100 safety clamp
    - 자산 threshold feature flag 및 비활성 시 hedge unwind
    - Theta 수익 > decay cost 검증
    - PnL high-watermark 기반 0.85/0.88/0.90 trailing
    - Profit trailing 후 상태 초기화
### Architecture 변환
Legacy OrderRequest, MarketTick, TimeService, Broker 직접 호출은 Standard Strategy에 복사하지 않는다. Strategy는 Signal/순수 판단을 만들고, 실제 FUT hedge 주문·가격·IOC/fallback은 Decision/OMS/Environment Execution으로 전달한다.
### 구현 상태
현재 Canonical MarketState에 gamma/delta/ATR/Theta/equity가 모두 없으므로 Track4MarketInput을 명시적 입력 DTO로 둔다. 입력이 없는 경우 synthetic 값을 생성하여 실제 기능이 작동하는 것처럼 처리하지 않는다.
### 다음 단계
순수 ATR/Deadband, Basecamp 조건, Delta Hedge Intent, Theta Guard, Profit Trailing을 구현하고 독립 테스트한다. 이후 Registry/Runtime 연결은 전략 개별 기능 검증 뒤 진행한다.
## No.031 실제 Standard Core 구현
원격 Track4 원문의 수치와 실행 의미를 유지하면서 실행 객체 생성은 제외했다.
```python
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Sequence
from core.strategy.contracts import Signal, StrategyContext
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal

@dataclass(frozen=True)
class Track4MarketInput:
    """Runtime materialized Track4 input.

    Required fields are authoritative same-tick observations. Attribution fields are
    optional because their production source is not yet available; consumers that
    require them must fail closed rather than receive a fabricated default.
    """
    observed_at: datetime
    current_price: Decimal
    active_vol: Decimal
    base_vol: Decimal
    time_str: str
    current_delta: Decimal
    current_gamma: Decimal
    current_pnl: Decimal
    current_equity: Decimal
    price_history: Sequence[Decimal]
    premium_spent: Optional[Decimal] = None
    accumulated_gamma_profit: Optional[Decimal] = None
    theta_decay_cost: Optional[Decimal] = None

@dataclass
class Track4State:
    basecamp_active: bool = False
    active_hedge_qty: int = 0
    scalp_high_pnl: Decimal = Decimal("0")
    is_active: bool = False

class Track4GammaScalping:
    strategy_id = "track4_gamma_scalping"
    version = "1.0"

    def __init__(self, equity_threshold: Decimal = Decimal("0")):
        self.equity_threshold = equity_threshold
        self.state = Track4State()

    def initialize(self, context: StrategyContext) -> None:
        self.reset()

    def on_market_state(self, context: StrategyContext) -> None:
        return None

    @staticmethod
    def atm_strike(price: Decimal) -> Decimal:
        return (price / Decimal("2.5")).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * Decimal("2.5")

    def evaluate_basecamp(self, data: Track4MarketInput) -> Sequence[Signal]:
        if self.state.basecamp_active or data.time_str >= "15:15:00":
            return ()
        atm = self.atm_strike(data.current_price)
        if data.active_vol <= data.base_vol * Decimal("0.85"):
            self.state.basecamp_active = True
            return (Signal(self.strategy_id, "BUILD", 1.0, f"WIDE_BASECAMP call={atm + Decimal('2.5')} put={atm - Decimal('2.5')}"),)
        if data.active_vol >= data.base_vol * Decimal("1.30"):
            self.state.basecamp_active = True
            return (Signal(self.strategy_id, "BUILD", 1.0, f"ATM_BASECAMP call={atm} put={atm}"),)
        return ()

    @staticmethod
    def calculate_observed_tick_deadband(price_history: Sequence[Decimal]) -> Decimal:
        """Observed tick-price movement 기반 deadband. OHLC가 없는 현재 입력계약에서 ATR을 가장 가깝게 보존한다."""
        if not price_history:
            return Decimal("0")
        last = price_history[-1]
        if len(price_history) >= 2:
            movements = [abs(price_history[i] - price_history[i - 1]) for i in range(1, len(price_history))]
            movement = sum(movements, Decimal("0")) / Decimal(len(movements))
        else:
            movement = Decimal("0")
        normalized = Decimal("0") if last == 0 else movement / last
        return max(Decimal("0.2"), min(normalized * Decimal("5.0"), Decimal("0.6")))

    def evaluate_delta_hedge(self, data: Track4MarketInput) -> Sequence[Signal]:
        self.state.is_active = data.current_equity >= self.equity_threshold
        if not self.state.is_active:
            if self.state.active_hedge_qty:
                side = "SELL" if self.state.active_hedge_qty > 0 else "BUY"
                qty = abs(self.state.active_hedge_qty)
                self.state.active_hedge_qty = 0
                return (Signal(self.strategy_id, side, 1.0, f"UNWIND_FUT_HEDGE qty={qty}"),)
            return ()
        if not data.price_history:
            return ()
        band = self.calculate_observed_tick_deadband(data.price_history)
        if abs(data.current_delta) <= band:
            return ()
        if data.current_delta > 0:
            hedge_side = "SELL"
        else:
            hedge_side = "BUY"
        from core.risk.delta_hedge_quantity import delta_to_mini_futures_qty
        qty = delta_to_mini_futures_qty(data.current_delta)
        qty = min(qty, 100)
        if qty == 0:
            return ()
        signed_qty = qty if hedge_side == "BUY" else -qty
        self.state.active_hedge_qty += signed_qty
        return (Signal(self.strategy_id, hedge_side, 1.0, f"GAMMA_REBALANCE qty={qty} delta={data.current_delta} band={band}", execution_proposal=StrategyExecutionProposal(
            proposed_quantity=qty,
            asset_type="FUTURES",
            requested_price=None,
            side=hedge_side,
            track_id=self.strategy_id,
            tag_id=None,
            option_type=None,
            strike=None,
        )),)

    @staticmethod
    def theta_guard(accumulated_gamma_profit: Decimal, theta_decay_cost: Decimal) -> bool:
        return accumulated_gamma_profit > theta_decay_cost

    def evaluate_profit_trailing(self, data: Track4MarketInput) -> Sequence[Signal]:
        self.state.scalp_high_pnl = max(self.state.scalp_high_pnl, data.current_pnl)
        high = self.state.scalp_high_pnl
        if high <= Decimal("30000"):
            return ()
        if data.premium_spent is None:
            return ()
        ratio = high / max(Decimal("1"), data.premium_spent)
        trailing = Decimal("0.90") if ratio >= Decimal("2.0") else Decimal("0.88") if ratio >= Decimal("1.3") else Decimal("0.85")
        if data.current_pnl <= high * trailing:
            self.state.scalp_high_pnl = Decimal("0")
            # trailing close 이후 strategy-local hedge state도 stale 상태로 남기지 않는다.
            self.state.active_hedge_qty = 0
            self.state.is_active = False
            return (Signal(self.strategy_id, "CLOSE", 1.0, f"PROFIT_TAKEN_TRAILING_STOP high={high} ratio={trailing}"),)
        return ()

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        strategy_input = context.input
        if strategy_input is None:
            return ()
        data = strategy_input.payload
        if not isinstance(data, Track4MarketInput):
            return ()
        if context.strategy_id != self.strategy_id:
            return ()
        # Track4MarketInput에는 strategy_id 필드가 없으므로
        # Strategy identity는 StrategyContext에서만 검증한다.
        signals = list(self.evaluate_basecamp(data))
        signals.extend(self.evaluate_delta_hedge(data))
        signals.extend(self.evaluate_profit_trailing(data))
        return tuple(signals)

    def reset(self) -> None:
        self.state = Track4State()
```
### Domain Definition 반영
    - Delta hedge 수량은 ceil(abs(상쇄 필요 순델타) × 5)로 계산한다.
    - core.risk.delta_hedge_quantity.delta_to_mini_futures_qty()를 Track1과 공유한다.
    - 순델타가 양수이면 SELL, 음수이면 BUY로 반대 방향 hedge intent를 생성한다.
    - 기존 ±100 safety clamp는 유지한다.
### 구현 판정
    - Basecamp 조건: 이식 완료
    - ATR Deadband: 이식 완료
    - Delta Hedge: 이식 완료
    - ±100 safety clamp: 이식 완료
    - Equity Feature Flag / Hedge Unwind: 이식 완료
    - Theta Guard: 이식 완료
    - 3단계 Profit Trailing: 이식 완료
    - Legacy OrderRequest/Broker 직접 호출: 없음
    - 실제 Execution: OMS/Environment 책임으로 미이식
원격 원문의 Basecamp/Delta/Trailing/ATR 수치를 대조했다. fileciteturn291file0L2-L6

[Child Page] track5_gap_divergence.py
```python
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Sequence

from core.strategy.contracts import Signal, StrategyContext


@dataclass(frozen=True)
class Track5MarketInput:
    strategy_id: str
    open_price: Decimal
    previous_close: Decimal
    active_vol: Decimal
    regime: str = "NORMAL"
    current_price: Decimal | None = None


@dataclass(frozen=True)
class Track5State:
    is_active: bool = False
    direction: str | None = None
    entry_price: Decimal = Decimal("0")
    target_price: Decimal = Decimal("0")
    stop_loss_price: Decimal = Decimal("0")
    open_ticks: int = 0
    peak_pnl: Decimal = Decimal("0")
    trailing_active: bool = False
    liquidity_stage: int = 0
    daily_std_pts: Decimal = Decimal("1.5")


class Track5GapDivergence:
    strategy_id = "track5_gap_divergence"
    version = "1.0"

    def __init__(self, z_threshold: Decimal = Decimal("1.5"), stop_loss_pts: Decimal = Decimal("1.5")) -> None:
        self.z_threshold = z_threshold
        self.stop_loss_pts = stop_loss_pts
        self.state = Track5State()

    def initialize(self, context: StrategyContext) -> None:
        self.reset()

    def on_market_state(self, context: StrategyContext) -> None:
        return None

    def reset(self) -> None:
        self.state = Track5State()

    @staticmethod
    def daily_std_points(previous_close: Decimal, active_vol: Decimal) -> Decimal:
        # Legacy formula: previous_close * ((0.15 / sqrt(252)) * active_vol)
        return previous_close * (Decimal("0.15") / Decimal("15.874507866")) * active_vol

    def effective_z_threshold(self, regime: str) -> Decimal:
        if regime in {"HIGH_VOL", "NOISE_CHOPPY", "CIRCUIT_BREAKER"}:
            return Decimal("1.8")
        if regime in {"NORMAL", "NEUTRAL"}:
            return Decimal("1.1")
        return self.z_threshold

    def evaluate_gap(self, data: Track5MarketInput) -> Sequence[Signal]:
        if self.state.is_active:
            return ()

        if data.previous_close <= 0 or data.active_vol < 0:
            return ()

        gap = data.open_price - data.previous_close
        daily_std = self.daily_std_points(data.previous_close, data.active_vol)
        if daily_std <= 0:
            return ()

        z_score = gap / max(Decimal("0.1"), daily_std)
        effective_z = self.effective_z_threshold(data.regime)
        if abs(z_score) < effective_z or abs(z_score) >= Decimal("4.0"):
            return ()

        stop_distance = max(Decimal("1.0"), daily_std * Decimal("0.8"))
        direction = "SHORT" if z_score > 0 else "LONG"
        stop = data.open_price + stop_distance if direction == "SHORT" else data.open_price - stop_distance
        self.state = replace(
            self.state,
            is_active=True,
            direction=direction,
            entry_price=data.open_price,
            target_price=data.previous_close,
            stop_loss_price=stop,
            open_ticks=0,
            peak_pnl=Decimal("0"),
            trailing_active=False,
            liquidity_stage=0,
            daily_std_pts=daily_std,
        )
        return (Signal(
            strategy_id=self.strategy_id,
            direction=direction,
            confidence=float(min(Decimal("1"), abs(z_score) / Decimal("4"))),
            reason=f"GAP_Z_SCORE:{z_score:.4f};ENTRY:{data.open_price};TARGET:{data.previous_close};STOP:{stop}",
        ),)

    def evaluate_mean_reversion(self, current_price: Decimal) -> Sequence[Signal]:
        if not self.state.is_active or self.state.direction is None:
            return ()

        state = replace(self.state, open_ticks=self.state.open_ticks + 1)
        direction = state.direction
        pnl = state.entry_price - current_price if direction == "SHORT" else current_price - state.entry_price
        state = replace(state, peak_pnl=max(state.peak_pnl, pnl))
        trail_threshold = max(Decimal("0.3"), state.daily_std_pts * Decimal("0.3"))
        trail_reversal = max(Decimal("0.1"), state.daily_std_pts * Decimal("0.1"))

        if (direction == "SHORT" and current_price <= state.target_price) or (direction == "LONG" and current_price >= state.target_price):
            self.reset()
            return (Signal(self.strategy_id, "CLOSE", 1.0, f"MEAN_REVERSION_TARGET:{state.target_price};PNL:{pnl}"),)

        if (direction == "SHORT" and current_price >= state.stop_loss_price) or (direction == "LONG" and current_price <= state.stop_loss_price):
            self.reset()
            return (Signal(self.strategy_id, "CLOSE", 1.0, f"DYNAMIC_STOP:{state.stop_loss_price};PNL:{pnl}"),)

        if state.open_ticks >= 30:
            self.reset()
            return (Signal(self.strategy_id, "CLOSE", 1.0, f"TIMEOUT_15M;PNL:{pnl}"),)

        trailing_active = state.trailing_active or pnl >= trail_threshold
        pnl_ratio = pnl / max(Decimal("0.1"), state.daily_std_pts)
        scale = Decimal("0.67") if pnl_ratio >= 1 else Decimal("0.80") if pnl_ratio >= Decimal("0.3") else Decimal("1")
        effective_reversal = trail_reversal * scale
        state = replace(state, trailing_active=trailing_active)

        if trailing_active and state.peak_pnl - pnl >= effective_reversal:
            self.reset()
            return (Signal(self.strategy_id, "CLOSE", 1.0, f"TRAILING_LOCK;PEAK:{state.peak_pnl};REVERSAL:{effective_reversal};PNL:{pnl}"),)

        if pnl >= trail_threshold * Decimal("0.75") and state.liquidity_stage == 0:
            self.state = replace(state, liquidity_stage=1)
            return (Signal(self.strategy_id, "LIQUIDITY", 0.7, f"LIQUIDITY_STAGE_1;PRICE:{current_price};PNL:{pnl}"),)

        if pnl >= trail_threshold * Decimal("1.5") and state.liquidity_stage == 1:
            self.state = replace(state, liquidity_stage=2)
            return (Signal(self.strategy_id, "LIQUIDITY", 0.8, f"LIQUIDITY_STAGE_2;PRICE:{current_price};PNL:{pnl}"),)

        self.state = state
        return ()

    def evaluate_input(self, data: Track5MarketInput) -> Sequence[Signal]:
        if data.current_price is None:
            return self.evaluate_gap(data)
        if self.state.is_active:
            return self.evaluate_mean_reversion(data.current_price)
        return self.evaluate_gap(data)

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        if context.strategy_id != self.strategy_id or context.input is None:
            return ()
        payload = context.input.payload
        if not isinstance(payload, Track5MarketInput):
            return ()
        if payload.strategy_id != self.strategy_id:
            return ()
        return self.evaluate_input(payload)
```
원격 Exp_Detail_1/option_program/strategy/plugins/track5.py의 Gap Divergence 기능을 Standard Core 경계로 옮긴 구현이다. Legacy 주문 객체·Broker·TimeService는 가져오지 않는다.

[Child Page] track6_daily_tail_insurance.py
```python
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Sequence

from core.strategy.contracts import Signal, StrategyContext
from core.strategy.multi_leg_plan import build_pair_plan
from contracts.types import MultiLegExecutionPlan


@dataclass(frozen=True)
class Track6MarketInput:
    strategy_id: str
    current_price: Decimal
    active_vol: Decimal
    base_vol: Decimal
    budget: Decimal
    date_str: str
    time_str: str = "09:00:00"


@dataclass(frozen=True)
class Track6State:
    is_active: bool = False
    bought_date: str | None = None
    long_put_strike: Decimal = Decimal("0")
    long_call_strike: Decimal = Decimal("0")
    premium_spent: Decimal = Decimal("0")
    high_watermark_intrinsic: Decimal = Decimal("0")
    trailing_stop_active: bool = False


class Track6DailyTailInsurance:
    strategy_id = "track6_daily_tail_insurance"
    version = "1.0"
    CAPITAL_ALLOCATION_RATE = Decimal("0.02")
    VOL_TRIGGER_MULTIPLIER = Decimal("1.3")
    STRIKE_OFFSET = Decimal("12.5")
    INSURANCE_QTY = 1
    MULTIPLIER = Decimal("250000")

    def __init__(
        self,
        vol_trigger_multiplier: Decimal = VOL_TRIGGER_MULTIPLIER,
        strike_offset: Decimal = STRIKE_OFFSET,
        insurance_qty: int = INSURANCE_QTY,
    ) -> None:
        self.vol_trigger_multiplier = vol_trigger_multiplier
        self.strike_offset = strike_offset
        self.insurance_qty = insurance_qty
        self.state = Track6State()

    def initialize(self, context: StrategyContext) -> None:
        self.reset()

    def on_market_state(self, context: StrategyContext) -> None:
        return None

    def reset(self) -> None:
        self.state = Track6State()

    @staticmethod
    def atm_strike(price: Decimal) -> Decimal:
        return (price / Decimal("2.5")).to_integral_value() * Decimal("2.5")

    def evaluate_buy(self, data: Track6MarketInput) -> Sequence[Signal]:
        if self.state.is_active:
            return ()
        if "15:15" <= data.time_str < "15:20":
            return (Signal(self.strategy_id, "CANCEL", 1.0, "CANCEL_PENDING_TRANCHES_15:15"),)
        estimated_cost = self.MULTIPLIER * self.insurance_qty
        if data.budget < estimated_cost:
            return ()
        if data.base_vol <= 0 or data.active_vol < data.base_vol * self.vol_trigger_multiplier:
            return ()

        atm = self.atm_strike(data.current_price)
        put_strike = atm - self.strike_offset
        call_strike = atm + self.strike_offset
        self.state = replace(
            self.state,
            is_active=True,
            bought_date=data.date_str,
            long_put_strike=put_strike,
            long_call_strike=call_strike,
            premium_spent=estimated_cost,
            high_watermark_intrinsic=Decimal("0"),
            trailing_stop_active=False,
        )
        return (Signal(
            self.strategy_id,
            "BUY_INSURANCE",
            1.0,
            f"VOL_SPIKE:{data.active_vol}>={data.base_vol * self.vol_trigger_multiplier};"
            f"PUT:{put_strike};CALL:{call_strike};QTY:{self.insurance_qty};"
            f"COST:{estimated_cost};EXECUTION:SUBSECOND_TICK_CHASER_IOC",
        ),)

    def build_execution_plan(self, group_id: str) -> MultiLegExecutionPlan | None:
        if not self.state.is_active or self.state.long_put_strike <= 0 or self.state.long_call_strike <= 0:
            return None
        return build_pair_plan(
            group_id=group_id, strategy_id=self.strategy_id, purpose="DAILY_TAIL_INSURANCE_ENTRY",
            put_strike=self.state.long_put_strike, call_strike=self.state.long_call_strike,
            put_quantity=self.insurance_qty, call_quantity=self.insurance_qty, side="BUY",
        )

    def evaluate_take_profit(
        self,
        current_price: Decimal,
        active_vol: Decimal,
        time_str: str,
    ) -> Sequence[Signal]:
        if not self.state.is_active:
            return ()
        if time_str >= "15:12:00":
            return ()

        put_intrinsic = max(Decimal("0"), self.state.long_put_strike - current_price) * self.MULTIPLIER * self.insurance_qty
        call_intrinsic = max(Decimal("0"), current_price - self.state.long_call_strike) * self.MULTIPLIER * self.insurance_qty
        total_intrinsic = put_intrinsic + call_intrinsic
        spent = self.state.premium_spent if self.state.premium_spent > 0 else self.MULTIPLIER

        minimum_multiplier = Decimal("1.5") if active_vol < Decimal("1.3") else Decimal("2.0")
        trailing_active = self.state.trailing_stop_active or total_intrinsic >= spent * minimum_multiplier
        if not trailing_active:
            return ()

        previous_high = self.state.high_watermark_intrinsic
        current_high = max(previous_high, total_intrinsic)
        pnl_ratio = current_high / max(Decimal("1"), spent)
        trailing_ratio = (
            Decimal("0.90") if pnl_ratio >= 2
            else Decimal("0.88") if pnl_ratio >= Decimal("1.3")
            else Decimal("0.85")
        )
        stop_trigger = current_high * trailing_ratio

        if current_high > 0 and total_intrinsic <= stop_trigger:
            self.reset()
            return (Signal(
                self.strategy_id,
                "CLOSE",
                1.0,
                f"TRAILING_STOP;REALIZED:{total_intrinsic};HIGH:{current_high};RATIO:{trailing_ratio}",
            ),)

        if previous_high == 0 or current_high >= previous_high * Decimal("1.01"):
            self.state = replace(
                self.state,
                trailing_stop_active=True,
                high_watermark_intrinsic=current_high,
            )
            return (Signal(
                self.strategy_id,
                "UPDATE_TRAILING",
                0.9,
                f"HIGH_WATERMARK:{current_high};STOP_TRIGGER:{stop_trigger};OFFSET_TICKS:2",
            ),)

        self.state = replace(self.state, trailing_stop_active=trailing_active)
        return ()

    def evaluate_expiry_cutoff(self, time_str: str) -> Sequence[Signal]:
        if not self.state.is_active:
            return ()
        if "15:00:00" <= time_str < "15:15:00":
            return (Signal(self.strategy_id, "CLOSE_LIMIT", 1.0, "DAILY_INSURANCE_15:00_CUTOFF"),)
        if time_str >= "15:15:00":
            self.reset()
            return (Signal(self.strategy_id, "CLOSE_FALLBACK", 1.0, "DAILY_INSURANCE_15:15_FALLBACK"),)
        return ()

    def evaluate_input(self, data: Track6MarketInput) -> Sequence[Signal]:
        if self.state.is_active:
            cutoff = self.evaluate_expiry_cutoff(data.time_str)
            if cutoff:
                return cutoff
            return self.evaluate_take_profit(data.current_price, data.active_vol, data.time_str)
        return self.evaluate_buy(data)

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        strategy_input = getattr(context, "input", None)
        data = getattr(strategy_input, "payload", None)
        if not isinstance(data, Track6MarketInput):
            return ()
        if getattr(context, "strategy_id", None) != self.strategy_id:
            return ()
        if data.strategy_id != self.strategy_id:
            return ()
        return self.evaluate_input(data)
```
원격 Legacy Track6의 Daily 0DTE Tail Insurance 기능을 Standard Core Strategy 경계로 유지한다. 실제 IOC/서브초 추격/지정가 큐/fallback 시장가 실행은 Strategy에서 직접 수행하지 않고 OMS·Environment Execution 계층으로 전달한다.
## No.049 typed payload 표준화
    - Track6MarketInput.strategy_id를 명시한다.
    - evaluate()는 임의 context.track6_input을 읽지 않고 context.input.payload만 사용한다.
    - Context와 payload의 strategy_id가 모두 track6_daily_tail_insurance와 일치할 때만 평가한다.
    - 입력 부재/타입 불일치/전략 ID 불일치 시 synthetic data 없이 no-op한다.
    - 활성 상태에서는 15:00/15:15 cutoff를 먼저 평가하여 만기 청산 우선순위를 유지한다.

[Child Page] track7_volatility_skew_weekly_insurance.py
```python
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Sequence

from core.strategy.contracts import Signal, StrategyContext


@dataclass(frozen=True)
class Track7MarketInput:
    strategy_id: str
    current_price: Decimal
    budget: Decimal
    date_str: str
    is_new_week_start: bool
    active_vol: Decimal
    call_iv: Decimal | None = None
    put_iv: Decimal | None = None
    skew_limit_timeout: bool = False
    ma_1m: Decimal | None = None
    ma_3m: Decimal | None = None
    ma_5m: Decimal | None = None
    ma_10m: Decimal | None = None
    support: Decimal | None = None
    resistance: Decimal | None = None
    time_str: str = "09:00:00"
    is_expiry_day: bool = False
    is_week_end: bool = False


@dataclass(frozen=True)
class Track7State:
    insurance_active: bool = False
    bought_date: str | None = None
    put_strike: Decimal = Decimal("0")
    call_strike: Decimal = Decimal("0")
    premium_spent: Decimal = Decimal("0")
    high_watermark_intrinsic: Decimal = Decimal("0")
    trailing_active: bool = False
    skew_active: bool = False
    skew_limit_pending: bool = False


class Track7VolatilitySkewWeeklyInsurance:
    strategy_id = "track7_volatility_skew_weekly_insurance"
    version = "1.0"
    STRIKE_OFFSET = Decimal("15.0")
    INSURANCE_QTY = 1
    MULTIPLIER = Decimal("250000")
    SKEW_ENTRY = Decimal("3.0")
    SKEW_STOP = Decimal("8.0")
    SKEW_EXIT = Decimal("0.5")
    FALLBACK_TIMEOUT_SEC = Decimal("5.0")

    def __init__(self, strike_offset: Decimal = STRIKE_OFFSET, insurance_qty: int = INSURANCE_QTY, expiry_mode: str = "D-0 CUTOFF") -> None:
        self.strike_offset = strike_offset
        self.insurance_qty = insurance_qty
        self.expiry_mode = expiry_mode
        self.state = Track7State()

    def initialize(self, context: StrategyContext) -> None:
        self.reset()

    def on_market_state(self, context: StrategyContext) -> None:
        return None

    def reset(self) -> None:
        self.state = Track7State()

    @staticmethod
    def atm_strike(price: Decimal) -> Decimal:
        return (price / Decimal("2.5")).to_integral_value() * Decimal("2.5")

    def insurance_cost(self, active_vol: Decimal) -> Decimal:
        vol_scale = Decimal("0.5") if active_vol < Decimal("1") else Decimal("1")
        return Decimal("1.4") * self.MULTIPLIER * self.insurance_qty * vol_scale

    def evaluate_insurance_buy(self, data: Track7MarketInput) -> Sequence[Signal]:
        if data.date_str != self.state.bought_date and self.state.bought_date is not None:
            self.reset()
        if self.state.insurance_active:
            return ()
        if "15:15" <= data.time_str < "15:20":
            return (Signal(self.strategy_id, "CANCEL", 1.0, "CANCEL_PENDING_TRANCHES_15:15"),)
        if not data.is_new_week_start:
            return ()
        cost = self.insurance_cost(data.active_vol)
        if data.budget < cost:
            return ()
        atm = self.atm_strike(data.current_price)
        put_strike = atm - self.strike_offset
        call_strike = atm + self.strike_offset
        self.state = replace(self.state, insurance_active=True, bought_date=data.date_str, put_strike=put_strike, call_strike=call_strike, premium_spent=cost)
        return (Signal(self.strategy_id, "BUY_LIMIT_WEEKLY_INSURANCE", 1.0, f"PUT:{put_strike};CALL:{call_strike};QTY:{self.insurance_qty};PRICING:MID_PRICE_OFFSET;TICK_OFFSET:1;FALLBACK_TIMEOUT_SEC:{self.FALLBACK_TIMEOUT_SEC};COST:{cost}"),)

    def evaluate_skew_arbitrage(self, data: Track7MarketInput) -> Sequence[Signal]:
        if data.call_iv is None or data.put_iv is None:
            return ()
        skew = data.put_iv - data.call_iv
        if not self.state.skew_active:
            if abs(skew) < self.SKEW_ENTRY:
                return ()
            self.state = replace(self.state, skew_active=True, skew_limit_pending=True)
            direction = "LONG_PUT_SHORT_CALL" if skew > 0 else "LONG_CALL_SHORT_PUT"
            return (Signal(self.strategy_id, "ENTER_SKEW_ARB_LIMIT", 1.0, f"TYPE:{direction};SKEW:{skew};QTY:1"),)
        if self.state.skew_limit_pending and data.skew_limit_timeout:
            self.state = replace(self.state, skew_limit_pending=False)
            return (Signal(self.strategy_id, "ENTER_SKEW_ARB_FALLBACK_MARKET", 1.0, f"SKEW:{skew};TIMEOUT_SEC:{self.FALLBACK_TIMEOUT_SEC};QTY:1"),)
        if abs(skew) > self.SKEW_STOP:
            self.state = replace(self.state, skew_active=False, skew_limit_pending=False)
            return (Signal(self.strategy_id, "CLOSE_SKEW_ARB_STOP_LOSS", 1.0, f"SKEW:{skew};STOP:{self.SKEW_STOP};QTY:1"),)
        if abs(skew) <= self.SKEW_EXIT:
            self.state = replace(self.state, skew_active=False, skew_limit_pending=False)
            return (Signal(self.strategy_id, "CLOSE_SKEW_ARB_LIMIT", 1.0, f"SKEW:{skew};EXIT:{self.SKEW_EXIT};QTY:1"),)
        return ()

    def evaluate_preemptive_take_profit(self, data: Track7MarketInput) -> Sequence[Signal]:
        required = (data.ma_1m, data.ma_3m, data.ma_5m, data.ma_10m)
        if any(value is None for value in required):
            return ()
        bullish_cross = data.ma_1m > data.ma_3m > data.ma_5m > data.ma_10m
        bearish_cross = data.ma_1m < data.ma_3m < data.ma_5m < data.ma_10m
        near_resistance = data.resistance is not None and data.current_price >= data.resistance
        near_support = data.support is not None and data.current_price <= data.support
        if bullish_cross or bearish_cross or near_resistance or near_support:
            return (Signal(self.strategy_id, "PREEMPTIVE_LIMIT_TAKE_PROFIT", 0.8, f"MA_CROSS:{bullish_cross or bearish_cross};SUPPORT:{data.support};RESISTANCE:{data.resistance};PRICE:{data.current_price}"),)
        return ()

    def evaluate_expiry_cutoff(self, data: Track7MarketInput) -> Sequence[Signal]:
        if not self.state.insurance_active:
            return ()
        if self.expiry_mode == "D-4" and self.state.bought_date == data.date_str and data.time_str >= "15:00:00":
            self.reset()
            return (Signal(self.strategy_id, "CLOSE_WEEKLY_INSURANCE_PREEMPTIVE_D4", 1.0, "D4_PREEMPTIVE_CUTOFF"),)
        expiry_active = data.is_expiry_day or data.is_week_end
        if not expiry_active:
            return ()
        if "15:00:00" <= data.time_str < "15:15:00":
            return (Signal(self.strategy_id, "CLOSE_WEEKLY_INSURANCE_LIMIT", 1.0, "15:00_LIMIT_CUTOFF"),)
        if data.time_str >= "15:15:00":
            self.reset()
            return (Signal(self.strategy_id, "CLOSE_WEEKLY_INSURANCE_FALLBACK_MARKET", 1.0, "15:15_FALLBACK_MARKET"),)
        return ()

    def evaluate_input(self, data: Track7MarketInput) -> Sequence[Signal]:
        if self.state.insurance_active:
            cutoff = self.evaluate_expiry_cutoff(data)
            if cutoff:
                return cutoff
        signals: list[Signal] = []
        if not self.state.insurance_active:
            signals.extend(self.evaluate_insurance_buy(data))
        signals.extend(self.evaluate_skew_arbitrage(data))
        if self.state.insurance_active:
            signals.extend(self.evaluate_preemptive_take_profit(data))
        return tuple(signals)

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        strategy_input = getattr(context, "input", None)
        data = getattr(strategy_input, "payload", None)
        if not isinstance(data, Track7MarketInput):
            return ()
        if getattr(context, "strategy_id", None) != self.strategy_id:
            return ()
        if data.strategy_id != self.strategy_id:
            return ()
        return self.evaluate_input(data)
```
원격 Legacy Track7의 Volatility Arbitrage / IV Skew / Weekly Tail Insurance 기능을 Standard Core Strategy 경계로 유지한다. 실제 Limit Queue, timeout 후 Fallback Market, IOC 등 주문 집행은 OMS·Environment Execution 계층의 책임으로 유지한다.
## No.050 typed payload 표준화
    - Track7MarketInput.strategy_id를 명시한다.
    - evaluate()는 임의 context.track7_input을 읽지 않고 context.input.payload만 사용한다.
    - Context와 payload의 strategy_id가 모두 track7_volatility_skew_weekly_insurance와 일치할 때만 평가한다.
    - 입력 부재/타입 불일치/전략 ID 불일치 시 synthetic data 없이 no-op한다.
    - 활성 보험 상태에서는 15:00/15:15 expiry cutoff를 먼저 평가한다.
    - Track7의 Weekly Insurance와 IV Skew Arbitrage는 동일 Strategy 내부의 독립 상태로 유지하며 Track6 Daily Insurance와 통합하지 않는다.
## Track7 typed execution boundary audit
    - Strategy-level Signal의 reason 문자열에서 strike/quantity/side를 역파싱하여 주문 leg를 생성하지 않는다.
    - 실제 계산 결과에 독립적인 leg별 option_type, strike, quantity, side가 이미 존재하는 경우에만 StrategyExecutionProposal로 보존한다.
    - instrument_id / symbol / expiry는 authoritative Option Identity Source가 공급하기 전까지 생성하지 않는다.
    - 단일 proposal로 복수 leg를 합쳐 표현하지 않고, leg별 provenance를 보존하는 composition을 사용한다.

[Child Page] track8_macro_regime_monthly_strangle.py
```python
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Sequence

from core.strategy.contracts import Signal, StrategyContext, StrategyInput
from core.strategy.multi_leg_plan import build_pair_plan
from contracts.types import MultiLegExecutionPlan


@dataclass(frozen=True)
class Track8MarketInput:
    strategy_id: str
    dte: Decimal
    budget: Decimal
    current_price: Decimal
    current_regime: str
    date_str: str
    current_pnl: Decimal = Decimal("0")
    total_fees: Decimal = Decimal("0")
    time_str: str = "09:00:00"
    active_vol: Decimal = Decimal("1")
    margin_ratio: Decimal = Decimal("0")
    risk_guard_active: bool = False


@dataclass(frozen=True)
class Track8State:
    is_active: bool = False
    premium_spent: Decimal = Decimal("0")
    call_strike: Decimal = Decimal("0")
    put_strike: Decimal = Decimal("0")
    qty_call: int = 0
    qty_put: int = 0
    entry_date: str | None = None
    high_watermark_intrinsic: Decimal = Decimal("0")
    trailing_stop_active: bool = False
    hysteresis_hold_counter: int = 0


class Track8MacroRegimeMonthlyStrangle:
    strategy_id = "track8_macro_regime_monthly_strangle"
    version = "1.0"
    MIN_BUDGET = Decimal("200000")
    DTE_ENTRY = Decimal("15")
    STRIKE_OFFSET = Decimal("15")
    MULTIPLIER = Decimal("250000")
    PROFIT_TARGET = Decimal("300000")

    def __init__(self, profit_target: Decimal = PROFIT_TARGET) -> None:
        self.profit_target = profit_target
        self.state = Track8State()

    def initialize(self, context: StrategyContext) -> None:
        self.reset()

    def on_market_state(self, context: StrategyContext) -> None:
        return None

    def reset(self) -> None:
        self.state = Track8State()

    @staticmethod
    def atm_strike(price: Decimal) -> Decimal:
        return (price / Decimal("2.5")).to_integral_value() * Decimal("2.5")

    def evaluate_entry(self, data: Track8MarketInput) -> Sequence[Signal]:
        if self.state.entry_date is not None and self.state.entry_date != data.date_str:
            self.reset()
        if self.state.is_active:
            return ()
        if data.dte < self.DTE_ENTRY or data.budget < self.MIN_BUDGET:
            return ()

        skew_ratio = Decimal("2") if data.current_regime == "HIGH_VOL" else Decimal("1.5")
        atm = self.atm_strike(data.current_price)
        call_strike = atm + self.STRIKE_OFFSET
        put_strike = atm - self.STRIKE_OFFSET
        unit_cost = (Decimal("1.20") + skew_ratio * Decimal("1.50")) * self.MULTIPLIER
        base_qty = max(1, int(data.budget / max(Decimal("1"), unit_cost)))
        qty_call = base_qty
        qty_put = int(Decimal(base_qty) * skew_ratio)
        estimated_cost = (Decimal(qty_call) * Decimal("1.20") + Decimal(qty_put) * Decimal("1.50")) * self.MULTIPLIER
        if data.budget < estimated_cost:
            return ()

        self.state = replace(
            self.state,
            is_active=True,
            premium_spent=estimated_cost,
            call_strike=call_strike,
            put_strike=put_strike,
            qty_call=qty_call,
            qty_put=qty_put,
            entry_date=data.date_str,
        )
        return (
            Signal(
                self.strategy_id,
                "BUY_LIMIT_TRANCHE",
                1.0,
                f"DTE:{data.dte};CALL:{call_strike};PUT:{put_strike};"
                f"QTY_CALL:{qty_call};QTY_PUT:{qty_put};"
                "PRICING:MID_PRICE_OFFSET;TICK:1;FALLBACK_SEC:5",
            ),
        )

    def build_execution_plan(self, group_id: str) -> MultiLegExecutionPlan | None:
        if not self.state.is_active or self.state.call_strike <= 0 or self.state.put_strike <= 0:
            return None
        return build_pair_plan(
            group_id=group_id, strategy_id=self.strategy_id, purpose="MONTHLY_STRANGLE_ENTRY",
            put_strike=self.state.put_strike, call_strike=self.state.call_strike,
            put_quantity=self.state.qty_put, call_quantity=self.state.qty_call, side="BUY",
        )

    def evaluate_take_profit(self, data: Track8MarketInput) -> Sequence[Signal]:
        if not self.state.is_active:
            return ()

        qty = max(self.state.qty_call, self.state.qty_put, 1)
        put_intrinsic = max(Decimal("0"), self.state.put_strike - data.current_price) * self.MULTIPLIER * qty
        call_intrinsic = max(Decimal("0"), data.current_price - self.state.call_strike) * self.MULTIPLIER * qty
        intrinsic = put_intrinsic + call_intrinsic
        min_multiplier = Decimal("1.8") if data.active_vol < Decimal("1.3") else Decimal("2.5")

        if intrinsic < self.state.premium_spent * min_multiplier:
            return ()

        prev_high = self.state.high_watermark_intrinsic
        high = max(prev_high, intrinsic)
        pnl_ratio = high / max(Decimal("1"), self.state.premium_spent)
        ratio = (
            Decimal("0.90") if pnl_ratio >= Decimal("2")
            else Decimal("0.88") if pnl_ratio >= Decimal("1.3")
            else Decimal("0.85")
        )
        stop = high * ratio

        if intrinsic <= stop:
            self.reset()
            return (
                Signal(
                    self.strategy_id,
                    "TAKE_PROFIT_HYBRID_TRAILING_STOP",
                    1.0,
                    f"REALIZED:{intrinsic};HIGH:{high};RATIO:{ratio}",
                ),
            )

        self.state = replace(
            self.state,
            trailing_stop_active=True,
            high_watermark_intrinsic=high,
        )
        if prev_high == 0 or high >= prev_high * Decimal("1.01"):
            return (
                Signal(
                    self.strategy_id,
                    "UPDATE_TRAILING",
                    0.9,
                    f"HIGH:{high};STOP:{stop};OFFSET_TICKS:2;FALLBACK_SEC:2",
                ),
            )
        return ()

    def evaluate_macro_regime_protection(self, data: Track8MarketInput) -> Sequence[Signal]:
        if data.current_regime in {"HIGH_VOL", "CIRCUIT_BREAKER", "CRASH"}:
            return (
                Signal(
                    self.strategy_id,
                    "MACRO_HEDGE_SCALE_UP",
                    1.0,
                    f"REGIME:{data.current_regime};HEDGE_MULTIPLIER:1.5",
                ),
            )
        return ()

    def evaluate_profit_rebuild(self, data: Track8MarketInput) -> Sequence[Signal]:
        if not self.state.is_active:
            return ()
        if data.risk_guard_active or data.margin_ratio > Decimal("0.85"):
            return ()

        net_pnl = data.current_pnl - data.total_fees
        if net_pnl < self.profit_target:
            return ()

        old_call, old_put = self.state.call_strike, self.state.put_strike
        atm = self.atm_strike(data.current_price)
        new_call, new_put = atm + self.STRIKE_OFFSET, atm - self.STRIKE_OFFSET
        qty = max(self.state.qty_call, self.state.qty_put, 1)

        self.state = replace(
            self.state,
            is_active=True,
            call_strike=new_call,
            put_strike=new_put,
            high_watermark_intrinsic=Decimal("0"),
            trailing_stop_active=False,
        )
        return (
            Signal(
                self.strategy_id,
                "DYNAMIC_PROFIT_TAKE",
                1.0,
                f"OLD_CALL:{old_call};OLD_PUT:{old_put};NET_PNL:{net_pnl}",
            ),
            Signal(
                self.strategy_id,
                "DYNAMIC_REBUILD_FENCE",
                1.0,
                f"CALL:{new_call};PUT:{new_put};QTY:{qty}",
            ),
        )

    def evaluate_expiry_cutoff(self, data: Track8MarketInput) -> Sequence[Signal]:
        if not self.state.is_active:
            return ()

        if "15:15" <= data.time_str < "15:20":
            return (
                Signal(
                    self.strategy_id,
                    "CANCEL_PENDING_TRANCHES",
                    1.0,
                    "15:15_CANCEL_PENDING_TRANCHES",
                ),
            )

        if data.dte > Decimal("4"):
            return ()

        call_k, put_k = self.state.call_strike, self.state.put_strike
        near_call = call_k > 0 and abs(data.current_price - call_k) / max(Decimal("1"), call_k) <= Decimal("0.03")
        near_put = put_k > 0 and abs(data.current_price - put_k) / max(Decimal("1"), put_k) <= Decimal("0.03")
        iv_expanded = data.active_vol >= Decimal("1.5")

        if near_call or near_put or iv_expanded:
            self.state = replace(
                self.state,
                hysteresis_hold_counter=self.state.hysteresis_hold_counter + 1,
            )
            return (
                Signal(
                    self.strategy_id,
                    "HOLD_LONG_ATTACK",
                    0.9,
                    "D4_D0_MONEYNESS_OR_IV_EXPANSION",
                ),
            )

        if self.state.hysteresis_hold_counter > 0:
            self.state = replace(
                self.state,
                hysteresis_hold_counter=self.state.hysteresis_hold_counter - 1,
            )
            return (
                Signal(
                    self.strategy_id,
                    "HOLD_HYSTERESIS",
                    0.8,
                    "TIME_WEIGHTED_HYSTERESIS",
                ),
            )

        spent, qty_call, qty_put = (
            self.state.premium_spent,
            self.state.qty_call,
            self.state.qty_put,
        )
        self.reset()
        return (
            Signal(
                self.strategy_id,
                "FLAT_STRANGLE",
                1.0,
                f"DTE:{data.dte};QTY_CALL:{qty_call};QTY_PUT:{qty_put};SPENT:{spent}",
            ),
        )

    def evaluate_input(self, data: Track8MarketInput) -> Sequence[Signal]:
        signals: list[Signal] = []
        signals.extend(self.evaluate_entry(data))
        signals.extend(self.evaluate_macro_regime_protection(data))
        signals.extend(self.evaluate_take_profit(data))
        signals.extend(self.evaluate_profit_rebuild(data))
        signals.extend(self.evaluate_expiry_cutoff(data))
        return tuple(signals)

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        if context.strategy_id != self.strategy_id:
            return ()
        data = context.input.payload
        if not isinstance(data, Track8MarketInput):
            return ()
        if data.strategy_id != self.strategy_id:
            return ()
        return self.evaluate_input(data)
```
원격 Exp_Detail_1/option_program/strategy/plugins/track8.py 기준으로 Track8의 Monthly Wide Strangle, Macro Regime Protection, Dynamic Profit Rebuild, D-4~D-0 Moneyness/IV 재평가와 시간가중 Hysteresis를 Standard Core에 유지했다.
    - 표준 입력: StrategyContext.input.payload
    - Context/payload strategy_id 이중 검증
    - Legacy track8_input 임의 속성 제거
    - 15:15 pending tranche cancel 유지
    - Profit Rebuild risk_guard/margin_ratio 차단 유지
    - 실제 주문 큐·지정가·fallback 실행은 Environment Execution 계층 책임

[Child Page] track9_event_overnight_insurance.py
```python
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Sequence

from core.strategy.contracts import Signal, StrategyContext, StrategyInput
from core.strategy.multi_leg_plan import build_pair_plan
from contracts.types import MultiLegExecutionPlan


@dataclass(frozen=True)
class Track9MarketInput:
    strategy_id: str
    current_price: Decimal
    active_sell_qty: int
    current_insurance_qty: int
    date_str: str
    time_str: str = "09:00:00"
    is_event_upcoming: bool = False
    iv_spike: Decimal = Decimal("0")
    iv_crush: Decimal = Decimal("0")
    current_pnl: Decimal = Decimal("0")
    total_fees: Decimal = Decimal("0")
    premium_spent: Decimal = Decimal("250000")
    target_insurance_qty: int | None = None
    market_stable: bool = True
    target_qty: int = 0
    existing_qty: int = 0
    margin_ratio: Decimal = Decimal("0")
    risk_guard_active: bool = False
    event_budget: Decimal = Decimal("0")
    estimated_event_cost: Decimal = Decimal("0")


@dataclass(frozen=True)
class Track9State:
    event_active: bool = False
    early_profit_take_executed_today: bool = False
    reentry_executed_today: bool = False
    state: str = "OVERNIGHT_HEDGE"
    event_high_pnl: Decimal = Decimal("0")
    active_date: str | None = None


class Track9EventOvernightInsurance:
    strategy_id = "track9_event_overnight_insurance"
    version = "1.0"
    STRIKE_OFFSET = Decimal("15")
    PREMIUM_COST = Decimal("0.15")
    EVENT_IV_SPIKE = Decimal("4")
    VOL_CRUSH = Decimal("-3")
    PROFIT_TARGET = Decimal("400000")

    def __init__(
        self,
        strike_offset: Decimal = STRIKE_OFFSET,
        early_profit_take_ratio: Decimal = Decimal("0.90"),
        profit_target: Decimal = PROFIT_TARGET,
    ) -> None:
        self.strike_offset = strike_offset
        self.early_profit_take_ratio = early_profit_take_ratio
        self.profit_target = profit_target
        self.state = Track9State()

    def initialize(self, context: StrategyContext) -> None:
        self.reset()

    def on_market_state(self, context: StrategyContext) -> None:
        return None

    def reset(self) -> None:
        self.state = Track9State()

    def _sync_date(self, date_str: str) -> None:
        if self.state.active_date is not None and self.state.active_date != date_str:
            self.reset()
        if self.state.active_date is None:
            self.state = replace(self.state, active_date=date_str)

    @staticmethod
    def atm_strike(price: Decimal) -> Decimal:
        return (price / Decimal("2.5")).to_integral_value() * Decimal("2.5")

    def target_overnight_insurance_qty(self, active_sell_qty: int) -> int:
        return max(1, int(Decimal(active_sell_qty) * Decimal("0.5")))

    def build_pair_execution_plan(self, group_id: str, purpose: str, current_price: Decimal, quantity: int) -> MultiLegExecutionPlan:
        atm = self.atm_strike(current_price)
        return build_pair_plan(
            group_id=group_id, strategy_id=self.strategy_id, purpose=purpose,
            put_strike=atm - self.strike_offset, call_strike=atm + self.strike_offset,
            put_quantity=quantity, call_quantity=quantity, side="BUY",
        )

    def evaluate_overnight_insurance(self, data: Track9MarketInput) -> Sequence[Signal]:
        self._sync_date(data.date_str)
        target = (
            data.target_insurance_qty
            if data.target_insurance_qty is not None
            else self.target_overnight_insurance_qty(data.active_sell_qty)
        )
        diff = target - data.current_insurance_qty
        if diff == 0:
            return (Signal(self.strategy_id, "HOLD_INSURANCE", 1.0, f"TARGET_QTY:{target}"),)

        if diff > 0:
            atm = self.atm_strike(data.current_price)
            return (
                Signal(
                    self.strategy_id,
                    "ADD_INSURANCE",
                    1.0,
                    f"TARGET_QTY:{target};DIFF:{diff};"
                    f"PUT:{atm-self.strike_offset};CALL:{atm+self.strike_offset};"
                    "PRICING:MID_PRICE_OFFSET;TICK:1;FALLBACK_SEC:2",
                ),
            )
        return (
            Signal(
                self.strategy_id,
                "REDUCE_INSURANCE",
                1.0,
                f"TARGET_QTY:{target};DIFF:{abs(diff)}",
            ),
        )

    def evaluate_early_profit_take(self, data: Track9MarketInput) -> Sequence[Signal]:
        if self.state.early_profit_take_executed_today:
            return ()
        if "09:00:00" <= data.time_str <= "09:05:00" and data.current_insurance_qty > 0:
            qty = max(1, int(Decimal(data.current_insurance_qty) * self.early_profit_take_ratio))
            self.state = replace(
                self.state,
                early_profit_take_executed_today=True,
                state="EARLY_PROFIT_TAKEN",
            )
            return (
                Signal(
                    self.strategy_id,
                    "EARLY_PROFIT_TAKE",
                    1.0,
                    f"QTY:{qty};RATIO:{self.early_profit_take_ratio};"
                    "PRICING:PREEMPTIVE_LIMIT_OR_MARKET",
                ),
            )
        if data.time_str > "09:05:00" and not self.state.early_profit_take_executed_today:
            self.state = replace(self.state, state="MARKET_STABILIZATION_MONITORING")
        return ()

    def evaluate_reentry(self, data: Track9MarketInput) -> Sequence[Signal]:
        if data.time_str < "09:30:00" or self.state.reentry_executed_today:
            return ()
        if data.market_stable and data.target_qty > data.existing_qty:
            qty = data.target_qty - data.existing_qty
            atm = self.atm_strike(data.current_price)
            self.state = replace(
                self.state,
                reentry_executed_today=True,
                state="REHEDGE_ACTIVE",
            )
            return (
                Signal(
                    self.strategy_id,
                    "REHEDGE_ENTRY",
                    1.0,
                    f"QTY:{qty};PUT:{atm-self.strike_offset};CALL:{atm+self.strike_offset};"
                    "PRICING:MID_PRICE_OFFSET;TICK:1",
                ),
            )
        return ()

    def evaluate_event_volatility(self, data: Track9MarketInput) -> Sequence[Signal]:
        self._sync_date(data.date_str)
        net_pnl = data.current_pnl - data.total_fees

        if not self.state.event_active:
            if not (data.is_event_upcoming or data.iv_spike >= self.EVENT_IV_SPIKE):
                return ()
            if data.event_budget > 0 and data.estimated_event_cost > data.event_budget:
                return (
                    Signal(
                        self.strategy_id,
                        "EVENT_BUDGET_BLOCKED",
                        1.0,
                        f"BUDGET:{data.event_budget};COST:{data.estimated_event_cost}",
                    ),
                )
            self.state = replace(
                self.state,
                event_active=True,
                event_high_pnl=max(Decimal("0"), net_pnl),
                state="EVENT_ACTIVE",
            )
            return (
                Signal(
                    self.strategy_id,
                    "ENTER_EVENT_STRANGLE",
                    1.0,
                    f"EVENT:{data.is_event_upcoming};IV_SPIKE:{data.iv_spike};"
                    "PRICING:MID_PRICE_OFFSET;TICK:1;FALLBACK_SEC:2;QTY:1",
                ),
            )

        high = max(self.state.event_high_pnl, net_pnl)
        spent = max(Decimal("1"), data.premium_spent)
        pnl_ratio = high / spent
        trailing_ratio = (
            Decimal("0.90") if pnl_ratio >= Decimal("2")
            else Decimal("0.88") if pnl_ratio >= Decimal("1.3")
            else Decimal("0.85")
        )

        if high > Decimal("50000") and net_pnl <= high * trailing_ratio:
            self.state = replace(self.state, event_active=False, state="EVENT_TRAILING_STOP")
            return (
                Signal(
                    self.strategy_id,
                    "CLOSE_EVENT_STRANGLE",
                    1.0,
                    f"TRAILING_STOP;HIGH:{high};RATIO:{trailing_ratio};"
                    "PRICING:PREEMPTIVE_STOP_LIMIT_QUEUE;OFFSET_TICKS:2",
                ),
            )

        if data.iv_crush <= self.VOL_CRUSH:
            self.state = replace(self.state, event_active=False, state="EVENT_CLOSED")
            return (
                Signal(
                    self.strategy_id,
                    "CLOSE_EVENT_STRANGLE",
                    1.0,
                    f"VOL_CRUSH:{data.iv_crush};PRICING:MID_PRICE_OFFSET;TICK:1",
                ),
            )

        self.state = replace(self.state, event_active=True, event_high_pnl=high)
        return ()

    def evaluate_dynamic_profit_rebuild(self, data: Track9MarketInput) -> Sequence[Signal]:
        if data.risk_guard_active or data.margin_ratio > Decimal("0.85"):
            return ()
        net_pnl = data.current_pnl - data.total_fees
        if net_pnl < self.profit_target:
            return ()

        call = self.atm_strike(data.current_price) + self.strike_offset
        put = self.atm_strike(data.current_price) - self.strike_offset
        qty = max(data.current_insurance_qty, data.target_qty, 1)
        self.state = replace(self.state, reentry_executed_today=True, state="REHEDGE_ACTIVE")
        return (
            Signal(
                self.strategy_id,
                "DYNAMIC_PROFIT_TAKE",
                1.0,
                f"NET_PNL:{net_pnl};QTY:{qty};TIME:{data.time_str}",
            ),
            Signal(
                self.strategy_id,
                "DYNAMIC_REBUILD_FENCE",
                1.0,
                f"CALL:{call};PUT:{put};QTY:{qty}",
            ),
        )

    def evaluate_input(self, data: Track9MarketInput) -> Sequence[Signal]:
        signals: list[Signal] = []
        signals.extend(self.evaluate_overnight_insurance(data))
        signals.extend(self.evaluate_early_profit_take(data))
        signals.extend(self.evaluate_reentry(data))
        signals.extend(self.evaluate_event_volatility(data))
        signals.extend(self.evaluate_dynamic_profit_rebuild(data))
        return tuple(signals)

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        if context.strategy_id != self.strategy_id:
            return ()
        data = context.input.payload
        if not isinstance(data, Track9MarketInput):
            return ()
        if data.strategy_id != self.strategy_id:
            return ()
        return self.evaluate_input(data)
```
원격 Exp_Detail_1/option_program/strategy/plugins/track9.py를 기준으로 Track9의 기능을 유지하면서 입력 경계를 표준 StrategyContext.input.payload로 통일했다.
    - Track1 활성 가두리 매도 수량의 50% Overnight Insurance
    - 09:00~09:05 Early Profit Take
    - 09:30 이후 시장 안정화 Re-entry
    - Event Upcoming / IV Spike Event Long Strangle
    - Event 이후 Vol Crush 및 3단계 Dynamic Trailing Stop
    - Net PnL 기반 Dynamic Profit Take & Rebuild
    - Risk Guard / Margin > 0.85 Rebuild 차단
    - 이벤트 예산 부족은 Strategy가 직접 AtomicBudgetManager를 실행하지 않고 Execution 경계에서 처리할 수 있도록 Signal화
    - Legacy getattr(context, "track9_input") 제거
    - Context/payload strategy_id 이중 검증
    - 실제 Atomic budget 동시성, 주문 큐, 지정가·fallback 실행은 Environment/Execution 계층 책임

[Child Page] standard_core_verification_runner.py
```python
"""Independent verification entry point for the Standard Core full integration test.

This file is a verification harness specification. It must not be treated as a
production Runtime component and must not import Legacy Runtime modules.
"""

from core.strategy.test_standard_strategy_orchestrator_full_integration import (
    test_all_contexts_match_standard_identity_manifest,
    test_all_nine_actual_strategies_complete_full_lifecycle,
    test_registry_accepts_strategy_payloads_without_optional_identity_field,
    test_reset_rebuilds_lifecycle_without_cross_strategy_state_sharing,
    test_same_fresh_registry_and_fixture_is_deterministic,
)


def run_independent_verification() -> None:
    """Run the five Standard Core integration assertions directly."""
    test_all_contexts_match_standard_identity_manifest()
    test_all_nine_actual_strategies_complete_full_lifecycle()
    test_registry_accepts_strategy_payloads_without_optional_identity_field()
    test_same_fresh_registry_and_fixture_is_deterministic()
    test_reset_rebuilds_lifecycle_without_cross_strategy_state_sharing()
    print("STANDARD_CORE_FULL_INTEGRATION_PASS")


if __name__ == "__main__":
    run_independent_verification()
```
## 목적
No.064에서 지정한 다음 단계인 실제 실행 가능한 독립 검증 경로를 고정한다. 이 harness는 Production Runtime이나 Legacy Runtime에 편입하지 않고 Standard Core Test만 직접 호출한다.
## 실행 경로
권장 1차 경로:
```plain text
python -m core.strategy.standard_core_verification_runner
```
pytest가 설치된 일반 개발환경에서는 기존 테스트도 별도로 실행한다.
```plain text
python -m pytest core/strategy/test_standard_strategy_orchestrator_full_integration.py -q
```
## 검증 범위
    1. STANDARD_STRATEGY_KEYS canonical identity와 9개 Context의 일치
    1. 실제 Track별 typed payload와 canonical MarketState 공급
    1. initialize -> on_market_state -> evaluate 전체 lifecycle
    1. Strategy 단위 failure가 없는지 확인
    1. fresh registry/fixture 반복 실행의 deterministic identity
    1. reset 후 state isolation
## 중요 제한
    - 이 파일 자체를 Production Runtime에 연결하지 않는다.
    - option_program/strategy/** Legacy Runtime을 import하지 않는다.
    - Broker/API/UI/Environment fixture를 추가하지 않는다.
    - Signal 개수나 특정 매매성과를 보편적 성공 조건으로 추가하지 않는다.
    - 원격 Exp_Detail_1에는 이 harness를 추가하지 않는다. 현재 작업공간은 Notion이며 원격 branch는 읽기/검증 기준으로만 사용한다.
## 실행 결과 기록 기준
PASS는 실제 실행 결과가 확보된 경우에만 기록한다. 정적 코드 검토, import 경로 추정, GitHub 기존 Quality Gate PASS는 이 Test의 PASS 증거로 사용하지 않는다.
## 현재 상태
현재 환경에서 이 harness를 실제 Python 프로세스로 실행했다는 증거는 아직 없다. 따라서 본 페이지 생성만으로 PASS를 선언하지 않는다.

[Child Page] strategy_execution_proposal.py
```python
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class StrategyExecutionProposal:
    """Strategy가 실제 실행에 필요하다고 제안한 값의 표준 운반 계약.

    이 계약은 승인 수량이나 주문 실행 의미를 결정하지 않는다.
    누락된 값은 임의의 기본값으로 채우지 않는다.
    """

    proposed_quantity: int
    asset_type: str
    requested_price: Decimal | None = None
    side: str | None = None
    track_id: str | None = None
    tag_id: str | None = None
    option_type: str | None = None
    strike: Decimal | None = None

    def __post_init__(self) -> None:
        if self.proposed_quantity <= 0:
            raise ValueError("PROPOSED_QUANTITY_REQUIRED")
        if not self.asset_type:
            raise ValueError("ASSET_TYPE_REQUIRED")
        if self.requested_price is not None and self.requested_price <= 0:
            raise ValueError("REQUESTED_PRICE_MUST_BE_POSITIVE")
        if self.strike is not None and self.strike <= 0:
            raise ValueError("STRIKE_MUST_BE_POSITIVE")
```
## 역할
Track 1~9의 기존 결과에서 실제로 존재하는 실행 제안값을 Standard 경계까지 보존하기 위한 최소 typed transport다.
## 보존 대상
    - proposed_quantity: 전략이 제안한 수량
    - requested_price: 전략 결과에 실제 존재하는 요청가격
    - asset_type: OPTION/FUTURES 등 실제 전략 결과의 자산 유형
    - side: 실제 결과에 명시된 경우에만 보존
    - track_id, tag_id: provenance
    - option_type, strike: 실제 옵션 선택값이 존재할 때만 보존
## 책임 분리
    - proposed_quantity는 승인 수량이 아니다.
    - requested_price는 체결가격이 아니다.
    - order_type, order_purpose는 이 계약에 넣지 않는다. 상위 Position/Risk/Order Policy의 authoritative 공급값으로 유지한다.
    - symbol/expiry/instrument_id는 이 계약에서 생성하지 않는다. 기존 OptionIdentityResolver/Master 경계를 사용한다.
    - 값이 없는 경우 임의의 1, 현재가, KOSPI200, CALL/PUT 등을 생성하지 않는다.
## 현재 상태
계약만 추가한다. 기존 Signal, StrategyOrchestrator, Track 1~9에는 아직 연결하지 않는다. 실제 전략별 공급값을 확인한 후 단계적으로 연결한다.

[Child Page] canonical_signal_adapter.py
```python
from dataclasses import dataclass
from typing import Optional

from contracts.types import OptionInstrumentIdentity
from core.strategy.contracts import Signal
from shared.contracts.canonical import (
    CanonicalAssetType,
    CanonicalOrderSide,
    CanonicalOptionType,
    CanonicalStrategySignal,
)


@dataclass(frozen=True)
class RuntimeSignalContext:
    """Authoritative values supplied by Runtime/Controller, not Strategy."""
    signal_id: str
    track_id: str
    price: float
    timestamp: str


def _require_non_empty(value: str, field_name: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise ValueError(f"{field_name}_REQUIRED")
    return value


def signal_to_canonical(
    signal: Signal,
    runtime: RuntimeSignalContext,
    instrument_identity: Optional[OptionInstrumentIdentity] = None,
) -> CanonicalStrategySignal:
    """Convert Standard Signal without generating missing authoritative values."""
    signal_id = _require_non_empty(runtime.signal_id, "SIGNAL_ID")
    track_id = _require_non_empty(runtime.track_id, "TRACK_ID")
    proposal = signal.execution_proposal
    if proposal is None:
        raise ValueError("EXECUTION_PROPOSAL_REQUIRED")
    if proposal.proposed_quantity <= 0:
        raise ValueError("QTY_REQUIRED")
    if not proposal.asset_type:
        raise ValueError("ASSET_TYPE_REQUIRED")
    if not proposal.side:
        raise ValueError("SIDE_REQUIRED")

    asset_type = CanonicalAssetType(str(proposal.asset_type))
    side = CanonicalOrderSide(str(proposal.side))
    signal_identity: Optional[OptionInstrumentIdentity] = signal.instrument_identity
    if signal_identity is not None and instrument_identity is not None and signal_identity != instrument_identity:
        raise ValueError("OPTION_IDENTITY_MISMATCH")
    identity: Optional[OptionInstrumentIdentity] = signal_identity or instrument_identity
    option_type: Optional[CanonicalOptionType] = None
    strike = 0.0
    symbol = ""
    expiry = ""
    instrument_id = ""

    if asset_type == CanonicalAssetType.OPTION:
        if identity is None:
            raise ValueError("OPTION_IDENTITY_REQUIRED")
        if not identity.instrument_id or not identity.symbol or not identity.expiry:
            raise ValueError("OPTION_IDENTITY_INCOMPLETE")
        if identity.option_type is None or identity.strike is None:
            raise ValueError("OPTION_IDENTITY_INCOMPLETE")
        if proposal.option_type is not None and str(proposal.option_type) != str(identity.option_type):
            raise ValueError("OPTION_TYPE_IDENTITY_MISMATCH")
        if proposal.strike is not None and proposal.strike != identity.strike:
            raise ValueError("STRIKE_IDENTITY_MISMATCH")
        option_type = CanonicalOptionType(str(identity.option_type))
        strike = float(identity.strike)
        symbol = identity.symbol
        expiry = identity.expiry
        instrument_id = identity.instrument_id

    return CanonicalStrategySignal(
        signal_id=signal_id,
        track_id=track_id,
        asset_type=asset_type,
        side=side,
        qty=proposal.proposed_quantity,
        price=float(runtime.price),
        option_type=option_type,
        strike=strike,
        tag_id=str(proposal.tag_id) if proposal.tag_id is not None else "",
        reason=signal.reason,
        timestamp=runtime.timestamp,
        symbol=symbol,
        expiry=expiry,
        instrument_id=instrument_id,
    )
```
## 최소 입력 계약
    - RuntimeSignalContext.signal_id: Runtime/Controller authoritative 공급. Adapter에서 생성하지 않음.
    - RuntimeSignalContext.track_id: 명시 공급. strategy_id로 대체하지 않음.
    - RuntimeSignalContext.price, timestamp: Runtime/Controller가 실제 입력으로 공급.
    - Signal.execution_proposal: 실제 qty / asset_type / side / tag_id / option_type / strike 공급원.
    - Signal.instrument_identity: 이미 Signal에 authoritative identity가 보존된 경우의 공급원.
    - instrument_identity 인자: Runtime/Controller/Resolver가 별도로 공급하는 authoritative identity. Strategy가 생성하지 않는다.
    - 두 identity가 동시에 존재하면 완전히 동일해야 하며 불일치 시 fail-closed.
    - OPTION identity가 최종 입력에 없거나 불완전하면 fail-closed.
    - Proposal의 option_type/strike가 존재할 경우 identity와 동일할 때만 보존.
    - FUTURES는 OptionInstrumentIdentity를 요구하지 않으며 option_type/strike는 비적용값으로 둔다.
    - Adapter는 Signal을 변경하지 않으며 CanonicalStrategySignal도 생성 후 변경하지 않는다.
## 적용 판단
Track1은 Strategy가 option_type/strike를 생성하지만 상품코드 자체를 만들지 않는다. 따라서 Track1 Signal에 authoritative OptionInstrumentIdentity를 외부에서 공급할 수 있을 때만 OPTION Canonical 변환을 허용한다. Adapter는 strike/type으로 instrument_id를 합성하지 않는다. Track4는 기존과 같이 Futures Proposal과 RuntimeSignalContext가 공급되면 변환할 수 있다. StrategyOrchestrator에 Runtime sequence나 상품 identity 생성 책임을 추가하지 않는다.