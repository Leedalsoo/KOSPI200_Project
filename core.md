폴더: 환경 독립 Standard Option Core.

[Child Page] domain
폴더 페이지
[Child Page] market_models.py
```python
from contracts.types import CanonicalMarketTick, DataQuality, MarketState


__all__ = ("CanonicalMarketTick", "DataQuality", "MarketState")
```
## Ownership correction
Canonical market DTO ownership is contracts/types.py.
This module remains as the existing Core-domain import surface so current Standard Core code can continue importing CanonicalMarketTick, DataQuality, and MarketState without creating a second DTO definition.
Rules remain unchanged: missing market data is explicit and synthetic fallback prices must not masquerade as real input.
[Child Page] option_contract.py
```python
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

@dataclass(frozen=True)
class OptionContract:
    instrument_id: str
    underlying_id: str
    option_type: str
    strike: Decimal
    expiry: date

class TradingCalendar(Protocol):
    def trading_days_between(self, start: date, end: date) -> int: ...

def calculate_dte(contract: OptionContract, today: date, calendar: TradingCalendar) -> int:
    return calendar.trading_days_between(today, contract.expiry)
```
External master download and Calendar source implementation are outside Core. Unverified production calendar remains BLOCKED.

[Child Page] strategy
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

[Child Page] signal
폴더 페이지
[Child Page] signal_processor.py
## 역할
Legacy option_program/strategy/signal_generator.py의 환경 독립 기능을 Standard Core Signal 계층으로 이식한다.
## 이식 범위
        - signal 필수 필드 검증
        - qty > 0 검증
        - price > 0 검증
        - track_id / tag_id 필수 검증
        - OPTION일 때 strike / option_type 검증
        - fingerprint 기반 debounce 중복 제거
        - clear_history
## 경계
Signal 계층은 KIS/VMS/VSSF/Broker/UI를 호출하지 않는다. 주문 실행도 담당하지 않는다. 검증 통과 결과는 표준 Signal/후속 Order Intent 계층에서 소비한다.
## 주의
Legacy의 CanonicalStrategySignal → CanonicalOrderCommand 직접 변환은 Core Signal 책임과 OMS/Position 책임을 섞으므로 그대로 복사하지 않는다. 주문 명령 생성은 Standard Core Pipeline의 후속 단계로 분리한다.
## 검증 상태
Notion 작업대에 기능 이식 설계를 기록했으며 실제 terminal pytest는 현재 실행할 수 없어 PASS로 판정하지 않는다.
[Child Page] test_signal_processor.py
## 독립 테스트 기준
Legacy SignalGenerator의 검증/중복제거 책임을 Standard Core Signal 계층에서 검증한다.
### 테스트 항목
            1. qty <= 0 신호 거부
            1. price <= 0 신호 거부
            1. track_id 누락 거부
            1. tag_id 누락 거부
            1. OPTION의 strike <= 0 거부
            1. OPTION의 option_type 누락 거부
            1. 동일 fingerprint의 debounce window 내 중복 억제
            1. debounce 이후 동일 신호 재허용
            1. clear_history() 후 재허용
            1. 주문 실행/브로커 호출이 발생하지 않는지 경계 검증
## 판정
기능 이식 기준은 수립했다. 실제 terminal pytest를 실행하지 못했으므로 실행 PASS는 아니다.
## No.085 Identity 전달 규칙
        - Signal Processor는 Signal.instrument_identity를 fingerprint/검증 과정에서 제거하거나 재생성하지 않는다.
        - 옵션 선택 변경은 option_type_override / strike_override처럼 명시적 주문 의도로만 표현한다.
        - Signal 계층은 authoritative symbol/expiry를 legacy 기본값으로 채우지 않는다.
        - 최종 immutable OptionInstrumentIdentity 확정은 OMS/OrderIntent 직전 Resolver가 담당한다.

[Child Page] decision
폴더 페이지
[Child Page] pipeline.py
```python
from dataclasses import dataclass
from typing import Sequence
from contracts.types import OrderIntent
from core.strategy.contracts import Signal

@dataclass(frozen=True)
class Decision:
    action: str
    signals: Sequence[Signal]

@dataclass(frozen=True)
class RiskResult:
    allowed: bool
    quantity: int
    reason: str

@dataclass(frozen=True)
class CorePipeline:
    def evaluate(self, strategy, context, risk_engine, position_logic):
        signals = strategy.evaluate(context)
        decision = self._decide(signals)
        risk = risk_engine.validate(decision, context)
        if not risk.allowed:
            return None
        return position_logic.to_order_intent(decision, risk, context)

    def _decide(self, signals):
        return Decision(action="NO_ACTION" if not signals else "EVALUATE", signals=signals)
```
Actual decision/risk rules are migrated from baseline evidence, not fabricated.
[Child Page] decision_arbiter.py
```python
"""Standard Decision Arbiter migrated from Reference Exp_Detail_1.

The arbiter resolves deterministic cross-strategy signal conflicts while
preserving each canonical signal object unchanged.
"""
from dataclasses import dataclass
from typing import Any, List, Tuple


# Reference values: lower number means higher priority.
STRATEGY_PRIORITY_MAP = {
    "HEDGE_DELTA": 1,
    "HEDGE_TAIL": 1,
    "Track1": 2,
    "Track6": 3,
    "Track9": 3,
    "Track3": 4,
    "Track4": 4,
    "Track7": 5,
    "Track8": 5,
    "Track2": 6,
    "Track5": 6,
}


@dataclass(frozen=True)
class ArbitrationResult:
    """Reference-compatible arbitration result DTO."""

    approved_signals: List[Any]
    rejected_signals: List[Tuple[Any, str]]
    netted_clashes: List[str]


class DecisionArbiter:
    """Deterministic priority and same-instrument side conflict resolver."""

    def __init__(self) -> None:
        pass

    def _get_priority(self, track_id: str) -> int:
        return STRATEGY_PRIORITY_MAP.get(track_id, 99)

    @staticmethod
    def _enum_value(value: Any) -> Any:
        return getattr(value, "value", value)

    @classmethod
    def _instrument_key(cls, signal: Any) -> str:
        asset_type = cls._enum_value(signal.asset_type)
        option_type = cls._enum_value(signal.option_type) if signal.option_type is not None else "NONE"
        return f"{asset_type}_{signal.strike}_{option_type}"

    def arbitrate(self, signals: List[Any], account: Any) -> ArbitrationResult:
        """Apply the Reference Exp_Detail_1 arbitration rules exactly.

        `account` is retained in the API for compatibility. The Reference
        implementation accepts it but does not directly use it in arbitration.
        """
        if not signals:
            return ArbitrationResult([], [], [])

        approved: List[Any] = []
        rejected: List[Tuple[Any, str]] = []
        netted_clashes: List[str] = []

        sorted_signals = sorted(
            signals,
            key=lambda signal: (
                self._get_priority(signal.track_id),
                -signal.qty,
                signal.signal_id,
            ),
        )

        instrument_claims: dict[str, Any] = {}

        for signal in sorted_signals:
            instrument_key = self._instrument_key(signal)
            existing = instrument_claims.get(instrument_key)

            if existing is None:
                instrument_claims[instrument_key] = signal
                approved.append(signal)
                continue

            if existing.side != signal.side:
                existing_side = self._enum_value(existing.side)
                signal_side = self._enum_value(signal.side)
                reason = (
                    f"CLASH_NETTING_REJECTED: Subordinate to "
                    f"{existing.track_id} ({existing_side})"
                )
                rejected.append((signal, reason))
                netted_clashes.append(
                    f"Clash on {instrument_key}: Kept "
                    f"{existing.track_id}({existing_side}), Rejected "
                    f"{signal.track_id}({signal_side})"
                )
            else:
                # Reference behavior: preserve the signal; do not aggregate qty.
                approved.append(signal)

        return ArbitrationResult(
            approved_signals=approved,
            rejected_signals=rejected,
            netted_clashes=netted_clashes,
        )
```
### Migration boundary
        - This module contains only Standard Decision arbitration logic; it does not import Legacy Runtime, KIS, VMS, VSSF, Broker, Risk, or OMS.
        - Canonical signal objects are passed through unchanged.
        - account remains an API-compatible argument but is not used to invent additional rules.
        - Provenance/Envelope remains a transport concern and is not used to recalculate priority or conflict decisions.
        - Quantity is never aggregated or rewritten by the arbiter.
[Child Page] decision_arbiter_envelope_adapter.py
```python
"""Parallel transport adapter between StrategySignalEnvelope and DecisionArbiter.

The adapter preserves the existing List[CanonicalStrategySignal] Decision API.
It does not perform arbitration, priority calculation, conflict detection, or
execution-intent inference.
"""
from typing import Iterable, Any

from core.oms.strategy_signal_envelope import StrategySignalEnvelope


def unwrap_strategy_signal_envelopes(
    envelopes: Iterable[StrategySignalEnvelope],
) -> list[Any]:
    """Return the unchanged canonical signals expected by DecisionArbiter."""
    return [envelope.signal for envelope in envelopes]


def index_strategy_signal_envelopes(
    envelopes: Iterable[StrategySignalEnvelope],
) -> dict[str, StrategySignalEnvelope]:
    """Index envelopes by the existing signal_id; fail closed on duplicates."""
    indexed: dict[str, StrategySignalEnvelope] = {}
    for envelope in envelopes:
        signal_id = envelope.signal_id
        if signal_id in indexed:
            raise ValueError(f"DUPLICATE_SIGNAL_ID: {signal_id}")
        indexed[signal_id] = envelope
    return indexed


def reconnect_approved_signal_envelopes(
    approved_signals: Iterable[Any],
    envelope_index: dict[str, StrategySignalEnvelope],
) -> list[StrategySignalEnvelope]:
    """Reconnect Arbiter output to the original envelopes by signal_id.

    The approved signal objects remain authoritative for Decision output; this
    function only restores the parallel provenance wrapper. Missing IDs fail
    closed rather than inventing or matching by list position.
    """
    result: list[StrategySignalEnvelope] = []
    for signal in approved_signals:
        signal_id = str(signal.signal_id)
        envelope = envelope_index.get(signal_id)
        if envelope is None:
            raise ValueError(f"SIGNAL_ID_NOT_FOUND: {signal_id}")
        if envelope.signal is not signal:
            # A matching ID is necessary but identity preservation is also
            # required: do not silently reconnect a different signal object.
            raise ValueError(f"SIGNAL_OBJECT_MISMATCH: {signal_id}")
        result.append(envelope)
    return result
```
### Boundary rules
        - unwrap_strategy_signal_envelopes() supplies exactly the canonical signal list required by the Reference-compatible DecisionArbiter.
        - index_strategy_signal_envelopes() is only an identity/provenance index and rejects duplicate signal_id.
        - reconnect_approved_signal_envelopes() uses signal_id and object identity; it never matches by list position or recalculates semantics.
        - No priority, sorting, clash, quantity, price, side, asset, strike, option type, order purpose, or order type is changed or inferred.
        - Risk/OMS are not imported and are intentionally outside this boundary.
[Child Page] test_decision_arbiter_envelope_adapter.py
```python
from dataclasses import dataclass
from enum import Enum
from decimal import Decimal

import pytest

from core.decision.decision_arbiter import DecisionArbiter
from core.decision.decision_arbiter_envelope_adapter import (
    index_strategy_signal_envelopes,
    reconnect_approved_signal_envelopes,
    unwrap_strategy_signal_envelopes,
)
from core.oms.execution_provenance import ExecutionProvenance
from core.oms.strategy_signal_envelope import StrategySignalEnvelope


class AssetType(str, Enum):
    OPTION = "OPTION"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OptionType(str, Enum):
    CALL = "CALL"


@dataclass(frozen=True)
class Signal:
    signal_id: str
    track_id: str
    qty: int
    asset_type: AssetType
    strike: Decimal
    option_type: OptionType | None
    side: Side


def make_signal(signal_id: str, track_id: str = "Track1", side: Side = Side.BUY, qty: int = 1):
    return Signal(signal_id, track_id, qty, AssetType.OPTION, Decimal("350"), OptionType.CALL, side)


def make_envelope(signal: Signal, **raw):
    provenance = ExecutionProvenance(
        strategy_id=raw.get("strategy_id"),
        track_id=raw.get("track_id", signal.track_id),
        tag_id=raw.get("tag_id"),
        action=raw.get("action"),
        reason=raw.get("reason"),
        declared_order_purpose=raw.get("order_purpose"),
        declared_order_type=raw.get("order_type"),
        metadata=raw.get("metadata"),
    )
    return StrategySignalEnvelope(signal=signal, provenance=provenance)


def test_unwrap_preserves_same_signal_objects():
    first = make_signal("s1")
    second = make_signal("s2", track_id="Track2")
    envelopes = [make_envelope(first), make_envelope(second)]
    unwrapped = unwrap_strategy_signal_envelopes(envelopes)
    assert unwrapped == [first, second]
    assert unwrapped[0] is first
    assert unwrapped[1] is second


def test_index_rejects_duplicate_signal_id_fail_closed():
    first = make_signal("same")
    second = make_signal("same", track_id="Track2")
    with pytest.raises(ValueError, match=r"DUPLICATE_SIGNAL_ID: same"):
        index_strategy_signal_envelopes([make_envelope(first), make_envelope(second)])


def test_arbiter_output_reconnects_to_original_envelopes_by_signal_id():
    winner = make_signal("winner", track_id="Track1", side=Side.BUY, qty=5)
    loser = make_signal("loser", track_id="Track2", side=Side.SELL, qty=1)
    winner_env = make_envelope(winner, action="OPEN", order_purpose="ENTRY")
    loser_env = make_envelope(loser, action="CLOSE", order_purpose="EXIT")
    envelopes = [winner_env, loser_env]
    index = index_strategy_signal_envelopes(envelopes)

    result = DecisionArbiter().arbitrate(unwrap_strategy_signal_envelopes(envelopes), account=None)
    approved = reconnect_approved_signal_envelopes(result.approved_signals, index)

    assert approved == [winner_env]
    assert approved[0] is winner_env
    assert approved[0].provenance.action == "OPEN"
    assert approved[0].provenance.declared_order_purpose == "ENTRY"


def test_reconnect_fails_closed_for_unknown_signal_id():
    known = make_signal("known")
    unknown = make_signal("unknown")
    index = index_strategy_signal_envelopes([make_envelope(known)])
    with pytest.raises(ValueError, match=r"SIGNAL_ID_NOT_FOUND: unknown"):
        reconnect_approved_signal_envelopes([unknown], index)


def test_reconnect_fails_closed_for_different_object_with_same_signal_id():
    original = make_signal("same")
    replacement = make_signal("same", track_id="Track2")
    index = index_strategy_signal_envelopes([make_envelope(original)])
    with pytest.raises(ValueError, match=r"SIGNAL_OBJECT_MISMATCH: same"):
        reconnect_approved_signal_envelopes([replacement], index)
```
### Verification target
pytest -q core/decision/test_decision_arbiter_envelope_adapter.py
The test intentionally verifies only parallel transport and provenance reconnection. It does not change the Reference branch and does not connect Risk/OMS.

[Child Page] risk
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

[Child Page] position
폴더 페이지
[Child Page] position_aggregate_risk_adapter.py
```python
from collections.abc import Mapping

from core.position.position_aggregate import PositionAggregate, PositionAggregateSource
from core.risk.risk_input import RiskPosition, RiskPositionInput


def position_aggregate_to_risk_input(
    source: PositionAggregateSource,
) -> RiskPositionInput:
    """Map authoritative Standard Position aggregates into the Risk contract."""
    snapshot = source.snapshot()
    if not isinstance(snapshot, Mapping):
        raise TypeError("RISK_POSITION_AGGREGATE_SOURCE_REQUIRED")

    positions: dict[str, RiskPosition] = {}
    for instrument_key, aggregate in snapshot.items():
        if not isinstance(instrument_key, str) or not instrument_key:
            raise TypeError("RISK_POSITION_INSTRUMENT_KEY_REQUIRED")
        if not isinstance(aggregate, PositionAggregate):
            raise TypeError("RISK_POSITION_AGGREGATE_REQUIRED")
        if not isinstance(aggregate.side, str) or not aggregate.side:
            raise TypeError("RISK_POSITION_SIDE_REQUIRED")
        if not isinstance(aggregate.qty, int):
            raise TypeError("RISK_POSITION_QTY_REQUIRED")

        positions[instrument_key] = RiskPosition(
            side=aggregate.side,
            qty=aggregate.qty,
        )

    return RiskPositionInput(positions=positions)
```
## 책임
        - PositionAggregateSource가 공급한 authoritative side/qty를 Risk의 최소 입력 계약으로 전달한다.
        - avg_price는 현재 Risk 입력에 필요하지 않으므로 버린다.
        - side를 quantity 부호, strategy action, order direction 등으로 추론하지 않는다.
        - Reference/VSSF PositionManager를 import하지 않는다.
## Fail-closed
        - source snapshot이 Mapping이 아니면 실패
        - instrument key가 없으면 실패
        - aggregate 타입이 아니면 실패
        - side가 없거나 잘못되면 실패
        - qty가 정수 계약을 만족하지 않으면 실패
## 비책임
        - FIFO/lot attribution
        - 반대방향 체결 계산
        - average price 계산
        - order_type/order_purpose 결정
        - Position state 변경
[Child Page] risk_position.py
## 목적
Authoritative PositionManager 상태의 side/qty를 Standard Core Risk 입력으로 전달하는 최소 Adapter 계약.
## 확인된 기준
        - Reference/VSSF PositionManager는 실제 체결의 side, qty, price, symbol 등을 받아 aggregate position을 관리한다.
        - PaperPositionSnapshot/현재 canonical PositionSnapshot에는 side가 없으므로 canonical snapshot에서 side를 추측하지 않는다.
        - 따라서 authoritative Position source에서 직접 RiskPositionInput을 구성한다.
## 계약
```python
from dataclasses import dataclass
from typing import Mapping

@dataclass(frozen=True)
class RiskPosition:
    side: str
    qty: int

@dataclass(frozen=True)
class RiskPositionInput:
    positions: Mapping[str, RiskPosition]


def position_manager_to_risk_input(position_manager) -> RiskPositionInput:
    positions = getattr(position_manager, "positions", None)
    if not isinstance(positions, Mapping):
        raise TypeError("RISK_POSITION_SOURCE_REQUIRED")

    result = {}
    for instrument_id, state in positions.items():
        if not isinstance(state, Mapping):
            raise TypeError("RISK_POSITION_STATE_REQUIRED")
        side = state.get("side")
        qty = state.get("qty")
        if side is None:
            raise ValueError("RISK_POSITION_SIDE_REQUIRED")
        if qty is None:
            raise ValueError("RISK_POSITION_QTY_REQUIRED")
        result[str(instrument_id)] = RiskPosition(side=str(side), qty=int(qty))
    return RiskPositionInput(positions=result)
```
## 주의
Reference PositionManager.positions는 symbol -> Mapping(qty, avg_price, side) 구조로 확인되었다. Adapter는 이 구조에만 의존한다. PositionSnapshot에 side를 임의 추가하거나 quantity 부호로 side를 추론하지 않는다.
PositionManager의 반대방향 체결/평단/FIFO 규칙 자체는 Adapter 책임이 아니다. Adapter는 이미 aggregate된 authoritative side/qty를 Risk 입력으로 전달하는 역할만 담당한다.
[Child Page] position_aggregate.py
```python
from dataclasses import dataclass
from typing import Mapping, Protocol


@dataclass(frozen=True)
class PositionAggregate:
    """Authoritative aggregate state required by pre-trade Risk."""

    side: str
    qty: int
    avg_price: float | None = None


class PositionAggregateSource(Protocol):
    """Supplies authoritative per-instrument aggregate positions."""

    def snapshot(self) -> Mapping[str, PositionAggregate]:
        ...
```
## 계약 목적
        - Standard Runtime이 Risk에 전달할 authoritative Position 상태를 정의한다.
        - Risk가 FIFO/lot attribution, 반대방향 체결 계산, 평단 계산을 재구현하지 않는다.
        - side와 qty는 source가 최종 aggregate한 값을 그대로 공급한다.
        - avg_price는 현재 Risk 입력에는 필수가 아니므로 provenance/상태 보존을 위한 선택 필드로만 둔다.
## 소유권
        - Standard Core의 Position aggregate 계약이다.
        - Reference/VSSF PositionManager를 import하거나 복제하지 않는다.
        - 기존 contracts.PositionSnapshot의 수량-only read model을 변경하지 않는다.
## 최소 경계
```plain text
Environment / Position implementation
        -> PositionAggregateSource.snapshot()
        -> Mapping[instrument_key, PositionAggregate]
        -> Risk Position Adapter
        -> RiskPositionInput
```
## 금지
        - quantity 부호로 side 추론
        - action/strategy signal로 position side 생성
        - FIFO 또는 lot attribution을 이 계약에 구현
        - order_type / order_purpose 추가
        - Reference DTO 재수출
## 검증 기준
        - 각 instrument의 side/qty가 source 값 그대로 보존되어야 한다.
        - side 또는 qty가 누락된 aggregate는 Risk 경계에서 fail-closed한다.
        - 실제 체결 상태를 관리하는 구현체와 Risk Adapter를 별도로 검증한다.

[Child Page] oms
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

[Child Page] option
폴더 페이지
[Child Page] black_scholes.py
## 목적
표준 Black-Scholes-Merton 유럽형 옵션 가격·Greeks의 순수 계산 함수다. 외부 source를 조회하거나 risk-free rate, DTE, option type을 추정하지 않는다.
## 산식 및 가정
        - 유럽형 옵션.
        - S, K, sigma, T, r, q는 각각 underlying price, strike, annualized volatility, time-to-expiry in years, continuously compounded risk-free rate, continuous dividend yield.
        - T와 r은 호출자가 authoritative source에서 공급한다.
        - option_type은 명시적인 CALL 또는 PUT만 허용한다.
        - theta는 연율(가격 단위/년)이며 일일 theta는 별도의 day-count convention이 확정된 뒤 변환한다.
        - 계산 자체는 업무적 attribution(수량·승수·KRW PnL)을 수행하지 않는다.
검증 참고: Cboe는 Delta/Gamma/Theta를 옵션 risk sensitivity의 핵심 지표로 설명한다. Black-Scholes 유럽형 Greeks의 폐형식은 https://book.derivative-securities.org/Chapter_BlackScholes.html 및 https://quantpie.co.uk/bsm_formula/bs_summary.php 의 식과 대조했다.
```python
from dataclasses import dataclass
from decimal import Decimal
from math import erf, exp, log, pi, sqrt
from typing import Literal

OptionType = Literal["CALL", "PUT"]

class BlackScholesInputError(ValueError):
    pass

@dataclass(frozen=True, slots=True)
class BlackScholesGreeks:
    price: Decimal
    delta: Decimal
    gamma: Decimal
    theta_annual: Decimal

def _cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))

def _pdf(x: float) -> float:
    return exp(-0.5 * x * x) / sqrt(2.0 * pi)

def calculate_black_scholes(*, underlying_price: Decimal, strike: Decimal, time_to_expiry_years: Decimal, volatility: Decimal, risk_free_rate: Decimal, dividend_yield: Decimal, option_type: OptionType) -> BlackScholesGreeks:
    if option_type not in {"CALL", "PUT"}:
        raise BlackScholesInputError("option_type must be CALL or PUT")
    if underlying_price <= 0 or strike <= 0:
        raise BlackScholesInputError("underlying_price and strike must be positive")
    if time_to_expiry_years <= 0:
        raise BlackScholesInputError("time_to_expiry_years must be positive")
    if volatility <= 0:
        raise BlackScholesInputError("volatility must be positive")

    S, K, T = float(underlying_price), float(strike), float(time_to_expiry_years)
    sigma, r, q = float(volatility), float(risk_free_rate), float(dividend_yield)
    sqrt_t = sqrt(T)
    d1 = (log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    discount_r, discount_q = exp(-r * T), exp(-q * T)
    n1 = _pdf(d1)

    if option_type == "CALL":
        price = S * discount_q * _cdf(d1) - K * discount_r * _cdf(d2)
        delta = discount_q * _cdf(d1)
        theta = -discount_q * S * n1 * sigma / (2.0 * sqrt_t) - r * K * discount_r * _cdf(d2) + q * S * discount_q * _cdf(d1)
    else:
        price = K * discount_r * _cdf(-d2) - S * discount_q * _cdf(-d1)
        delta = -discount_q * _cdf(-d1)
        theta = -discount_q * S * n1 * sigma / (2.0 * sqrt_t) + r * K * discount_r * _cdf(-d2) - q * S * discount_q * _cdf(-d1)

    gamma = discount_q * n1 / (S * sigma * sqrt_t)
    return BlackScholesGreeks(Decimal(str(price)), Decimal(str(delta)), Decimal(str(gamma)), Decimal(str(theta)))
```
## 구현 경계
        - Track4OptionValuationInput의 risk_free_rate와 time_to_expiry_years를 이 함수가 생성하지 않는다.
        - KIS가 이미 authoritative Greeks를 공급하는 Track4 runtime에서는 이 계산기로 Greeks를 덮어쓰지 않는다.
        - Production fallback 승격에는 별도 Domain 승인과 source provenance가 필요하다.
[Child Page] option_master.py
```python
# -*- coding: utf-8 -*-
"""Option Contract Master & KIS contract identity registry.

Preserves the legacy expiry lookup while additively retaining authoritative
KIS short/standard-code identity metadata from one raw MST parse boundary.
Calendar behavior is supplied through the standard TradingCalendar contract.
"""
import io
import logging
import re
import urllib.request
import zipfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Dict, Optional

from contracts.trading_calendar import TradingCalendar

logger = logging.getLogger(__name__)
KIS_FO_IDX_MASTER_URL = "https://new.real.download.dws.co.kr/common/master/fo_idx_code_mts.mst.zip"


class KisMasterSourceError(Exception):
    pass


class KisMasterDownloadError(KisMasterSourceError):
    pass


class KisMasterParseError(KisMasterSourceError):
    pass


@dataclass(frozen=True)
class KisOptionContractIdentity:
    shrn_iscd: str
    stnd_iscd: Optional[str]
    expiry: str
    option_type: Optional[str]
    strike: Optional[Decimal]
    info_type: Optional[str] = None


@dataclass(frozen=True)
class KisOptionMasterParseResult:
    legacy_contracts: Dict[str, str]
    identities: Dict[str, KisOptionContractIdentity]


KIS_INFO_TYPE_TO_OPTION_TYPE = {
    "5": "CALL", "D": "CALL", "L": "CALL",
    "6": "PUT", "E": "PUT", "M": "PUT",
}
_OPTION_INFO_TYPES = {"5", "6", "D", "E", "L", "M", "N", "O", "P", "Q", "R", "S"}
_MONTH_PATTERN = re.compile(r"20\d{4}")
_WEEKLY_PATTERN = re.compile(r"(\d{2})(\d{2})W(\d)")


def _require_calendar(calendar: Optional[TradingCalendar]) -> TradingCalendar:
    if calendar is None:
        raise KisMasterParseError(
            "TradingCalendar injection is required; no production calendar source "
            "is owned by OptionContractMaster."
        )
    return calendar


def calculate_krx_monthly_option_expiry(
    year: int, month: int, calendar: TradingCalendar
) -> str:
    first_day = date(year, month, 1)
    first_thursday = 1 + (3 - first_day.weekday()) % 7
    target_date = date(year, month, first_thursday + 7)
    while not calendar.is_trading_day(target_date):
        target_date = calendar.prev_trading_day(target_date)
    return target_date.strftime("%Y-%m-%d")


def calculate_krx_weekly_option_expiry(
    year: int, month: int, week_num: int, calendar: TradingCalendar
) -> str:
    first_day = date(year, month, 1)
    first_thursday = 1 + (3 - first_day.weekday()) % 7
    target_day = first_thursday + (week_num - 1) * 7
    max_days = (date(year, month + 1, 1) - timedelta(days=1)).day if month < 12 else 31
    target_date = date(year, month, min(target_day, max_days))
    while not calendar.is_trading_day(target_date):
        target_date = calendar.prev_trading_day(target_date)
    return target_date.strftime("%Y-%m-%d")


def _is_option_record(prod_type: str, symbol: str, name: str) -> bool:
    return (
        prod_type in _OPTION_INFO_TYPES
        or symbol.startswith(("2", "3", "B", "C"))
        or " C " in name or " P " in name
        or "Call" in name or "Put" in name
    )


def _calculate_expiry(
    symbol: str, name: str, calendar: TradingCalendar
) -> Optional[str]:
    weekly_m = _WEEKLY_PATTERN.search(name) or _WEEKLY_PATTERN.search(symbol)
    if weekly_m:
        try:
            return calculate_krx_weekly_option_expiry(
                2000 + int(weekly_m.group(1)),
                int(weekly_m.group(2)),
                int(weekly_m.group(3)),
                calendar,
            )
        except Exception as exc:
            logger.debug("Weekly option parse note (%s): %s", name, exc)
    month_m = _MONTH_PATTERN.search(name)
    if month_m:
        try:
            ym = month_m.group(0)
            year, month = int(ym[:4]), int(ym[4:6])
            if 1 <= month <= 12:
                return calculate_krx_monthly_option_expiry(year, month, calendar)
        except Exception as exc:
            logger.debug("Monthly option parse note (%s): %s", name, exc)
    return None


def _parse_strike(raw_acpr: str) -> Optional[Decimal]:
    raw_acpr = raw_acpr.strip()
    if not raw_acpr:
        return None
    try:
        value = Decimal(raw_acpr)
    except (InvalidOperation, ValueError):
        return None
    return value if value > 0 else None


def parse_kis_fo_idx_mst_result(
    raw_content: str, calendar: TradingCalendar
) -> KisOptionMasterParseResult:
    if not raw_content or not raw_content.strip():
        return KisOptionMasterParseResult({}, {})
    legacy: Dict[str, str] = {}
    identities: Dict[str, KisOptionContractIdentity] = {}

    for line in raw_content.splitlines():
        if not line or "|" not in line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 4:
            continue
        prod_type, symbol, standard_code, name = parts[:4]
        if not _is_option_record(prod_type, symbol, name):
            continue
        expiry = _calculate_expiry(symbol, name, calendar)
        if not symbol or not expiry:
            continue

        legacy[symbol] = expiry
        if standard_code:
            legacy[standard_code] = expiry

        strike = _parse_strike(parts[5]) if len(parts) >= 6 else None
        identity = KisOptionContractIdentity(
            shrn_iscd=symbol,
            stnd_iscd=standard_code or None,
            expiry=expiry,
            option_type=KIS_INFO_TYPE_TO_OPTION_TYPE.get(prod_type),
            strike=strike,
            info_type=prod_type or None,
        )
        existing = identities.get(symbol)
        if existing is not None and existing != identity:
            raise KisMasterParseError(
                f"Conflicting KIS identity for shrn_iscd '{symbol}'."
            )
        identities[symbol] = identity

    return KisOptionMasterParseResult(legacy, identities)


def parse_kis_fo_idx_mst(
    raw_content: str, calendar: TradingCalendar
) -> Dict[str, str]:
    return parse_kis_fo_idx_mst_result(raw_content, calendar).legacy_contracts


class KisOptionMasterLoader:
    @staticmethod
    def extract_raw_text_from_zip_bytes(zip_bytes: bytes) -> str:
        if not zip_bytes:
            raise KisMasterParseError(
                "Empty zip bytes provided for KIS master loading."
            )
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
                names = archive.namelist()
                target = next(
                    (
                        name for name in names
                        if "fo_idx_code_mts" in name
                        or "fo_idx_code" in name
                        or "optcode" in name
                    ),
                    None,
                )
                target = target or (names[0] if names else None)
                if not target:
                    raise KisMasterParseError(
                        "No valid master file found in zip archive."
                    )
                return archive.read(target).decode("cp949", errors="ignore")
        except KisMasterParseError:
            raise
        except Exception as exc:
            raise KisMasterParseError(
                f"Failed to extract zip archive: {exc}"
            ) from exc

    @classmethod
    def parse_raw_content(
        cls, raw_text: str, calendar: TradingCalendar
    ) -> KisOptionMasterParseResult:
        result = parse_kis_fo_idx_mst_result(raw_text, calendar)
        if not result.legacy_contracts:
            raise KisMasterParseError("Master file parsed 0 contracts.")
        return result

    @classmethod
    def load_result_from_zip_bytes(
        cls, zip_bytes: bytes, calendar: TradingCalendar
    ) -> KisOptionMasterParseResult:
        return cls.parse_raw_content(
            cls.extract_raw_text_from_zip_bytes(zip_bytes), calendar
        )

    @classmethod
    def load_from_zip_bytes(
        cls, zip_bytes: bytes, calendar: TradingCalendar
    ) -> Dict[str, str]:
        return cls.load_result_from_zip_bytes(
            zip_bytes, calendar
        ).legacy_contracts

    @classmethod
    def load_result_from_url(
        cls,
        url: str = KIS_FO_IDX_MASTER_URL,
        timeout: float = 10.0,
        calendar: Optional[TradingCalendar] = None,
    ) -> KisOptionMasterParseResult:
        cal = _require_calendar(calendar)
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return cls.load_result_from_zip_bytes(response.read(), cal)
        except KisMasterParseError:
            raise
        except Exception as exc:
            raise KisMasterDownloadError(
                f"Failed to download KIS master from {url}: {exc}"
            ) from exc

    @classmethod
    def load_from_url(
        cls,
        url: str = KIS_FO_IDX_MASTER_URL,
        timeout: float = 10.0,
        calendar: Optional[TradingCalendar] = None,
    ) -> Dict[str, str]:
        return cls.load_result_from_url(
            url, timeout, calendar
        ).legacy_contracts


class IOptionContractMaster(ABC):
    @abstractmethod
    def get_expiry(self, symbol: str) -> Optional[str]:
        pass

    @abstractmethod
    def register_contract(self, symbol: str, expiry: str) -> None:
        pass

    def get_contract_identity(
        self, shrn_iscd: str
    ) -> Optional[KisOptionContractIdentity]:
        return None

    def register_contract_identity(
        self, identity: KisOptionContractIdentity
    ) -> None:
        raise NotImplementedError(
            "This OptionContractMaster does not support identity registration."
        )

    @property
    def is_loaded(self) -> bool:
        return self.total_contracts > 0

    @property
    @abstractmethod
    def total_contracts(self) -> int:
        pass

    @property
    def last_error(self) -> Optional[str]:
        return None


class _IdentityOptionContractMaster(IOptionContractMaster):
    def _init_identity_registry(self) -> None:
        self._contract_identities: Dict[
            str, KisOptionContractIdentity
        ] = {}

    def get_contract_identity(
        self, shrn_iscd: str
    ) -> Optional[KisOptionContractIdentity]:
        return self._contract_identities.get(
            shrn_iscd.strip()
        ) if shrn_iscd else None

    def register_contract_identity(
        self, identity: KisOptionContractIdentity
    ) -> None:
        key = identity.shrn_iscd.strip()
        if not key:
            raise KisMasterParseError(
                "KIS identity requires non-empty shrn_iscd."
            )
        existing = self._contract_identities.get(key)
        if existing is not None and existing != identity:
            raise KisMasterParseError(
                f"Conflicting registered KIS identity for shrn_iscd '{key}'."
            )
        self._contract_identities[key] = identity
        self.register_contract(key, identity.expiry)
        if identity.stnd_iscd:
            self.register_contract(identity.stnd_iscd, identity.expiry)

    def _apply_parse_result(self, result: KisOptionMasterParseResult) -> None:
        self._contracts.update(result.legacy_contracts)
        for identity in result.identities.values():
            self.register_contract_identity(identity)


class InMemoryOptionContractMaster(_IdentityOptionContractMaster):
    def __init__(
        self,
        contracts: Optional[Dict[str, str]] = None,
        auto_load_kis_source: bool = False,
        calendar: Optional[TradingCalendar] = None,
    ) -> None:
        self._contracts: Dict[str, str] = dict(contracts or {})
        self._init_identity_registry()
        self._last_error: Optional[str] = None
        if auto_load_kis_source and not self._contracts:
            self.load_from_kis_source(calendar=calendar)

    def get_expiry(self, symbol: str) -> Optional[str]:
        return self._contracts.get(symbol.strip()) if symbol else None

    def register_contract(self, symbol: str, expiry: str) -> None:
        if symbol and expiry:
            self._contracts[symbol.strip()] = expiry.strip()

    def load_from_kis_source(
        self,
        calendar: Optional[TradingCalendar] = None,
        url: str = KIS_FO_IDX_MASTER_URL,
    ) -> int:
        try:
            result = KisOptionMasterLoader.load_result_from_url(
                url=url, calendar=calendar
            )
            self._apply_parse_result(result)
            self._last_error = None
            return len(result.legacy_contracts)
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning(
                "[InMemoryOptionContractMaster] KIS source load note: %s", exc
            )
            return 0

    def load_from_raw_mst_content(
        self, raw_text: str, calendar: TradingCalendar
    ) -> int:
        result = KisOptionMasterLoader.parse_raw_content(raw_text, calendar)
        self._apply_parse_result(result)
        self._last_error = None
        return len(result.legacy_contracts)

    @property
    def total_contracts(self) -> int:
        return len(self._contracts)

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error


class KisProductionOptionContractMaster(_IdentityOptionContractMaster):
    def __init__(
        self,
        contracts: Optional[Dict[str, str]] = None,
        calendar: Optional[TradingCalendar] = None,
        auto_load: bool = True,
        url: str = KIS_FO_IDX_MASTER_URL,
    ) -> None:
        self.calendar = _require_calendar(calendar)
        self._contracts: Dict[str, str] = dict(contracts or {})
        self._init_identity_registry()
        self._last_error: Optional[str] = None
        if auto_load and not self._contracts:
            self.load_from_kis_source(url=url)

    def get_expiry(self, symbol: str) -> Optional[str]:
        return self._contracts.get(symbol.strip()) if symbol else None

    def register_contract(self, symbol: str, expiry: str) -> None:
        if symbol and expiry:
            self._contracts[symbol.strip()] = expiry.strip()

    def load_from_kis_source(self, url: str = KIS_FO_IDX_MASTER_URL) -> int:
        try:
            result = KisOptionMasterLoader.load_result_from_url(
                url=url, calendar=self.calendar
            )
            self._apply_parse_result(result)
            self._last_error = None
            return len(result.legacy_contracts)
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning(
                "[KisProductionOptionContractMaster] Source download note: %s",
                exc,
            )
            return 0

    def load_from_raw_mst_content(self, raw_text: str) -> int:
        try:
            result = KisOptionMasterLoader.parse_raw_content(
                raw_text, self.calendar
            )
            self._apply_parse_result(result)
            self._last_error = None
            return len(result.legacy_contracts)
        except Exception as exc:
            self._last_error = str(exc)
            raise

    def load_from_zip_bytes(self, zip_bytes: bytes) -> int:
        try:
            result = KisOptionMasterLoader.load_result_from_zip_bytes(
                zip_bytes, self.calendar
            )
            self._apply_parse_result(result)
            self._last_error = None
            return len(result.legacy_contracts)
        except Exception as exc:
            self._last_error = str(exc)
            raise

    @property
    def total_contracts(self) -> int:
        return len(self._contracts)

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error


def create_default_option_master(
    calendar: Optional[TradingCalendar] = None,
    contracts: Optional[Dict[str, str]] = None,
    auto_load_kis: bool = True,
) -> IOptionContractMaster:
    return KisProductionOptionContractMaster(
        contracts=contracts,
        calendar=calendar,
        auto_load=auto_load_kis,
    )

```
[Child Page] kis_option_master_identity_parser_implementation.md
## 구현 대상
KIS 공식 fo_idx_code_mts.mst를 현재 shared/contracts/option_master.py의 legacy expiry lookup과 충돌 없이 확장한다.
## 현재 원격 구현의 핵심
현재 parse_kis_fo_idx_mst()는 KIS Master 한 줄을 |로 분리하고 다음 4개 필드를 사용한다.
        - parts[0] → prod_type
        - parts[1] → symbol (= KIS shrn_iscd 후보)
        - parts[2] → standard_code (= KIS stnd_iscd)
        - parts[3] → name
옵션 여부를 prod_type, symbol prefix, name으로 확인한 뒤 name/symbol의 월물·위클리 패턴으로 expiry를 계산한다. 결과는 현재 {symbol: expiry, standard_code: expiry} 형태의 Dict[str, str]이다.
## 최소 변경 설계
현재 legacy parser를 바로 Dict[str, KisOptionContractIdentity]로 변경하지 않는다. 다음 3층으로 분리한다.
```plain text
raw MST line
    ↓
_parse_kis_master_record()
    ↓
KisOptionContractIdentity
    ↓
legacy expiry map compatibility wrapper
```
### 1. Raw record parser
공식 9-column 순서를 기준으로 읽는다.
        1. prod_type / info_type
        1. shrn_iscd
        1. stnd_iscd
        1. kor_name
        1. atm_cls_code
        1. acpr
        1. mmsc_cls_code
        1. unas_shrn_iscd
        1. unas_kor_name
중요: parts[4]를 expiry로 해석하지 않는다.
### 2. Identity 변환
옵션에 대해 다음을 만든다.
        - shrn_iscd: raw parts[1]
        - stnd_iscd: raw parts[2] 또는 빈 값이면 None
        - info_type: raw parts[0]
        - option_type: 명시적 KIS mapping 결과
        - strike: acpr 검증 결과
        - expiry: 기존 이름/심볼 기반 계산 결과
instrument_id는 이 계층에서 만들지 않는다. 현재 KisOptionContractIdentity는 KIS Master identity 후보이지 Standard OptionInstrumentIdentity 그 자체가 아니다.
### 3. Legacy compatibility
기존 parse_kis_fo_idx_mst()의 외부 반환형과 기존 호출을 유지한다.
```plain text
symbol(shrn_iscd)     → expiry
standard_code(stnd_iscd) → expiry
```
동시에 새 identity parser/loader 경로에서는
```plain text
shrn_iscd → KisOptionContractIdentity
```
registry를 별도로 유지한다.
## info_type 매핑
허용된 명시적 변환만 사용한다.
```python
5/D/L → CanonicalOptionType.CALL
6/E/M → CanonicalOptionType.PUT
```
미지원 값은 Call/Put으로 추론하지 않는다. 옵션 identity를 생성해야 하는 경로에서는 매핑 실패를 명시적으로 기록하고 해당 identity를 주문 경계까지 전달하지 않는다.
## strike 검증
acpr를 무조건 float 변환하지 않는다.
권장:
        1. trim
        1. 빈 값이면 None
        1. Decimal 변환 실패면 None/parse failure
        1. <= 0이면 유효 strike로 사용하지 않음
        1. 정상 값만 Decimal로 보존
문자열 포맷의 정확한 소수점/공백 규칙은 실제 MST 샘플 대조 후 고정한다.
## expiry 보존
Master의 9개 공식 컬럼에 독립 expiry 컬럼은 없다. 따라서 기존 프로젝트의:
        - 일반 월물: 종목명에서 20YYYYMM 패턴
        - 위클리: YYMMWn 패턴
        - KRX calendar 기반 휴장일 보정
을 그대로 사용한다.
Identity 생성 시 계산된 expiry를 기록하되, expiry 계산 로직 자체는 이번 변경의 대상이 아니다.
## registry API
InMemoryOptionContractMaster와 KisProductionOptionContractMaster에 다음을 additive하게 추가한다.
```python
def get_contract_identity(self, shrn_iscd: str) -> KisOptionContractIdentity | None: ...
def register_contract_identity(self, identity: KisOptionContractIdentity) -> None: ...
```
기존:
```python
get_expiry(symbol)
register_contract(symbol, expiry)
```
은 그대로 유지한다.
새 Master load에서는 identity를 먼저 registry에 넣고, 동일 identity의 shrn_iscd 및 필요 시 stnd_iscd를 legacy expiry alias로 등록한다.
## Standard Identity와의 경계
KisOptionContractIdentity의 shrn_iscd가 곧바로 Standard instrument_id가 되는 것은 아니다.
향후:
```plain text
KIS Master Identity
    ↓ verified contract selection / resolver
Standard OptionInstrumentIdentity
    ├─ instrument_id  ← authoritative source 필요
    ├─ symbol
    ├─ expiry
    ├─ option_type
    └─ strike
```
instrument_id가 아직 authoritative하게 공급되지 않으면 Standard identity를 완성하지 않고 fail-closed한다.
## 구현 금지사항
        - standard_code → SHTN_PDNO 변환 금지
        - stnd_iscd → shrn_iscd 추정 금지
        - KOSPI200을 short code로 사용 금지
        - symbol + expiry + strike + option_type로 instrument_id 생성 금지
        - info_type 외의 action/track/tag/side로 option_type 추정 금지
        - parts[4]를 expiry로 재해석 금지
        - 기존 expiry 계산을 임의로 변경 금지
## 상태
이 문서는 실제 원격 코드에 적용하기 전의 최소 구현 계약이다. 현재 원격 Exp_Detail_1은 읽기 전용으로 유지하며, 적용 시에도 legacy parser/API의 기능 보존을 우선한다.
## No.147 반영 — Raw/Decimal 안전 규칙
        - KIS Master 공식 9-column 순서에 따라 shrn_iscd=parts[1], stnd_iscd=parts[2], info_type=parts[0], acpr=parts[5]로 해석한다.
        - 각 raw field는 strip() 후 의미를 보존한다.
        - acpr는 비어 있지 않고 Decimal(raw_acpr) 변환에 성공하며 결과가 0보다 클 때만 strike로 승격한다.
        - 실제 원문으로 확인되지 않은 소수점 scale 보정은 하지 않는다.
        - 5/D/L → CALL, 6/E/M → PUT은 KIS-specific adapter에서만 명시적으로 적용한다.
        - 기존 expiry 계산 및 legacy get_expiry()/register_contract() 의미는 유지한다.
        - 실제 최신 MST raw sample에서 확인되지 않은 acpr 암묵 scale은 확정하지 않는다.
## No.147 반영
Raw MST의 | 구분/field strip() 경계를 유지하고, acpr는 검증된 Decimal 값만 strike로 승격한다. 소수점 위치를 추정하지 않으며 기존 expiry 계산은 변경하지 않는다.
## No.148 준비 — Identity Parser/Registry additive 구현 경계
다음 구현은 기존 parse_kis_fo_idx_mst()와 legacy expiry map을 대체하지 않고, 별도의 Identity parser가 같은 raw MST를 읽어 KisOptionContractIdentity를 생성한 뒤 Registry에 등록하는 additive 경로로 설계한다.
## 구현 초안
```python
@dataclass(frozen=True)
class KisOptionContractIdentity:
    shrn_iscd: str
    stnd_iscd: str | None
    expiry: str
    option_type: str | None
    strike: Decimal | None
    info_type: str | None = None
```
Identity parser는 raw_content를 순회하면서 최소 6개 field가 있는 옵션 레코드만 대상으로 하고, info_type은 명시된 Call/Put 코드일 때만 CALL/PUT으로 변환한다. acpr는 검증된 Decimal만 사용한다. expiry는 기존 parser가 계산한 결과를 재사용하는 별도 compatibility helper를 통해 공급하며, expiry 계산식을 중복 구현하지 않는다.
Registry는 _contract_identities: Dict[str, KisOptionContractIdentity]를 두고 1차 key를 shrn_iscd로 한다. register_contract_identity()는 빈 단축코드 또는 동일 key의 의미가 다른 identity가 들어오면 fail-closed한다. get_contract_identity()는 trim된 shrn_iscd로 조회한다.
중요: stnd_iscd는 별도 보존 필드이며 SHTN_PDNO로 사용하지 않는다. shrn_iscd 역시 현재 Canonical symbol을 자동 변경하지 않는다. Standard instrument_id도 생성하지 않는다.
## 구현 전 보류
현재 단계에서는 원격 Exp_Detail_1에 parser/registry 코드를 직접 반영하지 않는다. 이유는 실제 최신 MST raw sample의 acpr 표현 및 기존 expiry 계산 결과와의 1:1 결합을 코드로 검증할 수 없는 상태이기 때문이다. 먼저 additive parser의 입력/출력 및 충돌 정책을 문서로 고정한 후 원격 적용 여부를 결정한다.
## No.148 반영 — 실제 option_master.py 구조 대조 결과
        - 원격 Exp_Detail_1/shared/contracts/option_master.py를 다시 대조한 결과, 현재 구현에는 KisOptionContractIdentity 또는 Identity Registry가 아직 존재하지 않는다.
        - 현재 parse_kis_fo_idx_mst()는 parts[0]~parts[3]만 직접 사용하며 반환형은 Dict[str, str]이다.
        - 현재 KisOptionMasterLoader.load_from_zip_bytes()와 load_from_url()도 기존 parser의 expiry map을 그대로 반환한다.
        - InMemoryOptionContractMaster와 KisProductionOptionContractMaster 모두 _contracts: Dict[str, str]만 보유하며 get_expiry() / register_contract()를 통해 legacy expiry map을 제공한다.
        - 따라서 No.148에서 확정한 Identity Registry를 기존 _contracts에 억지로 혼합하지 않고 별도 _contract_identities 저장소로 additive하게 두는 것이 실제 구조와 가장 안전하게 맞는다.
        - 두 Master 구현체에 동일한 Identity 조회/등록 API를 제공하려면 공통 IOptionContractMaster 계약 확장이 우선 검토 대상이다. 다만 기존 구현체의 외부 동작을 깨뜨리지 않도록 abstract method로 즉시 강제할지는 별도 판단이 필요하다.
        - 새 Identity loader는 기존 parse_kis_fo_idx_mst()를 교체하지 않고 별도 parser/helper로 두는 방향이 현재 코드 구조와 일치한다.
        - 기존 load_from_kis_source() 및 load_from_raw_mst_content()는 현재 expiry map만 갱신하므로, Identity 동시 등록을 적용할 경우 이 두 경로와 ZIP loader의 책임을 중복시키지 않는 공통 additive load helper가 필요하다.
        - 원격 브랜치에는 코드를 반영하지 않았다. 터미널 테스트도 수행하지 않았다.
### No.148 결론
현재 원격 구현은 No.148 구현계약을 수용할 수 있는 구조이지만, 실제 적용 시에는 기존 expiry map과 새 Identity registry를 병렬 유지하고, Master loading 과정에서 동일 raw MST를 중복 다운로드하지 않도록 parser/load 책임을 분리해야 한다. 또한 IOptionContractMaster의 기존 호출 계약을 보존하면서 Identity API를 추가하는 구체적인 인터페이스 확장 방식이 다음 작업의 핵심이다.
## 구현 상태 갱신 — No.152
No.151에서 확정한 공통 Raw Parse 경계를 실제 OptionProject 코드로 구현했다.
        - 실제 코드: OptionProject/core/oms/option_master.py
        - 테스트: OptionProject/core/oms/test_option_master.py
        - 한 번의 raw MST 순회에서 legacy expiry map과 identity registry를 함께 생성
        - 기존 parse_kis_fo_idx_mst() -> Dict[str, str]는 compatibility wrapper로 유지
        - _contracts와 _contract_identities 병렬 유지
        - IOptionContractMaster 기존 abstract API 유지, identity API는 concrete fallback
        - duplicate identity 충돌은 fail-closed
        - malformed acpr는 strike를 추정하지 않고 None
        - 실제 pytest 실행 환경 검증은 다음 단계로 남김
## No.153 검증 결과 보강
### 실제 import/package 정합성 점검
OptionProject/core/oms/option_master.py는 현재 from shared.calendar.krx_calendar import KrxTradingCalendar를 사용한다.
그러나 현재 OptionProject 최상위 구조에는 shared/ 작업공간이 존재하지 않고, core가 외부 Reference/Legacy 경로를 직접 import하지 않는 Architecture Lint 원칙도 존재한다. 따라서 현재 파일은 독립 OptionProject Python workspace로 materialize할 경우 import 단계에서 실패할 가능성이 높은 상태다.
### 회귀 보존 대조
원격 Exp_Detail_1/shared/contracts/option_master.py와 대조한 결과 기존 public expiry API와 loader API는 유지되어 있다. Identity 확장은 additive이며 기존 만기조회 호출 경로를 제거하지 않았다.
### 테스트 구조 점검
test_option_master.py의 core.oms... import 방식은 현재 프로젝트의 테스트 관례와 일치한다. 다만 OptionProject 자체가 물리 Python workspace로 실행될 때 shared.calendar...가 없으므로 pytest 이전에 module import가 막히는 구조적 선행 문제가 확인됐다.
### 결론
API 회귀 대조, 테스트 import 형태 대조, Git Reference 구조 대조는 완료했다. 실제 pytest 실행은 Calendar 구현 소유권/패키지 경로가 미정이므로 보류한다.
다음 구현 단계에서는 원격 Reference의 Calendar 기능을 무단 복제하지 않고 OptionProject Architecture에 맞는 Calendar Contract/Adapter 주입 경계를 먼저 확정한 뒤 option_master.py의 shared.calendar 직접 의존성을 제거해야 한다.
## No.154 구현 반영 — Calendar Contract 명시 주입 경계
        - OptionProject/contracts/trading_calendar.py에 최소 TradingCalendar Protocol을 생성했다.
        - OptionProject/core/oms/option_master.py에서 shared.calendar.krx_calendar 직접 import를 제거했다.
        - OptionContractMaster가 실제로 사용하는 is_trading_day()와 prev_trading_day()만 표준 Contract로 소비하도록 변경했다.
        - Core/OMS 내부에서 기본 KrxTradingCalendar()를 생성하지 않는다. Production Calendar 구현과 source 선택 책임은 Core 밖으로 유지한다.
        - raw MST parser와 loader의 만기 계산 경로는 Calendar를 명시적으로 주입받는다.
        - 기존 legacy expiry map과 Identity Registry의 additive 병렬 구조는 유지했다.
        - test_option_master.py에는 deterministic FakeTradingCalendar를 주입해 Calendar 구현과 parser 검증 책임을 분리했다.
        - 원격 Git Exp_Detail_1은 읽기/대조만 수행하는 기준을 유지하며 수정하지 않았다.
### 검증 경계
현재 Notion 작업공간은 실제 파일시스템 터미널 pytest 실행 환경이 아니므로 실제 pytest 실행 PASS는 확정하지 않는다. 이번 단계는 독립 import 차단 원인을 제거하고, 실행 가능한 테스트 주입 경계를 코드 구조로 확정한 단계다.
### 다음 작업 준비
다음 단계에서는 OptionProject 전체 코드 페이지를 실제 Python workspace 기준으로 materialize할 수 있는 범위를 확인하고, test_option_master.py를 포함한 targeted pytest 실행 가능 여부를 검증한다. 실제 실행이 가능할 경우에만 PASS/FAIL을 판정하고, Calendar production source 미검증 상태는 별도로 BLOCKED로 유지한다.
## No.156 정합성 점검 결과 — 기능 보존 회귀 위험
원격 Exp_Detail_1/shared/contracts/option_master.py와 현재 OptionProject 구현을 파일 단위로 재대조했다.
        - legacy get_expiry() / register_contract() 및 loader API는 유지됐다.
        - Identity Registry 추가는 additive 구조다.
        - 그러나 원격 구현은 calendar=None일 때 내부 KrxTradingCalendar()를 생성하여 기존 호출자가 Calendar를 전달하지 않아도 동작한다.
        - 현재 OptionProject는 Architecture 규칙에 따라 Core가 Production Calendar 구현을 소유하지 않도록 명시 주입으로 변경했고, 그 결과 parse_kis_fo_idx_mst, expiry 계산 함수, KisProductionOptionContractMaster, create_default_option_master의 무인자 기존 호출 경로가 즉시 동일하게 동작하지 않는다.
따라서 shared.calendar 직접 의존 제거 자체는 Architecture 적합성이지만, 기존 auto-load/production 생성 기능까지 제거하거나 사실상 필수 인자로 변경해서는 안 된다. 다음 단계에서는 Core 내부 기본 구현 생성 없이 Application/Environment 조립 계층이 Production TradingCalendar를 주입하는 경로를 마련하여 기존 무인자 public factory 기능과 새 의존성 경계를 동시에 보존해야 한다.
현재 이 회귀 위험은 코드 수준 확인 결과이며 실제 pytest PASS/FAIL은 실행환경 부재로 판정하지 않는다.
## No.157 구현 — Production TradingCalendar 조립 위치 및 기존 Auto-load 호환 경계 확정
### 결론
No.156의 다음 단계에 따라 OptionProject의 현재 계층을 확인했다.
        - core/oms/option_master.py는 contracts.trading_calendar.TradingCalendar만 소비한다.
        - application/environment_hub/factory.py는 이미 실제 Environment 구성요소를 외부 builder로 주입받는 composition 경계를 사용한다.
        - 따라서 Production Calendar의 concrete 구현 소유·선택·생성 책임은 Core가 아니라 Application composition root에 두는 것이 현재 구조와 일치한다.
### 기존 기능 보존 방식
Core의 create_default_option_master() 자체에 다시 KrxTradingCalendar()를 import하면 No.154의 의존성 경계를 되돌리게 된다.
따라서 호환 경계는 다음처럼 분리한다.
```plain text
Legacy-compatible application factory
    ↓ owns/creates Production TradingCalendar
create_default_option_master(calendar=calendar)
    ↓
KisProductionOptionContractMaster
    ↓ consumes contract only
TradingCalendar Protocol
```
즉 기존의 “Production 기본 조립” 목적은 Application factory가 담당하고, Core의 low-level parser/expiry 계산은 계속 명시 주입을 유지한다.
### Production Calendar source 상태
과거 Reference에는 shared/calendar/krx_calendar.py의 최소 Calendar engine이 존재했지만 실제 운영 휴장일 source는 별도 BLOCKED였고, KIS 실제 응답 교차검증도 FAIL/BLOCKED 이력이 있다.
따라서 이번 단계에서:
        - 원격 Calendar 구현을 Core로 복사하지 않음
        - 휴장일 목록을 임의 하드코딩하지 않음
        - weekend-only Calendar를 Production 대체품으로 만들지 않음
        - 검증되지 않은 Calendar source를 PASS로 선언하지 않음
### 실제 코드 수정 범위
이번 단계는 조립 위치와 책임 경계 확정 단계다.
Production Calendar concrete source 자체가 아직 OptionProject에서 authoritative하게 확정되지 않았으므로, 가짜 Production 구현을 생성하여 기존 무인자 호출을 억지로 복구하지 않았다.
대신 다음 구현 방향을 고정한다.
        1. contracts/trading_calendar.py는 Contract 유지
        1. core/oms/option_master.py는 concrete Calendar import 금지 유지
        1. application/에 Production composition factory를 두고 Calendar Provider/Builder를 소유
        1. 기존 무인자 auto-load 호환이 필요한 최종 public entrypoint는 Application factory에서 제공
        1. Core의 raw parser 직접 호출은 Calendar를 명시 주입
        1. authoritative Production Calendar source가 확정될 때에만 Application composition에 실제 구현 연결
### 판정
        - Core → Contract 의존 경계: PASS
        - Core의 concrete Calendar 직접 생성 금지: PASS
        - 기존 Production 조립 책임의 올바른 위치 확정: PASS
        - 기존 무인자 Core factory를 동일 시그니처로 즉시 복구: BLOCKED (authoritative Production Calendar source 미확정)
        - 원격 Git 수정: 없음
        - 실제 pytest: 실행환경 미확보로 미실행
### 다음 단계
No.158에서는 현재 Reference와 OptionProject의 기존 무인자 public 호출이 실제 어느 Runtime/Application entrypoint에서 사용되는지 추적한다.
그 결과에 따라:
        - Core-level legacy API 자체를 유지해야 하는지
        - Application-level compatibility entrypoint로 충분한지
를 실제 호출 증거로 판정한다.
호출 증거 없이 무인자 API를 추측 복구하지 않으며, authoritative Calendar source 미확정 상태도 그대로 BLOCKED로 유지한다.
## No.158 구현 — 기존 무인자 Public 호출 실제 경로 추적 및 호환 필요 범위 판정
### 조사 기준
No.157의 다음 단계에 따라 원격 Git Exp_Detail_1 최신 HEAD를 다시 확인했다.
        - 최신 HEAD: 51c57c1f88035523db9491fa56bbc52bcad9b20f
        - 최신 commit: fix(calendar): define real trading calendar source
### 실제 Reference Runtime 호출 증거
최신 원격 option_program/runtime/program_runtime.py의 기본 Runtime 생성 경로는 다음과 같다.
```plain text
OptionProgramRuntime()
  ├─ calendar 미주입
  │    → create_default_krx_calendar(auto_load_kis=True)
  └─ option_master 미주입
       → create_default_option_master(
             calendar=self.calendar,
             auto_load_kis=True
         )
```
즉 실제 Production Runtime은 이미 OptionContractMaster에 Calendar를 명시 전달한다.
따라서 현재 확인된 Reference Runtime 증거상:
        - create_default_option_master()를 Core에서 반드시 무인자로 지원해야 한다는 호출 증거는 없음
        - Production 기본 Calendar 생성 책임은 Runtime/Application composition에 존재
        - Core Master는 TradingCalendar를 명시 주입받는 현재 OptionProject 경계가 Reference 최신 Runtime과 양립 가능
### 중요한 최신 Reference 변경 확인
No.157 작성 당시의 “authoritative Production Calendar source 미확정” 상태는 최신 원격 HEAD와 일치하지 않게 되었다.
최신 Reference에는:
        - KisProductionHolidayProvider
        - KIS 공식 chk-holiday TR (CTCA0903R)
        - create_default_krx_calendar()
        - Runtime 기본 생성 시 Production Calendar auto-load
가 실제 구현되어 있다.
따라서 No.157의 BLOCKED 판단은 당시 확인 기준의 기록으로 유지하되, 현재 다음 작업에서는 최신 Reference를 기준으로 재검토해야 한다.
### OptionProject 호출 범위 판정
현재 OptionProject core/oms/option_master.py는:
        - create_default_option_master(calendar=...) 형태의 explicit DI를 수용
        - Core 내부 concrete Calendar 생성 없음
        - Parser/Expiry 계산의 Calendar Contract 소비 유지
따라서 Core-level legacy no-argument API 복구는 현재 증거 기준 필수 작업이 아니다.
대신 기능 보존을 위해 필요한 것은:
        1. 최신 Reference의 Production Calendar source 구현을 검증
        1. KIS 인증/HTTP 의존을 Core 밖에 유지
        1. Application/Runtime composition에서 Calendar 생성
        1. 생성된 Calendar를 create_default_option_master(calendar=...)에 주입
이다.
### 판정
        - 실제 Reference Runtime의 OptionMaster 호출 경로 추적: PASS
        - Runtime이 Calendar를 명시 주입한다는 증거 확인: PASS
        - Core-level 무인자 factory 복구 필요성: 현재 증거상 NOT REQUIRED
        - No.157의 Calendar source BLOCKED 상태 최신성: STALE → 재검토 필요
        - 원격 Git 수정: 없음
        - OptionProject 코드 임의 수정: 없음
### 다음 단계
No.159에서는 최신 Reference HEAD 51c57c1의 Production Calendar 구현을 상세 대조하여:
        - KIS Holiday Provider의 실제 책임
        - 인증 의존 위치
        - strict/failure semantics
        - Application/Infrastructure 이식 위치
를 확정한다.
그 후에만 OptionProject의 기존 “Production Calendar source BLOCKED” 문서를 갱신하고 실제 Application composition 코드를 구현한다.
## No.159 구현 — 최신 Reference Production TradingCalendar 책임·실패 의미·이식 위치 확정
### 기준
직전 No.158의 다음 단계에 따라 최신 Reference Exp_Detail_1 HEAD 51c57c1f와 Q&A-383의 구현 근거를 대조했다.
### 최신 Reference 구현 책임
shared/calendar/krx_calendar.py의 Production Calendar 구현은 다음 책임으로 분리되어 있다.
        - KisProductionHolidayProvider: KIS 공식 국내휴장일조회 API 호출 및 휴장일 데이터 공급
        - 공식 endpoint: /uapi/domestic-stock/v1/quotations/chk-holiday
        - TR ID: CTCA0903R
        - 인증: 기존 KISAuthManager를 통해 OAuth/인증 헤더 획득
        - create_default_krx_calendar(): Provider를 조립하여 KrxTradingCalendar 생성
        - Runtime: OptionProgramRuntime()에서 Calendar를 생성한 뒤 OptionMaster에 명시 주입
### 실패 의미 및 strict 경계
Reference의 핵심 안전 규칙도 확인했다.
        1. KIS API 오류를 빈 휴장일 집합의 정상 성공으로 은폐하지 않는다.
        1. Provider는 실패 원인을 last_error에 보존한다.
        1. strict_mode=True이고 source가 로드되지 않았으면 KisHolidayUnavailableError로 fail-closed한다.
        1. 명시적 테스트용 Calendar DI는 Runtime에서도 유지된다.
다만 실제 KisProductionHolidayProvider.is_loaded는 휴장일 1건 이상 로드된 경우를 성공으로 판단하므로, “해당 조회 구간에 휴장일이 없는 정상 응답”과 “source 미로드”를 장기적으로 구분해야 하는 개선 가능성은 존재한다. 이번 단계에서는 Reference 기능을 임의 변경하지 않는다.
### OptionProject 이식 위치 판정
No.006의 Core/Environment 분리 원칙과 No.154~158의 DI 경계를 함께 적용하면 다음 구조가 적합하다.
```plain text
Application / Infrastructure
    ├─ KIS Auth Adapter
    ├─ KIS Holiday Provider
    └─ Production Calendar Factory
              ↓
        TradingCalendar Contract
              ↓
        Core OptionContractMaster
```
따라서:
        - core/oms에 HTTP/KIS 인증 코드 이식 금지
        - contracts/trading_calendar.py는 유지
        - KIS API Provider는 Infrastructure 책임
        - Production Calendar 생성은 Application composition 책임
        - Core Master에는 생성된 Calendar를 명시 주입
### 현재 실제 구현 상태
이번 단계는 구조·책임 확정 및 Reference 대조 단계다.
        - 원격 Git 수정: 없음
        - OptionProject 코드 수정: 아직 없음
        - 이유: OptionProject에 KIS 인증 Adapter의 기존 표준 경로와 Application composition의 실제 public entrypoint를 먼저 확인하지 않은 상태에서 HTTP 구현을 임의 생성하지 않기 위함
### 결론
No.157의 “authoritative Production Calendar source 미확정” BLOCKED 상태는 최신 Reference 기준으로 해소되었다.
OptionProject에서 다음 실제 구현 대상은:
        1. Application/Infrastructure의 KIS 인증 기존 경계 조사
        1. KIS Holiday Provider 배치 위치 확정
        1. Production Calendar Factory 구현
        1. Factory → create_default_option_master(calendar=...) 실제 연결
        1. strict/failure semantics 테스트 가능한 경계 구축
이다.
### 다음 단계
No.160에서는 OptionProject 내부의 현재:
        - Application composition root
        - KIS 인증/HTTP Adapter
        - Runtime public entrypoint
를 전수 확인하여 Production Calendar Provider/Factory를 새로 구현할 정확한 위치와 재사용 가능한 인증 의존성을 확정한다.
호출 경로 확인 없이 새로운 KIS 인증 구현을 중복 생성하지 않는다.

[Child Page] runtime
폴더 페이지
[Child Page] STANDARD_OPTION_RUNTIME_CONTRACT.md
## 목적
Reference OptionProgramRuntime의 기능을 통째로 복제하지 않고, OptionProject에 이미 이식된 Standard Core를 실제 실행 가능한 하나의 Application/Runtime 경계로 연결하기 위한 계약이다.
## 확정된 입력
        - CanonicalMarketTick
        - OptionContractMaster + injected TradingCalendar
        - Strategy Registry/Orchestrator
        - Market Condition / Sensor 계층
        - Signal Processor
        - Decision / Risk 계층
        - Position/Execution Policy 및 OrderIntent Factory/Adapter
        - Environment가 공급하는 Account / Position / Broker / Execution 의존성
## 확정된 처리 순서
```plain text
CanonicalMarketTick
  -> Option identity / expiry resolution
  -> DTE calculation using the same TradingCalendar
  -> Market condition / sensor
  -> Track 1~9 StrategyOrchestrator
  -> Standard Signal validation/debounce
  -> DecisionArbiter
  -> Risk decision/gate
  -> Position/Execution Policy
  -> OrderIntent
  -> Environment-specific Order Command adapter
  -> OMS / Broker
```
## OptionMaster 계약
        1. Tick에 expiry가 있으면 authoritative value로 유지한다.
        1. expiry가 없고 symbol이 있으면 OptionContractMaster에서 조회한다.
        1. 조회한 expiry는 canonical tick에 반영한다.
        1. DTE는 동일한 injected TradingCalendar로 계산한다.
        1. 임의의 DTE fallback은 사용하지 않는다.
## 책임 분리
### Runtime/Application이 담당
        - 위 Core 단계의 호출 순서와 데이터 전달
        - Account/Position/Broker/Execution 의존성 연결
        - execution report 전달
        - runtime 상태 및 처리 metrics
        - startup recovery/reconciliation 호출 경계
### RuntimeController가 담당하지 않음
        - Track별 직접 분기
        - Broker API 직접 호출
        - VMS/VSSF 직접 조립
        - Legacy Conductor의 OS lockdown/uvloop 정책
        - UI/WebSocket 서버 소유
## 현재 구현 전제
StrategyOrchestrator는 Strategy lifecycle과 Signal 수집까지만 담당하며 Decision/Risk/Order 실행은 담당하지 않는다. Signal 계층 역시 Order Command를 직접 생성하지 않는다. 따라서 Runtime은 이 계층들의 실제 API를 확인한 뒤 연결해야 한다.
## 구현 보류 조건
현재 Notion에 저장된 일부 Core 문서는 실제 구현 API의 완전한 시그니처보다 설계/계약 문서가 앞서 있다. 특히 다음을 정확히 확인하기 전에는 production Runtime 구현체를 임의로 작성하지 않는다.
        - Track 1~9가 StrategyContext를 실제로 어떤 형태로 받는지
        - DecisionArbiter의 실제 입력/출력 타입과 호출 방식
        - RiskEngine/RiskGate의 실제 입력/출력 타입
        - OrderIntent Factory/Adapter의 실제 연결 타입
        - Execution Report → OMS FSM 상태 전이의 실제 API
        - Environment Bundle의 Broker/Account/Execution 실제 제공 객체
이 확인 없이 Reference의 긴 process_tick()을 복사하면 현재 Standard Core의 책임 분리와 충돌하거나 기존 전략 기능을 누락할 위험이 있다.
## 검증 원칙
        - Reference Exp_Detail_1은 읽기 전용이다.
        - 실제 terminal pytest PASS를 실행하지 못한 경우 PASS로 기록하지 않는다.
        - KIS HTTP 및 실제 Broker E2E는 별도 검증 대상이다.
## Runtime identity ownership 보완 — No.338
        - CanonicalMarketTick.source_sequence가 존재하면 Standard Runtime의 authoritative tick_sequence source로 사용한다.
        - VMS projection adapter는 Reference tick.seq_id를 source_sequence으로 lossless 전달하는 것이 이미 확인됐다.
        - 동일 tick 내 Strategy evaluation ordinal은 실제 Runtime loop가 소유하는 local_sequence으로 명시한다.
        - RuntimeExecutionContext(tick_sequence, local_sequence)가 signal/client order identity를 단일 규칙으로 파생한다.
        - source_sequence 누락 또는 0 이하를 tick counter fallback으로 보완하지 않으며 fail-closed 한다.
        - 아직 Standard process_tick() 구현체는 생성하지 않는다. 실제 Strategy evaluation loop가 materialize되기 전에는 context contract까지만 확정한다.
## Runtime signal collection ownership 확인 — No.339
        - StrategyOrchestrator.run()은 _strategy_keys/selected의 결정적 순서대로 strategy를 실행하고, 각 evaluate()의 produced를 그대로 signals.extend(tuple(produced))로 수집한다.
        - 따라서 Orchestrator 반환 StrategyRunResult.signals의 순서는 현재 구현상 실제 evaluation/collection 순서를 보존한다.
        - 단, Orchestrator는 tick sequence를 소유하지 않고 Runtime 독립 컴포넌트이므로 local_sequence ID 생성 owner로 승격하지 않는다.
        - authoritative owner는 tick을 보유한 Runtime 실행경계이며, StrategyOrchestrator는 Runtime이 enumerate할 수 있는 결정적 signal collection order를 제공한다.
        - 실제 production Runtime tick loop가 아직 없으므로 local_sequence counter를 Orchestrator 내부 상태로 추가하지 않는다.
## Runtime input-source audit — No.340
        - Virtual 경로의 CanonicalMarketTick authoritative source는 실제 VMS ReferenceCanonicalMarketTick이며 VMSMarketTickProjectionAdapter가 seq_id -> source_sequence을 lossless 전달한다.
        - 그러나 Track4 StrategyContext에는 CanonicalMarketTick만으로 계산할 수 없는 active_vol, base_vol, current_delta, current_pnl, premium_spent, accumulated_gamma_profit, theta_decay_cost, current_equity, OHLC history가 필요하다.
        - 현재 OptionProject에는 이 Track4 typed payload를 실제 Runtime authoritative source에서 조립하는 production provider/factory가 materialize되어 있지 않다. 기존 integration_fixtures.py는 테스트 fixture이므로 Runtime source로 승격하지 않는다.
        - 따라서 실제 Virtual tick source만으로 Track4 process_tick()을 조립하면 typed payload를 synthetic하게 채워야 하므로 production loop 구현을 계속 보류한다.
        - 다음 이식 대상은 synthetic payload factory가 아니라 Reference program_runtime.py process_tick()의 실제 market/position/greeks/pnl/history input acquisition 책임을 최소 source-provider 단위로 분리하는 것이다.
## Runtime input owner matrix — No.341
Reference Exp_Detail_1/option_program/runtime/program_runtime.py process_tick()를 실제 branch 기준으로 재대조했다.
<!-- Notion table block -->
| 입력 | Reference 획득 방식 | OptionProject authoritative owner | 판정 |
| current_price / timestamp / sequence | CanonicalMarketTick 직접 | VMS → VMSMarketTickProjectionAdapter | READY |
| active_vol / base_vol | MarketConditionAnalyzer.analyze(tick) | MarketConditionSensor의 tick history | READY |
| OHLC history / ATR | Reference price_history 기반 | MarketConditionSensor 내부 price history는 존재하나 Track4 read model 노출 없음 | ADAPTER SEAM NEEDED |
| current_equity / current_pnl | Reference Track4 현재 process_tick에서는 직접 공급하지 않음 | VSSF Account/PnL authoritative state + read-only AccountSnapshot projection | PARTIAL |
| current_delta / current_gamma | Reference Track4 현재 process_tick에서는 직접 공급하지 않음 | OptionProject에 authoritative Greeks provider 없음 | BLOCKED |
| premium_spent / accumulated_gamma_profit / theta_decay_cost | Reference Track4 현재 process_tick에서는 직접 공급하지 않음 | 전략/position attribution authoritative owner 없음 | BLOCKED |
확정 원칙:
        - Reference의 기존 process_tick은 일부 Track4 확장 입력을 실제로 acquisition하지 않고 Basecamp 중심 최소 호출만 수행한다.
        - Standard Track4는 Reference 기능 보존 과정에서 Delta Hedge, Theta Guard, Profit Trailing까지 명시적으로 typed input으로 확장되어 있으므로 Reference의 생략/기본값을 Standard Runtime synthetic fallback으로 복원하지 않는다.
        - Market/volatility/history와 Account/PnL은 기존 authoritative source에서 read-only provider로 연결 가능하다.
        - Greeks 및 strategy attribution metrics는 현재 authoritative owner가 없으므로 별도 Provider Port/Adapter seam 없이는 production Track4 payload를 완성할 수 없다.
        - 따라서 다음 구현 단위는 process_tick() 자체가 아니라 source별 read-only provider contract이며, missing source는 fail-closed 한다.
## Track4 Runtime Provider Port — No.342
No.341의 다음 단계에 따라 기존 자산을 전수 대조했다.
확인된 read-only source:
        - MarketConditionSensor: current_price, active_vol, base_vol
        - VSSFAccountSnapshotAdapter + AccountProvider: Account/PnL projection
미연결/부재 source:
        - Sensor 내부 가격 이력은 private state이며 Track4 OHLC read model contract 없음
        - authoritative current_delta/current_gamma 없음
        - premium_spent/accumulated_gamma_profit/theta_decay_cost attribution source 없음
따라서 contracts/track4_runtime_input_provider.py에 source별 ownership을 표현하는 최소 read-only Provider Port를 추가했다.
Track4RuntimeInputReadiness:
        - market
        - history
        - account_pnl
        - greeks
        - attribution
다섯 source가 모두 authoritative하게 연결될 때만 is_complete=True이다. incomplete 상태에서는 Runtime이 synthetic payload/default를 생성하지 않는다.
## Track4 Account/PnL partial projection — No.343
        - Track4VSSFAccountProjectionProvider를 추가했다.
        - 기존 AccountProvider.snapshot()의 authoritative cash를 current_equity로, realized_pnl + unrealized_pnl을 current_pnl로 read-only projection한다.
        - market/history/greeks/attribution은 연결하지 않았으며 호출 시 명시적으로 fail-closed 한다.
        - 따라서 account_pnl만 READY이고 전체 readiness.is_complete는 계속 false다.
        - MarketConditionSensor 내부 price history는 private state뿐이므로 기존 read-only OHLC projection seam은 발견하지 못했다.
## Runtime identity / execution seam audit — No.387
        - VMS ReferenceCanonicalMarketTick.seq_id → CanonicalMarketTick.source_sequence is lossless through VMSMarketTickProjectionAdapter.
        - RuntimeExecutionContext.tick_sequence consumes source_sequence directly; no legacy seq_id fallback is permitted.
        - local_sequence remains owned by the production Runtime loop. StrategyOrchestrator.run() preserves deterministic signal collection order but does not own the counter.
        - CanonicalStrategySignal.instrument_id is preserved unchanged by DecisionArbiter and validated at canonical transport; missing authoritative identity fails closed.
        - Risk ALLOW/REDUCE/DENY remains authoritative for executable quantity. requested_price/order_type/order_purpose are supplied by Position/Execution Policy, never inferred by Risk or transport.
        - Production process_tick() insertion remains deferred until Runtime-owned local ordinal, Track4 source completeness, and OrderIntentFactory invocation seams are all verified.
## Minimal process_tick boundary — No.392
        - core/runtime/standard_option_runtime.py를 추가하여 Standard Runtime의 최소 process_tick() 경계를 materialize했다.
        - Runtime은 source_sequence가 없는 tick에 counter fallback을 만들지 않고 즉시 fail-closed한다.
        - tick timestamp가 존재하면 호출 observed_at과 일치해야 Strategy seam으로 전달한다.
        - Runtime은 validated tick을 주입된 Strategy seam에 lossless 전달하며, Strategy seam이 Runtime-owned evaluation ordinal과 typed Track4 materialization을 담당한다.
        - 이 단계는 Decision/Risk/OMS execution을 연결하지 않는다.
        - instrument_id authoritative 공급 BLOCKED와 Profit Trailing attribution BLOCKED는 그대로 유지한다.
        - 임시 Python workspace에서 최소 Runtime 경계 테스트 5 passed를 확인했다. 이는 추출한 최소 경계 검증이며 전체 OptionProject import graph 통합 PASS를 의미하지 않는다.
## Standard Runtime → Track4 seam integration boundary — No.393
        - StandardOptionRuntime.process_tick()과 Track4 Runtime Strategy seam의 호출 경계를 별도 integration test로 연결했다.
        - authoritative tick은 동일 객체와 동일 observed_at으로 seam에 lossless 전달된다.
        - source_sequence 누락/비양수와 timestamp mismatch는 Track4 seam 진입 전에 Runtime에서 fail-closed한다.
        - 이번 통합은 Runtime→Strategy seam 경계까지만 검증한다. Track4 materializer/orchestrator 내부와 Decision/Risk/OMS는 기존 별도 계약 범위를 유지한다.
        - 임시 Python workspace에서 추출 최소 경계 테스트 3건 3 passed 확인.
        - 실제 전체 OptionProject import graph/E2E PASS로 해석하지 않는다.
[Child Page] reference_execution_pipeline.py
```python
"""Reference-compatible Decision -> RiskGate -> OrderRouter execution seam.

OrderIntent is intentionally not inserted here. This module preserves the existing
Reference execution transport while keeping Standard OrderIntent as a future seam.
"""
from dataclasses import dataclass
from typing import Any, Optional, Protocol

from shared.contracts.canonical import CanonicalAssetType, CanonicalOrderCommand


class OrderRouterLike(Protocol):
    def register_and_route(self, command: Any) -> Any: ...


@dataclass(frozen=True)
class CanonicalRiskCommandAdapter:
    """Structural compatibility adapter for Standard Risk without synthetic identity."""

    client_order_id: str
    track_id: str
    asset_type: Any
    side: Any
    qty: int
    price: float
    tag_id: str
    option_type: Any = None
    strike: float = 0.0
    symbol: str = ""
    expiry: str = ""

    @classmethod
    def from_command(cls, command: CanonicalOrderCommand) -> "CanonicalRiskCommandAdapter":
        return cls(
            client_order_id=command.client_order_id,
            track_id=command.track_id,
            asset_type=command.asset_type,
            side=command.side,
            qty=command.qty,
            price=command.price,
            tag_id=command.tag_id,
            option_type=command.option_type,
            strike=command.strike,
            symbol=command.symbol,
            expiry=command.expiry,
        )

    def get_instrument_key(self) -> str:
        """Derive only a Risk lookup key from fields already present on command."""
        asset = getattr(self.asset_type, "value", self.asset_type)
        if str(asset) == CanonicalAssetType.OPTION.value:
            if not self.symbol or not self.expiry or self.option_type is None or not self.strike:
                raise ValueError("OPTION_RISK_INSTRUMENT_KEY_INCOMPLETE")
            option_type = getattr(self.option_type, "value", self.option_type)
            return f"{asset}:{self.symbol}:{self.expiry}:{option_type}:{self.strike}"
        if not self.symbol:
            raise ValueError("FUTURES_RISK_INSTRUMENT_KEY_REQUIRED")
        return f"{asset}:{self.symbol}"


@dataclass(frozen=True)
class ReferenceExecutionResult:
    approved: bool
    decision: str
    routed: bool
    effective_command: Optional[CanonicalRiskCommandAdapter]
    rejection_reason: Optional[str] = None


def route_after_risk(
    command: CanonicalOrderCommand,
    *,
    risk_gate: Any,
    account: Any,
    positions: Any,
    order_router: OrderRouterLike,
    sensor_snapshot: Any = None,
    allow_reduction: bool = False,
) -> ReferenceExecutionResult:
    """Preserve Reference ALLOW/REDUCE/DENY semantics at the Risk->Router boundary."""
    adapted = CanonicalRiskCommandAdapter.from_command(command)
    approved, _token, rejection_reason = risk_gate.admit_order(
        adapted,
        account,
        positions,
        sensor_snapshot,
        allow_reduction,
    )
    result = risk_gate.last_evaluation_result

    if not approved or result is None:
        return ReferenceExecutionResult(
            approved=False,
            decision=getattr(result, "decision", "DENY"),
            routed=False,
            effective_command=None,
            rejection_reason=rejection_reason or getattr(result, "rejection_reason", None),
        )

    effective = (
        result.reduced_command
        if result.decision == "REDUCE" and result.reduced_command is not None
        else adapted
    )
    order_router.register_and_route(effective)
    return ReferenceExecutionResult(
        approved=True,
        decision=result.decision,
        routed=True,
        effective_command=effective,
    )

```
## No.336 보완
기존 route_after_risk()는 이미 변환된 Risk Account/Position 입력을 받는다. 실제 authoritative source를 직접 조립하는 별도 진입점 route_from_authoritative_sources()를 추가한다.
```python
def route_from_authoritative_sources(
    command: CanonicalOrderCommand,
    *,
    risk_gate: Any,
    account_snapshot: AccountSnapshot,
    position_manager: Any,
    order_router: OrderRouterLike,
    sensor_snapshot: Any = None,
    allow_reduction: bool = False,
) -> ReferenceExecutionResult:
    adapted = CanonicalRiskCommandAdapter.from_command(command)
    inputs = build_risk_runtime_inputs(
        adapted,
        account_snapshot,
        position_manager,
    )
    return _route_adapted_command(
        adapted,
        risk_gate=risk_gate,
        account=inputs.account,
        positions=inputs.positions,
        order_router=order_router,
        sensor_snapshot=sensor_snapshot,
        allow_reduction=allow_reduction,
    )
```
### 보장
        - AccountSnapshot → account_snapshot_to_risk_input() 기존 계약 재사용
        - PositionManager.positions(side/qty) → position_manager_to_risk_input() 기존 계약 재사용
        - authoritative source mutation 없음
        - Canonical identity/order_type/order_purpose 생성 없음
        - 기존 ALLOW/REDUCE/DENY Router 경계 재사용
## No.337 Decision 승인 → CanonicalOrderCommand 최소 변환
```python
@dataclass(frozen=True)
class DecisionCommandContext:
    """Authoritative order identity supplied by Runtime/Controller."""
    client_order_id: str


def approved_signal_to_command(
    signal: Any,
    *,
    context: DecisionCommandContext,
) -> CanonicalOrderCommand:
    """Lossless approved CanonicalStrategySignal -> CanonicalOrderCommand transport.

    This boundary does not generate order identity or execution fields.
    """
    client_order_id = str(context.client_order_id or "").strip()
    if not client_order_id:
        raise ValueError("CLIENT_ORDER_ID_REQUIRED")
    if int(signal.qty) <= 0:
        raise ValueError("QTY_REQUIRED")
    if not str(signal.track_id or "").strip():
        raise ValueError("TRACK_ID_REQUIRED")

    asset_type = getattr(signal.asset_type, "value", signal.asset_type)
    if str(asset_type) == CanonicalAssetType.OPTION.value:
        if not str(getattr(signal, "symbol", "") or "").strip():
            raise ValueError("OPTION_SYMBOL_REQUIRED")
        if not str(getattr(signal, "expiry", "") or "").strip():
            raise ValueError("OPTION_EXPIRY_REQUIRED")
        if getattr(signal, "option_type", None) is None:
            raise ValueError("OPTION_TYPE_REQUIRED")

    return CanonicalOrderCommand(
        client_order_id=client_order_id,
        track_id=signal.track_id,
        asset_type=signal.asset_type,
        side=signal.side,
        qty=signal.qty,
        price=signal.price,
        option_type=signal.option_type,
        strike=signal.strike,
        symbol=getattr(signal, "symbol", ""),
        expiry=getattr(signal, "expiry", ""),
        tag_id=signal.tag_id,
    )
```
### 경계
        - 입력은 DecisionArbiter가 승인한 Canonical signal 그대로 사용
        - client_order_id는 Runtime/Controller가 명시 공급하며 Adapter가 생성하지 않음
        - qty/price/side/asset_type/track_id/tag_id 재계산 없음
        - OPTION identity 누락은 fail-closed
        - FUTURES/OPTION 모두 legacy default symbol을 사용하지 않음
[Child Page] runtime_execution_context.py
```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeExecutionContext:
    """Authoritative per-evaluation identity owned by the Runtime loop."""

    tick_sequence: int
    local_sequence: int

    def __post_init__(self) -> None:
        if self.tick_sequence <= 0:
            raise ValueError("tick_sequence must be authoritative and positive")
        if self.local_sequence <= 0:
            raise ValueError("local_sequence must be positive")

    def signal_id(self, track_id: str) -> str:
        track = str(track_id).strip()
        if not track:
            raise ValueError("track_id is required")
        return f"SIG-{self.tick_sequence}-{track}-{self.local_sequence}"

    def client_order_id(self, track_id: str) -> str:
        track = str(track_id).strip()
        if not track:
            raise ValueError("track_id is required")
        return f"ORD-T{self.tick_sequence}-{track}-{self.local_sequence}"
```
## Ownership
        - tick_sequence는 CanonicalMarketTick.source_sequence의 authoritative 값을 Runtime loop가 그대로 전달한다.
        - local_sequence는 동일 tick 내 실제 Strategy evaluation 결과의 Runtime-owned ordinal이다.
        - Context 외부에서 signal/order id fallback을 생성하지 않는다.
        - source_sequence가 없거나 0 이하이면 fail-closed 한다.
        - 이 파일은 아직 process_tick() 구현체가 아니다. Runtime source가 확정되기 전 identity ownership 계약만 고정한다.
[Child Page] standard_option_runtime.py
```python
from __future__ import annotations

from datetime import datetime
from typing import Protocol, Any


class RuntimeTickStrategySeam(Protocol):
    def evaluate_tick(self, tick: Any, observed_at: datetime) -> tuple[Any, ...]:
        ...


class StandardOptionRuntime:
    """Minimal authoritative Runtime tick boundary.

    This Runtime owns the decision to accept one authoritative tick into the
    Strategy evaluation seam. It never invents a tick sequence, timestamp,
    option identity, requested price, or execution fields.
    """

    def __init__(self, strategy_seam: RuntimeTickStrategySeam) -> None:
        self._strategy_seam = strategy_seam

    def process_tick(self, tick: Any, observed_at: datetime) -> tuple[Any, ...]:
        source_sequence = getattr(tick, "source_sequence", None)
        if source_sequence is None or source_sequence <= 0:
            raise ValueError("RUNTIME_SOURCE_SEQUENCE_REQUIRED")

        tick_timestamp = getattr(tick, "timestamp", None)
        if tick_timestamp is not None and tick_timestamp != observed_at.isoformat():
            raise ValueError("RUNTIME_TICK_TIMESTAMP_MISMATCH")

        return self._strategy_seam.evaluate_tick(tick, observed_at)

```
## 책임 경계
        - process_tick()은 authoritative source_sequence가 있는 tick만 수용한다.
        - sequence counter fallback을 생성하지 않는다.
        - timestamp가 제공된 tick은 observed_at과 동일해야 한다.
        - 실제 Strategy 평가와 Runtime-owned local_sequence 부여는 주입된 Strategy seam에 위임한다.
        - Decision/Risk/OMS/Order execution은 아직 호출하지 않는다.
        - instrument_id 공급 부재는 별도 identity seam에서 fail-closed 유지한다.

[Child Page] sensor
폴더: 기존 option_program/market_analysis 기능을 환경 독립 Sensor 책임으로 이식하는 공간.
## 이식 원칙
    - 기존 파일을 복사하지 않고 기능 단위로 재구현한다.
    - 입력은 core.domain.market_models.MarketState / CanonicalMarketTick만 사용한다.
    - KIS/VMS/VSSF/Broker/UI/Legacy Runtime을 직접 import하지 않는다.
    - 실제 입력에 존재하지 않는 bid/ask/OI/basis 값은 임의값으로 만들지 않는다.
    - 기존 MarketConditionAnalyzer의 핵심 계산인 가격변화·단기/장기 변동성·변동성 비율·drawdown·stress/flags를 우선 이식한다.
[Child Page] market_condition_sensor.py
```python
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from statistics import pstdev

from core.domain.market_models import CanonicalMarketTick, MarketState


@dataclass(frozen=True)
class MarketConditionSnapshot:
    as_of: object
    instrument_id: str
    current_price: float
    price_change: float
    volatility: float
    baseline_volatility: float
    volatility_ratio: float
    drawdown: float
    stress_level: float
    stress_flags: tuple[str, ...]
    spread: float | None = None
    liquidity_level: str | None = None
    basis: float | None = None
    oi_trend_alert: bool | None = None


class MarketConditionSensor:
    """Legacy MarketConditionAnalyzer의 핵심 계산을 Core Sensor로 이식."""

    def __init__(self, return_window: int = 60, baseline_window: int = 240) -> None:
        self.return_window = max(10, return_window)
        self.baseline_window = max(self.return_window, baseline_window)
        self._prices: dict[str, deque[float]] = {}
        self._previous: dict[str, float] = {}

    @staticmethod
    def _ratio(value: float, base: float) -> float:
        if base <= 0:
            return 1.0
        return max(0.0, value / base)

    def price_history(self, instrument_id: str) -> tuple[float, ...]:
        """Return the observed tick-price history as a read-only snapshot."""
        prices = self._prices.get(instrument_id)
        if prices is None:
            return ()
        return tuple(prices)

    def analyze(self, state: MarketState, instrument_id: str) -> MarketConditionSnapshot:
        tick: CanonicalMarketTick = state.ticks[instrument_id]
        price = float(tick.price)
        prices = self._prices.setdefault(instrument_id, deque(maxlen=self.baseline_window + 1))
        previous = self._previous.get(instrument_id)
        price_change = 0.0 if previous is None else price - previous
        self._previous[instrument_id] = price
        prices.append(price)

        values = list(prices)
        returns = [math.log(values[i] / values[i - 1]) for i in range(1, len(values)) if values[i - 1] > 0 and values[i] > 0]
        short_returns = returns[-self.return_window:]
        long_returns = returns[-self.baseline_window:]
        volatility = pstdev(short_returns) if len(short_returns) >= 2 else 0.0
        baseline = pstdev(long_returns) if len(long_returns) >= 2 else volatility
        ratio = self._ratio(volatility, baseline)

        peak = max(values) if values else price
        drawdown = max(0.0, (peak - price) / peak) if peak > 0 else 0.0
        short_move = abs(price_change / previous) if previous else 0.0
        flash_move = short_move >= 0.005
        gap_detected = previous is not None and short_move >= 0.01
        circuit_breaker = short_move >= 0.08

        stress = min(1.0, min(1.0, max(0.0, ratio - 1.0) / 2.0) * 0.65 + min(1.0, drawdown / 0.10) * 0.25 + (0.10 if flash_move else 0.0))
        flags: list[str] = []
        if ratio >= 1.30:
            flags.append("VOLATILITY_SPIKE")
        if flash_move:
            flags.append("FLASH_MOVE")
        if gap_detected:
            flags.append("GAP")
        if circuit_breaker:
            flags.append("CIRCUIT_BREAKER")
        if drawdown >= 0.05:
            flags.append("DRAWDOWN")

        return MarketConditionSnapshot(state.as_of, instrument_id, price, price_change, volatility, baseline, ratio, drawdown, stress, tuple(flags))
```
## Legacy 대응
        - MarketConditionAnalyzer.analyze() → MarketConditionSensor.analyze()
        - 가격변화, 단기/장기 변동성, 변동성 비율, flash/gap/circuit-breaker/drawdown, stress/flags를 이식했다.
        - RegimeDetector는 Legacy import를 그대로 끌어오지 않고 별도 이식 대상으로 보류한다.
        - spread/basis/OI는 현재 Canonical 입력에 실제 필드가 없으므로 임의값을 만들지 않고 None으로 유지한다.
        - 이 단계는 Legacy 파일 삭제나 Runtime 교체가 아니라 기능 단위 1차 이식이다.

[Child Page] delta_hedge_quantity.py
```python
from __future__ import annotations

from decimal import Decimal, ROUND_CEILING


def delta_to_mini_futures_qty(net_delta: Decimal, contract_multiplier: Decimal = Decimal("5")) -> int:
    """Convert net-delta exposure to KOSPI200 mini-futures hedge quantity.

    Domain rule: hedge quantity = ceil(abs(net_delta) * 5).
    Quantity is always a non-negative contract count; hedge direction is decided
    separately from the sign of the exposure by the owning strategy.
    """
    if contract_multiplier <= 0:
        raise ValueError("CONTRACT_MULTIPLIER_MUST_BE_POSITIVE")
    if not net_delta.is_finite():
        raise ValueError("NET_DELTA_MUST_BE_FINITE")
    return int((abs(net_delta) * contract_multiplier).to_integral_value(rounding=ROUND_CEILING))
```