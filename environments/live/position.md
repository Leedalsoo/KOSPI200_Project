Live execution에 의해 변경되는 authoritative Position aggregate 경계. Position semantics는 최소 aggregate 수준으로 유지하며, KIS broker/ACK 로직과 분리한다.

[Child Page] live_position_aggregate.py
```python
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PositionAggregate:
    instrument_id: str
    side: str | None
    qty: int
    avg_price: Decimal | None


class LivePositionAggregate:
    """Live-owned authoritative side/quantity/average-price aggregate."""

    def __init__(self, instrument_id: str) -> None:
        instrument_id = str(instrument_id).strip()
        if not instrument_id:
            raise ValueError("INSTRUMENT_ID_REQUIRED")
        self.instrument_id = instrument_id
        self.side: str | None = None
        self.qty = 0
        self.avg_price: Decimal | None = None

    def apply_fill(self, *, side: str, quantity: int, price: Decimal) -> None:
        if side not in {"BUY", "SELL"}:
            raise ValueError("SIDE_INVALID")
        if not isinstance(quantity, int) or quantity <= 0:
            raise ValueError("QUANTITY_INVALID")
        if not isinstance(price, Decimal) or price <= 0:
            raise ValueError("PRICE_INVALID")

        if self.qty == 0 or self.side is None:
            self.side, self.qty, self.avg_price = side, quantity, price
            return

        if side == self.side:
            assert self.avg_price is not None
            self.avg_price = ((self.avg_price * self.qty) + (price * quantity)) / (self.qty + quantity)
            self.qty += quantity
            return

        if quantity < self.qty:
            self.qty -= quantity
            return
        if quantity == self.qty:
            self.side, self.qty, self.avg_price = None, 0, None
            return

        self.side = side
        self.qty = quantity - self.qty
        self.avg_price = price

    def snapshot(self) -> PositionAggregate:
        return PositionAggregate(self.instrument_id, self.side, self.qty, self.avg_price)
```
## Boundary rules
    - Position state is authoritative within the Live environment: instrument_id, side, qty, avg_price.
    - Same-side fills use weighted-average execution price.
    - Opposite-side fills reduce, clear, or flip the position according to quantity.
    - Side is explicit; no sign-based side inference is used.
    - FIFO, lot attribution, PnL, and Risk policy remain outside this aggregate.

[Child Page] live_position_fill_adapter.py
```python
from __future__ import annotations

from contracts.types import BrokerOrderCommand, ExecutionReport


class LivePositionFillAdapter:
    """Validate a canonical fill against its originating broker command."""

    def __init__(self, aggregate) -> None:
        self._aggregate = aggregate

    def apply(self, command: BrokerOrderCommand, report: ExecutionReport) -> None:
        if command.client_order_id != report.client_order_id:
            raise ValueError("CLIENT_ORDER_ID_MISMATCH")
        if command.instrument_id != self._aggregate.instrument_id:
            raise ValueError("INSTRUMENT_ID_MISMATCH")
        if command.side not in {"BUY", "SELL"}:
            raise ValueError("SIDE_INVALID")
        if report.filled_quantity <= 0 or report.filled_quantity > command.quantity:
            raise ValueError("FILLED_QUANTITY_INVALID")
        if report.execution_price is None:
            raise ValueError("EXECUTION_PRICE_REQUIRED")
        self._aggregate.apply_fill(
            side=command.side,
            quantity=report.filled_quantity,
            price=report.execution_price,
        )
```
## Boundary rules
    - client_order_id, instrument_id, side, quantity, and execution price are validated before Position mutation.
    - Side comes only from BrokerOrderCommand; it is never inferred from quantity sign.
    - requested_price is not used for settlement.
    - FIFO, lot attribution, PnL, and Risk policy remain outside this adapter.

[Child Page] live_execution_position_bridge.py
```python
from __future__ import annotations

from decimal import Decimal

from contracts.types import BrokerOrderCommand, ExecutionReport
from core.oms.oms_fsm import OrderStateMachine, OrderStateTransitionError


class LivePositionFillAdapter:
    """Validate a canonical fill against its originating broker command."""

    def __init__(self, aggregate) -> None:
        self._aggregate = aggregate

    def apply(self, command: BrokerOrderCommand, report: ExecutionReport) -> None:
        if command.client_order_id != report.client_order_id:
            raise ValueError("CLIENT_ORDER_ID_MISMATCH")
        if command.instrument_id != self._aggregate.instrument_id:
            raise ValueError("INSTRUMENT_ID_MISMATCH")
        if command.side not in {"BUY", "SELL"}:
            raise ValueError("SIDE_INVALID")
        if report.filled_quantity <= 0 or report.filled_quantity > command.quantity:
            raise ValueError("FILLED_QUANTITY_INVALID")
        if report.execution_price is None:
            raise ValueError("EXECUTION_PRICE_REQUIRED")
        self._aggregate.apply_fill(
            side=command.side,
            quantity=report.filled_quantity,
            price=Decimal(report.execution_price),
        )


class LiveExecutionPositionBridge:
    """Settle an accepted execution exactly once into OMS and Live Position."""

    def __init__(
        self,
        *,
        order_state_machine: OrderStateMachine,
        position_fill_adapter: LivePositionFillAdapter,
        execution_event_deduplicator,
        position_aggregate,
    ) -> None:
        self._oms = order_state_machine
        self._fill_adapter = position_fill_adapter
        self._dedup = execution_event_deduplicator
        self._position = position_aggregate

    def settle(self, report: ExecutionReport) -> object:
        state = self._oms.get(report.client_order_id)
        if state is None:
            raise OrderStateTransitionError("EXECUTION_BEFORE_ACK")

        # A known replay must be detected before the state-transition guard:
        # an already-settled execution can legitimately arrive after FILLED.
        # For a new event, validate the current state first so an invalid/stale
        # event is not consumed by the deduplication gate.
        execution_id = str(report.execution_id or "").strip()
        if not execution_id:
            raise ValueError("EXECUTION_EVENT_ID_REQUIRED")
        if self._dedup.contains(execution_id):
            return state

        if state.status not in {"ACKED", "PARTIALLY_FILLED"}:
            raise OrderStateTransitionError("EXECUTION_BEFORE_ACK")

        command = self._oms.get_broker_order_command(report.broker_order_id)
        if report.status not in {"PARTIALLY_FILLED", "FILLED"}:
            raise OrderStateTransitionError("UNSUPPORTED_EXECUTION_STATUS")
        if report.filled_quantity <= 0:
            raise OrderStateTransitionError("FILLED_QUANTITY_INVALID")
        cumulative = state.filled_quantity + report.filled_quantity
        if cumulative > state.order_quantity:
            raise OrderStateTransitionError("FILLED_QUANTITY_EXCEEDS_ORDER")
        if report.remaining_quantity != state.order_quantity - cumulative:
            raise OrderStateTransitionError("REMAINING_QUANTITY_MISMATCH")
        if report.broker_order_id and state.broker_order_id != report.broker_order_id:
            raise OrderStateTransitionError("BROKER_ORDER_ID_MISMATCH")

        # Consume the identity only after the complete transition has been
        # validated, while still keeping replay detection before any mutation.
        if not self._dedup.accept(report):
            return state
        state = self._oms.apply_execution(report)
        self._fill_adapter.apply(command, report)
        return state
```
## Boundary rules
    - client_order_id, instrument_id, side, quantity, and execution price are validated before Position mutation.
    - Side comes only from BrokerOrderCommand; it is never inferred from quantity sign.
    - requested_price is not used for settlement.
    - FIFO, lot attribution, PnL, and Risk policy remain outside this adapter.
    - LiveExecutionPositionBridge resolves the originating BrokerOrderCommand only from OMS-owned state.
    - Duplicate execution events are rejected before OMS/Position mutation.
    - No broker command, identity, side, quantity, or price is synthesized from ExecutionReport.

[Child Page] live_position_aggregate_risk_source.py
```python
# environments/live/position/live_position_aggregate_risk_source.py
from collections.abc import Mapping

from core.position.position_aggregate import PositionAggregate, PositionAggregateSource
from environments.live.position.live_position_aggregate import LivePositionAggregate


class LivePositionAggregateRiskSource(PositionAggregateSource):
    """Read-only projection of authoritative Live aggregates for pre-trade Risk."""

    def __init__(self, aggregates: Mapping[str, LivePositionAggregate]) -> None:
        if not isinstance(aggregates, Mapping):
            raise TypeError("LIVE_POSITION_AGGREGATE_MAPPING_REQUIRED")
        self._aggregates = aggregates

    def snapshot(self) -> Mapping[str, PositionAggregate]:
        projected: dict[str, PositionAggregate] = {}
        for instrument_id, aggregate in self._aggregates.items():
            if not isinstance(instrument_id, str) or not instrument_id:
                raise TypeError("LIVE_POSITION_INSTRUMENT_ID_REQUIRED")
            if not isinstance(aggregate, LivePositionAggregate):
                raise TypeError("LIVE_POSITION_AGGREGATE_REQUIRED")
            state = aggregate.snapshot()
            if state.instrument_id != instrument_id:
                raise ValueError("LIVE_POSITION_INSTRUMENT_ID_MISMATCH")
            if state.qty == 0:
                continue
            if state.side not in {'BUY', 'SELL'}:
                raise TypeError("LIVE_POSITION_SIDE_REQUIRED")
            if not isinstance(state.qty, int) or state.qty <= 0:
                raise TypeError("LIVE_POSITION_QTY_REQUIRED")
            projected[instrument_id] = PositionAggregate(
                side=state.side, qty=state.qty, avg_price=state.avg_price
            )
        return projected
```
## 경계
    - Live aggregate의 authoritative instrument_id/side/qty/avg_price를 읽기 전용으로 Standard PositionAggregateSource에 투영한다.
    - qty=0은 열린 포지션이 아니므로 Risk 입력에서 제외한다.
    - side/qty를 새로 계산하거나 추론하지 않는다.
    - FIFO/PnL/valuation/Risk 정책을 구현하지 않는다.
    - aggregate의 instrument_id와 mapping key 불일치는 fail-closed한다.

[Child Page] live_position_aggregate_risk_source.py
```python
from collections.abc import Mapping

from core.position.position_aggregate import PositionAggregate, PositionAggregateSource
from environments.live.position.live_position_aggregate import LivePositionAggregate


class LivePositionAggregateRiskSource(PositionAggregateSource):
    """Read-only projection of authoritative Live aggregates for pre-trade Risk."""

    def __init__(self, aggregates: Mapping[str, LivePositionAggregate]) -> None:
        if not isinstance(aggregates, Mapping):
            raise TypeError("LIVE_POSITION_AGGREGATE_MAPPING_REQUIRED")
        self._aggregates = aggregates

    def snapshot(self) -> Mapping[str, PositionAggregate]:
        projected = {}
        for instrument_id, aggregate in self._aggregates.items():
            if not isinstance(instrument_id, str) or not instrument_id:
                raise TypeError("LIVE_POSITION_INSTRUMENT_ID_REQUIRED")
            if not isinstance(aggregate, LivePositionAggregate):
                raise TypeError("LIVE_POSITION_AGGREGATE_REQUIRED")
            state = aggregate.snapshot()
            if state.instrument_id != instrument_id:
                raise ValueError("LIVE_POSITION_INSTRUMENT_ID_MISMATCH")
            if state.qty == 0:
                continue
            if state.side not in {"BUY", "SELL"}:
                raise TypeError("LIVE_POSITION_SIDE_REQUIRED")
            if not isinstance(state.qty, int) or state.qty <= 0:
                raise TypeError("LIVE_POSITION_QTY_REQUIRED")
            projected[instrument_id] = PositionAggregate(state.side, state.qty, state.avg_price)
        return projected
```
Read-only Live aggregate → Standard PositionAggregateSource projection. No side inference or state mutation.