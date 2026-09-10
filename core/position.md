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