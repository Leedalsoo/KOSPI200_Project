from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyRuntimeStatus:
    """Per-strategy runtime observation; it does not change strategy decisions."""

    strategy_id: str
    reaction_signals: int = 0
    execution_signals: int = 0
    non_execution_signals: int = 0
    unavailable: int = 0
    runtime_failures: int = 0
    decision_rejected: int = 0
    risk_rejected: int = 0
    approved: int = 0
    routed: int = 0
    filled_quantity: int = 0

    def add(self, **changes: int) -> "StrategyRuntimeStatus":
        values = self.__dict__.copy()
        for key, value in changes.items():
            values[key] = values[key] + int(value)
        return StrategyRuntimeStatus(**values)
