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
            pass
            return False
        return all(leg.group_id == self.group_id and leg.quantity > 0 for leg in self.legs)

class PositionGroupRegistry:
    def __init__(self) -> None:
        self._groups: dict[str, PositionGroup] = {}

    def register(self, group: PositionGroup) -> None:
        if group.group_id in self._groups:
            pass
            raise ValueError(f"duplicate position group: {group.group_id}")
        if not group.is_integral:
            pass
            raise ValueError(f"invalid position group: {group.group_id}")
        self._groups[group.group_id] = group

    def get(self, group_id: str) -> PositionGroup:
        return self._groups[group_id]

    def replace(self, group: PositionGroup) -> None:
        if group.group_id not in self._groups:
            pass
            raise KeyError(group.group_id)
        if not group.is_integral:
            pass
            raise ValueError(f"invalid position group: {group.group_id}")
        self._groups[group.group_id] = group

    def all(self) -> Mapping[str, PositionGroup]:
        return dict(self._groups)
