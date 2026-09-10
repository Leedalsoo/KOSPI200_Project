[Child Page] virtual_execution.py
```python
from typing import Callable, Iterable

from contracts.execution import ExecutionProvider
from contracts.types import BrokerOrderCommand, DataQuality, ExecutionReport


class VirtualExecutionEngine(ExecutionProvider):
    """Virtual execution boundary with an explicit authoritative-fill seam.

    The environment supplies the real VSSF market-match/execution adapter.
    This class does not invent an execution price when that adapter is absent.
    """

    def __init__(
        self,
        position,
        account,
        *,
        authoritative_execute: Callable[[BrokerOrderCommand], ExecutionReport]
        | None = None,
    ):
        self.position = position
        self.account = account
        self._authoritative_execute = authoritative_execute
        self._reports: dict[str, ExecutionReport] = {}

    def execute(self, order: BrokerOrderCommand) -> ExecutionReport:
        if self._authoritative_execute is not None:
            report = self._authoritative_execute(order)
            self._reports[order.client_order_id] = report
            return report

        # A virtual execution cannot be reported as FILLED without the
        # authoritative VSSF matching/execution path. Fail closed instead of
        # manufacturing a synthetic fill report.
        raise RuntimeError("AUTHORITATIVE_VSSF_EXECUTION_ADAPTER_REQUIRED")

    def cancel(self, client_order_id: str) -> ExecutionReport:
        report = ExecutionReport(
            client_order_id=client_order_id,
            broker_order_id=client_order_id,
            execution_id=None,
            status="CANCELLED",
            filled_quantity=0,
            remaining_quantity=0,
            execution_price=None,
            execution_timestamp=None,
            source_freshness=DataQuality(
                is_fresh=True,
                is_complete=False,
                source_available=True,
                reason="virtual_execution_cancel_policy",
            ),
        )
        self._reports[client_order_id] = report
        return report

    def query(self, client_order_id: str) -> ExecutionReport | None:
        return self._reports.get(client_order_id)

    def reports(self) -> Iterable[ExecutionReport]:
        return tuple(self._reports.values())

    def query_execution(self, execution_id: str) -> ExecutionReport | None:
        for report in self._reports.values():
            if report.execution_id == execution_id:
                return report
        return None
```
## 이번 단계 정합화
    - 원격 Exp_Detail_1의 실제 VSSF OrderBook.match_order()가 CanonicalOrderCommand.price를 그대로 체결가격으로 쓰지 않고 실제 best_ask/best_bid와 비교하여 matched_price를 산출하는 것을 확인했다.
    - 원격 VSSF ExecutionEngine.execute_order(command, fill_price, fill_qty)는 이 실제 매칭가격을 입력받아 SlippageEngine을 적용하고 CanonicalExecutionReport.executed_price를 확정한다.
    - 따라서 Standard VirtualExecutionEngine에는 임의 가격을 추가하지 않고, 실제 VMS/VSSF adapter를 authoritative_execute로 주입할 수 있는 명시적 경계를 추가했다.
    - adapter가 연결되면 흐름은 Standard BrokerOrderCommand → VSSF OrderBook 실제 matched_price → VSSF ExecutionEngine.execute_order(fill_price, fill_qty) → CanonicalExecutionReport → Standard ExecutionReport가 된다.
    - OrderIntent와 BrokerOrderCommand에는 requested_price를 보존하는 필드를 추가했다. 이는 주문 요청 의미를 전달하기 위한 것이며 실제 체결가격과 동일시하지 않는다.
    - adapter가 없을 때는 FILLED 또는 불완전 체결 보고서를 생성하지 않고 AUTHORITATIVE_VSSF_EXECUTION_ADAPTER_REQUIRED로 fail-closed한다.
    - 실제 VSSF Account/Position/PnL/Margin/Ledger 변경은 authoritative report의 실제 가격/수량/side를 확보한 후 다음 경계에서 연결한다.
    - No.125의 PRICE_MISMATCH 안전 원칙에 따라 주문가격을 체결가격 fallback으로 사용하지 않는다.
## 검증 상태
    - 원격 Exp_Detail_1 shared/contracts/canonical.py 확인: PASS
    - 원격 Exp_Detail_1 VMS HistoricalReplayEngine의 price/bid/ask source 확인: PASS
    - 원격 Exp_Detail_1 VSSF OrderBook.match_order() 확인: PASS
    - 원격 Exp_Detail_1 VSSF ExecutionEngine.execute_order() 확인: PASS
    - 원격 Git branch write: 미수행
    - Python/pytest: 원격 branch 수정 없이 실행 가능한 환경이 없어 미실행
    - 실제 VMS→VSSF→Standard runtime wiring: ConcreteVirtualEnvironmentBuilder에서 VSSFExecutionAdapter.execute를 authoritative_execute로 주입하는 경로가 구성되어 있다.

[Child Page] vssf_execution_adapter.py
```python
from dataclasses import dataclass
from typing import Protocol

from contracts.types import BrokerOrderCommand


class VSSFCommandContextProvider(Protocol):
	"""Standard 주문으로부터 실제 VSSF 주문 생성에 필요한 권위 데이터를 공급한다."""

	def build_command(self, order: BrokerOrderCommand) -> object: ...


class VSSFRuntime(Protocol):
	"""실제 VSSF 전체 주문→Risk→OrderBook→Execution 경로."""

	def process_order(self, command: object) -> object: ...


@dataclass(frozen=True)
class VSSFExecutionAdapter:
	"""Standard BrokerOrderCommand를 실제 VSSF Runtime 경계로 연결한다."""

	command_context: VSSFCommandContextProvider
	vssf_runtime: VSSFRuntime

	def execute(self, order: BrokerOrderCommand) -> object:
		vssf_command = self.command_context.build_command(order)
		return self.vssf_runtime.process_order(vssf_command)
```
## 이번 단계에서 확정된 실제 연결 경계
    - 원격 VirtualSecuritiesFirmRuntime.process_order()가 VSSF의 단일 주문 처리 진입점이다.
    - process_order() 내부에서 Margin/Risk 검증 → OrderBook.match_order() → ExecutionEngine.execute_order() → PaperTradingAccount.apply_execution()까지 연결된다.
    - 따라서 Standard Adapter에서 FillMatcher와 ExecutionEngine을 별도로 호출하여 동일 단계를 중복 실행하지 않는다.
    - Standard BrokerOrderCommand → 실제 VSSF CanonicalOrderCommand 변환은 VSSFCommandContextProvider가 담당한다.
    - 실제 옵션 identity와 가격은 이 provider가 기존 프로그램의 authoritative source에서 가져와야 한다.
## 확인된 Standard 입력의 한계
현재 Standard BrokerOrderCommand는 client_order_id, instrument_id, side, quantity, order_type, broker_symbol, session_id만 가진다.
따라서 price, track_id, asset_type, option_type, strike, expiry를 adapter에서 임의 생성하지 않는다.
특히 다음은 금지한다.
    - Standard 주문가격을 VSSF 체결가격으로 사용하지 않는다.
    - 0.0 또는 임의 가격을 VSSF command에 넣지 않는다.
    - 임의의 옵션 strike/expiry/type을 생성하지 않는다.
    - Standard Contract에 VSSF 전용 필드를 추가하지 않는다.
## 기존 프로그램 보존
    - 기존 PaperBrokerAdapter는 이미 send_order()와 poll_execution_reports()를 분리하고 VSSF Runtime을 호출한다.
    - OMS OrderRouter는 주문 등록/WAL/FSM을 담당하고 Broker 직접 발주는 Orchestrator에 위임한다.
    - 기존 VSSF의 Margin, Position, PnL, Ledger, Reconciliation, Recovery 책임은 VSSF 내부에 그대로 둔다.
    - 9개 전략 및 Legacy Runtime의 동작을 이 adapter 작업 때문에 변경하지 않는다.
## 실제 주문 생성부 추적 결과
원격 Exp_Detail_1에서 실제 CanonicalOrderCommand 생성부를 확인했다.
option_program/runtime/program_runtime.py의 OptionProgramRuntime.process_tick()에서 DecisionArbiter가 승인한 CanonicalStrategySignal을 기반으로 CanonicalOrderCommand를 직접 생성한다.
```plain text
VMS CanonicalMarketTick
  → OptionProgramRuntime.process_tick()
  → Track 1~9 전략 평가
  → CanonicalStrategySignal
  → DecisionArbiter
  → CanonicalOrderCommand 생성
  → RiskGate.admit_order()
  → OrderRouter.register_and_route()
  → TradingSystem.run_loop()
  → Broker.send_order()
  → VSSF Runtime.process_order()
```
실제 command 생성 시 다음 값은 approved_sig에서 공급된다.
    - track_id ← approved_sig.track_id
    - asset_type ← approved_sig.asset_type
    - side ← approved_sig.side
    - qty ← approved_sig.qty
    - price ← approved_sig.price
    - option_type ← approved_sig.option_type
    - strike ← approved_sig.strike
    - tag_id ← approved_sig.tag_id
    - client_order_id ← 현재 tick sequence + track + signal sequence로 생성
따라서 실제 프로그램에는 이미 Standard와 동일 계층의 canonical command가 존재하며, 현재 Paper/Shadow 경로에서는 별도의 VSSF 전용 command 변환 없이 같은 CanonicalOrderCommand가 VSSF Runtime으로 전달된다.
## 실제 VSSF 연결 결과
TradingSystem.run_loop()는 OptionProgramRuntime.process_tick()이 반환한 command를 Broker.send_order(cmd)로 전달한다. PaperBrokerAdapter.poll_execution_reports()는 pending command를 self.vssf.process_order(cmd)로 전달한다.
VSSF process_order()는 다음을 단일 권위 경로로 수행한다.
Margin/Risk → OrderBook.match_order() → matched_price → ExecutionEngine.execute_order() → PaperTradingAccount.apply_execution()
따라서 adapter가 OrderBook이나 ExecutionEngine을 다시 호출하면 기존 프로그램의 체결 경로를 중복하게 된다.
## 현재 Standard Adapter의 결론
현재 VSSFExecutionAdapter는 실제 VSSF 전체 경로를 직접 복제하지 않고 VSSFCommandContextProvider → VSSFRuntime.process_order()라는 경계만 제공하는 것이 맞다.
다만 Standard BrokerOrderCommand에는 실제 OptionProgram command가 보유하는 track_id / asset_type / price / option_type / strike / expiry 등이 없으므로, 이 adapter에 concrete translator를 추가하려면 authoritative context provider의 실제 source를 별도로 연결해야 한다.
다음 concrete 구현에서 임의 가격, 임의 strike/expiry/type, 주문가격을 체결가격으로 사용하는 fallback은 금지한다. 기존 PaperBrokerAdapter → VSSF Runtime 경로와 9개 전략, OMS/WAL/FSM, VSSF Margin/Position/PnL/Ledger/Reconciliation/Recovery를 유지한다.
원격 Exp_Detail_1에는 write하지 않는다.

[Child Page] order_intent_adapter.py
```python
from dataclasses import dataclass

from contracts.types import BrokerOrderCommand, OrderIntent


class OrderIntentMappingError(ValueError):
    """Raised when an OrderIntent cannot be safely translated."""


@dataclass(frozen=True)
class OrderIntentAdapter:
    """Environment boundary: OrderIntent -> BrokerOrderCommand.

    This layer performs validation and environment-neutral field preservation.
    Broker-specific symbol/API conversion belongs to the concrete environment
    adapter, not to Core/OMS.
    """

    def to_broker_command(self, intent: OrderIntent) -> BrokerOrderCommand:
        if not intent.client_order_id:
            raise OrderIntentMappingError("CLIENT_ORDER_ID_REQUIRED")
        if not intent.instrument_id:
            raise OrderIntentMappingError("INSTRUMENT_ID_REQUIRED")
        if intent.quantity <= 0:
            raise OrderIntentMappingError("QUANTITY_REQUIRED")
        if not intent.side:
            raise OrderIntentMappingError("SIDE_REQUIRED")
        if not intent.order_type:
            raise OrderIntentMappingError("ORDER_TYPE_REQUIRED")

        identity = intent.instrument_identity
        if intent.asset_type == "OPTION":
            if identity is None:
                raise OrderIntentMappingError("OPTION_IDENTITY_REQUIRED")
            if not identity.symbol or not identity.expiry:
                raise OrderIntentMappingError("OPTION_SYMBOL_EXPIRY_REQUIRED")
            if identity.option_type is None or identity.strike is None or identity.strike <= 0:
                raise OrderIntentMappingError("OPTION_CONTRACT_FIELDS_REQUIRED")
            if identity.instrument_id != intent.instrument_id:
                raise OrderIntentMappingError("INSTRUMENT_IDENTITY_MISMATCH")

        return BrokerOrderCommand(
            client_order_id=intent.client_order_id,
            instrument_id=intent.instrument_id,
            side=intent.side,
            quantity=intent.quantity,
            order_type=intent.order_type,
            broker_symbol=identity.symbol if identity is not None else None,
            instrument_identity=identity,
            asset_type=intent.asset_type,
            requested_price=intent.requested_price,
            strategy_id=intent.strategy_id,
            order_purpose=intent.order_purpose,
            track_id=intent.track_id,
            tag_id=intent.tag_id,
            group_id=intent.group_id,
            leg_id=intent.leg_id,
        )
```
## 매핑 원칙
    - OrderIntent가 확정한 identity를 다시 추론하거나 legacy default로 보완하지 않는다.
    - instrument_id, side, quantity, order_type, requested price, strategy/provenance metadata를 보존한다.
    - OPTION은 symbol/expiry/option_type/strike와 instrument_id 일치 여부를 매핑 직전에 검증한다.
    - requested_price는 주문 요청 의미이며 실제 체결가격은 ExecutionReport.execution_price로만 표현한다.
    - 실제 VSSF/KIS symbol/API 형식 변환은 구체적인 Environment Adapter의 책임이다.
    - broker command 생성 실패 시 주문을 전송하지 않는다.

[Child Page] test_order_intent_adapter.py
```python
from decimal import Decimal

import pytest

from contracts.types import OptionInstrumentIdentity, OrderIntent
from environments.virtual.execution.order_intent_adapter import (
    OrderIntentAdapter,
    OrderIntentMappingError,
)


def test_option_intent_maps_identity_and_requested_price_without_fabrication():
    identity = OptionInstrumentIdentity(
        instrument_id="OPT-700-C-202609",
        symbol="KOSPI200",
        expiry="202609",
        option_type="CALL",
        strike=Decimal("700"),
    )
    intent = OrderIntent(
        client_order_id="ORD-1",
        instrument_id=identity.instrument_id,
        side="BUY",
        quantity=2,
        intent_type="ENTRY",
        strategy_id="track1",
        instrument_identity=identity,
        asset_type="OPTION",
        requested_price=Decimal("1.25"),
        order_type="LIMIT",
        order_purpose="ENTRY",
        track_id="track1",
        tag_id="tail-defense",
    )

    command = OrderIntentAdapter().to_broker_command(intent)

    assert command.instrument_id == identity.instrument_id
    assert command.instrument_identity == identity
    assert command.broker_symbol == identity.symbol
    assert command.requested_price == Decimal("1.25")
    assert command.order_type == "LIMIT"
    assert command.strategy_id == "track1"
    assert command.track_id == "track1"
    assert command.tag_id == "tail-defense"


def test_option_identity_mismatch_fails_closed():
    identity = OptionInstrumentIdentity(
        instrument_id="OPT-700-C-202609",
        symbol="KOSPI200",
        expiry="202609",
        option_type="CALL",
        strike=Decimal("700"),
    )
    intent = OrderIntent(
        client_order_id="ORD-2",
        instrument_id="OTHER",
        side="BUY",
        quantity=1,
        intent_type="ENTRY",
        instrument_identity=identity,
        asset_type="OPTION",
        order_type="LIMIT",
        order_purpose="ENTRY",
    )

    with pytest.raises(OrderIntentMappingError, match="INSTRUMENT_IDENTITY_MISMATCH"):
        OrderIntentAdapter().to_broker_command(intent)


def test_missing_requested_price_is_allowed_for_market_semantics():
    intent = OrderIntent(
        client_order_id="ORD-3",
        instrument_id="FUT-1",
        side="BUY",
        quantity=1,
        intent_type="ENTRY",
        asset_type="FUTURES",
        requested_price=None,
        order_type="MARKET",
        order_purpose="ENTRY",
    )

    command = OrderIntentAdapter().to_broker_command(intent)
    assert command.requested_price is None
    assert command.order_type == "MARKET"
```
## 검증 기준
    - 확정된 identity가 BrokerOrderCommand까지 보존된다.
    - requested_price와 execution_price의 의미가 분리된다.
    - OPTION의 symbol/expiry/option_type/strike/instrument_id 불일치는 fail-closed 한다.
    - MARKET 주문처럼 요청가격이 없는 경우 None을 보존하며 임의 가격을 만들지 않는다.
    - 실제 Broker/VSSF API 호출은 수행하지 않는다.

[Child Page] execution_event_deduplicator.py
```python
from contracts.types import ExecutionReport
from environments.virtual.execution.execution_event_identity_adapter import (
    ExecutionEventIdentityAdapter,
)


class ExecutionEventDeduplicator:
    """Environment-owned execution-event gate for exactly-once downstream delivery."""

    def __init__(self, identity_adapter: ExecutionEventIdentityAdapter | None = None):
        self._identity_adapter = identity_adapter or ExecutionEventIdentityAdapter()
        self._seen_execution_ids: set[str] = set()

    def accept(self, report: ExecutionReport) -> bool:
        """Return True only for a previously unseen execution identity."""
        identity = self._identity_adapter.identify(report)
        if identity.execution_id in self._seen_execution_ids:
            return False
        self._seen_execution_ids.add(identity.execution_id)
        return True
```

[Child Page] test_execution_event_deduplicator.py
```python
from datetime import datetime
from decimal import Decimal

import pytest

from contracts.types import ExecutionReport
from environments.virtual.execution.execution_event_deduplicator import (
    ExecutionEventDeduplicator,
)


def report(execution_id="EXEC-001", client_order_id="ORD-001"):
    return ExecutionReport(
        client_order_id=client_order_id,
        broker_order_id="BRK-001",
        execution_id=execution_id,
        status="FILLED",
        filled_quantity=3,
        remaining_quantity=0,
        execution_price=Decimal("101.5"),
        execution_timestamp=datetime(2026, 9, 5),
    )


def test_first_execution_event_is_accepted():
    assert ExecutionEventDeduplicator().accept(report()) is True


def test_same_execution_id_is_accepted_only_once():
    gate = ExecutionEventDeduplicator()
    assert gate.accept(report("EXEC-001")) is True
    assert gate.accept(report("EXEC-001", "ORD-002")) is False


def test_distinct_execution_ids_are_independent():
    gate = ExecutionEventDeduplicator()
    assert gate.accept(report("EXEC-001")) is True
    assert gate.accept(report("EXEC-002", "ORD-002")) is True


def test_missing_execution_id_fails_closed():
    with pytest.raises(ValueError, match="EXECUTION_EVENT_ID_REQUIRED"):
        ExecutionEventDeduplicator().accept(report(None))
```

[Child Page] virtual_execution_position_bridge.py
```python
from contracts.types import BrokerOrderCommand, ExecutionReport
from environments.virtual.execution.execution_event_deduplicator import ExecutionEventDeduplicator
from environments.virtual.position.virtual_position_fill_adapter import VirtualPositionFillAdapter


class VirtualExecutionPositionBridge:
    """Environment-owned bridge from one broker execution to Position settlement."""

    def __init__(self, broker, deduplicator: ExecutionEventDeduplicator, fill_adapter: VirtualPositionFillAdapter):
        self.broker = broker
        self.deduplicator = deduplicator
        self.fill_adapter = fill_adapter

    def submit(self, command: BrokerOrderCommand) -> ExecutionReport:
        report = self.broker.submit(command)
        if self.deduplicator.accept(report):
            self.fill_adapter.apply(command, report)
        return report
```
## 책임
    - 기존 VirtualBroker.submit()을 먼저 호출한다.
    - 반환된 ExecutionReport를 Environment execution-event deduplication 경계에 통과시킨다.
    - 최초 execution event만 VirtualPositionFillAdapter.apply()로 전달한다.
    - 중복 event는 Position에 다시 적용하지 않는다.
    - filled_quantity를 cumulative/delta로 재해석하지 않는다.
    - 기존 VirtualBroker, VirtualExecutionEngine, ExecutionReport 계약은 변경하지 않는다.
## 연결 위치
    - Bridge는 Environment 실행→정산 경계다.
    - 실제 객체 조립은 application/composition이 담당한다.
    - 현재 단계에서는 기존 Runtime/Environment Factory를 변경하지 않고 bridge와 독립 테스트만 유지한다.
    - 다음 단계에서 실제 Virtual Broker 공급 위치를 확인한 뒤 최소 wiring 여부를 결정한다.

[Child Page] test_virtual_execution_position_bridge.py
```python
from decimal import Decimal

from contracts.types import BrokerOrderCommand, ExecutionReport
from environments.virtual.execution.execution_event_deduplicator import ExecutionEventDeduplicator
from environments.virtual.execution.virtual_execution_position_bridge import VirtualExecutionPositionBridge
from environments.virtual.position.virtual_position_aggregate import VirtualPositionAggregate
from environments.virtual.position.virtual_position_fill_adapter import VirtualPositionFillAdapter


class StubBroker:
    def __init__(self, report):
        self.report = report

    def submit(self, command):
        return self.report


def command():
    return BrokerOrderCommand(
        client_order_id="o1", instrument_id="K200-C-350", side="BUY", quantity=3, order_type="LIMIT"
    )


def report(execution_id="e1"):
    return ExecutionReport(
        client_order_id="o1", broker_order_id="b1", execution_id=execution_id,
        status="FILLED", filled_quantity=3, remaining_quantity=0,
        execution_price=Decimal("101"), execution_timestamp=None,
    )


def test_one_execution_is_applied_once():
    position = VirtualPositionAggregate("K200-C-350")
    broker = StubBroker(report())
    bridge = VirtualExecutionPositionBridge(
        broker, ExecutionEventDeduplicator(), VirtualPositionFillAdapter(position)
    )
    bridge.submit(command())
    bridge.submit(command())
    assert position.snapshot()["K200-C-350"].qty == 3


def test_distinct_execution_events_are_each_applied():
    position = VirtualPositionAggregate("K200-C-350")
    broker = StubBroker(report("e1"))
    bridge = VirtualExecutionPositionBridge(
        broker, ExecutionEventDeduplicator(), VirtualPositionFillAdapter(position)
    )
    bridge.submit(command())
    broker.report = report("e2")
    bridge.submit(command())
    assert position.snapshot()["K200-C-350"].qty == 6
```
실제 pytest 실행은 아직 수행하지 않았다.

[Child Page] vssf_command_context_provider.py
```python
from dataclasses import dataclass
from decimal import Decimal

from contracts.types import BrokerOrderCommand
from shared.contracts.canonical import (
    CanonicalAssetType, CanonicalOptionType, CanonicalOrderCommand, CanonicalOrderSide,
)

class VSSFCommandContextError(ValueError):
    """Raised when a Standard order cannot be losslessly converted for VSSF."""

@dataclass(frozen=True)
class CanonicalVSSFCommandContextProvider:
    """Concrete Standard BrokerOrderCommand -> Reference CanonicalOrderCommand adapter."""

    def build_command(self, order: BrokerOrderCommand) -> CanonicalOrderCommand:
        identity = order.instrument_identity
        if not order.client_order_id:
            raise VSSFCommandContextError("CLIENT_ORDER_ID_REQUIRED")
        if not order.track_id:
            raise VSSFCommandContextError("TRACK_ID_REQUIRED")
        if order.quantity <= 0:
            raise VSSFCommandContextError("QUANTITY_REQUIRED")
        if order.requested_price is None:
            raise VSSFCommandContextError("REQUESTED_PRICE_REQUIRED")
        if order.asset_type != CanonicalAssetType.OPTION.value:
            raise VSSFCommandContextError("OPTION_ASSET_TYPE_REQUIRED")
        if order.side not in {CanonicalOrderSide.BUY.value, CanonicalOrderSide.SELL.value}:
            raise VSSFCommandContextError("CANONICAL_SIDE_REQUIRED")
        if identity is None:
            raise VSSFCommandContextError("OPTION_IDENTITY_REQUIRED")
        if identity.instrument_id != order.instrument_id:
            raise VSSFCommandContextError("INSTRUMENT_IDENTITY_MISMATCH")
        if not identity.symbol:
            raise VSSFCommandContextError("OPTION_SYMBOL_REQUIRED")
        if not identity.expiry:
            raise VSSFCommandContextError("OPTION_EXPIRY_REQUIRED")
        if identity.option_type not in {
            CanonicalOptionType.CALL.value, CanonicalOptionType.PUT.value,
        }:
            raise VSSFCommandContextError("CANONICAL_OPTION_TYPE_REQUIRED")
        if identity.strike is None or identity.strike <= Decimal("0"):
            raise VSSFCommandContextError("OPTION_STRIKE_REQUIRED")
        if not order.tag_id:
            raise VSSFCommandContextError("TAG_ID_REQUIRED")

        return CanonicalOrderCommand(
            client_order_id=order.client_order_id,
            track_id=order.track_id,
            asset_type=CanonicalAssetType(order.asset_type),
            side=CanonicalOrderSide(order.side),
            qty=order.quantity,
            price=float(order.requested_price),
            option_type=CanonicalOptionType(identity.option_type),
            strike=float(identity.strike),
            symbol=identity.symbol,
            expiry=identity.expiry,
            tag_id=order.tag_id,
        )
```
## 계약
    - 최신 Reference CanonicalOrderCommand 생성자와 직접 대조했다.
    - Standard 문자열 값은 Reference Enum으로 명시 정규화한다.
    - Decimal 가격/행사가는 Reference DTO의 float 계약에 맞춘다.
    - identity 역조회/synthetic identity 생성은 하지 않는다.
    - 허용되지 않는 side/option_type도 fail-closed한다.

[Child Page] test_vssf_command_context_provider.py
```python
from decimal import Decimal
import pytest

from contracts.types import BrokerOrderCommand, OptionInstrumentIdentity
from shared.contracts.canonical import (
    CanonicalAssetType, CanonicalOptionType, CanonicalOrderSide,
)
from environments.virtual.execution.vssf_command_context_provider import (
    CanonicalVSSFCommandContextProvider, VSSFCommandContextError,
)

def order() -> BrokerOrderCommand:
    identity = OptionInstrumentIdentity(
        instrument_id="AUTH-OPTION-1", symbol="KOSPI200",
        expiry="202609", option_type="CALL", strike=Decimal("350.0"),
    )
    return BrokerOrderCommand(
        client_order_id="ORD-1", instrument_id=identity.instrument_id,
        side="BUY", quantity=2, order_type="LIMIT",
        instrument_identity=identity, asset_type="OPTION",
        requested_price=Decimal("1.25"), track_id="TRACK-1", tag_id="TAG-1",
    )

def test_build_command_matches_reference_canonical_contract():
    result = CanonicalVSSFCommandContextProvider().build_command(order())
    assert result.client_order_id == "ORD-1"
    assert result.track_id == "TRACK-1"
    assert result.asset_type is CanonicalAssetType.OPTION
    assert result.side is CanonicalOrderSide.BUY
    assert result.qty == 2
    assert result.price == 1.25
    assert result.symbol == "KOSPI200"
    assert result.expiry == "202609"
    assert result.option_type is CanonicalOptionType.CALL
    assert result.strike == 350.0
    assert result.tag_id == "TAG-1"

def test_missing_identity_fails_closed():
    bad = order()
    bad = BrokerOrderCommand(**{**bad.__dict__, "instrument_identity": None})
    with pytest.raises(VSSFCommandContextError, match="OPTION_IDENTITY_REQUIRED"):
        CanonicalVSSFCommandContextProvider().build_command(bad)

def test_instrument_id_mismatch_fails_closed():
    bad = order()
    bad = BrokerOrderCommand(**{**bad.__dict__, "instrument_id": "OTHER"})
    with pytest.raises(VSSFCommandContextError, match="INSTRUMENT_IDENTITY_MISMATCH"):
        CanonicalVSSFCommandContextProvider().build_command(bad)

def test_invalid_reference_enum_values_fail_closed():
    bad_side = BrokerOrderCommand(**{**order().__dict__, "side": "HOLD"})
    with pytest.raises(VSSFCommandContextError, match="CANONICAL_SIDE_REQUIRED"):
        CanonicalVSSFCommandContextProvider().build_command(bad_side)

    bad_identity = OptionInstrumentIdentity(
        instrument_id="AUTH-OPTION-1", symbol="KOSPI200",
        expiry="202609", option_type="OTHER", strike=Decimal("350.0"),
    )
    bad_option_type = BrokerOrderCommand(
        **{**order().__dict__, "instrument_identity": bad_identity}
    )
    with pytest.raises(VSSFCommandContextError, match="CANONICAL_OPTION_TYPE_REQUIRED"):
        CanonicalVSSFCommandContextProvider().build_command(bad_option_type)
```
## 검증 기준
    - 최신 Reference Canonical DTO의 Enum/float 필드까지 정확히 대조한다.
    - identity 누락·instrument_id 불일치·허용되지 않는 enum 값은 모두 fail-closed한다.
    - identity 역조회 없이 Standard에서 이미 보존된 authoritative identity만 사용한다.