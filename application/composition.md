Application composition root. Infrastructure implementations are assembled here and injected into Core through contracts.

## FUTURES target configuration ownership

- KOSPI200 target selection input is owned by application/composition, not EnvironmentConfig.

- Composition must supply exactly one authoritative selector key to the existing FUTURES selector: underlying_short_code or underlying_name.

- No KOSPI200/U200 default, broker symbol, or Standard instrument_id is synthesized inside the selector or Environment layer.

- The concrete production value remains BLOCKED until an authoritative configuration source is identified in Exp_Detail_1 or the project documentation.

[Child Page] option_master_factory.py
```python
"""Application composition for production option master dependencies."""
from __future__ import annotations
from typing import Optional

from core.oms.option_master import IOptionContractMaster, create_default_option_master
from infrastructure.kis.auth import KISAuthManager
from infrastructure.kis.holiday_provider import KISHolidayProvider
from infrastructure.kis.trading_calendar import ProductionTradingCalendar


def create_production_trading_calendar(*, auth_manager: Optional[KISAuthManager] = None, auto_load_kis: bool = True, strict_mode: bool = False, target_year: Optional[int] = None) -> ProductionTradingCalendar:
    auth = auth_manager or KISAuthManager.from_env()
    provider = KISHolidayProvider(auth_manager=auth, auto_load=auto_load_kis, strict_mode=strict_mode, target_year=target_year)
    return ProductionTradingCalendar(provider)


def create_production_option_master(*, auth_manager: Optional[KISAuthManager] = None, auto_load_calendar: bool = True, auto_load_kis_master: bool = True, strict_calendar: bool = False, target_year: Optional[int] = None) -> IOptionContractMaster:
    calendar = create_production_trading_calendar(auth_manager=auth_manager, auto_load_kis=auto_load_calendar, strict_mode=strict_calendar, target_year=target_year)
    return create_default_option_master(calendar=calendar, auto_load_kis=auto_load_kis_master)
```
Composition order: Auth → Holiday Provider → ProductionTradingCalendar → OptionContractMaster. Core receives only the calendar capability.

## Risk Composition 경계 확정 — No.198 작업

- Standard Risk Runtime 연결의 조립 위치는 application/composition으로 확정한다.

- Account는 AccountProvider.snapshot() -> AccountSnapshot -> account_snapshot_to_risk_input() 경로를 사용한다.

- Position은 현재 Standard PositionSnapshot에 side가 없으므로 이를 Risk 입력으로 변환하지 않는다. authoritative aggregate positions를 제공하는 별도 Position source가 필요하다.

- Reference CanonicalAccountSummary.positions를 Standard Core로 직접 주입하거나 Legacy DTO adapter를 Core에 추가하지 않는다.

- Runtime은 RiskRuntimeComposition 수준에서 RiskGate + AccountProvider + authoritative Position source를 조립하고, RiskRuntimeInputs를 생성한 뒤 RiskGate에 전달하는 구조로 연결한다.

- 실제 Runtime Controller 연결은 authoritative Position source가 확정되기 전에는 수행하지 않는다.

- Risk 결과의 REDUCE quantity는 last_evaluation_result.reduced_command / approved_qty를 다음 Position/Order Execution 단계에 전달하는 것으로 고정한다.

[Child Page] virtual_builder_contract.py
```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from environments.virtual.bundle import VirtualEnvironmentBundle


@dataclass(frozen=True)
class VirtualAuthoritativeScope:
    """Composition-time identity of one authoritative VSSF runtime scope."""

    vssf_runtime: Any
    broker: Any
    account: Any
    position: Any
    execution: Any


class VirtualEnvironmentBuilder(Protocol):
    """Minimal Application composition contract for a Virtual Environment."""

    def build(self, config: Any, policy: Any) -> VirtualEnvironmentBundle:
        """Build one complete Virtual Environment Bundle within one composition scope."""


class VirtualAuthoritativeScopeFactory(Protocol):
    """Create the shared VSSF-derived state owner used by Virtual projections."""

    def create(self, config: Any, policy: Any) -> VirtualAuthoritativeScope:
        """Return one VSSF runtime and its directly derived Environment components."""
```
## 계약 의미
    - VirtualEnvironmentBuilder는 Application composition이 제공해야 하는 최소 입력/출력 계약이다.
    - Builder는 config와 policy만 입력받으며 임의의 Core 객체를 생성하지 않는다.
    - VirtualAuthoritativeScope는 Reference의 VirtualSecuritiesFirmRuntime 1개를 composition scope의 authoritative state owner로 고정하기 위한 계약이다.
    - broker / account / position / execution은 이 동일 scope에서 생성·투영되어야 한다.
    - Position은 별도 mutable owner가 아니라 authoritative VSSF Position을 읽는 projection이어야 한다.
    - Market과 Clock은 Bundle 생성 시 별도 Environment component로 제공되며 VSSF state owner와 동일한 composition lifetime을 가진다.
    - 이 계약은 concrete VSSF Runtime, initial capital, market price, simulator scenario를 발명하지 않는다.
    - 실제 builder 구현에서는 Reference의 기존 생성 의미를 주입값으로 보존해야 한다.
## 의도적으로 보장하지 않는 것
    - Protocol 자체가 broker 내부의 vssf_runtime identity를 런타임 타입 시스템으로 강제하지 않는다.
    - 따라서 concrete builder 테스트에서 동일 authoritative runtime 인스턴스가 Broker/Account/Position/Execution 경계에 연결되는지를 검증해야 한다.
    - 현재는 concrete dependency source가 없으므로 이 계약만 추가하고 실제 Runtime wiring은 하지 않는다.

[Child Page] virtual_composition_dependencies.py
```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from contracts.virtual_contract_resolver import (
    OptionContractIdentityRegistry,
    VirtualContractMapping,
    VirtualContractResolver,
)


@dataclass(frozen=True)
class VirtualCompositionDependencies:
    """Explicit Application-level dependencies for one Virtual composition scope."""

    contract_registry: OptionContractIdentityRegistry
    contract_mappings: Mapping[str, VirtualContractMapping]
    initial_capital: float
    vssf_command_context: Any
    scenario_source: Any | None = None
    replay_source: Any | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.initial_capital, (int, float)) or self.initial_capital <= 0:
            raise ValueError("VIRTUAL_INITIAL_CAPITAL_REQUIRED")
        if not callable(getattr(self.vssf_command_context, "build_command", None)):
            raise TypeError("VSSF_COMMAND_CONTEXT_REQUIRED")

    def create_contract_resolver(self) -> VirtualContractResolver:
        """Create a resolver sharing this scope's authoritative registry instance."""
        return VirtualContractResolver(
            mappings=self.contract_mappings,
            registry=self.contract_registry,
        )
```
## 계약
    - authoritative registry와 mapping은 Application Composition Root가 공급한다.
    - resolver 생성은 같은 dependency container가 보유한 registry 인스턴스를 그대로 사용한다.
    - registry 복제/재생성은 금지한다.
    - concrete VMS/VSSF 생성 책임은 포함하지 않는다.
    - scenario_source/replay_source는 source lifetime을 composition scope에 명시하기 위한 optional dependency다.

[Child Page] test_virtual_composition_dependencies.py
```python
from application.composition.virtual_composition_dependencies import (
    VirtualCompositionDependencies,
)
from contracts.virtual_contract_resolver import VirtualContractMapping


class Registry:
    def __init__(self):
        self.identity = object()
        self.requested = []

    def get_contract_identity(self, shrn_iscd: str):
        self.requested.append(shrn_iscd)
        return self.identity if shrn_iscd == "201ABC" else None


class CommandContext:
    def build_command(self, order):
        return order


def make_dependencies(registry):
    return VirtualCompositionDependencies(
        contract_registry=registry,
        contract_mappings={
            "scenario-call": VirtualContractMapping(
                scenario_contract_key="scenario-call",
                shrn_iscd="201ABC",
            )
        },
        initial_capital=50_000_000,
        vssf_command_context=CommandContext(),
    )


def test_dependencies_create_resolver_with_same_authoritative_registry_instance():
    registry = Registry()
    dependencies = make_dependencies(registry)

    resolver = dependencies.create_contract_resolver()

    assert resolver._registry is registry
    assert resolver.resolve("scenario-call") is registry.identity
    assert registry.requested == ["201ABC"]


def test_dependencies_preserve_single_registry_for_multiple_resolvers():
    registry = Registry()
    dependencies = make_dependencies(registry)

    first = dependencies.create_contract_resolver()
    second = dependencies.create_contract_resolver()

    assert first._registry is registry
    assert second._registry is registry


def test_dependencies_preserve_explicit_vssf_inputs():
    registry = Registry()
    context = CommandContext()
    dependencies = VirtualCompositionDependencies(
        contract_registry=registry,
        contract_mappings={},
        initial_capital=12_345_678,
        vssf_command_context=context,
    )

    assert dependencies.initial_capital == 12_345_678
    assert dependencies.vssf_command_context is context
```
## 검증 의도
    - authoritative registry를 새로 만들지 않고 동일 인스턴스를 공유하는 기존 계약을 유지한다.
    - initial_capital과 vssf_command_context가 dependency scope에 명시적으로 보존되는지 확인한다.
    - concrete VMS/VSSF runtime은 이 테스트에서 생성하지 않는다.

[Child Page] virtual_contract_identity_adapter.py
```python
from __future__ import annotations

from typing import Protocol, TypeVar

from contracts.virtual_contract_resolver import (
    VirtualContractResolutionError,
    VirtualContractResolver,
)


class ContractKeyEvent(Protocol):
    scenario_contract_key: str | None


EventT = TypeVar("EventT", bound=ContractKeyEvent)


class VirtualContractIdentityResolverAdapter:
    """Consume explicit Scenario/Replay contract keys at the identity-required boundary."""

    def __init__(self, resolver: VirtualContractResolver) -> None:
        self._resolver = resolver

    def resolve_event(self, event: EventT):
        key = event.scenario_contract_key
        if key is None or not key.strip():
            raise VirtualContractResolutionError("SCENARIO_CONTRACT_KEY_REQUIRED")
        return self._resolver.resolve(key)
```
## 책임
    - ScenarioEvent와 ReplayEvent가 공통으로 가진 scenario_contract_key만 소비한다.
    - key 누락/공백은 즉시 fail-closed 한다.
    - 실제 key → shrn_iscd → authoritative identity 해석은 기존 VirtualContractResolver에 위임한다.
    - payload, sequence, observed_at, ordering, replay lifecycle을 변경하지 않는다.
    - Adapter는 mapping 생성, registry fallback, symbol/expiry 역추론을 하지 않는다.
## 사용 위치
Scenario/Replay 엔진 내부가 아니라 Virtual market/order instrument identity가 실제로 필요한 projection 직전 경계에서 호출한다.

[Child Page] virtual_composition_root.py
```python
"""Concrete wiring for explicit Virtual composition dependencies."""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from application.composition.virtual_builder_contract import VirtualEnvironmentBuilder
from application.composition.virtual_composition_dependencies import (
    VirtualCompositionDependencies,
)
from application.composition.virtual_contract_mapping_loader import (
    VirtualContractMappingLoader,
)
from application.environment_hub.factory import EnvironmentFactory


def create_virtual_composition_dependencies(
    *,
    contract_registry: Any,
    scenario_configuration: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    initial_capital: float,
    vssf_command_context: Any,
    scenario_source: Any | None = None,
    replay_source: Any | None = None,
    mapping_loader: VirtualContractMappingLoader | None = None,
) -> VirtualCompositionDependencies:
    """Materialize one Virtual dependency scope without creating identities."""
    loader = mapping_loader or VirtualContractMappingLoader()
    mappings = loader.load(scenario_configuration)
    return VirtualCompositionDependencies(
        contract_registry=contract_registry,
        contract_mappings=mappings,
        initial_capital=initial_capital,
        vssf_command_context=vssf_command_context,
        scenario_source=scenario_source,
        replay_source=replay_source,
    )


def create_virtual_environment_builder(
    *,
    dependencies: VirtualCompositionDependencies,
    builder_type: type | None = None,
) -> VirtualEnvironmentBuilder:
    """Create the concrete Virtual builder from one explicit dependency scope."""
    if builder_type is None:
        from application.composition.concrete_virtual_environment_builder import (
            ConcreteVirtualEnvironmentBuilder,
        )
        builder_type = ConcreteVirtualEnvironmentBuilder
    return builder_type(dependencies=dependencies)


def create_virtual_environment_factory(
    *,
    builder: VirtualEnvironmentBuilder,
) -> EnvironmentFactory:
    """Expose an explicit Virtual builder through the existing Factory seam."""
    return EnvironmentFactory(
        virtual_builder=CallableVirtualBuilderAdapter(builder),
    )


class CallableVirtualBuilderAdapter:
    """Bridge the Protocol build(config, policy) contract to Factory callable form."""

    def __init__(self, builder: VirtualEnvironmentBuilder) -> None:
        self._builder = builder

    def __call__(self, config: Any, policy: Any):
        return self._builder.build(config=config, policy=policy)
```
## 이번 단계 연결 결과
    - create_virtual_composition_dependencies()가 initial_capital과 vssf_command_context를 명시적으로 받는다.
    - 동일 VirtualCompositionDependencies 인스턴스를 create_virtual_environment_builder()에 전달한다.
    - Concrete Builder는 이 dependency 객체를 ReferenceVirtualAuthoritativeScopeFactory까지 전달한다.
    - VSSF 생성 시 dependencies.initial_capital을 사용하고, VSSF execution adapter에는 dependencies.vssf_command_context를 사용한다.
    - 기존 authoritative contract registry/mapping은 dependency 객체 내부 인스턴스를 그대로 공유한다.
    - EnvironmentFactory.virtual_builder 기존 seam은 변경하지 않는다.
    - 실제 Market Identity mapping 값은 생성하지 않는다.
    - 원격 Exp_Detail_1은 수정하지 않는다.

[Child Page] concrete_virtual_environment_builder.py
```python
"""Concrete authoritative VMS/VSSF builder for one Virtual environment scope."""
from __future__ import annotations
from typing import Any

from application.composition.virtual_builder_contract import VirtualAuthoritativeScope, VirtualAuthoritativeScopeFactory
from application.composition.virtual_composition_dependencies import VirtualCompositionDependencies
from environments.virtual.bundle import VirtualEnvironmentBundle
from environments.virtual.broker.virtual_broker import VirtualBroker
from environments.virtual.account.vssf_account_snapshot_adapter import VSSFAccountSnapshotAdapter
from environments.virtual.position.vssf_position_aggregate_adapter import VSSFPositionAggregateAdapter
from environments.virtual.execution.virtual_execution import VirtualExecutionEngine
from environments.virtual.execution.vssf_execution_adapter import VSSFExecutionAdapter
from environments.virtual.clock.vms_clock_provider_adapter import VMSClockProvider
from environments.virtual.market.reference_vms_market.simulator_runtime import VirtualMarketSimulatorRuntime
from environments.virtual.authoritative_vssf.firm_runtime import VirtualSecuritiesFirmRuntime

class ReferenceVirtualAuthoritativeScopeFactory(VirtualAuthoritativeScopeFactory):
    def __init__(self, *, dependencies: VirtualCompositionDependencies) -> None:
        self._dependencies = dependencies

    def create(self, config: Any, policy: Any) -> VirtualAuthoritativeScope:
        dependencies = self._dependencies
        vssf = VirtualSecuritiesFirmRuntime(initial_capital=float(dependencies.initial_capital))
        account = VSSFAccountSnapshotAdapter(vssf.account)
        position = VSSFPositionAggregateAdapter(vssf.account)
        execution_adapter = VSSFExecutionAdapter(command_context=dependencies.vssf_command_context, vssf_runtime=vssf)
        execution = VirtualExecutionEngine(position=position, account=account, authoritative_execute=execution_adapter.execute)
        return VirtualAuthoritativeScope(vssf_runtime=vssf, broker=VirtualBroker(execution), account=account, position=position, execution=execution)

class ConcreteVirtualEnvironmentBuilder:
    def __init__(self, *, dependencies: VirtualCompositionDependencies, scope_factory: VirtualAuthoritativeScopeFactory | None = None, vms_factory=VirtualMarketSimulatorRuntime) -> None:
        self._dependencies = dependencies
        self._scope_factory = scope_factory or ReferenceVirtualAuthoritativeScopeFactory(dependencies=dependencies)
        self._vms_factory = vms_factory

    def build(self, config: Any, policy: Any) -> VirtualEnvironmentBundle:
        scope = self._scope_factory.create(config, policy)
        vms = self._vms_factory()
        return VirtualEnvironmentBundle.create(config=config, policy=policy, market=vms, clock=VMSClockProvider(vms.clock), broker=scope.broker, account=scope.account, position=scope.position, execution=scope.execution)
```
## 변경 사항
    - VSSF Runtime import를 외부 virtual_securities_firm에서 OptionProject 내부 environments.virtual.authoritative_vssf로 변경했다.
    - VMS/VSSF 모두 OptionProject 내부 source에서 생성한다.
    - 기존 ScopeFactory injection, vms_factory injection, Standard Adapter 경계와 Bundle lifecycle은 변경하지 않았다.

[Child Page] runtime_composition_factory.py
```python
"""Explicit application assembly for one Virtual runtime scope."""
from __future__ import annotations
from collections.abc import Mapping, Sequence
from typing import Any
from application.composition.virtual_composition_root import create_virtual_composition_dependencies, create_virtual_environment_builder, create_virtual_environment_factory
from application.environment_hub.hub import EnvironmentHub
from application.runtime_controller.controller import RuntimeController


def create_virtual_runtime_controller(*, contract_registry: Any, scenario_configuration: Mapping[str, Any] | Sequence[Mapping[str, Any]], initial_capital: float, vssf_command_context: Any, scenario_source: Any | None = None, replay_source: Any | None = None) -> RuntimeController:
    dependencies = create_virtual_composition_dependencies(
        contract_registry=contract_registry,
        scenario_configuration=scenario_configuration,
        initial_capital=initial_capital,
        vssf_command_context=vssf_command_context,
        scenario_source=scenario_source,
        replay_source=replay_source,
    )
    builder = create_virtual_environment_builder(dependencies=dependencies)
    factory = create_virtual_environment_factory(builder=builder)
    return RuntimeController(hub=EnvironmentHub(factory=factory))
```
## 책임
    - 최상위 Application assembly만 담당한다.
    - RuntimeController lifecycle 책임을 침범하지 않는다.
    - EnvironmentFactory 기존 seam을 유지한다.
    - identity, mapping, initial capital, VSSF command context를 caller가 명시 공급한다.
    - hidden default나 synthetic configuration을 생성하지 않는다.

[Child Page] vms_market_tick_projection_adapter.py
```python
from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from contracts.types import CanonicalMarketTick
from environments.virtual.market.reference_vms_market.canonical import ReferenceCanonicalMarketTick


class VMSMarketTickProjectionAdapter:
    """Project Reference VMS ticks into the OptionProject standard contract."""

    def __init__(self, instrument_id: str) -> None:
        if not instrument_id or not instrument_id.strip():
            raise ValueError("instrument_id is required")
        self._instrument_id = instrument_id

    def project(self, tick: ReferenceCanonicalMarketTick) -> CanonicalMarketTick:
        if tick.last_price <= 0:
            raise ValueError("reference tick last_price must be positive")
        try:
            observed_at = datetime.fromisoformat(tick.timestamp)
        except ValueError as exc:
            raise ValueError("reference tick timestamp is invalid") from exc
        return CanonicalMarketTick(
            instrument_id=self._instrument_id,
            observed_at=observed_at,
            price=Decimal(str(tick.last_price)),
            volume=Decimal(str(tick.volume)),
            source_sequence=tick.seq_id,
        )
```
Reference DTO를 변경하지 않고 Standard Market DTO로 읽기 전용 투영한다.

[Child Page] track4_runtime_input_provider_factory.py
```python
from __future__ import annotations

from typing import Callable, Sequence

from contracts.track4_composite_runtime_input_provider import Track4CompositeRuntimeInputProvider
from contracts.track4_kis_greeks_provider import Track4KisGreeksProvider
from contracts.track4_market_projection_provider import Track4MarketProjectionProvider
from contracts.track4_runtime_input_provider import Track4RuntimeInputProvider
from contracts.track4_vssf_account_projection_provider import Track4VSSFAccountProjectionProvider
from core.sensor.market_condition_sensor import MarketConditionSnapshot
from contracts.account import AccountProvider


class Track4RuntimeInputProviderFactory:
    """Build the Track4 partial Runtime provider graph from explicit authoritative sources.

    The factory wires existing source adapters only. It does not synthesize missing
    valuation, OHLC, attribution, risk-free-rate, or DTE inputs and does not start
    the Track4 production process_tick loop.
    """

    @staticmethod
    def create(
        *,
        snapshot_supplier: Callable[[], MarketConditionSnapshot | None],
        price_history_supplier: Callable[[str], Sequence[float]],
        account_provider: AccountProvider,
        greeks_provider: Track4KisGreeksProvider | None = None,
    ) -> Track4RuntimeInputProvider:
        market_provider = Track4MarketProjectionProvider(
            snapshot_supplier=snapshot_supplier,
            price_history_supplier=price_history_supplier,
            greeks_provider=greeks_provider,
        )
        account_projection = Track4VSSFAccountProjectionProvider(account_provider)
        return Track4CompositeRuntimeInputProvider(market_provider, account_projection)
```
## 계약
    - Market source: MarketConditionSensor가 생성한 최신 MarketConditionSnapshot을 Runtime owner가 명시적으로 공급한다.
    - History source: Sensor의 공개 price_history(instrument_id) projection만 공급한다.
    - Account/PnL source: 기존 VSSFAccountSnapshotAdapter를 거친 AccountProvider만 사용한다.
    - Greeks source: 제공된 경우 KIS authoritative Track4KisGreeksProvider를 그대로 전달한다.
    - 미공급 attribution은 fail-closed이며 synthetic 값으로 대체하지 않는다.
    - 이 factory는 provider graph를 조립하지만 production process_tick을 자동 연결하거나 실행하지 않는다.

[Child Page] track4_market_input_materializer.py
```python
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from contracts.track4_kis_greeks_provider import Track4KisGreeksProvider
from contracts.track4_runtime_input_provider import Track4InputSourceUnavailable
from contracts.track4_composite_runtime_input_provider import Track4CompositeRuntimeInputProvider
from core.strategy.track4_gamma_scalping import Track4MarketInput


class Track4RuntimeInputMaterializer:
    """Materialize Track4MarketInput from same-tick authoritative providers.

    The materializer does not invent missing values. Attribution fields remain None
    until an authoritative production source exists, so profit-trailing logic can
    fail closed while market/hedge calculations remain usable.
    """

    def __init__(
        self,
        runtime_provider: Track4CompositeRuntimeInputProvider,
        greeks_provider: Track4KisGreeksProvider,
    ) -> None:
        self._runtime_provider = runtime_provider
        self._greeks_provider = greeks_provider

    def materialize(self, tick_observed_at: datetime) -> Track4MarketInput:
        source_at = self._runtime_provider.observed_at()
        if source_at != tick_observed_at:
            raise Track4InputSourceUnavailable(
                f"TRACK4_TICK_SOURCE_TIMESTAMP_MISMATCH: tick={tick_observed_at!s} source={source_at!s}"
            )

        greeks_raw = self._greeks_provider.snapshot.observed_at
        try:
            greeks_at = datetime.fromisoformat(greeks_raw)
        except ValueError as exc:
            raise Track4InputSourceUnavailable(
                f"TRACK4_GREEKS_TIMESTAMP_INVALID: {greeks_raw!s}"
            ) from exc
        if greeks_at != tick_observed_at:
            raise Track4InputSourceUnavailable(
                f"TRACK4_GREEKS_TIMESTAMP_MISMATCH: tick={tick_observed_at!s} greeks={greeks_at!s}"
            )

        readiness = self._runtime_provider.readiness()
        if not (readiness.market and readiness.history and readiness.account_pnl):
            raise Track4InputSourceUnavailable(
                "TRACK4_CORE_INPUT_INCOMPLETE"
            )
        # Greeks are supplied explicitly to this materializer; their observation
        # timestamp was validated above against the same Runtime tick.

        history = tuple(self._runtime_provider.price_history())
        if not history:
            raise Track4InputSourceUnavailable("TRACK4_HISTORY_SOURCE_UNAVAILABLE")

        return Track4MarketInput(
            observed_at=tick_observed_at,
            current_price=self._runtime_provider.current_price(),
            active_vol=self._greeks_provider.active_vol(),
            base_vol=self._runtime_provider.base_vol(),
            time_str=tick_observed_at.strftime("%H:%M:%S"),
            current_delta=self._greeks_provider.current_delta(),
            current_gamma=self._greeks_provider.current_gamma(),
            current_pnl=self._runtime_provider.current_pnl(),
            current_equity=self._runtime_provider.current_equity(),
            price_history=history,
            premium_spent=None,
            accumulated_gamma_profit=None,
            theta_decay_cost=None,
        )
```
## 계약
    - Runtime tick의 observed_at과 Market/Account composite source의 observed_at이 동일해야 한다.
    - KIS Greeks snapshot의 observed_at도 동일 tick이어야 한다.
    - Market history가 없으면 materialization을 거부한다.
    - Market + history + Account/PnL + timestamp-validated KIS Greeks가 확보되면 Track4의 시장/Delta Hedge 입력을 materialize한다.
    - premium_spent, accumulated_gamma_profit, theta_decay_cost는 authoritative attribution source가 없으므로 None으로 유지한다. 숫자 0 또는 임의 상수를 넣지 않는다.
    - Profit trailing은 premium_spent 부재 시 실행하지 않도록 fail-closed한다.
    - OHLC를 합성하지 않는다.

[Child Page] track4_runtime_strategy_seam.py
```python
from __future__ import annotations

from datetime import datetime

from application.composition.runtime_strategy_result_collection_adapter import (
    RuntimeStrategyEvaluation,
    RuntimeStrategyResultCollectionAdapter,
)
from core.strategy.contracts import StrategyContext, StrategyInput
from core.strategy.strategy_orchestrator import StrategyOrchestrator
from core.strategy.track4_gamma_scalping import Track4MarketInput
from contracts.track4_market_input_materializer import Track4RuntimeInputMaterializer
from shared.contracts.canonical import CanonicalMarketTick


class Track4RuntimeStrategySeam:
    """Connect one authoritative market tick to Track4 without synthetic defaults."""

    def __init__(
        self,
        materializer: Track4RuntimeInputMaterializer,
        orchestrator: StrategyOrchestrator,
        result_collection_adapter: RuntimeStrategyResultCollectionAdapter | None = None,
    ) -> None:
        self._materializer = materializer
        self._orchestrator = orchestrator
        self._result_collection_adapter = (
            result_collection_adapter or RuntimeStrategyResultCollectionAdapter()
        )

    def evaluate_tick(
        self,
        tick: CanonicalMarketTick,
        observed_at: datetime,
    ) -> tuple[RuntimeStrategyEvaluation, ...]:
        if tick.source_sequence is None or tick.source_sequence <= 0:
            raise ValueError("TRACK4_RUNTIME_SOURCE_SEQUENCE_REQUIRED")
        if tick.timestamp != observed_at.isoformat():
            raise ValueError("TRACK4_RUNTIME_TICK_TIMESTAMP_MISMATCH")

        payload = self._materializer.materialize(observed_at)
        if not isinstance(payload, Track4MarketInput):
            raise TypeError("TRACK4_RUNTIME_TYPED_PAYLOAD_REQUIRED")

        context = StrategyContext(
            strategy_id="track4_gamma_scalping",
            input=StrategyInput(payload=payload),
        )
        result = self._orchestrator.run(
            {context.strategy_id: context}
        )

        return self._result_collection_adapter.collect(
            tick_sequence=tick.source_sequence,
            context=context,
            result=result,
        )
```
### 책임 경계
    - CanonicalMarketTick.source_sequence만 Runtime tick_sequence의 source로 사용한다.
    - Track4 입력은 Track4RuntimeInputMaterializer가 동일 tick에서 materialize한다.
    - StrategyContext.input.payload에는 Track4MarketInput만 전달한다.
    - Strategy는 sequence/client identity를 생성하지 않는다.
    - 이 seam은 아직 Decision/Risk/OMS를 호출하지 않는다.
    - 다전략 production loop에서는 Runtime이 StrategyRunResult 수집 순서대로 1-based local_sequence를 부여해야 한다.
    - requested_price, order_type, order_purpose, OPTION identity는 이 seam에서 생성하지 않는다.
    - source timestamp/sequence가 불일치하거나 누락되면 fail-closed한다.
## No.394 보완 예정 연결
    - RuntimeStrategyResultCollectionAdapter를 추가하여 StrategyRunResult.signals의 실제 순서를 Runtime-owned local_sequence로 materialize하는 구현을 별도 파일로 생성했다.
    - 기존 seam 본문 직접 replace는 도구 validation 오류로 적용되지 않아, 코드 본문 갱신은 이번 Process의 미완료 항목으로 유지한다.

[Child Page] runtime_strategy_result_collection_adapter.py
```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.runtime.runtime_execution_context import RuntimeExecutionContext


@dataclass(frozen=True)
class RuntimeStrategyEvaluation:
    """One Strategy signal with Runtime-owned deterministic local ordinal."""

    context: Any
    result: Any
    local_sequence: int
    runtime_context: RuntimeExecutionContext


class RuntimeStrategyResultCollectionAdapter:
    """Assign local_sequence from StrategyRunResult.signals order at Runtime boundary."""

    def collect(
        self,
        *,
        tick_sequence: int,
        context: Any,
        result: Any,
    ) -> tuple[RuntimeStrategyEvaluation, ...]:
        if tick_sequence <= 0:
            raise ValueError("RUNTIME_SOURCE_SEQUENCE_REQUIRED")

        signals = getattr(result, "signals", None)
        if signals is None:
            raise TypeError("RUNTIME_STRATEGY_SIGNAL_COLLECTION_REQUIRED")

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
            for local_sequence, signal in enumerate(tuple(signals), start=1)
        )
```
## 책임
    - StrategyRunResult.signals의 실제 순서를 Runtime 경계에서 1-based ordinal로 변환한다.
    - Strategy/Orchestrator 내부 counter를 추가하지 않는다.
    - 빈 signal collection은 빈 evaluation으로 유지한다.
    - signal collection이 아닌 결과는 fail-closed한다.
    - RuntimeExecutionContext는 기존 core/runtime 계약을 재사용한다.

[Child Page] futures_target_configuration.py
from dataclasses import dataclass
from typing import Optional
class FuturesTargetConfigurationError(ValueError):
"""Raised when the futures target configuration is ambiguous or incomplete."""
@dataclass(frozen=True)
class FuturesTargetConfiguration:
"""Application-owned explicit target selector input for FUTURES composition.
The configuration identifies the target product; it does not invent a broker
symbol or Standard instrument_id. Exactly one selector key must be supplied
by the Application Composition Root.
"""
underlying_short_code: Optional[str] = None
underlying_name: Optional[str] = None
def post_init(self) -> None:
short_code = (self.underlying_short_code or "").strip()
name = (self.underlying_name or "").strip()
if bool(short_code) == bool(name):
raise FuturesTargetConfigurationError(
"exactly one of underlying_short_code or underlying_name is required"
)
def selector_kwargs(self) -> dict[str, str]:
short_code = (self.underlying_short_code or "").strip()
name = (self.underlying_name or "").strip()
if short_code:
return {"underlying_short_code": short_code}
return {"underlying_name": name}

[Child Page] virtual_contract_mapping_loader.py
```python
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from contracts.virtual_contract_resolver import VirtualContractMapping


class VirtualContractMappingConfigurationError(ValueError):
    pass


class VirtualContractMappingLoader:
    """Materialize explicit Virtual contract mappings without inference."""

    def load(
        self, source: Mapping[str, Any] | Sequence[Mapping[str, Any]]
    ) -> dict[str, VirtualContractMapping]:
        entries = (
            source.get("contract_mappings")
            if isinstance(source, Mapping) and "contract_mappings" in source
            else source
        )
        if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
            raise VirtualContractMappingConfigurationError(
                "CONTRACT_MAPPINGS_REQUIRED"
            )

        mappings: dict[str, VirtualContractMapping] = {}
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise VirtualContractMappingConfigurationError(
                    "INVALID_CONTRACT_MAPPING_ENTRY"
                )
            key = entry.get("scenario_contract_key")
            shrn_iscd = entry.get("shrn_iscd")
            if not isinstance(key, str) or not key.strip():
                raise VirtualContractMappingConfigurationError(
                    "SCENARIO_CONTRACT_KEY_REQUIRED"
                )
            if not isinstance(shrn_iscd, str) or not shrn_iscd.strip():
                raise VirtualContractMappingConfigurationError(
                    "SHRN_ISCD_REQUIRED"
                )
            normalized_key = key.strip()
            if normalized_key in mappings:
                raise VirtualContractMappingConfigurationError(
                    "DUPLICATE_SCENARIO_CONTRACT_KEY"
                )
            mappings[normalized_key] = VirtualContractMapping(
                scenario_contract_key=normalized_key,
                shrn_iscd=shrn_iscd.strip(),
            )
        return mappings
```
## 최소 source 형식
```plain text
contract_mappings:
  - scenario_contract_key: <명시적 Scenario/Replay key>
    shrn_iscd: <OptionMaster registry에 이미 존재하는 코드>
```
## 경계
    - loader는 실제 source 값을 생성·추론하지 않는다.
    - key 또는 shrn_iscd 기본값/fallback을 제공하지 않는다.
    - registry 검증은 기존 VirtualContractResolver가 동일 OptionMaster instance를 통해 수행한다.
    - 현재 source 형식은 mapping 목록 또는 최상위 contract_mappings 목록만 허용한다.

[Child Page] futures_contract_target_resolver.py
```python
"""Application composition seam for selecting the authoritative current FUTURES contract."""
from __future__ import annotations

from contracts.futures_contract_master import (
    KisCurrentFuturesContractSource,
    KisFuturesContractIdentity,
)
from application.composition.futures_target_configuration import FuturesTargetConfiguration


def resolve_current_futures_contract(
    *,
    source: KisCurrentFuturesContractSource,
    target: FuturesTargetConfiguration,
) -> KisFuturesContractIdentity:
    """Bind Application-owned target configuration to the authoritative KIS source."""
    if source is None:
        raise ValueError("FUTURES_CONTRACT_SOURCE_REQUIRED")
    if target is None:
        raise ValueError("FUTURES_TARGET_CONFIGURATION_REQUIRED")
    return source.with_target(**target.selector_kwargs()).current_contract()
```
## 책임
    - FuturesTargetConfiguration을 KIS FUTURES Contract Master selector에 연결한다.
    - KIS source-specific KisFuturesContractIdentity를 그대로 반환한다.
    - instrument_id 또는 Standard identity를 생성·추정하지 않는다.
    - broker execution symbol은 선택된 record의 shrn_iscd로 후속 adapter에서 명시적으로 연결한다.
## 다음 보완
현재 seam은 Contract Master → Target Configuration까지 연결되었다. Runtime/Environment에는 아직 이 결과를 소비하는 FUTURES concrete provider가 없으므로, 다음 단계에서 KisFuturesContractIdentity.shrn_iscd를 authoritative execution symbol로 전달하는 최소 adapter seam을 구현한다.

[Child Page] test_futures_contract_target_resolver.py
```python
from contracts.futures_contract_master import KisCurrentFuturesContractSource, parse_kis_futures_contracts
from application.composition.futures_contract_target_resolver import resolve_current_futures_contract
from application.composition.futures_target_configuration import FuturesTargetConfiguration

RAW = """1|101W09|STANDARD|KOSPI200|x|x|1|U200|KOSPI200\n3|101W10|STANDARD|KOSPI200|x|x|2|U200|KOSPI200\n"""


def test_target_configuration_selects_authoritative_current_contract():
    records = parse_kis_futures_contracts(RAW)
    source = KisCurrentFuturesContractSource(records, underlying_short_code="U200")
    target = FuturesTargetConfiguration(underlying_short_code="U200")

    selected = resolve_current_futures_contract(source=source, target=target)

    assert selected.shrn_iscd == "101W09"
    assert selected.unas_shrn_iscd == "U200"


def test_target_configuration_does_not_create_standard_identity():
    records = parse_kis_futures_contracts(RAW)
    source = KisCurrentFuturesContractSource(records, underlying_short_code="U200")
    target = FuturesTargetConfiguration(underlying_name="KOSPI200")

    selected = resolve_current_futures_contract(source=source, target=target)

    assert selected.shrn_iscd == "101W09"
    assert not hasattr(selected, "instrument_id")
```

[Child Page] live_execution_position_composition_factory.py
```python
"""Explicit application assembly for the Live execution -> OMS -> Position seam."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from contracts.types import BrokerOrderCommand, ExecutionReport
from core.oms.oms_fsm import OrderStateMachine
from environments.live.position.live_execution_position_bridge import LiveExecutionPositionBridge, LivePositionFillAdapter


@dataclass(frozen=True)
class LiveExecutionPositionComposition:
    """Concrete dependency bundle for one Live settlement scope."""
    execution_source: Any
    broker_command_source: OrderStateMachine
    order_state_machine: OrderStateMachine
    position_fill_adapter: Any
    execution_event_deduplicator: Any
    position_aggregate: Any
    settlement_bridge: LiveExecutionPositionBridge

    def settle(self, report: ExecutionReport) -> object:
        """Resolve the originating BrokerOrderCommand from OMS and settle the report."""
        return self.settlement_bridge.settle(report)


def create_live_execution_position_composition(
    *,
    execution_source: Any,
    order_state_machine: OrderStateMachine,
    position_fill_adapter: Any,
    execution_event_deduplicator: Any,
    position_aggregate: Any,
) -> LiveExecutionPositionComposition:
    """Assemble existing Live execution/OMS/Position components without hidden defaults."""
    required = {
        "execution_source": execution_source,
        "order_state_machine": order_state_machine,
        "position_fill_adapter": position_fill_adapter,
        "execution_event_deduplicator": execution_event_deduplicator,
        "position_aggregate": position_aggregate,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        raise ValueError("LIVE_COMPOSITION_DEPENDENCY_REQUIRED:" + ",".join(missing))

    bridge = LiveExecutionPositionBridge(
        order_state_machine=order_state_machine,
        position_fill_adapter=position_fill_adapter,
        execution_event_deduplicator=execution_event_deduplicator,
        position_aggregate=position_aggregate,
    )
    return LiveExecutionPositionComposition(
        execution_source=execution_source,
        broker_command_source=order_state_machine,
        order_state_machine=order_state_machine,
        position_fill_adapter=position_fill_adapter,
        execution_event_deduplicator=execution_event_deduplicator,
        position_aggregate=position_aggregate,
        settlement_bridge=bridge,
    )
```
## 책임
    - application/composition만 concrete dependency assembly를 담당한다.
    - LiveExecutionPositionBridge의 settlement 순서와 책임을 변경하지 않는다.
    - BrokerOrderCommand authoritative source는 OMS OrderStateMachine이다.
    - broker command는 broker execution notice에서 재구성하지 않는다.
    - broker symbol, instrument identity, price, quantity, side를 composition에서 생성하지 않는다.
    - 인증정보·실계좌·실주문·실시간 네트워크 의존성을 생성하지 않는다.
    - 누락 dependency는 fail-closed한다.

[Child Page] test_live_execution_position_composition_factory.py
```python
from __future__ import annotations

from contracts.types import BrokerOrderCommand, ExecutionReport, OrderAckEvent, OrderIntent
from core.oms.oms_fsm import OrderStateMachine
from environments.live.execution.execution_event_deduplicator import ExecutionEventDeduplicator
from environments.live.position.live_position_aggregate import LivePositionAggregate
from environments.live.position.live_execution_position_bridge import LiveExecutionPositionBridge, LivePositionFillAdapter
from application.composition.live_execution_position_composition_factory import create_live_execution_position_composition


def test_live_execution_position_composition_uses_real_bridge_contract():
    oms = OrderStateMachine()
    oms.apply_intent(OrderIntent("C1", "I1", "BUY", 2, "OPEN"))
    command = BrokerOrderCommand("C1", "I1", "BUY", 2, "MARKET")
    oms.register_broker_order_command(command)
    oms.apply_ack(OrderAckEvent("C1", True, "B1"))

    aggregate = LivePositionAggregate("I1")
    dedup = ExecutionEventDeduplicator()
    composition = create_live_execution_position_composition(
        execution_source=object(),
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(aggregate),
        execution_event_deduplicator=dedup,
        position_aggregate=aggregate,
    )

    report = ExecutionReport(
        client_order_id="C1",
        broker_order_id="B1",
        execution_id="E1",
        status="PARTIALLY_FILLED",
        filled_quantity=1,
        remaining_quantity=1,
        execution_price=101.25,
        execution_timestamp=None,
    )
    state = composition.settle(report)

    assert state.filled_quantity == 1
    assert aggregate.snapshot().qty == 1
    assert dedup.contains("E1")


def test_duplicate_execution_is_blocked_before_second_position_mutation():
    oms = OrderStateMachine()
    oms.apply_intent(OrderIntent("C1", "I1", "BUY", 2, "OPEN"))
    command = BrokerOrderCommand("C1", "I1", "BUY", 2, "MARKET")
    oms.register_broker_order_command(command)
    oms.apply_ack(OrderAckEvent("C1", True, "B1"))

    aggregate = LivePositionAggregate("I1")
    bridge = LiveExecutionPositionBridge(
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(aggregate),
        execution_event_deduplicator=ExecutionEventDeduplicator(),
        position_aggregate=aggregate,
    )
    report = ExecutionReport(
        client_order_id="C1",
        broker_order_id="B1",
        execution_id="E1",
        status="PARTIALLY_FILLED",
        filled_quantity=1,
        remaining_quantity=1,
        execution_price=101.25,
        execution_timestamp=None,
    )

    first = bridge.settle(report)
    duplicate = bridge.settle(report)

    assert first.filled_quantity == 1
    assert duplicate.filled_quantity == 1
    assert aggregate.snapshot().qty == 1
```
## 검증 목적
    - 테스트가 별도 가짜 LiveExecutionPositionBridge를 정의하지 않고 실제 구현을 사용한다.
    - 실제 composition → bridge → dedup → OMS → Position 경계를 검증한다.
    - 동일 execution_id는 Position에 두 번 반영되지 않는다.
    - ACK 이후에만 ExecutionReport 정산을 허용한다.

[Child Page] live_runtime_composition_factory.py
```python
"""Explicit application assembly for one Live runtime scope."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from application.environment_hub.contracts import EnvironmentConfig, RuntimePolicy
from application.environment_hub.factory import EnvironmentFactory
from application.environment_hub.hub import EnvironmentHub
from application.runtime_controller.controller import RuntimeController
from environments.live.bundle import LiveEnvironmentBundle
from environments.live.contracts import LiveSafetyPolicy


def create_live_runtime_controller(
    *,
    live_builder: Callable[[EnvironmentConfig, RuntimePolicy], LiveEnvironmentBundle],
) -> RuntimeController:
    """Create a Live RuntimeController using only caller-supplied dependencies."""
    if live_builder is None:
        raise ValueError("LIVE_RUNTIME_BUILDER_REQUIRED")
    factory = EnvironmentFactory(live_builder=live_builder)
    return RuntimeController(hub=EnvironmentHub(factory=factory))


def build_live_bundle_from_components(
    *,
    market: Any,
    broker: Any,
    account: Any,
    position: Any,
    reconciler: Any,
    recovery: Any,
    safety_policy: LiveSafetyPolicy,
) -> Callable[[EnvironmentConfig, RuntimePolicy], LiveEnvironmentBundle]:
    """Bind concrete Live components without creating synthetic defaults."""
    required = {
        "market": market,
        "broker": broker,
        "account": account,
        "position": position,
        "reconciler": reconciler,
        "recovery": recovery,
        "safety_policy": safety_policy,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        raise ValueError("LIVE_RUNTIME_DEPENDENCY_REQUIRED:" + ",".join(missing))

    def builder(config: EnvironmentConfig, policy: RuntimePolicy) -> LiveEnvironmentBundle:
        if config.environment.value != "live":
            raise ValueError("LIVE_RUNTIME_BUILDER_ENVIRONMENT_MISMATCH")
        return LiveEnvironmentBundle(
            market=market,
            broker=broker,
            account=account,
            position=position,
            reconciler=reconciler,
            recovery=recovery,
            policy=safety_policy,
        )

    return builder
```
## 책임
    - Live Runtime의 concrete assembly는 application/composition에서만 수행한다.
    - RuntimeController의 lifecycle 책임은 유지한다.
    - Live broker/market/account/position/reconciler/recovery를 임의 생성하지 않는다.
    - 누락 dependency는 fail-closed한다.
    - 인증정보, 실계좌 정보, 실주문을 생성하거나 자동 승인하지 않는다.
    - LiveExecutionPositionComposition은 별도의 execution settlement seam으로 유지하며, 이 factory에서 correlation 값을 합성하지 않는다.

[Child Page] live_execution_runtime_composition_factory.py
```python
"""Concrete Live execution runtime assembly.

The factory connects the dedicated KIS execution consumer to the existing
OMS-owned correlation and Live Position settlement seam. It does not create
credentials, accounts, broker identities, or synthetic order context.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from contracts.types import BrokerOrderCommand, BrokerOrderResponse
from core.oms.oms_fsm import OrderStateMachine
from environments.live.execution.kis_futures_execution_consumer import KISFuturesExecutionConsumer
from environments.live.execution.kis_futures_execution_correlation_provider import KISFuturesExecutionCorrelationProvider
from environments.live.execution.kis_futures_execution_adapter import KISFuturesExecutionNoticeAdapter
from environments.live.position.live_execution_position_bridge import LiveExecutionPositionBridge
from application.composition.live_execution_position_composition_factory import (
    LiveExecutionPositionComposition,
    create_live_execution_position_composition,
)
from application.composition.live_execution_recovery_composition_factory import (
    create_live_execution_recovery_composition,
)


@dataclass
class OMSCommandRegisteringBroker:
    """Composition-only wrapper that records the exact command before broker send."""

    broker: Any
    order_state_machine: OrderStateMachine

    def submit(self, command: BrokerOrderCommand, *args: Any, **kwargs: Any) -> BrokerOrderResponse:
        self.order_state_machine.register_broker_order_command(command)
        return self.broker.submit(command, *args, **kwargs)


@dataclass(frozen=True)
class LiveExecutionRuntimeComposition:
    execution_consumer: KISFuturesExecutionConsumer
    settlement: LiveExecutionPositionComposition
    broker: OMSCommandRegisteringBroker
    recovery_service: Any | None = None

    async def start_execution(self, hts_id: str) -> None:
        await self.execution_consumer.start(hts_id)

    async def receive_execution_once(self):
        return await self.execution_consumer.receive_once()

    async def close_execution(self) -> None:
        await self.execution_consumer.close()


def create_live_execution_runtime_composition(
    *,
    transport: Any,
    execution_adapter: KISFuturesExecutionNoticeAdapter,
    correlation_provider: KISFuturesExecutionCorrelationProvider,
    broker: Any,
    order_state_machine: OrderStateMachine,
    position_fill_adapter: Any,
    execution_event_deduplicator: Any,
    position_aggregate: Any,
    recovery_transport: Any | None = None,
    recovery_adapter: Any | None = None,
) -> LiveExecutionRuntimeComposition:
    """Assemble concrete KIS execution ingress with OMS/Position settlement."""
    required = {
        "transport": transport,
        "execution_adapter": execution_adapter,
        "correlation_provider": correlation_provider,
        "broker": broker,
        "order_state_machine": order_state_machine,
        "position_fill_adapter": position_fill_adapter,
        "execution_event_deduplicator": execution_event_deduplicator,
        "position_aggregate": position_aggregate,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        raise ValueError("LIVE_EXECUTION_RUNTIME_DEPENDENCY_REQUIRED:" + ",".join(missing))

    settlement = create_live_execution_position_composition(
        execution_source=transport,
        order_state_machine=order_state_machine,
        position_fill_adapter=position_fill_adapter,
        execution_event_deduplicator=execution_event_deduplicator,
        position_aggregate=position_aggregate,
    )
    consumer = KISFuturesExecutionConsumer(
        transport=transport,
        adapter=execution_adapter,
        correlation_provider=correlation_provider,
        on_report=settlement.settle,
    )

    if (recovery_transport is None) != (recovery_adapter is None):
        raise ValueError("LIVE_RECOVERY_TRANSPORT_ADAPTER_MUST_BE_PAIRED")
    recovery_service = None
    if recovery_transport is not None:
        recovery_service = create_live_execution_recovery_composition(
            transport=recovery_transport,
            adapter=recovery_adapter,
            correlation_provider=correlation_provider,
            settlement_callback=settlement.settle,
        )

    return LiveExecutionRuntimeComposition(
        execution_consumer=consumer,
        settlement=settlement,
        broker=OMSCommandRegisteringBroker(
            broker=broker,
            order_state_machine=order_state_machine,
        ),
        recovery_service=recovery_service,
    )
```
## 책임 경계
    - KIS execution transport는 H0IFCNI0 wire notice만 공급한다.
    - KISFuturesExecutionConsumer가 adapter → OMS correlation → ExecutionReport를 수행한다.
    - LiveExecutionPositionComposition이 ExecutionReport → dedup → OMS FSM → Position을 수행한다.
    - BrokerOrderCommand는 broker submit 직전 OMS에 원본 command를 등록한다.
    - ACK의 broker_order_id가 OMS correlation map을 만들며, execution settlement는 그 map으로 원본 BrokerOrderCommand를 조회한다.
    - execution notice에서 instrument identity, side, quantity, broker command를 재구성하지 않는다.
    - 기존 OrderRouter의 ACK 처리 책임을 중복 구현하지 않는다.
    - 실제 KIS credential/account/order/network는 이 factory에서 생성하지 않는다.

[Child Page] execution_path_composition.py
```python
"""Explicit ownership boundary for Runtime transport and Standard OrderIntent execution seams."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from application.composition.runtime_authoritative_risk_router_adapter import RiskRouterContext

@dataclass(frozen=True)
class RuntimeTransportComposition:
    strategy_runtime: Any
    strategy_to_decision: Any
    decision_to_command: Any
    risk_gate: Any
    risk_context: RiskRouterContext

    def __post_init__(self) -> None:
        required = {
            'strategy_runtime': self.strategy_runtime,
            'strategy_to_decision': self.strategy_to_decision,
            'decision_to_command': self.decision_to_command,
            'risk_gate': self.risk_gate,
            'risk_context': self.risk_context,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise ValueError("RUNTIME_TRANSPORT_DEPENDENCY_REQUIRED:" + ",".join(missing))

@dataclass(frozen=True)
class StandardOrderIntentComposition:
    signal_identity_provider: Any
    position_execution_decision_provider: Any
    order_intent_factory: Any
    order_intent_adapter: Any

    def __post_init__(self) -> None:
        required = {
            'signal_identity_provider': self.signal_identity_provider,
            'position_execution_decision_provider': self.position_execution_decision_provider,
            'order_intent_factory': self.order_intent_factory,
            'order_intent_adapter': self.order_intent_adapter,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise ValueError("STANDARD_ORDER_INTENT_DEPENDENCY_REQUIRED:" + ",".join(missing))

def create_runtime_transport_composition(*, strategy_runtime: Any, strategy_to_decision: Any, decision_to_command: Any, risk_gate: Any, account_snapshot: Any, position_source: Any, order_router: Any, broker_command: Any) -> RuntimeTransportComposition:
    context = RiskRouterContext(account_snapshot, position_source, order_router, broker_command)
    return RuntimeTransportComposition(strategy_runtime, strategy_to_decision, decision_to_command, risk_gate, context)

def create_standard_order_intent_composition(*, signal_identity_provider: Any, position_execution_decision_provider: Any, order_intent_factory: Any, order_intent_adapter: Any) -> StandardOrderIntentComposition:
    return StandardOrderIntentComposition(signal_identity_provider, position_execution_decision_provider, order_intent_factory, order_intent_adapter)
```
## 책임
    - Runtime transport와 Standard OrderIntent 확장 seam의 composition root를 명시적으로 분리한다.
    - Runtime transport는 Account/Position/RiskGate/StandardOrderRouter 및 authoritative BrokerOrderCommand를 명시 공급받는다.
    - Standard OrderIntent seam은 authoritative Signal identity와 explicit PositionExecutionDecision supplier 없이는 생성되지 않는다.
    - 두 composition을 synthetic translator나 optional default로 연결하지 않는다.
    - Core Strategy/Decision/OMS의 책임을 이 composition 객체가 중복 수행하지 않는다.

[Child Page] live_runtime_tick_entry.py
```python
# application/composition/live_runtime_tick_entry.py
from dataclasses import dataclass, replace
from typing import Any


@dataclass
class LiveRuntimeTickEntry:
    runtime: Any
    strategy_to_decision: Any
    decision_to_command: Any
    risk_gate: Any
    route_authoritative: Any
    account_snapshot_provider: Any
    position_source_provider: Any

    def process_tick(self, tick: Any, observed_at: Any, *, risk_context: Any):
        if risk_context is None:
            raise ValueError("RUNTIME_RISK_CONTEXT_REQUIRED")
        evaluations = self.runtime.process_tick(tick, observed_at)
        decisions = self.strategy_to_decision.evaluate(evaluations)
        commands = self.decision_to_command.commands(decisions, evaluations)

        account = self.account_snapshot_provider()
        positions = self.position_source_provider()
        if account is None or positions is None:
            raise ValueError("RUNTIME_RISK_AUTHORITATIVE_STATE_REQUIRED")

        call_context = replace(
            risk_context,
            account_snapshot=account,
            position_source=positions,
        )
        return tuple(
            self.route_authoritative(
                command,
                risk_gate=self.risk_gate,
                context=call_context,
            )
            for command in commands
        )
```
## 수정
    - 실제 route_from_runtime_authoritative_sources(command, risk_gate, context) 계약에 맞춰 호출한다.
    - 호출마다 authoritative Account/Position으로 immutable per-call RiskRouterContext를 생성한다.
    - RuntimeTransport의 router/broker ownership은 유지하고 stale Account/Position은 재사용하지 않는다.

[Child Page] live_runtime_risk_state_factory.py
```python
"""Composition helpers for the Live runtime Risk/tick boundary."""
from __future__ import annotations

from application.composition.execution_path_composition import (
    create_runtime_transport_composition,
)
from application.composition.live_runtime_tick_entry import LiveRuntimeTickEntry
from core.strategy.orchestrator.runtime_authoritative_risk_router_adapter import (
    route_from_runtime_authoritative_sources,
)


def create_live_runtime_tick_transport(
    *,
    strategy_runtime,
    strategy_to_decision,
    decision_to_command,
    risk_gate,
    order_router,
    broker_command,
    risk_state_providers,
):
    """Create the one-shot Runtime transport and TickEntry from one dependency graph.

    The transport's Risk context is an initial composition contract. The
    TickEntry refreshes authoritative Account/Position state on every tick.
    """
    if risk_state_providers is None:
        raise ValueError("LIVE_RUNTIME_RISK_STATE_PROVIDERS_REQUIRED")

    account_snapshot_provider = risk_state_providers.account_snapshot_provider
    position_source_provider = risk_state_providers.position_source_provider

    transport = create_runtime_transport_composition(
        strategy_runtime=strategy_runtime,
        strategy_to_decision=strategy_to_decision,
        decision_to_command=decision_to_command,
        risk_gate=risk_gate,
        account_snapshot=account_snapshot_provider(),
        position_source=position_source_provider(),
        order_router=order_router,
        broker_command=broker_command,
    )
    entry = LiveRuntimeTickEntry(
        runtime=strategy_runtime,
        strategy_to_decision=strategy_to_decision,
        decision_to_command=decision_to_command,
        risk_gate=risk_gate,
        route_authoritative=route_from_runtime_authoritative_sources,
        account_snapshot_provider=account_snapshot_provider,
        position_source_provider=position_source_provider,
    )
    return transport, entry


__all__ = ["create_live_runtime_tick_transport"]

## 책임
- `LiveRuntimeRiskStateProviders`를 `RuntimeTransportComposition`과 `LiveRuntimeTickEntry`에 단일 composition root에서 wiring한다.
- initial Account/Position context는 기존 composition 계약 충족용이며 실제 tick Risk 평가는 entry가 호출 시점 authoritative state로 교체한다.
- synthetic Account/Position을 만들지 않는다.
- Strategy/Decision/Risk 의존성과 provider callable은 caller-supplied 객체를 그대로 공유한다.

```

[Child Page] live_execution_recovery_composition_factory.py
```python
"""Explicit assembly for REST execution recovery into the shared Live settlement seam."""
from __future__ import annotations

from typing import Any

from environments.live.execution.live_execution_recovery_service import LiveExecutionRecoveryService


def create_live_execution_recovery_composition(
    *,
    transport: Any,
    adapter: Any,
    correlation_provider: Any,
    settlement_callback: Any,
) -> LiveExecutionRecoveryService:
    required = {
        "transport": transport,
        "adapter": adapter,
        "correlation_provider": correlation_provider,
        "settlement_callback": settlement_callback,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        raise ValueError("LIVE_RECOVERY_COMPOSITION_DEPENDENCY_REQUIRED:" + ",".join(missing))

    return LiveExecutionRecoveryService(
        transport=transport,
        adapter=adapter,
        correlation_provider=correlation_provider,
        on_report=settlement_callback,
    )
```
## 책임
    - REST recovery transport/adapter/correlation을 기존 settlement callback에 명시적으로 연결한다.
    - recovery 전용 OMS/Position/dedup 상태를 새로 생성하지 않는다.
    - correlation은 OMS-owned provider를 사용한다.
    - 모든 dependency는 caller가 주입하며 숨은 credential/network/account를 생성하지 않는다.

[Child Page] live_runtime_lifecycle_coordinator.py
```python
"""Explicit production lifecycle coordinator for Live runtime startup/shutdown ordering."""
from __future__ import annotations

import asyncio

from typing import Any, Callable


class LiveRuntimeLifecycleCoordinator:
    """Own the cross-component Live startup/recovery/execution lifecycle."""

    def __init__(
        self,
        *,
        controller: Any,
        bootstrap: Any,
        release_execution_transport_ownership: Callable[[], None] | None = None,
    ) -> None:
        if controller is None:
            raise ValueError("LIVE_RUNTIME_CONTROLLER_REQUIRED")
        if bootstrap is None:
            raise ValueError("LIVE_RUNTIME_BOOTSTRAP_REQUIRED")
        self._controller = controller
        self._bootstrap = bootstrap
        self._release_execution_transport_ownership = release_execution_transport_ownership
        self._controller_identity = id(controller)
        self._bootstrap_identity = id(bootstrap)
        self._started = False
        self._stopping = False
        self._active_receives = 0
        self._receive_tasks: set[asyncio.Task[Any]] = set()
        self._receives_drained = asyncio.Event()
        self._receives_drained.set()
        self._policy: Any | None = None
        self._technical_state: str | None = None

    def _assert_dependency_identity(self) -> None:
        if id(self._controller) != self._controller_identity:
            raise RuntimeError("LIVE_RUNTIME_CONTROLLER_IDENTITY_CHANGED")
        if id(self._bootstrap) != self._bootstrap_identity:
            raise RuntimeError("LIVE_RUNTIME_BOOTSTRAP_IDENTITY_CHANGED")

    def _release_transport_ownership(self) -> None:
        if self._release_execution_transport_ownership is not None:
            self._release_execution_transport_ownership()
            self._release_execution_transport_ownership = None

    def _restart_admitted(self) -> bool:
        """Only a fully stopped lifecycle may reuse this coordinator."""
        return (
            not self._started
            and not self._stopping
            and self._technical_state is None
        )

    async def start(self, config: Any, policy: Any, *, hts_id: str, recovery_query: Any) -> Any:
        self._assert_dependency_identity()
        if not self._restart_admitted():
            raise RuntimeError("LIVE_RUNTIME_RESTART_NOT_ADMITTED")

        execution_start_attempted = False
        try:
            self._controller.start(config, policy)
            recovered = self._bootstrap.startup_reconcile(recovery_query)
            execution_start_attempted = True
            await self._bootstrap.start_execution(hts_id)
        except asyncio.CancelledError as startup_cancelled:
            # Cancellation is a startup failure too.  CancelledError inherits
            # BaseException, so it must not bypass cleanup and leave a started
            # controller or claimed transport looking restart-admissible.
            if execution_start_attempted:
                try:
                    await self._bootstrap.close_execution()
                except asyncio.CancelledError:
                    # Startup cleanup was itself interrupted before execution
                    # closure was proven. Retain ownership and block replacement
                    # runtime creation rather than continuing as a clean stop.
                    self._started = False
                    self._stopping = True
                    self._technical_state = "STARTUP_CLEANUP_CANCELLED"
                    raise
                except Exception:
                    pass

            try:
                self._safe_controller_stop()
            except Exception as controller_stop_error:
                self._started = False
                self._stopping = True
                self._technical_state = "STOP_CONTROLLER_FAILED"
                controller_stop_error.__cause__ = startup_cancelled
                raise

            try:
                self._release_transport_ownership()
            except Exception as ownership_release_error:
                self._started = False
                self._stopping = True
                self._technical_state = "TRANSPORT_OWNERSHIP_RELEASE_FAILED"
                ownership_release_error.__cause__ = startup_cancelled
                raise
            raise
        except Exception as startup_error:
            if execution_start_attempted:
                try:
                    await self._bootstrap.close_execution()
                except asyncio.CancelledError:
                    # Startup cleanup was itself interrupted before execution
                    # closure was proven. Retain ownership and block replacement
                    # runtime creation rather than continuing as a clean stop.
                    self._started = False
                    self._stopping = True
                    self._technical_state = "STARTUP_CLEANUP_CANCELLED"
                    raise
                except Exception:
                    pass

            try:
                self._safe_controller_stop()
            except Exception as controller_stop_error:
                # Startup failed and controller shutdown also failed. The
                # production graph is not proven stopped, so retain transport
                # ownership and permanently block restart rather than masking
                # the lifecycle failure with a potentially unsafe new start.
                self._started = False
                self._stopping = True
                self._technical_state = "STOP_CONTROLLER_FAILED"
                controller_stop_error.__cause__ = startup_error
                raise

            try:
                self._release_transport_ownership()
            except Exception as ownership_release_error:
                # Startup cleanup is not complete if the claimed execution
                # transport cannot be proven released. Retain the terminal
                # technical state and block replacement runtime startup.
                self._started = False
                self._stopping = True
                self._technical_state = "TRANSPORT_OWNERSHIP_RELEASE_FAILED"
                ownership_release_error.__cause__ = startup_error
                raise
            raise

        self._started = True
        self._stopping = False
        self._policy = policy
        self._technical_state = None
        return recovered

    async def receive_execution_once(self) -> Any:
        self._assert_dependency_identity()
        if not self._started or self._stopping:
            raise RuntimeError("LIVE_RUNTIME_NOT_STARTED")
        task = asyncio.current_task()
        self._active_receives += 1
        self._receives_drained.clear()
        if task is not None:
            self._receive_tasks.add(task)
        try:
            return await self._bootstrap.receive_execution_once()
        finally:
            if task is not None:
                self._receive_tasks.discard(task)
            self._active_receives -= 1
            if self._active_receives == 0:
                self._receives_drained.set()

    async def _wait_receives_drained(self, timeout_seconds: float) -> None:
        await asyncio.wait_for(
            self._receives_drained.wait(),
            timeout=timeout_seconds,
        )

    async def _cancel_inflight_receives(self) -> None:
        """Use transport-provided cancellation first, otherwise cancel admitted tasks."""
        cancel = getattr(self._bootstrap, "cancel_execution_receives", None)
        if callable(cancel):
            result = cancel()
            if hasattr(result, "__await__"):
                await result
            return

        current = asyncio.current_task()
        for task in tuple(self._receive_tasks):
            if task is not current and not task.done():
                task.cancel()

    @property
    def runtime_controller(self) -> Any:
        """Authoritative controller owned by this production lifecycle graph."""
        self._assert_dependency_identity()
        return self._controller

    @property
    def technical_state(self) -> str | None:
        """Control-plane lifecycle state; independent from Domain order/position state."""
        self._assert_dependency_identity()
        return self._technical_state

    async def stop(self) -> None:
        self._assert_dependency_identity()
        if not self._started:
            if self._technical_state is not None:
                raise RuntimeError("LIVE_RUNTIME_RESTART_NOT_ADMITTED")
            try:
                self._safe_controller_stop()
            except Exception as controller_stop_error:
                # Even an unstarted coordinator may own a claimed execution
                # transport. If controller cleanup cannot be proven, retain
                # ownership and permanently block a replacement runtime.
                self._started = False
                self._stopping = True
                self._technical_state = "STOP_CONTROLLER_FAILED"
                raise controller_stop_error
            try:
                self._release_transport_ownership()
            except Exception:
                # Ownership release is part of the clean-stop proof. If it
                # fails, the transport may still be owned by this graph, so
                # fail closed and retain the terminal technical state.
                self._started = False
                self._stopping = True
                self._technical_state = "TRANSPORT_OWNERSHIP_RELEASE_FAILED"
                raise
            return

        graceful_timeout = float(
            getattr(self._policy, "graceful_shutdown_timeout_seconds", 10.0)
        )
        cancellation_timeout = float(
            getattr(self._policy, "cancellation_drain_timeout_seconds", 5.0)
        )
        if graceful_timeout < 0 or cancellation_timeout < 0:
            raise ValueError("LIVE_RUNTIME_INVALID_SHUTDOWN_TIMEOUT")

        # Validate the shutdown policy before mutating lifecycle state.  A
        # malformed policy must not poison an otherwise-started coordinator
        # into a permanently stopping state.
        self._stopping = True
        close_error: Exception | None = None
        timeout_error: Exception | None = None

        shutdown_cancelled: asyncio.CancelledError | None = None
        try:
            try:
                await self._bootstrap.close_execution()
            except asyncio.CancelledError as exc:
                # Shutdown cancellation means execution close was not proven
                # complete. Do not continue into controller stop or ownership
                # release, because the transport may still be active.
                shutdown_cancelled = exc
            except Exception as exc:
                close_error = exc

            if shutdown_cancelled is None:
                try:
                    await self._wait_receives_drained(graceful_timeout)
                except asyncio.CancelledError as exc:
                    # The receive-drain barrier was interrupted. The admitted
                    # receive ownership is unresolved, so release/restart must
                    # remain fail-closed.
                    shutdown_cancelled = exc
                except asyncio.TimeoutError:
                    try:
                        await self._cancel_inflight_receives()
                    except asyncio.CancelledError as exc:
                        shutdown_cancelled = exc
                    except Exception as exc:
                        # Cancellation failure means receive ownership is not
                        # proven to be drained. Fail closed and retain ownership.
                        timeout_error = RuntimeError(
                            "LIVE_RUNTIME_SHUTDOWN_CANCELLATION_FAILED"
                        )
                        timeout_error.__cause__ = exc
                    if timeout_error is None and shutdown_cancelled is None:
                        try:
                            await self._wait_receives_drained(cancellation_timeout)
                        except asyncio.CancelledError as exc:
                            shutdown_cancelled = exc
                        except asyncio.TimeoutError:
                            timeout_error = RuntimeError(
                                "LIVE_RUNTIME_SHUTDOWN_DRAIN_TIMEOUT"
                            )
        finally:
            if shutdown_cancelled is not None:
                # Fail-closed: a shutdown task cancellation never proves the
                # execution graph or receive ownership stopped. In particular,
                # do not call controller.stop() or release transport ownership
                # from this cancellation path.
                self._started = False
                self._stopping = True
                self._technical_state = "STOP_SHUTDOWN_CANCELLED"
            elif timeout_error is None:
                self._started = False
                try:
                    self._controller.stop()
                except Exception as exc:
                    # Controller shutdown failure means the production
                    # lifecycle is not proven fully stopped. Retain transport
                    # ownership and permanently block restart rather than
                    # allowing a second runtime to overlap the failed graph.
                    self._stopping = True
                    self._technical_state = "STOP_CONTROLLER_FAILED"
                    if close_error is not None:
                        exc.__cause__ = close_error
                    raise
                else:
                    if close_error is not None:
                        # Execution close failed, so the execution transport
                        # is not proven fully released even though the
                        # controller itself stopped successfully. Retain
                        # ownership and block restart rather than allowing a
                        # second runtime to overlap the uncertain transport.
                        self._stopping = True
                        self._technical_state = "STOP_EXECUTION_CLOSE_FAILED"
                    else:
                        try:
                            self._release_transport_ownership()
                        except Exception:
                            # Clean lifecycle completion is not proven until
                            # ownership release succeeds. Retain ownership
                            # and block restart on release failure.
                            self._stopping = True
                            self._technical_state = "TRANSPORT_OWNERSHIP_RELEASE_FAILED"
                            raise
                        else:
                            self._stopping = False
                            self._technical_state = None
            else:
                # Fail-closed: unresolved receive ownership is never released
                # and this coordinator is permanently restart-blocked.
                self._started = False
                self._stopping = True
                self._technical_state = "STOP_TIMEOUT"

        if shutdown_cancelled is not None:
            raise shutdown_cancelled
        if timeout_error is not None:
            raise timeout_error
        if close_error is not None:
            raise close_error

    def _safe_controller_stop(self) -> None:
        self._controller.stop()
```
## 책임
    - RuntimeController 내부에 bootstrap/execution lifecycle을 넣지 않는다.
    - 정상 lifecycle은 controller.start → reconciliation → execution.start 순서를 유지한다.
    - 정상 stop은 execution close → receive drain → controller.stop → ownership release 순서를 유지한다.
    - STOP_TIMEOUT은 Domain 주문/포지션 상태가 아닌 technical lifecycle failure다.
    - STOP_TIMEOUT 발생 후에는 unresolved receive ownership이 존재할 수 있으므로 coordinator 재시작과 ownership release를 모두 금지한다.
    - restart는 clean stop이 완료되어 _stopping=False, technical_state=None인 경우에만 허용한다.
    - ERROR/timeout 상태를 새 start로 덮어쓰거나 강제로 정상화하지 않는다.
    - Control-plane status를 읽는 경로도 controller/bootstrap identity를 먼저 검증하여 external dependency mutation을 정상 status로 투영하지 않는다.
    - 실계좌/credential/network를 생성하지 않으며 모든 실제 dependency는 caller가 주입한다.
## No.566 보완 — unstarted cleanup controller.stop 실패 fail-closed 계약
    - _started=False cleanup 경로에서 controller.stop() 실패 시 STOP_CONTROLLER_FAILED terminal technical state를 유지하고 ownership을 release하지 않는다.
    - 후속 restart는 LIVE_RUNTIME_RESTART_NOT_ADMITTED로 차단한다.
    - clean cleanup에서는 기존 ownership release를 유지한다.

[Child Page] live_runtime_production_factory.py
```python
"""Explicit production assembly for the Live runtime lifecycle."""
from __future__ import annotations

from typing import Any

from application.bootstrap import create_live_runtime_bootstrap
from application.composition.live_runtime_composition_factory import (
	build_live_bundle_from_components,
	create_live_runtime_controller,
)
from application.composition.live_runtime_lifecycle_coordinator import (
	LiveRuntimeLifecycleCoordinator,
)
from application.composition.control_tower_runtime_composition import (
	create_live_control_tower_runtime_api,
)


class _LiveExecutionTransportOwnershipRegistry:
	"""Fail-closed ownership registry for one shared execution transport."""

	def __init__(self) -> None:
		self._owners: dict[int, object] = {}

	def claim(self, transport: Any):
		key = id(transport)
		if key in self._owners:
			raise RuntimeError("LIVE_EXECUTION_TRANSPORT_ALREADY_OWNED")
		token = object()
		self._owners[key] = token

		def release() -> None:
			if self._owners.get(key) is token:
				self._owners.pop(key, None)

		return release


_execution_transport_ownership = _LiveExecutionTransportOwnershipRegistry()


def create_live_control_tower_runtime(*, lifecycle_coordinator: LiveRuntimeLifecycleCoordinator):
	"""Attach the authoritative Live lifecycle graph to the Control Tower boundary."""
	return create_live_control_tower_runtime_api(
		lifecycle_coordinator=lifecycle_coordinator,
	)


def create_live_runtime_lifecycle_coordinator(
	*,
	market: Any,
	broker: Any,
	account: Any,
	position: Any,
	reconciler: Any,
	transport: Any,
	execution_adapter: Any,
	correlation_provider: Any,
	order_state_machine: Any,
	position_fill_adapter: Any,
	execution_event_deduplicator: Any,
	position_aggregate: Any,
	safety_policy: Any,
	recovery_transport: Any | None = None,
	recovery_adapter: Any | None = None,
	runtime_transport: Any | None = None,
	tick_entry: Any | None = None,
	risk_state_providers: Any | None = None,
) -> LiveRuntimeLifecycleCoordinator:
	"""Assemble one concrete Live controller + bootstrap dependency graph.

	All broker, market, account, position, execution, recovery, and policy
	objects are caller-supplied. No credential, network client, or synthetic
	business dependency is created here.
	"""
	position_owner = getattr(position_fill_adapter, "_aggregate", None)
	if position_owner is not position_aggregate:
		raise ValueError("LIVE_RUNTIME_POSITION_AGGREGATE_OWNERSHIP_MISMATCH")

	execution_dependencies = {
		"transport": transport,
		"execution_adapter": execution_adapter,
		"correlation_provider": correlation_provider,
		"broker": broker,
		"order_state_machine": order_state_machine,
		"position_fill_adapter": position_fill_adapter,
		"execution_event_deduplicator": execution_event_deduplicator,
		"position_aggregate": position_aggregate,
		"recovery_transport": recovery_transport,
		"recovery_adapter": recovery_adapter,
	}
	if tick_entry is not None:
		if risk_state_providers is None:
			raise ValueError("LIVE_RUNTIME_RISK_STATE_PROVIDERS_REQUIRED")
		provider_mismatches = [
			name
			for name in ("account_snapshot_provider", "position_source_provider")
			if getattr(tick_entry, name, None)
			is not getattr(risk_state_providers, name, None)
		]
		if provider_mismatches:
			raise ValueError(
				"LIVE_RUNTIME_RISK_STATE_PROVIDER_OWNERSHIP_MISMATCH:"
				+ ",".join(provider_mismatches)
			)

	bootstrap = create_live_runtime_bootstrap(
		runtime_transport=runtime_transport,
		tick_entry=tick_entry,
		**execution_dependencies,
	)

	bundle_builder = build_live_bundle_from_components(
		market=market,
		broker=broker,
		account=account,
		position=position,
		reconciler=reconciler,
		recovery=bootstrap.recovery_service,
		safety_policy=safety_policy,
	)
	controller = create_live_runtime_controller(live_builder=bundle_builder)
	release_transport_ownership = _execution_transport_ownership.claim(transport)
	try:
		return LiveRuntimeLifecycleCoordinator(
			controller=controller,
			bootstrap=bootstrap,
			release_execution_transport_ownership=release_transport_ownership,
		)
	except Exception:
		# Coordinator construction is part of assembly.  If it fails after the
		# transport claim, release the claim so a failed assembly cannot poison
		# the transport for the next explicit runtime construction.
		release_transport_ownership()
		raise
```
## 책임
    - application/composition에서만 concrete Live production dependency graph를 조립한다.
    - create_live_runtime_controller()와 create_live_runtime_bootstrap()을 하나의 명시적 coordinator factory 경계에서 결합한다.
    - RuntimeController에는 bootstrap/execution lifecycle을 추가하지 않는다.
    - 동일 broker, order_state_machine, execution/recovery correlation_provider를 각각의 composition에 전달하고, execution settlement의 position_aggregate와 position_fill_adapter가 동일 aggregate를 가리키도록 하여 silent duplicate settlement state를 만들지 않는다.
    - LiveEnvironmentBundle.position은 Risk/Environment 쪽 authoritative position source이고 execution-owned position_aggregate와는 계약상 역할이 다르므로 동일 객체라고 강제하지 않는다.
    - injected tick_entry가 존재하는 경우 risk_state_providers를 함께 명시 공급받고 Account/Position provider callable identity를 검증하여 production coordinator에서 다른 Risk state owner가 조용히 연결되지 않도록 한다.
    - runtime_transport/tick_entry 자체를 새로 생성하거나 synthetic provider를 만들지는 않는다. 실제 tick graph 생성은 기존 create_live_runtime_tick_transport() composition seam과 caller-supplied strategy/decision/Risk dependencies가 담당한다.
    - recovery dependency는 execution composition이 만든 recovery_service를 LiveEnvironmentBundle에도 그대로 공급한다.
    - 누락 dependency와 ownership mismatch는 하위 factory/bootstrap의 기존 fail-closed 검증을 그대로 사용한다.
    - 인증정보, 실계좌, 실주문, KIS network client를 생성하지 않는다.

[Child Page] control_tower_runtime_composition.py
```python
"""Authoritative Control Tower assembly for runtime status/control exposure."""
from __future__ import annotations

from interfaces.control_tower.live_runtime_api import LiveControlTowerRuntimeAPI


def create_live_control_tower_runtime_api(*, lifecycle_coordinator) -> LiveControlTowerRuntimeAPI:
    """Expose one Live production lifecycle graph through the Control Tower boundary.

    The same coordinator owns the technical lifecycle state and its authoritative
    RuntimeController. Splitting these sources would allow STOP_TIMEOUT to be
    silently omitted from UI/control-plane status.
    """
    if lifecycle_coordinator is None:
        raise ValueError("LIVE_RUNTIME_LIFECYCLE_COORDINATOR_REQUIRED")

    controller = getattr(lifecycle_coordinator, "runtime_controller", None)
    if controller is None:
        raise ValueError("LIVE_RUNTIME_CONTROLLER_REQUIRED")

    marker = "_control_tower_runtime_api"
    try:
        existing = getattr(lifecycle_coordinator, marker, None)
    except Exception as exc:
        raise RuntimeError("LIVE_RUNTIME_CONTROL_TOWER_ASSEMBLY_READ_FAILED") from exc
    if existing is not None:
        if not isinstance(existing, LiveControlTowerRuntimeAPI):
            raise RuntimeError("LIVE_RUNTIME_CONTROL_TOWER_ASSEMBLY_CHANGED")
        if getattr(existing, "_lifecycle_coordinator", None) is not lifecycle_coordinator:
            raise RuntimeError("LIVE_RUNTIME_CONTROL_TOWER_COORDINATOR_MISMATCH")
        return existing

    api = LiveControlTowerRuntimeAPI(lifecycle_coordinator)
    try:
        setattr(lifecycle_coordinator, marker, api)
    except Exception as exc:
        raise RuntimeError("LIVE_RUNTIME_CONTROL_TOWER_ASSEMBLY_WRITE_FAILED") from exc

    try:
        stored = getattr(lifecycle_coordinator, marker)
    except Exception as exc:
        raise RuntimeError("LIVE_RUNTIME_CONTROL_TOWER_ASSEMBLY_READ_FAILED") from exc
    if stored is not api:
        raise RuntimeError("LIVE_RUNTIME_CONTROL_TOWER_ASSEMBLY_CHANGED")
    return api
```
## 책임
    - Live production coordinator가 보유한 동일 controller와 technical_state source를 하나의 Control Tower API에 연결한다.
    - 별도 lifecycle source 또는 synthetic status를 생성하지 않는다.
    - STOP_TIMEOUT은 RuntimeStatus.technical_state로만 노출하며 Domain 상태와 혼합하지 않는다.
    - terminal STOP_TIMEOUT coordinator는 Control Tower assembly로 새 정상 lifecycle을 만들지 않으며, command API의 start/restart admission guard가 controller 직접 우회를 차단한다.
    - coordinator/controller identity 불일치는 coordinator의 기존 fail-closed guard에 맡긴다.