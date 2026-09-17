from dataclasses import dataclass
from dataclasses import dataclass
from decimal import Decimal
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
    contract_multiplier: Decimal
    identity_source: str
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

@dataclass(frozen=True)
class PositionGroupLegPnL:
    leg_id: str
    group_id: str
    instrument_id: str
    quantity: int
    contract_multiplier: Decimal
    identity_source: str
    avg_price: float
    current_price: float
    pnl: float


@dataclass(frozen=True)
class PositionGroupSnapshot:
    group_id: str
    strategy_id: str
    complete: bool
    legs: tuple[PositionGroupLegPnL, ...]
    total_pnl: float


class PositionGroupRegistry:
    def __init__(self) -> None:
        self._groups: dict[str, PositionGroup] = {}
        self._snapshots: dict[str, PositionGroupSnapshot] = {}

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

    def snapshot(self, group_id: str) -> PositionGroupSnapshot | None:
        return self._snapshots.get(group_id)

    def update_snapshot(self, snapshot: PositionGroupSnapshot) -> None:
        if snapshot.group_id not in self._groups:
            raise KeyError(snapshot.group_id)
        self._snapshots[snapshot.group_id] = snapshot
