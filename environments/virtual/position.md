[Child Page] virtual_position.py
```python
from dataclasses import dataclass
from decimal import Decimal

from contracts.position import PositionProvider
from contracts.types import DataQuality, PositionSnapshot
from environments.virtual.clock import ClockProvider


@dataclass
class VirtualPosition(PositionProvider):
    instrument_id: str
    quantity: int = 0
    average_price: float = 0.0
    clock: ClockProvider | None = None

    def apply_fill(self, quantity: int, price: float) -> None:
        self.quantity += quantity
        self.average_price = price

    def snapshot(self) -> PositionSnapshot:
        if self.clock is None:
            raise RuntimeError("VirtualPosition.snapshot requires an injected ClockProvider")
        return PositionSnapshot(
            as_of=self.clock.now(),
            positions={self.instrument_id: Decimal(str(self.quantity))},
            freshness=DataQuality(
                is_fresh=True,
                is_complete=True,
                source_available=True,
                reason="virtual_position_state",
            ),
        )
```
## Standard Contract 정합화
    - 기존 instrument_id / quantity / average_price / apply_fill() 동작은 유지한다.
    - PositionProvider.snapshot()을 구현하여 Virtual Position 상태를 canonical PositionSnapshot으로 노출한다.
    - PositionSnapshot.as_of는 주입된 Virtual Clock에서 취득한다.
    - 기존 생성 코드의 호환성을 위해 clock은 optional이며, snapshot 호출 시 ClockProvider가 없으면 명시적으로 실패한다.
    - positions에는 현재 VirtualPosition이 실제로 관리하는 단일 instrument_id의 수량만 매핑한다.
    - average_price는 기존 VSSF/VMS 의미를 유지하고 이번 snapshot DTO에서는 수량만 노출한다. 가격/평가금액 계산 규칙을 임의로 추가하지 않는다.
[Child Page] execution_event_identity_adapter.py
```python
from dataclasses import dataclass

from contracts.types import ExecutionReport


@dataclass(frozen=True)
class ExecutionEventIdentity:
    """Environment-owned identity for one canonical execution event."""

    execution_id: str
    client_order_id: str


class ExecutionEventIdentityAdapter:
    """Preserve an Environment execution report's event identity without changing the DTO."""

    def identify(self, report: ExecutionReport) -> ExecutionEventIdentity:
        if not report.execution_id:
            raise ValueError("EXECUTION_EVENT_ID_REQUIRED")
        if not report.client_order_id:
            raise ValueError("EXECUTION_EVENT_CLIENT_ORDER_ID_REQUIRED")
        return ExecutionEventIdentity(
            execution_id=report.execution_id,
            client_order_id=report.client_order_id,
        )
```
## Contract
        - Existing ExecutionReport is unchanged.
        - ExecutionReport.execution_id is treated as the Environment-provided execution-event identity when present.
        - No UUID is generated when the report omits an identity.
        - No deduplication state is introduced here; this adapter only validates and preserves identity.
        - client_order_id is retained alongside execution identity so an event cannot be detached from its order context.
[Child Page] test_execution_event_identity_adapter.py
```python
from datetime import datetime
from decimal import Decimal

import pytest

from contracts.types import DataQuality, ExecutionReport
from environments.virtual.execution.execution_event_identity_adapter import (
    ExecutionEventIdentityAdapter,
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


def test_execution_id_is_preserved_without_reconstruction():
    identity = ExecutionEventIdentityAdapter().identify(report())
    assert identity.execution_id == "EXEC-001"
    assert identity.client_order_id == "ORD-001"


def test_missing_execution_id_fails_closed():
    with pytest.raises(ValueError, match="EXECUTION_EVENT_ID_REQUIRED"):
        ExecutionEventIdentityAdapter().identify(report(execution_id=None))


def test_missing_client_order_id_fails_closed():
    with pytest.raises(ValueError, match="EXECUTION_EVENT_CLIENT_ORDER_ID_REQUIRED"):
        ExecutionEventIdentityAdapter().identify(report(client_order_id=""))
```
## Scope
        - Identity preservation only.
        - No Position mutation.
        - No partial-fill accumulation.
        - No deduplication policy.

[Child Page] virtual_position_aggregate.py
```python
from dataclasses import dataclass
from typing import Mapping

from core.position.position_aggregate import PositionAggregate, PositionAggregateSource


@dataclass
class VirtualPositionAggregate(PositionAggregateSource):
    """Environment-owned authoritative side/qty position state.

    This aggregate is deliberately separate from VirtualPosition/PositionSnapshot.
    It receives execution-side information explicitly and never infers side from
    quantity sign or strategy intent.
    """

    instrument_id: str
    side: str | None = None
    qty: int = 0
    avg_price: float | None = None

    def apply_fill(self, *, side: str, quantity: int, price: float | None = None) -> None:
        if not isinstance(side, str) or not side:
            raise ValueError("POSITION_AGGREGATE_SIDE_REQUIRED")
        if side not in {"BUY", "SELL"}:
            raise ValueError("POSITION_AGGREGATE_SIDE_INVALID")
        if not isinstance(quantity, int) or quantity <= 0:
            raise ValueError("POSITION_AGGREGATE_QTY_REQUIRED")

        if self.qty == 0:
            self.side = side
            self.qty = quantity
            self.avg_price = price
            return

        if self.side == side:
            old_qty = self.qty
            self.qty += quantity
            if price is not None:
                if self.avg_price is None:
                    self.avg_price = price
                else:
                    self.avg_price = ((self.avg_price * old_qty) + (price * quantity)) / self.qty
            return

        if quantity < self.qty:
            self.qty -= quantity
            return

        if quantity == self.qty:
            self.side = None
            self.qty = 0
            self.avg_price = None
            return

        self.side = side
        self.qty = quantity - self.qty
        self.avg_price = price

    def snapshot(self) -> Mapping[str, PositionAggregate]:
        if self.qty == 0:
            return {}
        if self.side is None:
            raise RuntimeError("POSITION_AGGREGATE_SIDE_REQUIRED")
        return {
            self.instrument_id: PositionAggregate(
                side=self.side,
                qty=self.qty,
                avg_price=self.avg_price,
            )
        }
```
## 책임 경계
    - 기존 VirtualPosition과 PositionSnapshot은 변경하지 않는다.
    - 체결 갱신 시 side는 BrokerOrderCommand/실행 경로가 명시적으로 공급한다.
    - quantity 부호, strategy action, order purpose로 side를 추론하지 않는다.
    - 동일 방향 체결은 aggregate quantity를 증가시키고 평균 체결가격을 갱신한다.
    - 반대 방향 체결은 기존 quantity를 감소시키며 초과분이 있으면 새로운 side의 잔여 position으로 전환한다.
    - position이 0이면 side도 제거한다.
    - FIFO/lot attribution은 이 최소 aggregate의 책임이 아니다. Risk에는 최종 aggregate side/qty만 공급한다.
    - 실제 Runtime wiring은 별도 단계에서 진행한다.

[Child Page] test_virtual_position_aggregate.py
```python
from core.position.position_aggregate import PositionAggregate
from environments.virtual.position.virtual_position_aggregate import VirtualPositionAggregate


def test_buy_fill_preserves_authoritative_side_and_qty():
    position = VirtualPositionAggregate("OPTION_X")
    position.apply_fill(side="BUY", quantity=3, price=1.25)

    snapshot = position.snapshot()
    assert snapshot["OPTION_X"] == PositionAggregate(side="BUY", qty=3, avg_price=1.25)


def test_same_side_fill_accumulates_quantity():
    position = VirtualPositionAggregate("OPTION_X")
    position.apply_fill(side="BUY", quantity=2, price=1.0)
    position.apply_fill(side="BUY", quantity=2, price=2.0)

    aggregate = position.snapshot()["OPTION_X"]
    assert aggregate.side == "BUY"
    assert aggregate.qty == 4
    assert aggregate.avg_price == 1.5


def test_opposite_fill_reduces_existing_position_without_side_inference():
    position = VirtualPositionAggregate("OPTION_X")
    position.apply_fill(side="BUY", quantity=5, price=1.0)
    position.apply_fill(side="SELL", quantity=2, price=1.2)

    aggregate = position.snapshot()["OPTION_X"]
    assert aggregate.side == "BUY"
    assert aggregate.qty == 3


def test_opposite_fill_beyond_existing_quantity_creates_residual_new_side():
    position = VirtualPositionAggregate("OPTION_X")
    position.apply_fill(side="BUY", quantity=2, price=1.0)
    position.apply_fill(side="SELL", quantity=5, price=1.2)

    aggregate = position.snapshot()["OPTION_X"]
    assert aggregate.side == "SELL"
    assert aggregate.qty == 3
    assert aggregate.avg_price == 1.2


def test_flat_position_has_no_authoritative_position_entry():
    position = VirtualPositionAggregate("OPTION_X")
    position.apply_fill(side="BUY", quantity=2, price=1.0)
    position.apply_fill(side="SELL", quantity=2, price=1.1)

    assert position.snapshot() == {}


def test_invalid_side_fails_closed():
    position = VirtualPositionAggregate("OPTION_X")
    try:
        position.apply_fill(side="UNKNOWN", quantity=1, price=1.0)
    except ValueError as exc:
        assert str(exc) == "POSITION_AGGREGATE_SIDE_INVALID"
    else:
        raise AssertionError("invalid side must fail closed")
```
## 검증 목적
Environment aggregate의 최소 상태 전이만 검증한다. Risk 정책, FIFO/lot attribution, Broker API 연결은 테스트 대상이 아니다.

[Child Page] virtual_position_fill_adapter.py
```python
from contracts.types import BrokerOrderCommand, ExecutionReport
from environments.virtual.position.virtual_position_aggregate import VirtualPositionAggregate


class VirtualPositionFillAdapter:
    """Apply an authoritative execution report to a virtual position aggregate.

    The command supplies side/instrument identity; the report supplies actual
    filled quantity and execution price. This adapter performs validation only
    and delegates position semantics to VirtualPositionAggregate.
    """

    def apply(
        self,
        command: BrokerOrderCommand,
        report: ExecutionReport,
        aggregate: VirtualPositionAggregate,
    ) -> None:
        if command.client_order_id != report.client_order_id:
            raise ValueError("POSITION_FILL_CLIENT_ORDER_ID_MISMATCH")

        if not command.instrument_id:
            raise ValueError("POSITION_FILL_INSTRUMENT_ID_REQUIRED")
        if command.instrument_id != aggregate.instrument_id:
            raise ValueError("POSITION_FILL_INSTRUMENT_ID_MISMATCH")

        if not isinstance(command.side, str) or not command.side:
            raise ValueError("POSITION_FILL_SIDE_REQUIRED")
        if command.side not in {"BUY", "SELL"}:
            raise ValueError("POSITION_FILL_SIDE_INVALID")

        quantity = report.filled_quantity
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
            raise ValueError("POSITION_FILL_FILLED_QTY_REQUIRED")
        if quantity > command.quantity:
            raise ValueError("POSITION_FILL_FILLED_QTY_EXCEEDS_COMMAND")

        price = report.execution_price
        if price is None:
            raise ValueError("POSITION_FILL_EXECUTION_PRICE_REQUIRED")

        aggregate.apply_fill(
            side=command.side,
            quantity=quantity,
            price=float(price),
        )
```
## 책임 경계
    - ExecutionReport에 side/instrument_id를 추가하지 않는다.
    - side는 BrokerOrderCommand.side에서만 공급한다.
    - Position 갱신 수량은 ExecutionReport.filled_quantity만 사용한다.
    - Position 가격은 ExecutionReport.execution_price만 사용하며 requested_price를 fallback으로 사용하지 않는다.
    - command.client_order_id == report.client_order_id를 확인한다.
    - aggregate의 instrument_id와 command의 instrument_id가 일치해야 한다. Report에 존재하지 않는 instrument_id를 새로 요구하지 않는다.
    - 부분체결은 filled_quantity < command.quantity인 정상 입력으로 허용한다.
    - 중복 체결 방지/deduplication은 이 adapter의 책임으로 새로 정의하지 않는다. 실제 execution 흐름에서 동일 execution report의 반복 가능성을 확인한 뒤 별도 단계에서 결정한다.
    - 실제 반대방향 체결, 평균가격 계산 등 Position semantics는 VirtualPositionAggregate에 위임한다.

[Child Page] test_virtual_position_fill_adapter.py
```python
from decimal import Decimal

import pytest

from contracts.types import BrokerOrderCommand, ExecutionReport
from environments.virtual.position.virtual_position_aggregate import VirtualPositionAggregate
from environments.virtual.position.virtual_position_fill_adapter import VirtualPositionFillAdapter


def command(*, client_order_id="order-1", side="BUY", quantity=10, requested_price=Decimal("100")):
    return BrokerOrderCommand(
        client_order_id=client_order_id,
        instrument_id="OPT-001",
        side=side,
        quantity=quantity,
        order_type="MARKET",
        requested_price=requested_price,
    )


def report(*, client_order_id="order-1", filled_quantity=10, execution_price=Decimal("101")):
    return ExecutionReport(
        client_order_id=client_order_id,
        broker_order_id="broker-1",
        execution_id="exec-1",
        status="FILLED",
        filled_quantity=filled_quantity,
        remaining_quantity=0,
        execution_price=execution_price,
        execution_timestamp=None,
    )


def test_buy_fill_preserves_command_side_and_actual_execution_price():
    aggregate = VirtualPositionAggregate(instrument_id="OPT-001")

    VirtualPositionFillAdapter().apply(command(side="BUY"), report(), aggregate)

    assert aggregate.side == "BUY"
    assert aggregate.qty == 10
    assert aggregate.avg_price == 101.0


def test_sell_fill_preserves_command_side():
    aggregate = VirtualPositionAggregate(instrument_id="OPT-001")

    VirtualPositionFillAdapter().apply(command(side="SELL"), report(), aggregate)

    assert aggregate.side == "SELL"
    assert aggregate.qty == 10
    assert aggregate.avg_price == 101.0


def test_partial_fill_uses_filled_quantity_not_command_quantity():
    aggregate = VirtualPositionAggregate(instrument_id="OPT-001")

    VirtualPositionFillAdapter().apply(
        command(quantity=10),
        report(filled_quantity=4),
        aggregate,
    )

    assert aggregate.qty == 4


def test_client_order_identity_mismatch_fails_closed():
    aggregate = VirtualPositionAggregate(instrument_id="OPT-001")

    with pytest.raises(ValueError, match="POSITION_FILL_CLIENT_ORDER_ID_MISMATCH"):
        VirtualPositionFillAdapter().apply(
            command(client_order_id="order-1"),
            report(client_order_id="order-2"),
            aggregate,
        )


def test_missing_or_invalid_side_fails_closed():
    aggregate = VirtualPositionAggregate(instrument_id="OPT-001")

    with pytest.raises(ValueError, match="POSITION_FILL_SIDE_REQUIRED"):
        VirtualPositionFillAdapter().apply(command(side=""), report(), aggregate)

    with pytest.raises(ValueError, match="POSITION_FILL_SIDE_INVALID"):
        VirtualPositionFillAdapter().apply(command(side="HOLD"), report(), aggregate)


def test_invalid_filled_quantity_fails_closed():
    aggregate = VirtualPositionAggregate(instrument_id="OPT-001")

    for quantity in (0, -1, True):
        with pytest.raises(ValueError, match="POSITION_FILL_FILLED_QTY_REQUIRED"):
            VirtualPositionFillAdapter().apply(
                command(), report(filled_quantity=quantity), aggregate
            )


def test_filled_quantity_cannot_exceed_command_quantity():
    aggregate = VirtualPositionAggregate(instrument_id="OPT-001")

    with pytest.raises(ValueError, match="POSITION_FILL_FILLED_QTY_EXCEEDS_COMMAND"):
        VirtualPositionFillAdapter().apply(
            command(quantity=5),
            report(filled_quantity=6),
            aggregate,
        )


def test_missing_execution_price_fails_closed():
    aggregate = VirtualPositionAggregate(instrument_id="OPT-001")

    with pytest.raises(ValueError, match="POSITION_FILL_EXECUTION_PRICE_REQUIRED"):
        VirtualPositionFillAdapter().apply(
            command(requested_price=Decimal("100")),
            report(execution_price=None),
            aggregate,
        )


def test_instrument_identity_mismatch_fails_closed():
    aggregate = VirtualPositionAggregate(instrument_id="OPT-002")

    with pytest.raises(ValueError, match="POSITION_FILL_INSTRUMENT_ID_MISMATCH"):
        VirtualPositionFillAdapter().apply(command(), report(), aggregate)
```
## 검증 의도
    - 정상 BUY/SELL 체결에서 command의 side가 그대로 aggregate에 전달되는지 확인한다.
    - 부분체결에서 filled_quantity만 position quantity로 반영되는지 확인한다.
    - requested price가 아니라 실제 execution_price가 평균 체결가격에 사용되는지 확인한다.
    - command/report identity mismatch, side 오류, filled quantity 오류, execution price 누락, instrument identity mismatch를 fail-closed로 확인한다.
    - 실제 pytest 실행은 별도 실행 결과가 없는 한 UNVERIFIED로 유지한다.

[Child Page] virtual_position_fill_adapter.py
```python
from contracts.types import BrokerOrderCommand, ExecutionReport
from environments.virtual.position.virtual_position_aggregate import VirtualPositionAggregate


class VirtualPositionFillAdapter:
    """Apply one authoritative execution fill to the virtual position aggregate."""

    def __init__(self, position: VirtualPositionAggregate):
        self.position = position

    def apply(self, command: BrokerOrderCommand, report: ExecutionReport) -> None:
        if command.client_order_id != report.client_order_id:
            raise ValueError("POSITION_FILL_CLIENT_ORDER_ID_MISMATCH")
        if command.instrument_id != self.position.instrument_id:
            raise ValueError("POSITION_FILL_INSTRUMENT_ID_MISMATCH")
        if not command.side or command.side not in {"BUY", "SELL"}:
            raise ValueError("POSITION_FILL_SIDE_REQUIRED")
        if not isinstance(report.filled_quantity, int) or report.filled_quantity <= 0:
            raise ValueError("POSITION_FILL_QTY_REQUIRED")
        if report.execution_price is None:
            raise ValueError("POSITION_FILL_PRICE_REQUIRED")

        self.position.apply_fill(
            side=command.side,
            quantity=report.filled_quantity,
            price=float(report.execution_price),
        )
```
    - side는 BrokerOrderCommand에서 명시적으로 공급한다.
    - 체결 수량은 ExecutionReport.filled_quantity만 사용한다.
    - 실제 체결가격은 ExecutionReport.execution_price만 사용한다.
    - Position 의미를 추론하거나 execution_id를 임의로 deduplicate하지 않는다.

[Child Page] test_virtual_position_fill_adapter.py
```python
from decimal import Decimal

import pytest

from contracts.types import BrokerOrderCommand, ExecutionReport
from environments.virtual.position.virtual_position_aggregate import VirtualPositionAggregate
from environments.virtual.position.virtual_position_fill_adapter import VirtualPositionFillAdapter


def command(side="BUY", order_id="o1"):
    return BrokerOrderCommand(
        client_order_id=order_id,
        instrument_id="K200-C-350",
        side=side,
        quantity=10,
        order_type="LIMIT",
    )


def report(order_id="o1", qty=3, price=Decimal("101.5")):
    return ExecutionReport(
        client_order_id=order_id,
        broker_order_id="b1",
        execution_id="e1",
        status="PARTIALLY_FILLED",
        filled_quantity=qty,
        remaining_quantity=7,
        execution_price=price,
        execution_timestamp=None,
    )


def test_buy_and_sell_side_are_preserved():
    p = VirtualPositionAggregate("K200-C-350")
    a = VirtualPositionFillAdapter(p)
    a.apply(command("BUY"), report())
    assert p.snapshot()["K200-C-350"].side == "BUY"
    assert p.snapshot()["K200-C-350"].qty == 3

    p2 = VirtualPositionAggregate("K200-C-350")
    a2 = VirtualPositionFillAdapter(p2)
    a2.apply(command("SELL"), report())
    assert p2.snapshot()["K200-C-350"].side == "SELL"


def test_identity_mismatch_fails_closed():
    p = VirtualPositionAggregate("K200-C-350")
    with pytest.raises(ValueError, match="POSITION_FILL_CLIENT_ORDER_ID_MISMATCH"):
        VirtualPositionFillAdapter(p).apply(command(order_id="o1"), report(order_id="o2"))


def test_missing_execution_price_fails_closed():
    p = VirtualPositionAggregate("K200-C-350")
    with pytest.raises(ValueError, match="POSITION_FILL_PRICE_REQUIRED"):
        VirtualPositionFillAdapter(p).apply(command(), report(price=None))
```
    - 정상 BUY/SELL, 부분체결, identity mismatch, execution price 누락을 독립 검증한다.
    - 실제 pytest 실행은 별도 검증 단계에서 수행한다.

[Child Page] vssf_position_aggregate_adapter.py
```python
from collections.abc import Mapping
from typing import Any

from core.position.position_aggregate import PositionAggregate, PositionAggregateSource


class VSSFPositionAggregateAdapter(PositionAggregateSource):
    """Read-only projection of VSSF authoritative positions into the Standard contract."""

    def __init__(self, position_source: Any):
        self._position_source = position_source

    def snapshot(self) -> Mapping[str, PositionAggregate]:
        positions = getattr(self._position_source, "positions", None)
        if not isinstance(positions, Mapping):
            raise TypeError("VSSF_POSITION_SOURCE_REQUIRED")

        projected: dict[str, PositionAggregate] = {}
        for instrument_key, state in positions.items():
            if not isinstance(instrument_key, str) or not instrument_key:
                raise TypeError("VSSF_POSITION_INSTRUMENT_KEY_REQUIRED")
            if not isinstance(state, Mapping):
                raise TypeError("VSSF_POSITION_STATE_REQUIRED")

            side = state.get("side")
            qty = state.get("qty")
            avg_price = state.get("avg_price")

            if not isinstance(side, str) or side not in {"BUY", "SELL"}:
                raise TypeError("VSSF_POSITION_SIDE_REQUIRED")
            if not isinstance(qty, int) or qty <= 0:
                raise TypeError("VSSF_POSITION_QTY_REQUIRED")
            if avg_price is not None and not isinstance(avg_price, (int, float)):
                raise TypeError("VSSF_POSITION_AVG_PRICE_INVALID")

            projected[instrument_key] = PositionAggregate(
                side=side,
                qty=qty,
                avg_price=float(avg_price) if avg_price is not None else None,
            )

        return projected
```
## 책임 경계
    - 입력은 VSSF authoritative PositionManager.positions를 노출하는 객체의 positions read interface다.
    - symbol -> {qty, avg_price, side}를 Standard immutable PositionAggregate로 투영한다.
    - source mapping과 내부 entry를 수정하지 않는다.
    - FIFO/lot attribution, PnL, 반대방향 체결, Position mutation은 수행하지 않는다.
    - side는 반드시 VSSF state가 명시한 값을 사용하며 quantity 부호로 추론하지 않는다.
    - avg_price는 Standard projection에 보존하지만 Risk Adapter에서 소비하지 않는다.
## Fail-closed
    - positions가 Mapping이 아니면 실패
    - instrument key가 유효하지 않으면 실패
    - position state가 Mapping이 아니면 실패
    - side가 BUY/SELL이 아니면 실패
    - qty가 양의 정수가 아니면 실패
    - avg_price가 존재하면서 숫자가 아니면 실패
## 수명/구성 원칙
현재 단계에서는 Application Composition에 연결하지 않는다. VSSF Runtime의 authoritative mutation은 Account.apply_execution() -> PositionManager.update_position() 경로가 담당하므로, 이 Adapter는 읽기 전용 projection으로만 사용한다.

[Child Page] test_vssf_position_aggregate_adapter.py
```python
from copy import deepcopy

import pytest

from core.position.position_aggregate import PositionAggregate
from environments.virtual.position.vssf_position_aggregate_adapter import (
    VSSFPositionAggregateAdapter,
)


class StubVSSFPositionSource:
    def __init__(self, positions):
        self.positions = positions


def test_buy_sell_qty_and_avg_price_are_preserved():
    source = StubVSSFPositionSource({
        "K200-C-350": {"qty": 3, "avg_price": 101.5, "side": "BUY"},
        "K200-P-350": {"qty": 5, "avg_price": 98.25, "side": "SELL"},
    })

    snapshot = VSSFPositionAggregateAdapter(source).snapshot()

    assert snapshot["K200-C-350"] == PositionAggregate("BUY", 3, 101.5)
    assert snapshot["K200-P-350"] == PositionAggregate("SELL", 5, 98.25)


def test_missing_side_fails_closed():
    source = StubVSSFPositionSource({"K200-C-350": {"qty": 3, "avg_price": 101.5}})

    with pytest.raises(TypeError, match="VSSF_POSITION_SIDE_REQUIRED"):
        VSSFPositionAggregateAdapter(source).snapshot()


def test_invalid_qty_fails_closed():
    source = StubVSSFPositionSource({"K200-C-350": {"qty": 0, "avg_price": 101.5, "side": "BUY"}})

    with pytest.raises(TypeError, match="VSSF_POSITION_QTY_REQUIRED"):
        VSSFPositionAggregateAdapter(source).snapshot()


def test_malformed_mapping_fails_closed():
    source = StubVSSFPositionSource({"K200-C-350": ["BUY", 3, 101.5]})

    with pytest.raises(TypeError, match="VSSF_POSITION_STATE_REQUIRED"):
        VSSFPositionAggregateAdapter(source).snapshot()


def test_non_mapping_source_fails_closed():
    source = StubVSSFPositionSource([])

    with pytest.raises(TypeError, match="VSSF_POSITION_SOURCE_REQUIRED"):
        VSSFPositionAggregateAdapter(source).snapshot()


def test_source_is_not_mutated():
    positions = {
        "K200-C-350": {"qty": 3, "avg_price": 101.5, "side": "BUY"},
    }
    before = deepcopy(positions)
    source = StubVSSFPositionSource(positions)

    VSSFPositionAggregateAdapter(source).snapshot()

    assert positions == before

```