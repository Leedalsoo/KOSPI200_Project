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
