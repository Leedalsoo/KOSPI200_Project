from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

@dataclass(frozen=True)
class Track9PositionExecutionSnapshot:
    active_sell_qty: int
    insurance_qty: int
    premium_spent: Decimal
    source: str

class Track9PositionExecutionReadModel(Protocol):
    def snapshot(self, *, run_id: str, strategy_id: str) -> Track9PositionExecutionSnapshot | None: ...

class Track9EventSource(Protocol):
    def upcoming(self, *, run_id: str, as_of) -> object | None: ...

@dataclass(frozen=True)
class Track9EventRiskSnapshot:
    event_budget: Decimal | None
    estimated_event_cost: Decimal | None
    source: str

class Track9EventRiskSource(Protocol):
    def snapshot(self, *, run_id: str, as_of) -> Track9EventRiskSnapshot | None: ...
